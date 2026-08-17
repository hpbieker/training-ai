---
name: yr
description: Use when working with Yr/MET Norway Locationforecast data, weather forecasts, forecast source semantics, or live Yr forecast access.
---

# Yr

## Start Here

Use the `get_forecast` MCP tool for all live Yr/MET Norway access. Supply
explicit coordinates, the forecast location's IANA timezone, and `from_local`.
Omit `to_local` for one forecast at or immediately after that time; provide it
for an inclusive local-time window.

Use `get_forecasts` when several already-selected points need forecasts at
different local times, such as estimated arrivals along a route. Provide one
shared timezone and one to 25 requests with unique IDs. This accommodates a
six-hour route sampled at the start and every 15 minutes. The caller still owns
point selection, arrival-time estimates, route meaning, and aggregation.

Pass normalized MCP output to repo helpers through their source-input
interfaces; helpers must not import or invoke the Yr plugin directly.

## Source Semantics

Read [references/forecast.md](references/forecast.md) before
interpreting fields, units, periods, uncertainty, or route limitations.

## Boundaries

- This plugin owns live point-forecast access and Yr/MET Norway semantics.
- The caller chooses forecast points, combines multi-point results, applies
  domain context, and owns persistence, plotting, reports, and decisions.
