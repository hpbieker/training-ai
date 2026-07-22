# Locationforecast Semantics

## Interpreting Fields

- `properties.timeseries[].time` is the forecast timestamp in UTC.
- `data.instant.details` contains conditions at that timestamp.
- `data.next_1_hours`, `data.next_6_hours` and `data.next_12_hours` describe
  periods starting at that timestamp.
- `air_temperature` is degrees C, `relative_humidity` and
  `cloud_area_fraction` are percentages, and wind speed/gust are m/s.
- `wind_from_direction` is degrees clockwise from north and describes where the
  wind comes from, not where it is going.
- `precipitation_amount` is millimetres accumulated over its named period, not
  an instantaneous rate.
- Do not use `summary.symbol_code` alone when precipitation, wind, gusts or
  temperature matter.

## Usage Notes

- Use fresh data for time-sensitive decisions.
- Keep source timestamps in UTC; use the forecast location's explicit timezone
  for filtering and presentation.
- Model route weather as separate relevant time/place point forecasts.
- Long-range periods may lack `next_1_hours`; do not relabel a 6- or 12-hour
  precipitation total as hourly rain.
- The caller owns caching and should respect MET Norway's response headers.
