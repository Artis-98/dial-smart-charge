"""Constants for DIAL Smart Charge."""

DOMAIN = "dial_smart_charge"

# Setup (entry.data)
CONF_PRICE_ENTITY = "price_entity"
CONF_PRICE_AREA = "price_area"
CONF_SOC_ENTITY = "soc_entity"
CONF_CAPACITY = "capacity_kwh"
CONF_LOAD_ENTITY = "load_entity"
CONF_SOLAR_TODAY = "solar_today_entity"
CONF_SOLAR_TOMORROW = "solar_tomorrow_entity"
CONF_DRIVER = "driver"
CONF_SWITCH_ENTITY = "switch_entity"
CONF_BTB_ENTITY = "back_to_battery_entity"
CONF_MINSOC_ENTITY = "min_soc_start_entity"
CONF_CURRENT_ENTITY = "charge_current_entity"

DRIVER_NONE = "none"
DRIVER_SWITCH = "switch"
DRIVER_DIAL_GROWATT = "dial_growatt"
DRIVERS = [DRIVER_NONE, DRIVER_SWITCH, DRIVER_DIAL_GROWATT]

# Tuning (entry.options), with defaults
OPT_MIN_SOC = "min_soc"
OPT_RESERVE = "reserve_soc"
OPT_MAX_SOC = "max_soc"
OPT_CHARGE_KW = "charge_kw"
OPT_TAPER_SOC = "taper_soc"
OPT_TAPER_FACTOR = "taper_factor"
OPT_SPIKE = "spike_price"
OPT_CHEAP_ABS = "cheap_abs"
OPT_CHEAP_FRACTION = "cheap_fraction"
OPT_ROUND_TRIP = "round_trip"
OPT_WEAR = "wear_cost"
OPT_MIN_BLOCK = "min_block_slots"
OPT_EMERGENCY_MARGIN = "emergency_margin"
OPT_EMERGENCY_TO = "emergency_to"
OPT_MIN_RUN = "min_run_minutes"
OPT_COOLDOWN = "cooldown_minutes"
OPT_PV_CONFIDENCE = "pv_confidence"
OPT_OVERHEAD_W = "overhead_w"
OPT_LOAD_MARGIN = "load_margin"
OPT_FALLBACK_LOAD_W = "fallback_load_w"
OPT_START_OFFSET = "start_offset"
OPT_MAX_CURRENT = "max_current"

DEFAULTS = {
    OPT_MIN_SOC: 30,
    OPT_RESERVE: 5,
    OPT_MAX_SOC: 100,
    OPT_CHARGE_KW: 1.8,
    OPT_TAPER_SOC: 85,
    OPT_TAPER_FACTOR: 0.4,
    OPT_SPIKE: 0.15,
    OPT_CHEAP_ABS: 0.03,
    OPT_CHEAP_FRACTION: 0.5,
    OPT_ROUND_TRIP: 0.85,
    OPT_WEAR: 0.045,
    OPT_MIN_BLOCK: 4,
    OPT_EMERGENCY_MARGIN: 3,
    OPT_EMERGENCY_TO: 60,
    OPT_MIN_RUN: 20,
    OPT_COOLDOWN: 20,
    OPT_PV_CONFIDENCE: 0.5,
    OPT_OVERHEAD_W: 40,
    OPT_LOAD_MARGIN: 1.15,
    OPT_FALLBACK_LOAD_W: 300,
    OPT_START_OFFSET: 10,
    OPT_MAX_CURRENT: 40,
}

PLAN_INTERVAL_MIN = 15
CONTROL_INTERVAL_S = 60
