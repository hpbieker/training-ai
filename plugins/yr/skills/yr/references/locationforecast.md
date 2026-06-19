# Yr/MET Norway Locationforecast

Yr uses MET Norway's public Locationforecast API for point forecasts. The local client calls the compact endpoint:

```text
https://api.met.no/weatherapi/locationforecast/2.0/compact
```

The API requires a non-generic `User-Agent` with contact information. The local client sets `codex-yr-plugin/0.1 github.com/hanspetterbieker` by default.

## Interpreting Fields

- `properties.timeseries[].time` is the forecast timestamp in UTC.
- `data.instant.details` contains instantaneous conditions such as air temperature, humidity, wind speed, wind direction, gusts and cloud cover.
- `data.next_1_hours`, `data.next_6_hours` and `data.next_12_hours` summarize upcoming periods when available.
- `precipitation_amount` is the expected precipitation amount for the period block, not an instantaneous rain rate.
- `summary.symbol_code` is useful for readable conditions, but consumers should also inspect precipitation, wind, gusts and temperature when those conditions matter.

## Usage Notes

Fetch one or more relevant forecast points for the area being evaluated. Callers can pass custom coordinates when a specific anchor point is needed. For a planned route or other time/place sequence, treat it as an ordered list of forecast points and fetch each relevant point explicitly.

Use fresh live data for time-sensitive decisions.

Use local timezone conversion at the presentation boundary when explaining forecast times. Keep source timestamps intact in source payloads.
