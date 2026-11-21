# Route Planner

A local MCP server that plans cycling routes using BRouter and OpenStreetMap.
It uses the bundled `assets/profiles/fastbike-road-flow.brf` cycling profile.

```sh
python3 scripts/build_plugin.py route-planner
codex plugin add route-planner@training-ai
```

Call `plan_route` with `start`, `end` and optional `waypoints` in travel order.
Coordinates are objects with `lat` and `lon`.
The server sends coordinates and the cycling profile to BRouter. It checks
that the route passes the supplied points in order, within 100 m at the
endpoints and 15 m at intermediate waypoints.

The tool returns a route ID, revision, distance, estimated time, routing cost,
and verified points. It saves the route and its GeoJSON locally.

Set `ROUTE_PLANNER_ROUTES` to select a local directory for saved routes.
