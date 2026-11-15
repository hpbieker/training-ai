# Strava Route Builder

## Transport

Use the persistent private browser session. When renewal is required, capture
Copy as cURL in Safari Web Inspector and run `strava_session.py import-curl`
to create a verified mode-0600 `Cookie:` header file. Pass that path as
`--cookie-file`. Use the shared Python HTTP session for:

1. authenticated training-page read and athlete-ID discovery;
2. Route Builder GET with the same live browser session cookie;
3. fresh CSRF extraction;
4. API POST with the same runtime cookie and CSRF;
5. HTTP and JSON validation.

Keep full copied cURL, Authorization and CSRF values out of stored artifacts.
Reuse the private Cookie cache until it expires or is explicitly cleared.
The supported renewal path is the Web Inspector import in the
[authentication instructions](../SKILL.md#authentication).

Use `strava_session.py status` for a live session check and
`status --local-only` for a file and permission check. Use `clear` only for
explicit credential cleanup. The default cache is `~/.strava/session.headers`;
`STRAVA_COOKIE_FILE` overrides it and the importer also accepts `--cookie-file`.
Keep the directory at mode 0700 and the file at mode 0600.

## Saved Route Listing

MCP `list_routes` reads `/athlete/routes` for the current CSRF token and calls
`POST /api/next/data/routes/my-routes` as a read-only search. The request uses
`pageSize`, `after` (initially `"0"`), `searchArgs`, and `resolutions: []`.
`searchArgs` includes `query`, `onlyStarred`, `createdBy` (`Any`, `Athlete`,
`Others`), explicit `routeTypes`, and unbounded distance/elevation maxima.
An empty route-type array matches no routes, so the default sends all supported
types. The response is `me.searchRoutes.nodes` with `pageInfo.hasNextPage` and
`pageInfo.endCursor`. These semantics were verified against the live My Routes
page and its JavaScript on 2026-09-08. The service validates pagination rather
than treating malformed or error responses as an empty collection.

The MCP exposes `query`, `created_by`, `only_starred` and `route_types`. Follow
`next_cursor` with unchanged filters when `has_more` is true. The default
`max_pages` is 20 with 16 routes per page. `count` covers returned unique routes.
An unknown `private` value does not establish visibility.

## Saved Route Details

MCP `get_route(route_id)` reads `GET /routes/{route_id}` and extracts
`props.pageProps.route` from the page's `__NEXT_DATA__` JSON. It checks that the
returned ID matches the requested route. The route keeps its native field
names and values. The extraction excludes other page state, including session data.

By default the MCP response uses `{route_id, route, omitted_arrays}` and omits
`elements`, `legs`, `segmentsOnRoute`, `segments`, `elevation`, `polyline`,
`distanceStream` and `routePolylineData.media` from `route`. Each omission reports
the JSON-pointer path, item count and UTF-8 JSON byte size. Use `save_full=true`
to save the complete `{route_id, route}` to `full_route_file`; the response also
provides `full_route_format` and `full_route_byte_size`.

## MCP Build

`build_route(requests)` passes `{ "requests": [...] }` to the build endpoint.
Each request contains exactly two native waypoint `elements` and complete
`routePrefs`. It returns the entire source response unchanged, including
`buildRoute` and any additional fields. Each result corresponds to a request,
not an alternative complete route. Missing/incomplete build results are errors.
No route is saved, and no confirmation parameter is needed. Route planning,
target-distance waypoint selection, analysis, and GeoJSON conversion are
separate operations. A two-request build was verified live through MCP.

Use `save_full=true` to save the unchanged build response to `full_build_file`
as private JSON. The compact response includes `result_count`, `leg_count`,
`full_build_format` and `full_build_byte_size`. The file is accepted directly
as a replacement by `prepare_route_update.py`.

## MCP Writes

`create_route` accepts `props` containing Strava's native write fields:
`name`, `description`, `visibility`, `starred`, `elements`, `legs`, `routePrefs`.
`name`, `elements`, `legs`, and complete `routePrefs` are required. Creation
supplies the authenticated `athleteId` and defaults omitted metadata to an empty
description, `OnlyMe`, and unstarred. It does not build a route.

Preserve the complete path objects returned by `build_route`; do not reduce a
built path to its Google polyline. Each element's waypoint must contain the
`metadata` key (use `null` when there is no metadata), and each built leg must
retain its `legType` (normally `Search`) as well as its zero-based
`startElement`. Strava may silently normalize a leg's structure after saving,
so verify the saved route and report unresolved geometry rather than treating
an acknowledged POST as exact verification.

`update_route` takes `route_id` and a nonempty `patch` using the same write
fields. Read `/maps/create?routeId=...` and use
`props.pageProps.prefetchedRoute` to preserve current editor state, including
`routePrefs`. Send `routeId` on update, not `athleteId`. Check ownership before
writing. Omitted fields are preserved; preference keys are merged. Geometry
replacement requires both `elements` and `legs`.

Both tools require `confirm: true`. The write envelopes are `{ "props": ... }`.
The native request field names and envelopes were checked against the live
builder JavaScript on 2026-09-08. `routePrefs` uses `routeType`, `surfaceType`
(`Unknown`, `Paved`, `Unpaved`), `popularity`, `elevation`, and `straightLine`.
Read and write shapes differ: `title` becomes request `name`,
`routeDescription` becomes `description`, and `isPrivate` maps to `visibility`.

After POST, read editor state again and compare metadata, elements, preferences,
and per-path polylines. Then return a fresh, unchanged `get_route` object.
Any failure after submission reports `write_unverified` with the operation,
stage and known route ID, without automatic retry. These write paths have
mocked success/failure coverage and read-only live editor validation; no live
route was created or modified during implementation.

## Route Deletion

`delete_route(route_id, confirm=true)` uses `DELETE /routes/{route_id}`, matching
the delete action in My Routes. It verifies the route belongs to the currently
authenticated athlete before sending the request with the current CSRF token.
A successful response alone is insufficient: a fresh GET must return HTTP 404
or 410, followed by a successful authentication check for the same athlete.
Other errors and redirects do not establish deletion. Post-submission failures
retain the route ID and report `write_unverified`; no automatic retry occurs.
This path is covered by mocked deletion/readback tests; no real route was
deleted during implementation.

## Route Building Tools

Use the Strava MCP tool `build_route` with `requests` containing waypoint
pairs and route preferences. Use `strava_build_route.py` to propose and inspect
candidates from a start point and target distance. Use MCP for route creation,
updates and deletion. The `strava_route_api.py auth` command checks the
authenticated session.

## Endpoints

- `POST /api/next/data/routes/build-route`
- `POST /api/next/data/routes/create-route`
- `POST /api/next/data/routes/update-route`

Build requests contain pairs of waypoint elements and `routePrefs`. A waypoint:

```json
{
  "elementType": "Waypoint",
  "waypoint": {
    "point": {"lat": 59.9, "lng": 10.7},
    "metadata": {"title": "Anchor"}
  }
}
```

Road defaults:

```json
{
  "routeType": "Ride",
  "surfaceType": "Paved",
  "popularity": 0,
  "elevation": 0,
  "straightLine": false
}
```

`Paved` is a preference, not proof. Inspect returned
`surfaceTypeOffsets`, polylines, directions, distance, elevation, and leg count.
Add zero-based `startElement` to built legs before create/update.

## Analysis

Run the helper from the Strava plugin directory.

```bash
python3 -B scripts/analyze_strava_build.py /absolute/path/response.json \
  --geojson-out /absolute/path/route.geojson --json
```

Build before writing, apply distance and surface gates, default to private, and
verify the created route page.

## Target-Distance Candidates

For a route from a start place and target distance, resolve:

- start name, latitude, and longitude;
- target kilometres and `loop` or `out-and-back`;
- preferred direction or bearing;
- `Paved`, `Any`, or `Dirt`;
- `flat` or `hilly`, and direct versus popular routing;
- optional deliberate via points;
- route name and visibility.

Prefer explicit user choices, current-location context, actual saved activity
geometry, and map-backed anchors. A generated bearing is only a candidate;
inspect it because it can point across water or unsuitable roads.

Use repeatable `--via LAT,LNG,NAME` arguments for deliberate anchors. Inspect
`analysis.json` and `route.geojson`, then read
[route quality](route-quality.md). Revise poor
candidates instead of suppressing the 15 percent distance guardrail.

Run `strava_build_route.py` with `--cookie-file`, the resolved start,
distance, shape, routing choices, and an output directory to build and inspect. Save through MCP `create_route` only when the user explicitly asked to create
or save the inspected route. New routes default to
`OnlyMe`; use `Everyone` only when explicitly requested. Report the verified
route URL, distance, elevation, surface uncertainty, shape, and material road
or traffic caveats.
