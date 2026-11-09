"""Plan sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy
from homeassistant.util import dt as dt_util

from .entity import SmartChargeEntity

MAX_ATTR_SLOTS = 96


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([
        PlanSensor(c), NextChargeSensor(c), EnergySensor(c), AvgPriceSensor(c),
        SocForecastSensor(c), StatusSensor(c),
    ])


class PlanSensor(SmartChargeEntity, SensorEntity):
    """State is a one line summary. Attributes hold every slot, for charts."""

    def __init__(self, c):
        super().__init__(c, "plan")

    @property
    def native_value(self):
        d = self.coordinator.data
        if d is None:
            return None
        p = d.plan
        if not p.blocks:
            return f"Nothing to buy for the next {len(d.prices) / 4:.1f} h"
        a, b = p.blocks[0]
        t0 = dt_util.as_local(d.slot_time(a)).strftime("%a %H:%M")
        t1 = dt_util.as_local(d.slot_time(b)).strftime("%H:%M")
        more = f", +{len(p.blocks) - 1} more" if len(p.blocks) > 1 else ""
        return f"{t0} to {t1}, {p.energy_kwh:.1f} kWh at {p.avg_price:.3f}{more}"

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data
        if d is None:
            return None
        p = d.plan
        blocks = []
        for a, b in p.blocks:
            blocks.append({
                "start": dt_util.as_local(d.slot_time(a)).isoformat(),
                "end": dt_util.as_local(d.slot_time(b)).isoformat(),
                "avg_price": round(sum(d.prices[a:b]) / (b - a), 4),
            })
        cap = float(self.coordinator.conf["capacity_kwh"])
        slots = []
        for i in range(min(len(d.prices), MAX_ATTR_SLOTS)):
            slots.append({
                "start": dt_util.as_local(d.slot_time(i)).isoformat(),
                "price": round(d.prices[i], 4),
                "charge": p.charge[i],
                "soc": round(p.soc_kwh[i] / cap * 100, 1),
            })
        return {
            "blocks": blocks,
            "horizon_hours": len(d.prices) / 4,
            "cost": round(p.cost, 3),
            "shortfall_at": dt_util.as_local(d.slot_time(p.shortfall_at)).isoformat()
            if p.shortfall_at is not None else None,
            "built": dt_util.as_local(d.built).isoformat(),
            "slots": slots,
        }


class NextChargeSensor(SmartChargeEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, c):
        super().__init__(c, "next_charge")

    @property
    def native_value(self):
        d = self.coordinator.data
        if d is None or not d.plan.blocks:
            return None
        now_i = d.index(dt_util.utcnow())
        for a, b in d.plan.blocks:
            if b > now_i:
                return d.slot_time(max(a, 0))
        return None


class EnergySensor(SmartChargeEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, c):
        super().__init__(c, "planned_energy")

    @property
    def native_value(self):
        d = self.coordinator.data
        return round(d.plan.energy_kwh, 3) if d else None


class AvgPriceSensor(SmartChargeEntity, SensorEntity):
    _attr_suggested_display_precision = 4

    def __init__(self, c):
        super().__init__(c, "planned_price")

    @property
    def native_unit_of_measurement(self):
        return f"{self.hass.config.currency}/kWh"

    @property
    def native_value(self):
        d = self.coordinator.data
        return round(d.plan.avg_price, 4) if d and d.plan.avg_price is not None else None


class SocForecastSensor(SmartChargeEntity, SensorEntity):
    """Lowest battery level the plan expects in the horizon."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, c):
        super().__init__(c, "lowest_soc")

    @property
    def native_value(self):
        d = self.coordinator.data
        if d is None or not d.plan.soc_kwh:
            return None
        return round(min(d.plan.soc_kwh) / float(self.coordinator.conf["capacity_kwh"]) * 100, 1)


class StatusSensor(SmartChargeEntity, SensorEntity):
    """What the controller is doing and why, in words."""

    def __init__(self, c):
        super().__init__(c, "status")

    @property
    def native_value(self):
        return self.coordinator.reason
