# Route Planner

A local MCP server that plans cycling routes using BRouter and OpenStreetMap.
It uses the bundled `assets/profiles/fastbike-road-flow.brf` cycling profile.

```sh
python3 scripts/build_plugin.py route-planner
codex plugin add route-planner@training-ai
```

Call `plan_route` with `start`, `end` and optional `waypoints` in travel order.
Coordinates are objects with `lat` and `lon`.
The server sends coordinates and the cycling profile to BRouter. Both
`plan_route` and `update_route` check that the route passes the requested
points in order. The default limits are 100 m for start and end and 15 m
for intermediate waypoints.

The tool returns a route ID, revision, distance, estimated time, routing cost,
and verified points. It saves the route and its GeoJSON locally.

Call `update_route` with `route_id`, the `expected_revision` from the last
successful call, and the requested change. Use `add_waypoint`, `move_waypoint`,
or `remove_waypoint_id` to edit one waypoint, or pass `waypoints` in travel
order to replace the list. A waypoint ID alone keeps its existing coordinates.
You can also replace `start` or `end`. Set `snap_to_route: true` when adding or
moving a waypoint to raise the limit for that point to 50 m. The tool then
saves the position on the calculated route.

The tool returns the new revision and verified points. If calculation fails
or the saved revision has changed, the update leaves the current route intact.
If the revision has changed, call `get_route` before retrying.

Call `get_route` with `route_id` to read the current saved summary, including
its revision and ordered waypoint IDs.

Call `export_route` with `route_id` to get a local GPX file. Set `format` to
`geojson` to get the saved GeoJSON. The result includes the exported revision
and the local file path.

Set `ROUTE_PLANNER_ROUTES` to select a local directory for saved routes.
