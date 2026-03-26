# homeassistant-powerest

This repository contains a Home Assistant PyScript that estimates battery reserve
and safe export values.

## PyScript

### `src/battery_reserve_estimator.py`

`battery_reserve_estimator.py` runs every 15 minutes (and when key inputs change)
to:

- estimate the required starting battery (`input_number.required_battery_kwh`) to
  avoid hourly deficits,
- estimate how many battery-run hours are currently possible
  (`input_number.battery_hours_remaining`),
- estimate the simulated max battery level
  (`input_number.battery_est_max_level_wh`), and
- compute a safe battery export amount
  (`input_number.battery_safe_export_kwh`) that can still leave `sell_by_wh`
  remaining by the configured `sell_by_time` tomorrow.

At a high level, it:

1. reads historical hourly house consumption from recorder,
2. builds a usage profile aligned by hour,
3. merges all forecast `wh_period` values into a single hourly series,
4. runs the calculation-heavy sufficiency and export simulations in a worker thread via `task.executor`, and
5. writes results to `input_number` helpers and a debug notification.

## Installation

1. Install the [PyScript integration](https://hacs-pyscript.readthedocs.io/) in
   Home Assistant.
2. In your Home Assistant configuration, enable the global `hass` object for
   PyScript because this script reads recorder statistics via
   `hass.services.async_call`:

   ```yaml
   pyscript:
     hass_is_global: true
   ```

3. Copy `src/battery_reserve_estimator.py` from this repository into your Home
   Assistant `<config>/pyscript/` directory.
4. Remove or disable any previous YAML automation version of this estimator so it
   does not run twice.
5. Ensure the following entities already exist with the same names used by the
   previous automation:

   - `sensor.actual_battery_capacity_remaining`
   - `sensor.estimated_daily_power_draw`
   - `sensor.goodwe_house_consumption` (with recorder statistics available)
   - `input_number.battery_false_floor_wh`
   - `input_number.sell_by_wh`
   - `input_number.required_battery_kwh`
   - `input_number.battery_hours_remaining`
   - `input_number.battery_est_max_level_wh`
   - `input_number.battery_safe_export_kwh`
   - all `sensor.home_energy_production_*` forecast sensors referenced in the
     script

6. Reload PyScript or restart Home Assistant.

## Behavior

The PyScript preserves the same entity inputs, trigger cadence, result helpers,
and debug notification output as the prior YAML automation. It also exposes an
optional manual service, `pyscript.battery_reserve_estimator_run`, if you want to
force an immediate recalculation.
