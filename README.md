# homeassistant-powerest

This repository contains a Home Assistant automation that estimates battery reserve and safe export values.

## Automation

### `src/automation.battery_reserve_estimator.yaml`

`Battery: Reserve Estimator` runs every 15 minutes (and when key inputs change) to:

- estimate the required starting battery (`input_number.required_battery_kwh`) to avoid hourly deficits,
- estimate how many zero-draw days are currently possible (`input_number.zero_draw_days_possible`),
- estimate the simulated max battery level (`input_number.battery_est_max_level_wh`), and
- compute safe battery export amount (`input_number.battery_safe_export_kwh`) that
  can still leave `sell_by_wh` remaining by the configured `sell_by_time` tomorrow.

At a high level, it:

1. reads historical hourly house consumption from recorder,
2. builds a usage profile aligned by hour,
3. merges all forecast `wh_period` values into a single hourly series,
4. runs sufficiency and export simulations, and
5. writes results to `input_number` helpers and a debug notification.
