# Route Planner

An MCP server for cycling routes using BRouter.de and OpenStreetMap data.
It uses the bundled [`fastbike-road-flow.brf`](assets/profiles/fastbike-road-flow.brf) profile.

Follow the repository’s [plugin installation instructions](../../README.md#plugin-installation)
for `route-planner`.

## Tools

- `search_places`: look up a public place named in a route request via
  [Nominatim](https://operations.osmfoundation.org/policies/nominatim/).
  Use it for individual, user-triggered route requests. Keep private addresses
  and other personal or confidential data out of queries. Autocomplete, bulk
  searches and periodic jobs are outside this workflow. The plugin sends at
  most one request per second across local processes and caches successful
  replies for 24 hours in the system temporary directory. Optional `near`
  (`lat`, `lon`) ranks the returned matches locally. Coordinates are
  representative place locations. Use `find_road_points` for carriageway guides.
- `find_road_points`: pass up to ten `locations`, each with an approximate
  `near` point and an optional exact street name or road reference as `road`. The
  tool uses an external OpenStreetMap-based service to return up to five
  carriageway candidates per location within 300 m, with points on the mapped
  roads, road classifications and links to the OSM ways.
  Use the chosen coordinate as a guide point in `create_route` or `update_route`.
- `create_route`: pass `start`, `end` and optional `waypoints` in travel order.
  Every new point is an object with decimal `lat` and `lon`. The tool returns
  a `route_id`, `revision`, distance, estimated time, routing cost and verified
  points. Each intermediate point has a `waypoint_id`.
  It validates the geometry and checks passage within 100 m of the endpoints and
  15 m of intermediate points. Road selection and access handling follow the
  bundled BRouter profile.
- `update_route`: pass `route_id`, the `expected_revision` you last read, and
  the change. Use `move_waypoint` with `waypoint_id`, `lat` and `lon` to move
  a point without changing its order, or `remove_waypoint_id` to remove it.
  Use `add_waypoint` to insert a point, or send a replacement `waypoints`
  list to change the order. A `waypoint_id` alone keeps the existing
  coordinates. Include coordinates to move the point, or omit its ID to
  create a new point. An empty list removes all
  intermediate points. You can also change `start` or `end`; omitted
  fields are kept. The same default limits as for `create_route` apply. Set
  `snap_to_route: true` on `add_waypoint` or `move_waypoint` to raise the limit
  for that waypoint from 15 m to 50 m and save its position on the calculated
  route. If the revision is out of date, read `get_route` before retrying.
  Failed updates keep the previous revision. The update returns a compact
  summary. Use `get_route` for verified points. The open map fetches the new
  revision while keeping its zoom and position.
- `evaluate_route_change`: use the same inputs as `update_route` to calculate
  a candidate without saving it. Returns the base revision, before and after
  distances, distance change in metres, and the first 20 changed spans in
  travel order with offsets and endpoints on each route. The comparison uses
  geometry, so a change in coordinate sampling can appear as a changed span.
  `same_profile` tells whether the bundled profile matches the saved one, or
  is null when the saved route has no profile hash. The calculation sends the
  proposed coordinates and bundled profile to BRouter.
- `get_route`: pass `route_id` to read the latest summary and waypoint IDs.
- `locate_on_route`: pass `route_id`, `near` (latitude and longitude) and an
  optional `radius_m` (100 m by default, up to 1,000 m). Returns the closest
  point in each visit to that radius, in travel order, with kilometres from
  the route start, offset from the lookup coordinate, true-north bearing and
  any road name or number in the saved metadata. Use `search_places` first
  for a place name, or a smaller radius to distinguish nearby visits.
- `show_route`: pass exactly one of `route_id`, `route_file`, or `geojson`.
  A saved route shows its latest revision and numbered waypoints. Drag a
  waypoint on the map to move it, or select it and choose **Remove waypoint**.
  Drag the route line to insert a waypoint on that section. Where sections
  overlap, choose which one to edit before the waypoint is saved. These
  actions recalculate and save the route.
  Dragged waypoints snap to the
  routed position within 50 m of the drop. To view a planned or completed
  ride, pass an absolute GPX, GeoJSON, or training-ai
  route JSON file, or inline GeoJSON line geometry. Imports preserve segment
  breaks and accept optional display metadata such as date, distance, moving
  time, and elevation gain. Imports only display the route.
  Hold **M** while the map has focus to hide the route and its markers.
- `inspect_route`: pass `route_id` or the absolute path to a GeoJSON `route_file`. The tool
  returns distance totals and ordered `sections` with kilometre offsets,
  endpoint coordinates, length, road type, surface and relevant OSM tags.
  Optionally pass one filter: `distance_range` with `from_km` and `to_km`,
  or `waypoint_range` with `from_waypoint_id` and `to_waypoint_id` from
  `get_route`. Waypoint filters require a saved route and IDs in travel order.
  Both filters clip the sections and totals to the selected interval. Kilometre
  offsets still refer to the start of the whole route.
  Section lengths follow the saved geometry, while tag totals use BRouter's
  distances. For a filtered interval, BRouter distances are prorated by overlap
  with the geometry, and unlocated tags contribute as `not_tagged` where possible.
  Sections with missing or unmatched metadata are marked `unknown`.
- `export_route`: pass `route_id` to get a local GPX file. Set `format` to
  `geojson` to get the saved GeoJSON instead.

The plugin requests visible OpenStreetMap tiles, revealing the viewed area
to the tile provider, and caches them for seven days in `~/.cache/route-planner/osm`
or under `XDG_CACHE_HOME` when set.

### Street View

Hold Shift and click the map to open a nearby Google Street View panorama.
A small route map remains visible. Clicks within 25 m of the route use its
direction of travel as the initial camera heading. Opening Street View
sends the selected point to Google.

Follow the [Street View setup instructions](../../README.md#route-planner)
to enable it in Codex.

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

## Files and services

Route revisions are saved in a per-route directory under the system temporary
directory by default. Use `ROUTE_PLANNER_ROUTES` for storage across temporary
directory cleanup. Copy exported files elsewhere to keep them. The plugin writes
nothing to the workspace.

Each calculation uploads the bundled profile and sends the ordered coordinates
to [BRouter.de](https://brouter.de/). GeoJSON records the server URL, uploaded
profile ID, profile hash and engine version. The public service has no guaranteed
availability. The plugin reports failures without retrying automatically.
See the [BRouter privacy policy](https://brouter.de/privacypolicy.html).

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
