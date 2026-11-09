"""DIAL Smart Charge: buy grid energy for a home battery at the cheapest time."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SmartChargeCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.BUTTON]

type SmartChargeConfigEntry = ConfigEntry[SmartChargeCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SmartChargeConfigEntry) -> bool:
    coordinator = SmartChargeCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SmartChargeConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_shutdown()
    return ok


async def _reload(hass: HomeAssistant, entry: SmartChargeConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
