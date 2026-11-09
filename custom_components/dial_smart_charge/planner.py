"""The charge planner. Pure Python, no Home Assistant imports, so it can be
tested and backtested on its own.

It is a battery simulation, not a shopping list. Starting from the live state
of charge it walks forward in 15 minute slots, adding forecast solar and
taking away forecast load. Wherever the battery would fall through the
protected floor it books the cheapest contiguous block before that moment and
walks again, until the horizon survives or one battery's worth is booked.

Why contiguous blocks: every separate charge session is another operation of
the inverter's transfer relay. A few long charges beat many short ones even
when scattered slots would be marginally cheaper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

SLOT_HOURS = 0.25


@dataclass
class PlanInput:
    """Everything the planner needs. All energy in kWh, prices per kWh."""

    prices: list[float]
    """Price of every slot from now. The list ends where the market data ends."""
    solar_kwh: list[float]
    load_kwh: list[float]
    soc_kwh: float
    floor_kwh: float
    """Protected floor: the battery must never be planned below this."""
    max_kwh: float
    taper_kwh: float
    """Above this the battery accepts charge more slowly."""
    charge_kwh: float
    """Energy one slot of grid charging puts in, below the taper."""
    taper_factor: float = 0.4
    spike_price: float = 0.15
    """Preferred ceiling. A preference, not a gate: relaxed if nothing fits."""
    cheap_abs: float = 0.03
    """Below this a window is always worth filling right up."""
    cheap_fraction: float = 0.5
    """A block within this fraction of the median price fills right up."""
    round_trip: float = 0.85
    wear: float = 0.045
    """Battery wear cost per kWh cycled."""
    min_block: int = 4
    max_attempts: int = 48


@dataclass
class Plan:
    charge: list[bool]
    soc_kwh: list[float]
    """Simulated energy at the end of each slot, with the plan applied."""
    blocks: list[tuple[int, int]] = field(default_factory=list)
    """Booked blocks as (first slot, slot after the last)."""
    energy_kwh: float = 0.0
    avg_price: float | None = None
    cost: float = 0.0
    shortfall_at: int | None = None
    """First slot where the battery still falls through the floor, if any."""


def _slots_to_fill(from_kwh: float, inp: PlanInput, load: float = 0.0) -> int:
    """Slots to charge from from_kwh to full, with the house still drawing
    load per slot while it charges, and the slow phase above the taper."""
    bulk = max(min(inp.taper_kwh, inp.max_kwh) - from_kwh, 0.0)
    top = max(inp.max_kwh - max(inp.taper_kwh, from_kwh), 0.0)
    slots = (bulk / max(inp.charge_kwh - load, 0.01)
             + top / max(inp.charge_kwh * inp.taper_factor - load, 0.01))
    return max(math.ceil(slots - 1e-9), 1)


def simulate(inp: PlanInput, chosen: set[int]) -> tuple[list[float], int | None]:
    """Walk the battery forward. Returns the trajectory and the first failure."""
    e = inp.soc_kwh
    traj: list[float] = []
    fail: int | None = None
    for i in range(len(inp.prices)):
        add = 0.0
        if i in chosen:
            add = inp.charge_kwh * (inp.taper_factor if e >= inp.taper_kwh else 1.0)
        e = max(min(e + inp.solar_kwh[i] + add - inp.load_kwh[i], inp.max_kwh), 0.0)
        traj.append(e)
        if fail is None and e < inp.floor_kwh:
            fail = i
    return traj, fail


def _runs(slots: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for i in sorted(slots):
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def build_plan(inp: PlanInput) -> Plan:
    n = len(inp.prices)
    if n == 0 or inp.charge_kwh <= 0:
        traj, fail = simulate(inp, set())
        return Plan(charge=[False] * n, soc_kwh=traj, shortfall_at=fail)

    prices = inp.prices
    ordered = sorted(prices)
    median = ordered[len(ordered) // 2]

    # How many slots one full battery can carry at the forecast load, and the
    # mean of that many of the dearest slots in view. That is what stored
    # energy really displaces, so it is the bar a purchase has to beat after
    # paying for the round trip and the wear.
    mean_load = max(sum(inp.load_kwh) / n, 0.0125)
    cover = max(round((inp.max_kwh - inp.floor_kwh) / mean_load), 4)
    dear = ordered[::-1][:cover]
    avoid = sum(dear) / len(dear) if dear else median

    def worth(p: float) -> bool:
        return p <= inp.cheap_abs or p / inp.round_trip + inp.wear < avoid

    # Slots where forecast solar alone covers the house. Buying then is
    # pointless, the battery fills for free.
    sun_covers = [inp.solar_kwh[i] > 0 and inp.solar_kwh[i] >= inp.load_kwh[i]
                  for i in range(n)]

    fill = _slots_to_fill(inp.floor_kwh, inp, mean_load)
    # One tank, not a whole horizon of buying: at most what it takes to go
    # from the floor to full. Measured from the floor rather than from the
    # level now, because the house drains the battery before the cheap
    # window arrives. The next replan books the next window afresh.
    budget = fill

    chosen: set[int] = set()
    for _ in range(inp.max_attempts):
        if len(chosen) >= budget:
            break
        traj, fail = simulate(inp, chosen)
        if fail is None:
            break
        best: tuple[float, int, int] | None = None  # (avg, start, length)
        # Relax in order: full block under the ceiling, full block at any
        # price, short block under the ceiling, anything.
        for pss in range(4):
            min_len = min(fill, 4) if pss < 2 else 1
            ceiling = inp.spike_price if pss in (0, 2) else math.inf
            for s in range(0, fail + 1):
                # A cheap window may run past the failure point to fill the
                # battery; a dear one only buys enough to survive.
                cap_at = n if worth(prices[s]) else fail + 1
                length = min(fill, cap_at - s)
                if length < min_len:
                    continue
                window = range(s, s + length)
                if any(prices[k] > ceiling for k in window):
                    continue
                if pss < 3 and any(sun_covers[k] for k in window):
                    continue
                if all(k in chosen for k in window):
                    continue
                avg = sum(prices[k] for k in window) / length
                if best is None or avg < best[0]:
                    best = (avg, s, length)
            if best is not None:
                break
        if best is None:
            break
        avg, s, length = best
        # Fill right up in a cheap window. In a dear one buy the minimum
        # block and let the next pass find something better.
        if avg <= inp.cheap_abs or avg <= median * inp.cheap_fraction or worth(avg):
            take = length
        else:
            take = min(min(fill, 4), length)
        # Never more than it takes to fill from the level the battery will
        # actually be at when this block starts.
        level = inp.soc_kwh if s == 0 else traj[s - 1]
        take = min(take, _slots_to_fill(min(level, inp.max_kwh), inp, mean_load))
        room = max(budget - len(chosen), 0)
        for k in range(min(take, room)):
            chosen.add(s + k)

    # Tidy the booking. Bridge single slot gaps, they are cheaper joined than
    # served as two sessions. Then drop runs shorter than min_block, unless
    # every run is short, because then short is all there is.
    raw = sorted(chosen)
    bridged = set(raw)
    for i in raw:
        if i + 2 in bridged and i + 1 not in bridged and i + 1 < n:
            bridged.add(i + 1)
    runs = _runs(sorted(bridged))
    longest = max((len(r) for r in runs), default=0)
    keep = [i for r in runs if len(r) >= inp.min_block or longest < inp.min_block for i in r]
    final = set(keep)

    # Drop booked slots where the battery is already full: they buy nothing
    # and only keep the inverter on the grid.
    # Once a block reaches full, the rest of that block goes, so a block is
    # cut cleanly rather than chopped into pieces near the top.
    e = inp.soc_kwh
    done = False
    for i in range(n):
        add = 0.0
        if i in final:
            if done or e >= inp.max_kwh - 1e-6:
                final.discard(i)
                done = True
            else:
                add = inp.charge_kwh * (inp.taper_factor if e >= inp.taper_kwh else 1.0)
        else:
            done = False
        e = min(e + inp.solar_kwh[i] + add - inp.load_kwh[i], inp.max_kwh)
    keep = sorted(final)

    traj, fail = simulate(inp, final)
    charge = [i in final for i in range(n)]
    blocks = [(r[0], r[-1] + 1) for r in _runs(keep)]

    # Energy actually delivered, replaying the taper.
    energy = 0.0
    cost = 0.0
    e = inp.soc_kwh
    for i in range(n):
        add = 0.0
        if charge[i]:
            add = inp.charge_kwh * (inp.taper_factor if e >= inp.taper_kwh else 1.0)
            add = min(add, max(inp.max_kwh - e, 0.0))
            energy += add
            cost += add * prices[i]
        e = min(e + inp.solar_kwh[i] + add - inp.load_kwh[i], inp.max_kwh)

    avg_price = sum(prices[i] for i in final) / len(final) if final else None
    return Plan(
        charge=charge,
        soc_kwh=traj,
        blocks=blocks,
        energy_kwh=energy,
        avg_price=avg_price,
        cost=cost,
        shortfall_at=fail,
    )
