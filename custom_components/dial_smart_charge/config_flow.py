"""Setup screens. Finds a DIAL and the usual price and solar sensors itself."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector as sel

from .const import (
    CONF_BTB_ENTITY, CONF_CAPACITY, CONF_CURRENT_ENTITY, CONF_DRIVER, CONF_LOAD_ENTITY,
    CONF_MINSOC_ENTITY, CONF_PRICE_AREA, CONF_PRICE_ENTITY, CONF_SOC_ENTITY,
    CONF_SOLAR_TODAY, CONF_SOLAR_TOMORROW, CONF_SWITCH_ENTITY, DEFAULTS, DOMAIN,
    DRIVER_DIAL_GROWATT, DRIVER_NONE, DRIVER_SWITCH, DRIVERS,
)


def _find(hass: HomeAssistant, domain: str, *suffixes: str) -> str | None:
    """First entity of a domain whose id ends with a suffix, DIAL first."""
    found = []
    for ent in er.async_get(hass).entities.values():
        if ent.domain != domain or ent.disabled:
            continue
        for rank, suf in enumerate(suffixes):
            if ent.entity_id.endswith(suf):
                dial = 0 if ent.platform == "esphome" and "dial" in ent.entity_id else 1
                found.append((rank, dial, ent.entity_id))
    return sorted(found)[0][2] if found else None


def _find_price(hass: HomeAssistant) -> str | None:
    for ent in er.async_get(hass).entities.values():
        if ent.domain == "sensor" and ent.platform == "nordpool" and ent.entity_id.endswith("current_price"):
            return ent.entity_id
    for ent in er.async_get(hass).entities.values():
        if ent.domain == "sensor" and ent.platform in ("nordpool", "entsoe", "tibber"):
            return ent.entity_id
    return None


def _ent(domain: str | list[str]) -> sel.EntitySelector:
    return sel.EntitySelector(sel.EntitySelectorConfig(domain=domain))


def _opt(key: str, default: Any) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": default}) if default else vol.Optional(key)


class SmartChargeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_control()
        h = self.hass
        schema = vol.Schema({
            vol.Required(CONF_PRICE_ENTITY, default=_find_price(h) or vol.UNDEFINED): _ent("sensor"),
            vol.Optional(CONF_PRICE_AREA): sel.TextSelector(),
            vol.Required(CONF_SOC_ENTITY, default=_find(h, "sensor", "battery_soc", "battery_state_of_charge", "_soc") or vol.UNDEFINED): _ent("sensor"),
            vol.Required(CONF_CAPACITY, default=5.12): sel.NumberSelector(
                sel.NumberSelectorConfig(min=0.5, max=200, step=0.01, unit_of_measurement="kWh", mode="box")),
            _opt(CONF_LOAD_ENTITY, _find(h, "sensor", "load_power", "house_power", "consumption")): _ent("sensor"),
            _opt(CONF_SOLAR_TODAY, _find(h, "sensor", "solcast_pv_forecast_forecast_today")): _ent("sensor"),
            _opt(CONF_SOLAR_TOMORROW, _find(h, "sensor", "solcast_pv_forecast_forecast_tomorrow")): _ent("sensor"),
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_control(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            kind = user_input[CONF_DRIVER]
            if kind == DRIVER_SWITCH:
                return await self.async_step_switch()
            if kind == DRIVER_DIAL_GROWATT:
                return await self.async_step_dial()
            return self._done()
        has_dial = _find(self.hass, "number", "min_soc_to_start_grid_charge") is not None
        schema = vol.Schema({
            vol.Required(CONF_DRIVER, default=DRIVER_DIAL_GROWATT if has_dial else DRIVER_NONE):
                sel.SelectSelector(sel.SelectSelectorConfig(options=DRIVERS, translation_key="driver")),
        })
        return self.async_show_form(step_id="control", data_schema=schema)

    async def async_step_switch(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self._done()
        schema = vol.Schema({vol.Required(CONF_SWITCH_ENTITY): _ent(["switch", "input_boolean"])})
        return self.async_show_form(step_id="switch", data_schema=schema)

    async def async_step_dial(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self._done()
        h = self.hass
        schema = vol.Schema({
            vol.Required(CONF_BTB_ENTITY, default=_find(h, "number", "back_to_battery_soc") or vol.UNDEFINED): _ent("number"),
            vol.Required(CONF_MINSOC_ENTITY, default=_find(h, "number", "min_soc_to_start_grid_charge") or vol.UNDEFINED): _ent("number"),
            _opt(CONF_CURRENT_ENTITY, _find(h, "number", "charge_current_limit", "max_charge_current")): _ent("number"),
        })
        return self.async_show_form(step_id="dial", data_schema=schema)

    def _done(self) -> ConfigFlowResult:
        return self.async_create_entry(title="DIAL Smart Charge", data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return SmartChargeOptionsFlow()


NUM = {
    "min_soc": (5, 90, 1, "%"),
    "reserve_soc": (0, 30, 1, "%"),
    "max_soc": (50, 100, 1, "%"),
    "charge_kw": (0.1, 50, 0.1, "kW"),
    "taper_soc": (50, 100, 1, "%"),
    "taper_factor": (0.05, 1, 0.05, None),
    "spike_price": (0, 2, 0.005, "/kWh"),
    "cheap_abs": (0, 1, 0.005, "/kWh"),
    "cheap_fraction": (0.1, 2, 0.05, None),
    "round_trip": (0.5, 1, 0.01, None),
    "wear_cost": (0, 0.5, 0.005, "/kWh"),
    "min_block_slots": (1, 16, 1, "slots"),
    "emergency_margin": (0, 20, 1, "%"),
    "emergency_to": (10, 100, 1, "%"),
    "min_run_minutes": (0, 120, 1, "min"),
    "cooldown_minutes": (0, 120, 1, "min"),
    "pv_confidence": (0, 1, 0.05, None),
    "overhead_w": (0, 500, 5, "W"),
    "load_margin": (1, 2, 0.05, None),
    "fallback_load_w": (0, 10000, 10, "W"),
    "start_offset": (1, 50, 1, "%"),
    "max_current": (1, 200, 1, "A"),
}


class SmartChargeOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        cur = {**DEFAULTS, **self.config_entry.options}
        fields = {}
        for key, (lo, hi, step, unit) in NUM.items():
            fields[vol.Required(key, default=cur[key])] = sel.NumberSelector(
                sel.NumberSelectorConfig(min=lo, max=hi, step=step, mode="box",
                                         unit_of_measurement=unit))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
