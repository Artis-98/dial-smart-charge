"""Replan now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .entity import SmartChargeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ReplanButton(entry.runtime_data)])


class ReplanButton(SmartChargeEntity, ButtonEntity):
    def __init__(self, c):
        super().__init__(c, "replan")

    async def async_press(self):
        await self.coordinator.async_request_refresh()
