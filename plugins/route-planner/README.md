# Route Planner

A local MCP server that plans cycling routes using BRouter and OpenStreetMap.
It uses the bundled `assets/profiles/fastbike-road-flow.brf` cycling profile.

Install Node.js and `npm` alongside `uv` before building the plugin.

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

Call `find_road_points` with up to ten `locations`. Each location needs a
`near` coordinate and can include an exact street name or road number in
`road`. The tool sends coordinates to the public
[Valhalla demo server](https://github.com/valhalla/valhalla#demo-server)
and returns up to five candidates within 300 m for each location. Candidates
are mapped roads open to cars and bicycles. Check the returned road name
or reference before using its coordinate in `plan_route` or `update_route`.

Call `show_route` to open the interactive map. Pass a saved `route_id`, an
absolute `route_file` path to GPX, GeoJSON or training-ai route JSON, or
inline `geojson`. Imported tracks keep their segment breaks. They can
include display metadata such as title, date, distance and elevation gain.

The map shows pinned waypoints and picks up new saved revisions. On a saved
route, drag a waypoint to move it, select it to remove it, or drag the route
line to insert one. Where route sections overlap, choose the section before
the waypoint is saved. GeoJSON and GPX imports are displayed as read-only tracks.

The map
requests visible OpenStreetMap tiles and caches them locally for seven
days. Tile requests reveal the viewed area to the tile provider.

Set `ROUTE_PLANNER_ROUTES` to select a local directory for saved routes.

### Street View

Hold Shift and click the map to open a nearby Google Street View panorama.
Clicks within 25 m of the route use its direction of travel as the initial
camera heading. Opening Street View sends the selected point to Google.

To enable Street View, save the browser key in `~/.route_planner_mcp.json`.

```json
{
  "google_maps_embed_key": "<google-maps-embed-key>"
}
```

Restrict the browser key to the
[Maps Embed API](https://developers.google.com/maps/documentation/embed/embedding-map)
and the URL that hosts the Codex map. The map UI uses the key in the Embed URL.

### Local map preview

Run from the Route Planner plugin directory after installing Node.js and `uv`.
The preview loads the MCP map resource and serves it through the MCP Apps
bridge on loopback. To test changes to a saved route, use a disposable route
ID in the arguments file. Map edits recalculate and save that route.

```sh
npm --prefix web ci
npm --prefix web run build:preview
uv run --no-project --with-requirements requirements.txt python -B scripts/preview.py --arguments /absolute/path/to/arguments.json
```

Open `http://127.0.0.1:8767/`. The arguments file is a JSON object with the
same inputs as `show_route`.

For local development, set the optional `google_maps_javascript_key` in
`~/.route_planner_mcp.json` to enable the Maps JavaScript API panorama at the
preview root. Restrict the browser key to the Maps JavaScript API and the
loopback preview origin.
With that key, the minimap follows the reported panorama position and
camera heading. Shift-click checks for a panorama within 50 m and shows a
brief hint when none is available. Open `/mcp-test` to test the MCP Apps
bridge and Maps Embed mode.
