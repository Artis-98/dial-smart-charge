"""Control switch. Off by default: the plan runs, nothing is touched."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import SmartChargeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ControlSwitch(entry.runtime_data)])


class ControlSwitch(SmartChargeEntity, SwitchEntity, RestoreEntity):
    def __init__(self, c):
        super().__init__(c, "control")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == "on":
            await self.coordinator.async_set_control(True)

    @property
    def is_on(self):
        return self.coordinator.control_enabled

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_control(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_control(False)
        self.async_write_ha_state()
