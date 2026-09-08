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

Do not store full copied cURL, Authorization, or CSRF values. Reuse the private
mode-0600 Cookie cache until it expires or is explicitly cleared. Keep only sanitized
templates, response bodies, and redacted logs. Do not use Curl Safari for
Strava until its cookie-completeness issue is resolved; its
disk-backed jar omitted `_strava4_session` from a session Safari demonstrably
used.

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

## Saved Route Details

MCP `get_route(route_id)` reads `GET /routes/{route_id}` and extracts
`props.pageProps.route` from the page's `__NEXT_DATA__` JSON. It checks that the
returned ID matches the requested route, then returns that object without
renaming, deriving, filtering, or flattening fields. Only the route object is
returned, excluding other page state such as session data. The response shape
was verified on 2026-09-08; missing values and future fields stay source-native.

## MCP Build

`build_route(requests)` passes `{ "requests": [...] }` to the build endpoint.
Each request contains exactly two native waypoint `elements` and complete
`routePrefs`. It returns the entire source response unchanged, including
`buildRoute` and any additional fields. Each result corresponds to a request,
not an alternative complete route. Missing/incomplete build results are errors.
No route is saved, and no confirmation parameter is needed. Route planning,
target-distance waypoint selection, analysis, and GeoJSON conversion are
separate operations. A two-request build was verified live through MCP.

## MCP Writes

`create_route` accepts `props` containing Strava's native write fields:
`name`, `description`, `visibility`, `starred`, `elements`, `legs`, `routePrefs`.
`name`, `elements`, `legs`, and complete `routePrefs` are required. Creation
supplies the authenticated `athleteId` and defaults omitted metadata to an empty
description, `OnlyMe`, and unstarred. It does not build a route.

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

## CLI Boundaries

`strava_build_route.py` builds and inspects candidates only. Route creation,
updates, and deletion use MCP. The low-level `strava_route_api.py` CLI exposes
only `auth` and `build`; its internal create/update transport remains available
to the MCP service.

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

```bash
python3 -B plugins/strava/scripts/analyze_strava_build.py <response.json> \
  --geojson-out <route.geojson> --json
```

Build before writing, apply distance and surface gates, default to private, and
verify the created route page.
