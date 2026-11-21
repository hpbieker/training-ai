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

Call `inspect_route` with a saved `route_id` or the absolute path to a BRouter
GeoJSON `route_file`. It reports road types, surfaces and access tags from the
file, with totals and sections in travel order. Optionally filter by
`distance_range` (`from_km`, `to_km`) or, for saved routes, `waypoint_range`
(`from_waypoint_id`, `to_waypoint_id`). Section offsets are measured from
the route start. Filtered tag totals are prorated by overlap with the
saved geometry. Sections with missing or unmatched metadata are marked
`unknown`.

Call `locate_on_route` with a saved `route_id` and a coordinate in `near`.
The optional `radius_m` defaults to 100 m and accepts values up to 1,000 m.
The tool returns the closest point for each separate passage, in travel
order, with distance from the route start, offset from the lookup point and
bearing clockwise from true north. Road names and references come from
saved metadata when available.

Call `evaluate_route_change` with the same inputs as `update_route` to
preview a change without saving a revision. It sends the proposed coordinates
and bundled profile to BRouter. The result includes the base revision,
before and after distances, the distance difference in metres, and up to
20 changed sections in travel order. `same_profile` reports whether the
saved route used the same profile, or is null if its profile hash is unknown.
Changes in coordinate sampling can appear as changes to the route.

Call `search_places` with a public place name in `query`. Optionally add
`near` to rank the matches by distance locally. Treat returned coordinates
as representative points for places, and verify any waypoint on its road.

The default service follows [Nominatim's usage policy](https://operations.osmfoundation.org/policies/nominatim/).
Use it for individual searches triggered by a user. Keep personal and
confidential information out of queries. The public service prohibits
autocomplete and systematic lookups. The plugin sends at most one request
per second across local processes and caches responses for 24 hours.
Use `ROUTE_PLANNER_GEOCODER_URL` to select a Nominatim-compatible service.

Set `ROUTE_PLANNER_ROUTES` to select a local directory for saved routes.
