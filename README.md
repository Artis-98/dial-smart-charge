# DIAL Smart Charge

A Home Assistant integration that charges your home battery from the grid in
the cheapest hours, and never lets it run down to the floor.

It's built by [IITEG](https://iiteg.com) for [DIAL](https://dial.iiteg.com),
the RS485 inverter link, but it also works without one.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Artis-98&repository=dial-smart-charge&category=integration)

## What it does

Every 15 minutes it simulates your battery forward in 15 minute steps:
today's and tomorrow's prices, the solar forecast, and your house's own daily
load pattern. Wherever the battery would drop through the protected floor,
it books the cheapest **contiguous** block before that moment, then runs the
simulation again.

* **Sun first.** It never buys in slots where the forecast says the panels
  cover the house.
* **Few, long charges.** Every charge start is a click of the inverter's
  transfer relay. Blocks are at least an hour, single slot gaps are bridged,
  and there's a minimum run time and a cooldown.
* **Fill up only when it pays.** A cheap window fills the battery. A dear
  one buys just enough to reach the next cheap window. "Cheap" means cheaper
  than the hours the stored energy will replace, after the round trip loss
  and battery wear.
* **No maximum price.** If the battery needs energy, it buys it. Running
  below the floor is always worse.
* **Emergency top up** if the battery gets close to the floor anyway.

It learns your load from 21 days of recorder history: median per hour,
weekdays and weekends kept separate. It uses a median rather than a mean, so
one afternoon of heavy appliances doesn't skew the plan.

## Install

1. In HACS, add this repository as a custom repository (category
   *Integration*), or use the button above.
2. Install **DIAL Smart Charge** and restart Home Assistant.
3. Go to *Settings → Devices & services → Add integration → DIAL Smart Charge*.

The setup finds a DIAL, Nord Pool and Solcast on its own and fills them in.

## Sources

| What | Supported |
|---|---|
| Prices | Nord Pool (built in integration, 15 minute or hourly), HACS Nord Pool, ENTSO-e, and any sensor with a list of `start` / `price` rows in its attributes |
| Battery | Any state of charge sensor in % |
| Load | Any power sensor in W with long term statistics. Optional; a flat value is used without it |
| Solar | Solcast (`detailedForecast`). Optional |

## Control

Choose one during setup:

* **Advisory only.** You get a *Charge now* sensor to use in your own
  automation. Nothing is touched.
* **A switch.** Any `switch` or `input_boolean` that means "charge from the
  grid".
* **DIAL / Growatt SPF.** It drives the two inverter settings that start and
  stop grid charging: *Back To Battery SOC* and *Min SOC To Start Grid
  Charge*. It ramps the charge current down before stopping, which is gentler
  on the relay. Watchdogs put both settings back if they drift.

Nothing reaches the inverter until you turn on **Control inverter**. It
starts off, so you can watch the plan for a few days first.

## Entities

| Entity | |
|---|---|
| Plan | One line summary. Attributes hold every slot (`start`, `price`, `charge`, `soc`) for charts |
| Next charge | Start of the next booked block |
| Planned energy, Planned average price | What the current plan buys |
| Lowest planned battery | The lowest the battery is expected to go |
| Status | What the controller is doing and why |
| Charge now | On while the current slot is booked |
| Charging | On while this integration has a charge running |
| Control inverter | Master switch, off by default |
| Replan now | Rebuild the plan immediately |

All tuning lives under *Configure*: floor, reserve, charge power, taper,
price preferences, relay protection and more.

## Adding an inverter

The planner is the same for every system. Only the driver differs, so a new
inverter means a new class in `driver.py` with `start`, `stop` and,
optionally, `watchdog`. Pull requests are welcome. Inverter *reading*
belongs in the DIAL firmware: [Artis-98/dial](https://github.com/Artis-98/dial).

## Development

```bash
python -m pytest tests
```

The planner (`planner.py`) is pure Python with no Home Assistant imports, so
it can be tested and backtested on its own.

## License

MIT, © SIA IITEG.
