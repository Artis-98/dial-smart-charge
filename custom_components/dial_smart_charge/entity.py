"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartChargeCoordinator


class SmartChargeEntity(CoordinatorEntity[SmartChargeCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartChargeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="DIAL Smart Charge",
            manufacturer="IITEG",
            model="Smart Charge planner",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://github.com/Artis-98/dial-smart-charge",
        )
