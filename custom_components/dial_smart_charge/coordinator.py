"""Builds the plan every 15 minutes and drives the inverter every minute."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import sources
from .const import (
    CONF_CAPACITY, CONF_DRIVER, CONF_LOAD_ENTITY, CONF_MINSOC_ENTITY, CONF_PRICE_AREA,
    CONF_PRICE_ENTITY, CONF_SOC_ENTITY, CONF_SOLAR_TODAY, CONF_SOLAR_TOMORROW,
    CONF_SWITCH_ENTITY, CONTROL_INTERVAL_S, DEFAULTS, DOMAIN, DRIVER_DIAL_GROWATT,
    DRIVER_SWITCH, PLAN_INTERVAL_MIN,
)
from .driver import make_driver
from .planner import Plan, PlanInput, build_plan

_LOGGER = logging.getLogger(__name__)


@dataclass
class PlanData:
    start: datetime
    """UTC start of slot 0."""
    plan: Plan
    prices: list[float]
    solar_kwh: list[float]
    load_kwh: list[float]
    soc: float
    built: datetime

    def index(self, t: datetime) -> int:
        return int((sources.slot_floor(t) - self.start) / sources.SLOT)

    def slot_time(self, i: int) -> datetime:
        return self.start + sources.SLOT * i


class SmartChargeCoordinator(DataUpdateCoordinator[PlanData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN,
            update_interval=timedelta(minutes=PLAN_INTERVAL_MIN),
        )
        self.conf: dict[str, Any] = {**entry.data}
        self.driver = make_driver(hass, self.conf, self.conf.get(CONF_DRIVER, "none"))
        self.control_enabled = False
        self.charging = False
        self.emergency = False
        self.reason = "Starting"
        self._changed_at = dt_util.utcnow() - timedelta(hours=1)
        self._profile: dict[tuple[bool, int], float] | None = None
        self._profile_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._owned = False
        self._unsub = None

    # -------------------------------------------------------------- options
    @property
    def opts(self) -> dict[str, Any]:
        return {**DEFAULTS, **self.config_entry.options}

    def soc(self) -> float | None:
        st = self.hass.states.get(self.conf[CONF_SOC_ENTITY])
        try:
            return float(st.state) if st else None
        except (TypeError, ValueError):
            return None

    @property
    def effective_floor(self) -> float:
        o = self.opts
        return float(o["min_soc"]) + float(o["reserve_soc"])

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        self._unsub = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=CONTROL_INTERVAL_S),
        )

    async def async_shutdown(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        await super().async_shutdown()

    def _infer_charging(self) -> bool:
        """After a restart, ask the inverter whether a charge is running."""
        kind = self.conf.get(CONF_DRIVER)
        if kind == DRIVER_SWITCH:
            st = self.hass.states.get(self.conf.get(CONF_SWITCH_ENTITY) or "")
            return bool(st and st.state == "on")
        if kind == DRIVER_DIAL_GROWATT:
            soc = self.soc()
            st = self.hass.states.get(self.conf.get(CONF_MINSOC_ENTITY) or "")
            try:
                return soc is not None and st is not None and float(st.state) > soc
            except ValueError:
                return False
        return False

    # ----------------------------------------------------------------- plan
    async def _async_update_data(self) -> PlanData:
        o = self.opts
        soc = self.soc()
        if soc is None:
            raise UpdateFailed("Battery SOC is unavailable")

        now = dt_util.utcnow()
        start = sources.slot_floor(now)
        price_map = await sources.async_get_prices(
            self.hass, self.conf[CONF_PRICE_ENTITY], self.conf.get(CONF_PRICE_AREA) or None,
        )
        prices: list[float] = []
        t = start
        while t in price_map and len(prices) < 192:
            prices.append(price_map[t])
            t += sources.SLOT
        if not prices:
            raise UpdateFailed("No prices for the current slot")

        solar_map = sources.solar_slots(
            self.hass,
            [self.conf.get(CONF_SOLAR_TODAY), self.conf.get(CONF_SOLAR_TOMORROW)],
            float(o["pv_confidence"]),
        )

        if self._profile_at is None or now - self._profile_at > timedelta(hours=6):
            self._profile = await sources.async_load_profile(self.hass, self.conf.get(CONF_LOAD_ENTITY))
            self._profile_at = now

        flat = float(o["fallback_load_w"])

        solar, load = [], []
        for i in range(len(prices)):
            ts = start + sources.SLOT * i
            solar.append(solar_map.get(ts, 0.0))
            if self._profile:
                loc = dt_util.as_local(ts)
                w = self._profile[(loc.weekday() >= 5, loc.hour)]
            else:
                w = flat
            w = (w + float(o["overhead_w"])) * float(o["load_margin"])
            load.append(w * 0.25 / 1000)
        # The slot in progress is partly gone.
        frac = 1 - (now - start) / sources.SLOT
        solar[0] *= frac
        load[0] *= frac

        cap = float(self.conf[CONF_CAPACITY])
        max_soc = float(o["max_soc"])
        inp = PlanInput(
            prices=prices,
            solar_kwh=solar,
            load_kwh=load,
            soc_kwh=soc / 100 * cap,
            floor_kwh=self.effective_floor / 100 * cap,
            max_kwh=max_soc / 100 * cap,
            taper_kwh=min(float(o["taper_soc"]), max_soc) / 100 * cap,
            charge_kwh=float(o["charge_kw"]) * 0.25,
            taper_factor=float(o["taper_factor"]),
            spike_price=float(o["spike_price"]),
            cheap_abs=float(o["cheap_abs"]),
            cheap_fraction=float(o["cheap_fraction"]),
            round_trip=max(float(o["round_trip"]), 0.5),
            wear=float(o["wear_cost"]),
            min_block=int(o["min_block_slots"]),
        )
        plan = await self.hass.async_add_executor_job(build_plan, inp)
        data = PlanData(start=start, plan=plan, prices=prices, solar_kwh=solar,
                        load_kwh=load, soc=soc, built=now)
        self.hass.async_create_task(self._control(data))
        return data

    # -------------------------------------------------------------- control
    @callback
    def _tick(self, _now: datetime) -> None:
        self.hass.async_create_task(self._control(self.data))

    def want_now(self, data: PlanData | None) -> bool:
        if data is None:
            return False
        i = data.index(dt_util.utcnow())
        return 0 <= i < len(data.plan.charge) and data.plan.charge[i]

    async def _control(self, data: PlanData | None) -> None:
        async with self._lock:
            o = self.opts
            soc = self.soc()
            if soc is None:
                self.reason = "Battery SOC unavailable"
                return
            if not self.driver.controls:
                self.reason = "Advisory only, no inverter control configured"
                self.async_update_listeners()
                return
            if not self.control_enabled:
                if self.charging and self._owned:
                    await self._switch(False, soc, "Control turned off")
                self.charging = False
                self.reason = "Control is off"
                self.async_update_listeners()
                return

            floor = self.effective_floor
            if soc <= floor + float(o["emergency_margin"]):
                self.emergency = True
            elif soc >= float(o["emergency_to"]):
                self.emergency = False

            full = soc >= float(o["max_soc"])
            want = (self.want_now(data) or self.emergency) and not full
            minutes = (dt_util.utcnow() - self._changed_at).total_seconds() / 60

            if self.charging and not want:
                if not full and minutes < float(o["min_run_minutes"]):
                    self.reason = "Finishing the minimum run to spare the relay"
                else:
                    await self._switch(False, soc, "Battery full" if full else "Booked block ended")
            elif not self.charging and want:
                if self.emergency:
                    await self._switch(True, soc, "Emergency, battery near the floor")
                elif minutes < float(o["cooldown_minutes"]):
                    self.reason = "Cooling down after the last charge"
                elif float(o["max_soc"]) - soc < 4:
                    self.reason = "Nearly full, not worth a relay operation"
                else:
                    await self._switch(True, soc, "Booked cheap block")
            else:
                self.reason = "Charging" if self.charging else "Waiting for the next booked block"

            try:
                await self.driver.watchdog(self.charging, soc, o)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Watchdog write failed: %s", err)
            self.async_update_listeners()

    async def _switch(self, on: bool, soc: float, why: str) -> None:
        o = self.opts
        try:
            if on:
                await self.driver.start(soc, o)
            else:
                await self.driver.stop(soc, o)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Could not %s charging: %s", "start" if on else "stop", err)
            if on:
                return
        self.charging = on
        self._owned = on
        self._changed_at = dt_util.utcnow()
        self.reason = why
        _LOGGER.info("%s charging: %s (SOC %.0f%%)", "Started" if on else "Stopped", why, soc)

    async def async_set_control(self, enabled: bool) -> None:
        if enabled and not self.control_enabled:
            # Take over a charge that is already running rather than
            # cycling the relay to restart it.
            self.charging = self._infer_charging()
            self._owned = self.charging
        self.control_enabled = enabled
        await self._control(self.data)
