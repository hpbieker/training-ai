# Strava Route Builder

## Session Diagnostics

If a tool returns `auth_required`, follow the
[authentication instructions](../SKILL.md#authentication). From the Strava
plugin directory, run `python3 -B scripts/strava_session.py status` to verify
the session or add `--local-only` to check the cache without contacting Strava.
The default cache is `~/.strava/session.headers`. Set `STRAVA_COOKIE_FILE` to
override it. Keep the session directory at mode 0700 and the file at mode 0600.

## Find And Export A Saved Route

Use `list_routes` with `query`, `created_by`, `only_starred` or `route_types`
to narrow the search. If `has_more` is true, use `next_cursor` with the same
filters. `count` is the number of unique routes returned. A null `private`
value leaves visibility unknown.

Use `get_route(route_id, save_full=true)` to obtain the complete native route for
geometry inspection or editing. The compact response lists omitted arrays in
`omitted_arrays`. The `full_route_file` contains `{route_id, route}` and is
the source input for the [route-editing helper](route-editing.md).

## Build Between Waypoints

Use MCP `build_route` with a `requests` array. Each request requires two
waypoint `elements` and complete `routePrefs`. For example:

```json
{
  "elementType": "Waypoint",
  "waypoint": {
    "point": {"lat": 51.5074, "lng": -0.1278},
    "metadata": null
  }
}
```

```json
{
  "routeType": "Ride",
  "surfaceType": "Paved",
  "popularity": 0,
  "elevation": 0,
  "straightLine": false
}
```

For MCP, `surfaceType` accepts `Unknown`, `Paved` and `Unpaved`. Inspect the
returned surface data before treating a paved preference as evidence of
actual surface. Each `buildRoute` result corresponds to one request. Check the
legs, polylines, elevation, distance and directions before saving.

Set `save_full=true` for file-based work. `full_build_file` contains the native
response and can be used by `prepare_route_update.py`. To inspect the result
and export GeoJSON, run this from the Strava plugin directory:

```sh
python3 -B scripts/analyze_strava_build.py /absolute/path/response.json \
  --geojson-out /absolute/path/route.geojson --json
```

## Build A Candidate From A Target Distance

Use `scripts/strava_build_route.py` when only a start point and target distance
are known. It generates waypoint candidates and requests geometry directly
through the plugin's Strava session. It produces `analysis.json` and
`route.geojson` for inspection.

Resolve the start, distance, loop or out-and-back shape, bearing and surface.
Use deliberate via points where they matter. Inspect the candidate against the
[route quality checks](route-quality.md), including distance, connectors and
surface uncertainty. Revise weak candidates before saving.

## Save, Update Or Delete

Use MCP for writes after explicit user authorization. Read the
[write-safety reference](write-safety.md#route-creation-and-updates).

- `create_route` takes `props` with `name`, `elements`, `legs` and complete
  `routePrefs`. Optional fields are `description`, `visibility` and `starred`.
  New routes default to `OnlyMe`. Preserve each built leg's `legType` and full
  path objects. Set zero-based `startElement` indices and retain waypoint
  metadata, using `null` when it is absent.
- `update_route` takes `route_id` and either a `patch` or a prepared
  `patch_file`. Supply only fields to change. Omitted fields are preserved
  and supplied `routePrefs` keys are merged. Geometry replacement requires
  both `elements` and `legs`.
- `delete_route` requires the exact owned `route_id`. Confirm deletion only
  when the tool verifies that the route is gone under the same account.

Pass `confirm=true` for the authorized write. On `write_unverified`, inspect
the current remote state and verification details before retrying.
