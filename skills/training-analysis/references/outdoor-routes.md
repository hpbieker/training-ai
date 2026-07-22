# Outdoor Route Recommendations

## Candidate Source And Filtering

- Start from saved outdoor activities and actual GPS geometry. Resolve the
  start/end anchor, radius, surface, and bike intent before running helpers.
- Use `scripts/route_recommendations.py` for recommendations and
  `scripts/build_route_catalog.py` for incremental catalog/map-match work.
- Refresh only missing/stale source activity packages. Unnecessary rewrites
  invalidate route caches without adding information.
- If no suitable saved route exists, say so before offering a fallback idea.

## Ranking

Rank route geometry and suitability, not how the historical activity was
executed. Do not score by moving time, load, intensity, watts, recency, activity
name, repeat count, familiarity, or query match. `route_reference_count` is
metadata only.

Use:

- start/end-anchor fit;
- requested distance when supplied;
- actual surface compatibility;
- steady-pedalling terrain and descent disruption;
- map-backed crossings/junction conflicts when requested.

Treat the registered bike as equipment metadata, not proof of surface. Report
road, gravel, or unknown explicitly and explain any mismatch.

## Route Identity And Display

Group and deduplicate by route shape. Treat materially different variants as
separate historical routes. Repair generic display names from meaningful places
on the same route group, but never let naming affect identity or score.

## Terrain And OSM

- For endurance routes, use `steady_endurance` and report both kilometres and
  route percentages above the relevant descent thresholds. Downgrade suspect
  altitude data unless another clean reference supports the same route.
- Use `--junction-source osm` for junction/conflict estimates. Map-match the
  cleaned GPS route first; do not count arbitrary nearby nodes or present GPS
  bearing changes as junctions.
- Treat explicit stop/give-way nodes and inferred priority conflicts as
  planning interruption estimates, not legal proof. Ignore service-road noise
  and evaluate repeated passes independently.
- Reuse `outputs/route-analysis-cache.json`; rebuild it only when OSM data or
  conflict semantics deliberately need refresh.

## Weather, Clothing, And Presentation

- Fetch fresh point forecasts for materially different parts/times of the
  actual route corridor, not one generic point.
- Read `config/cycling-clothing.md` when clothing guidance is requested or
  useful. Recommend known items only when inventory context exists; otherwise
  give generic layers.
- Include a direct saved-activity reference when useful. Embed a locally cached
  route map when the packet provides one; otherwise use the source map URL or
  state that no map was available.
- Do not mention route areas unsupported by the selected geometry or explicit
  user instruction.
