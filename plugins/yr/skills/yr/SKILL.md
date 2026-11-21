---
name: yr
description: Use for Yr/MET Norway forecasts, Frost historical station observations, station discovery, and weather source semantics.
---

# Yr

## Start Here

Use the `get_forecast` MCP tool for live Yr/MET Norway forecasts. Supply
explicit coordinates, the forecast location's IANA timezone, and `from_local`.
Omit `to_local` for one forecast at or immediately after that time; provide it
for an inclusive local-time window.

Use `get_forecasts` when several already-selected points need forecasts at
different local times, such as estimated arrivals along a route. Provide one
shared timezone and one to 25 requests with unique IDs. This accommodates a
six-hour route sampled at the start and every 15 minutes. The caller still owns
point selection, arrival-time estimates, route meaning, and aggregation.

Use `get_route_forecasts_summary` for a GeoJSON LineString in longitude/latitude
order, a local start and a planned duration. It samples five points by default,
including start and finish, with a forecast window of 30 minutes on each side
of passage. Supply `elapsed_seconds` aligned with the coordinates to scale a
recorded ride's timing. Check coverage and missing hours. Precipitation sums
the complete source hours overlapping the requested window, including partial
boundary hours at their full amount.

Pass normalized MCP output to repo helpers through their source-input
interfaces; helpers must not import or invoke the Yr plugin directly.

## Historical Observations

- Use `get_route_observations_summary` with a GeoJSON LineString, a shared
  historical window and the desired Frost elements. Each sampled route point
  references nearby stations and shared summaries. Check station distance,
  altitude and measurement gaps before applying the summaries to the route.
- Use `find_observation_stations` to locate stations and check series
  availability. Inspect distance, altitude and exposure. Availability metadata
  alone does not establish that all expected samples are present.
- Use `get_observation_series` to read time series from known station IDs.
- Use `get_observations_summary` to compare temperature, precipitation and
  snow depth over a shared window. Check missing hours and station
  representativeness. Frost snow depth `-1` marks zero depth or partial snow
  cover. Calculate a change only when both samples report a measured depth.
- Use `get_observations` for observations near selected points and times.
  Inspect the actual times, missing elements, warnings and per-point errors.
- Read [references/observations.md](references/observations.md) before
  interpreting historical observations, measurement periods or quality codes.

## Source Semantics

Read [references/forecast.md](references/forecast.md) before
interpreting fields, units, periods, uncertainty, or route limitations.

## Boundaries

- This plugin owns point forecasts, Frost station observations and source semantics.
- The caller chooses forecast points, combines multi-point results, applies
  domain context, and owns persistence, plotting, reports, and decisions.
