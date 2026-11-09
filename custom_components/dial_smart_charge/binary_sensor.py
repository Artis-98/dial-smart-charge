"""Charge now: on while the plan books the current slot."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import SmartChargeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([ChargeNow(c), Charging(c)])


class ChargeNow(SmartChargeEntity, BinarySensorEntity):
    """For advisory setups: use this in your own automation."""

    def __init__(self, c):
        super().__init__(c, "charge_now")

    @property
    def is_on(self):
        return self.coordinator.want_now(self.coordinator.data)


class Charging(SmartChargeEntity, BinarySensorEntity):
    """On while this integration has a grid charge running."""

    def __init__(self, c):
        super().__init__(c, "charging")

    @property
    def is_on(self):
        return self.coordinator.charging

    @property
    def extra_state_attributes(self):
        return {"emergency": self.coordinator.emergency}
