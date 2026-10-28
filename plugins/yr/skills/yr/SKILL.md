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

Pass normalized MCP output to repo helpers through their source-input
interfaces; helpers must not import or invoke the Yr plugin directly.

## Historical Observations

- Use `find_observation_stations` with coordinates, timezone, local window and
  exact Frost element IDs. The search starts with at least three candidates
  (or the requested result limit) and expands through 10, 25 and 50 only when
  coverage is insufficient. Results are ranked by distance among candidates
  with all requested series available in the window. Availability
  metadata does not guarantee complete samples. Check altitude and exposure.
- Use `get_observation_series` for up to 10 known station IDs and 10 elements,
  an inclusive window of up to 31 days, and `PT1H` (default) or `PT10M` resolution.
  Requests are bounded to 50000 expected samples; reduce scope when necessary.
- Use `get_observations` for 1–25 selected point/time requests. It starts with
  three nearby candidates and fetches their observations in one request,
  normally making two API calls per point. It expands to 10, 25 and 50 candidates
  only when coverage is incomplete, fetching only newly encountered stations.
  It prefers complete element coverage then distance, and
  selects the nearest sample per element within `tolerance_minutes` (default
  60, maximum 180). Ties select the earlier sample. Each result uses one station;
  inspect actual times, missing elements, warnings and per-point errors.
- Station metadata and series-availability metadata are cached for 15 minutes
  in the server process, in a bounded cache. Metadata found by a nearest search
  is reused for explicit station reads for the same validity interval. Repeated
  point lookups normally need only the observation request. Observations are
  always fetched fresh. `available_series` is empty for point results because
  those use actual sample coverage rather than a separate availability request.
- Frost reads `frost.client_id` from `~/.yr_mcp.json`; keep this file private
  (0600). `client_secret` may be stored there but is not needed or sent for public
  observations. Never print credentials or put them in tool arguments.
- Read [references/observations.md](references/observations.md) before
  interpreting historical observations, measurement periods or quality codes.

## Source Semantics

Read [references/forecast.md](references/forecast.md) before
interpreting fields, units, periods, uncertainty, or route limitations.

## Boundaries

- This plugin owns point forecasts, Frost station observations and source semantics.
- The caller chooses forecast points, combines multi-point results, applies
  domain context, and owns persistence, plotting, reports, and decisions.
