"""Read prices, solar forecast and load history out of Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from statistics import median
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

SLOT = timedelta(minutes=15)


def slot_floor(t: datetime) -> datetime:
    t = dt_util.as_utc(t)
    return t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)


def _as_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return dt_util.as_utc(v) if v.tzinfo else dt_util.as_utc(v.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE))
    if isinstance(v, str):
        d = dt_util.parse_datetime(v)
        if d is None:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(d)
    return None


def _spread(rows: list[tuple[datetime, datetime | None, float]]) -> dict[datetime, float]:
    """Turn price periods of any length into a map of 15 minute slots."""
    rows = sorted(rows, key=lambda r: r[0])
    out: dict[datetime, float] = {}
    for n, (start, end, price) in enumerate(rows):
        if end is None:
            if n + 1 < len(rows):
                end = rows[n + 1][0]
                if end - start > timedelta(hours=1):
                    end = start + timedelta(hours=1)
            else:
                end = start + timedelta(hours=1)
        t = slot_floor(start)
        while t < end:
            out[t] = price
            t += SLOT
    return out


def _scale(unit: str | None, attrs: dict[str, Any]) -> float:
    unit = (unit or "").lower()
    if "mwh" in unit:
        return 1 / 1000
    if attrs.get("price_in_cents") or unit.startswith(("c/", "ct/", "cent", "snt", "öre", "øre", "ore/")):
        return 1 / 100
    return 1.0


def _parse_list(items: Any, scale: float) -> list[tuple[datetime, datetime | None, float]]:
    rows = []
    if not isinstance(items, list):
        return rows
    for it in items:
        if not isinstance(it, dict):
            continue
        start = _as_dt(it.get("start") or it.get("time") or it.get("hour") or it.get("startsAt"))
        end = _as_dt(it.get("end")) if it.get("end") else None
        val = it.get("value", it.get("price", it.get("total")))
        if start is None or val is None:
            continue
        try:
            rows.append((start, end, float(val) * scale))
        except (TypeError, ValueError):
            continue
    return rows


async def async_get_prices(hass: HomeAssistant, entity_id: str, area: str | None) -> dict[datetime, float]:
    """Prices per 15 minute slot in currency per kWh.

    Supports the built in Nord Pool integration (through its
    get_prices_for_date action), the HACS Nord Pool and ENTSO-e sensors, and
    any sensor that carries a list of start/price rows as an attribute.
    """
    ent = er.async_get(hass).async_get(entity_id)
    if ent is not None and ent.platform == "nordpool" and ent.config_entry_id:
        rows: list[tuple[datetime, datetime | None, float]] = []
        today = dt_util.now().date()
        for d in (today - timedelta(days=1), today, today + timedelta(days=1)):
            data = {"config_entry": ent.config_entry_id, "date": d.isoformat()}
            if area:
                data["areas"] = [area]
            try:
                resp = await hass.services.async_call(
                    "nordpool", "get_prices_for_date", data,
                    blocking=True, return_response=True,
                )
            except Exception as err:  # noqa: BLE001 tomorrow is often not out yet
                _LOGGER.debug("Nord Pool %s: %s", d, err)
                continue
            if not isinstance(resp, dict):
                continue
            keys = [area] if area and area in resp else list(resp)
            if keys:
                rows += _parse_list(resp.get(keys[0]), 1 / 1000)
        if rows:
            return _spread(rows)

    state = hass.states.get(entity_id)
    if state is None:
        return {}
    attrs = dict(state.attributes)
    scale = _scale(attrs.get("unit_of_measurement"), attrs)
    if attrs.get("unit") and "mwh" in str(attrs["unit"]).lower():
        scale = 1 / 1000
    rows = []
    for key in ("raw_today", "raw_tomorrow", "prices_today", "prices_tomorrow",
                "today_prices", "tomorrow_prices", "forecast_prices", "prices", "forecast", "data"):
        rows += _parse_list(attrs.get(key), scale)
    return _spread(rows)


def solar_slots(hass: HomeAssistant, entities: list[str], confidence: float) -> dict[datetime, float]:
    """Forecast solar energy per 15 minute slot, in kWh.

    Reads Solcast style detailedForecast attributes. confidence blends from
    the pessimistic estimate10 (0) to the median estimate (1).
    """
    out: dict[datetime, float] = {}
    for eid in entities:
        st = hass.states.get(eid) if eid else None
        if st is None:
            continue
        periods = st.attributes.get("detailedForecast") or st.attributes.get("detailed_forecast") or []
        for p in periods:
            start = _as_dt(p.get("period_start"))
            if start is None:
                continue
            try:
                mid = float(p.get("pv_estimate", 0) or 0)
                low = float(p.get("pv_estimate10", mid) or 0)
            except (TypeError, ValueError):
                continue
            kw = low + (mid - low) * confidence
            t = slot_floor(start)
            for k in range(2):  # Solcast periods are 30 minutes
                out[t + SLOT * k] = kw * 0.25
    return out


async def async_load_profile(hass: HomeAssistant, entity_id: str | None) -> dict[tuple[bool, int], float] | None:
    """Median house load in W for every (weekend, hour), from 21 days of
    hourly statistics. A median, never a mean: one afternoon of 2 kW
    appliances must not convince the planner the evening will be heavy."""
    if not entity_id:
        return None
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period
    except ImportError:
        return None
    end = dt_util.utcnow()
    start = end - timedelta(days=21)
    try:
        stats = await get_instance(hass).async_add_executor_job(
            statistics_during_period, hass, start, end, {entity_id}, "hour", None, {"mean"},
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not read load statistics for %s: %s", entity_id, err)
        return None
    rows = stats.get(entity_id) or []
    buckets: dict[tuple[bool, int], list[float]] = {}
    for r in rows:
        mean = r.get("mean")
        ts = r.get("start")
        if mean is None or ts is None:
            continue
        t = dt_util.as_local(dt_util.utc_from_timestamp(ts) if isinstance(ts, (int, float)) else ts)
        buckets.setdefault((t.weekday() >= 5, t.hour), []).append(float(mean))
    every = [v for vals in buckets.values() for v in vals]
    if len(every) < 72:
        return None
    overall = median(every)
    prof: dict[tuple[bool, int], float] = {}
    for weekend in (False, True):
        for h in range(24):
            vals = buckets.get((weekend, h), [])
            if len(vals) < 2:
                vals = buckets.get((not weekend, h), [])
            prof[(weekend, h)] = median(vals) if len(vals) >= 2 else overall
    return prof
