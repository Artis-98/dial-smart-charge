"""Drivers: how a charge decision reaches the inverter.

The planner is the same for everyone. Only this part differs between
inverters, so a new inverter means a new driver here, nothing else.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_BTB_ENTITY,
    CONF_CURRENT_ENTITY,
    CONF_MINSOC_ENTITY,
    CONF_SWITCH_ENTITY,
    DRIVER_DIAL_GROWATT,
    DRIVER_SWITCH,
)

_LOGGER = logging.getLogger(__name__)


class Driver:
    """Advisory only: the plan and the Charge now sensor, no control."""

    controls = False

    def __init__(self, hass: HomeAssistant, conf: dict[str, Any]) -> None:
        self.hass = hass
        self.conf = conf

    async def start(self, soc: float, opts: dict[str, Any]) -> None:
        """Begin grid charging."""

    async def stop(self, soc: float, opts: dict[str, Any]) -> None:
        """End grid charging."""

    async def watchdog(self, charging: bool, soc: float, opts: dict[str, Any]) -> None:
        """Put the inverter back if it drifted from what we asked for."""

    async def _set_number(self, entity_id: str | None, value: float) -> None:
        if not entity_id:
            return
        st = self.hass.states.get(entity_id)
        if st is not None:
            lo = st.attributes.get("min")
            hi = st.attributes.get("max")
            if lo is not None:
                value = max(value, float(lo))
            if hi is not None:
                value = min(value, float(hi))
        domain = entity_id.split(".", 1)[0]
        await self.hass.services.async_call(
            domain, "set_value", {"entity_id": entity_id, "value": value}, blocking=True,
        )

    def _num(self, entity_id: str | None) -> float | None:
        st = self.hass.states.get(entity_id) if entity_id else None
        try:
            return float(st.state) if st else None
        except (TypeError, ValueError):
            return None


class SwitchDriver(Driver):
    """Any switch or input_boolean that means "charge from the grid"."""

    controls = True

    async def _turn(self, on: bool) -> None:
        eid = self.conf.get(CONF_SWITCH_ENTITY)
        if not eid:
            return
        await self.hass.services.async_call(
            "homeassistant", "turn_on" if on else "turn_off", {"entity_id": eid}, blocking=True,
        )

    async def start(self, soc, opts):
        await self._turn(True)

    async def stop(self, soc, opts):
        await self._turn(False)


class DialGrowattDriver(Driver):
    """Growatt SPF through DIAL (or any Modbus link exposing the same two
    registers). There is no charge switch on these inverters. Grid charging
    is started by raising Back To Battery SOC first, then Min SOC To Start
    Grid Charge above the current SOC, and stopped in the reverse order.

    Leaving Min SOC at the floor when idle is deliberate: it is the
    inverter's own low battery rescue if Home Assistant goes down.
    """

    controls = True

    async def start(self, soc, opts):
        btb = self.conf.get(CONF_BTB_ENTITY)
        mins = self.conf.get(CONF_MINSOC_ENTITY)
        cur = self.conf.get(CONF_CURRENT_ENTITY)
        if cur:
            await self._set_number(cur, float(opts["max_current"]))
        await self._set_number(btb, 100)
        await asyncio.sleep(5)
        await self._set_number(mins, min(100, round(soc) + float(opts["start_offset"])))

    async def stop(self, soc, opts):
        btb = self.conf.get(CONF_BTB_ENTITY)
        mins = self.conf.get(CONF_MINSOC_ENTITY)
        cur = self.conf.get(CONF_CURRENT_ENTITY)
        # Ramp down before the relay drops, it switches far more gently.
        if cur:
            for amps in (20, 10, 5):
                now = self._num(cur)
                if now is None or now > amps:
                    await self._set_number(cur, amps)
                    await asyncio.sleep(3)
        for eid, val in ((mins, float(opts["min_soc"])), (btb, round(soc))):
            try:
                await self._set_number(eid, val)
            except Exception as err:  # noqa: BLE001 always try the second write
                _LOGGER.warning("Stop write to %s failed: %s", eid, err)
        # The current register caps solar charging too, so give it back.
        if cur:
            await self._set_number(cur, float(opts["max_current"]))

    async def watchdog(self, charging, soc, opts):
        btb = self.conf.get(CONF_BTB_ENTITY)
        mins = self.conf.get(CONF_MINSOC_ENTITY)
        b, m = self._num(btb), self._num(mins)
        if charging:
            # The inverter only pulls from the grid while Min SOC is above SOC.
            if m is not None and m <= soc and soc < float(opts["max_soc"]):
                await self._set_number(mins, min(100, round(soc) + float(opts["start_offset"])))
        else:
            # Left high, these make the inverter grid charge on its own.
            if m is not None and m > float(opts["min_soc"]) + 0.5:
                await self._set_number(mins, float(opts["min_soc"]))
            if b is not None and b > soc + 2:
                await self._set_number(btb, round(soc))


def make_driver(hass: HomeAssistant, conf: dict[str, Any], kind: str) -> Driver:
    if kind == DRIVER_SWITCH:
        return SwitchDriver(hass, conf)
    if kind == DRIVER_DIAL_GROWATT:
        return DialGrowattDriver(hass, conf)
    return Driver(hass, conf)
