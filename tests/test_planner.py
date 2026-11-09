"""Planner tests. Run with: python -m pytest tests"""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "planner", Path(__file__).parents[1] / "custom_components/dial_smart_charge/planner.py")
planner = importlib.util.module_from_spec(_spec)
sys.modules["planner"] = planner
_spec.loader.exec_module(planner)
PlanInput, build_plan = planner.PlanInput, planner.build_plan

CAP = 5.12


def make(prices, soc=50, solar=None, load_w=250, **kw):
    n = len(prices)
    return PlanInput(
        prices=prices,
        solar_kwh=solar or [0.0] * n,
        load_kwh=[load_w * 0.25 / 1000] * n,
        soc_kwh=soc / 100 * CAP,
        floor_kwh=0.35 * CAP,
        max_kwh=CAP,
        taper_kwh=0.85 * CAP,
        charge_kwh=1.8 * 0.25,
        **kw,
    )


def test_no_need_no_purchase():
    p = build_plan(make([0.1] * 16, soc=90))
    assert not any(p.charge)
    assert p.shortfall_at is None


def test_buys_in_the_cheap_window_before_the_shortfall():
    # 24 h, cheap 02:00 to 05:00, battery at 45 % would hit the floor.
    prices = [0.20] * 96
    for i in range(8, 20):
        prices[i] = 0.02
    p = build_plan(make(prices, soc=45))
    booked = [i for i, c in enumerate(p.charge) if c]
    assert booked, "should book something"
    assert booked[0] >= 8, booked
    assert p.cost / p.energy_kwh < 0.025
    # Cheap window: filled right up, not just enough to survive.
    assert max(p.soc_kwh) >= CAP * 0.99


def test_blocks_are_contiguous_and_not_tiny():
    prices = [0.20 if i % 3 else 0.05 for i in range(96)]
    p = build_plan(make(prices, soc=40))
    for a, b in p.blocks:
        assert b - a >= 4 or len(p.blocks) == 1


def test_never_books_where_the_sun_covers_the_house():
    prices = [0.10] * 96
    solar = [0.0] * 96
    for i in range(36, 64):  # 09:00 to 16:00
        solar[i] = 0.4
        prices[i] = 0.01  # cheapest of the day, but the sun is free
    p = build_plan(make(prices, soc=60, solar=solar))
    assert not any(p.charge[36:64])


def test_spike_ceiling_is_a_preference():
    # Every slot is above the ceiling: it must still buy rather than fail.
    p = build_plan(make([0.30] * 96, soc=36, spike_price=0.15))
    assert any(p.charge)


def test_budget_is_one_tank():
    p = build_plan(make([0.05] * 192, soc=40, load_w=400))
    assert p.energy_kwh <= CAP * 0.65 + 0.01
