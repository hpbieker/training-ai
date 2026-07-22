# Locationforecast Semantics

## Interpreting Fields

- `properties.timeseries[].time` is the forecast timestamp in UTC.
- `data.instant.details` contains conditions at that timestamp.
- `data.next_1_hours`, `data.next_6_hours` and `data.next_12_hours` describe
  periods starting at that timestamp.
- `precipitation_amount` is the total for its period, not an instantaneous rate.
- Do not use `summary.symbol_code` alone when precipitation, wind, gusts or
  temperature matter.

## Usage Notes

- Use fresh data for time-sensitive decisions.
- Keep source timestamps in UTC; use the forecast location's explicit timezone
  for filtering and presentation.
- Model route weather as separate relevant time/place point forecasts.
- The caller owns caching and should respect MET Norway's response headers.
