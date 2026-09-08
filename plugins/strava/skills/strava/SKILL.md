---
name: strava
description: Read and change Strava activities, tags, visibility, routes, Route Builder state, and authenticated Strava data through local MCP tools and Python helpers using a private Safari session. Use for activity or route inspection and mutation, or when creating a cycling route from a start location, target distance, route shape, direction, surface, elevation, popularity, and optional via points.
---

# Strava

Use the local MCP tools for activity, saved routes, gear, and media
operations. The server reads
`~/.strava/session.headers` for each operation; it does not authenticate through
Safari, refresh cookies, or retry failed writes.

## Authentication

On `errorCode: auth_required`, follow `browser-curl-replay` to copy a live
Strava authenticated request as cURL in Safari Web Inspector, then import it:

```bash
python3 -B plugins/strava/scripts/strava_session.py import-curl
```

The importer reads the clipboard, retains only the Cookie header in
`~/.strava/session.headers`, and verifies the authenticated session. Never print
Cookie, Authorization, CSRF, or copied full cURL content. The private directory
must be mode 0700 and the file mode 0600. Safari must already be logged in;
a new Web Inspector capture requires the Mac to be unlocked.

After renewal, call the MCP tool again; no server restart is needed. For a failed
write, first read the current activity state to determine whether it already
changed. For a partial batch, inspect `details.updated`, `details.failed`, and
`details.not_attempted`; do not blindly repeat the whole batch.

Use `strava_session.py status` for live diagnostics, or `status --local-only`
for file/permission checks. Use `clear` only for explicit credential cleanup.
The cookie path resolves from `STRAVA_COOKIE_FILE`, then the persistent default;
CLI helpers also accept `--cookie-file` where documented. Cookies and cookie paths
are not MCP tool arguments.

`strava_session_from_safari.py` remains an experimental helper. Do not rely on
curl-safari for renewal until its previously missing Strava session cookies are
verified fixed. Copy as cURL in Web Inspector is separate from curl-safari.

## Network Execution

Live CLI diagnostics, session import verification, and route helper calls
require escalated network permission on the first attempt. Offline help and
local artifact inspection do not. MCP calls use the configured local server.

## Activities

Read [references/write-safety.md](references/write-safety.md) before writes.
Use MCP `list_activities`, `get_activity`, `list_gear`, `get_gear`,
`update_activity`, and `update_activities`. Discover exact IDs through reads;
`list_activities` accepts inclusive `since` and `until` dates. Writes take a
`patch` and `confirm=true` for an already authorized action. Omitted fields are
preserved. Use `tag: null` to clear a tag or `bike_id: "none"` to clear a bike.
Visibility, hidden start time, and mute are independent settings. Updates verify
API metadata plus edit-page-only bike, start-time, and mute state.

Activity, gear, and media operations are available only through MCP. The Python
activity helpers are internal modules without CLI entry points. CLI commands
remain for session management, route building, and route analysis.

Use `list_gear` to retrieve current and retired bikes and shoes. `get_gear`
accepts an ID returned by that list; provide `gear_type` (`bike` or `shoe`) when
the type is already known.

Use `list_activity_media` with one exact activity ID before downloading or
uploading. `download_activity_media` requires the returned `media_id` and an
explicit `destination_dir`; it will not overwrite a local file unless
`overwrite=true` is explicit.

`upload_activity_media` is an activity write. It accepts one local JPG, PNG,
GIF, MP4, or MOV file and requires `confirm=true`. The upload is staged through
Strava's short-lived media-storage URL, then attached through the activity edit
form. Do not send the Strava cookie to that storage URL. Report success only
after fresh media-list readback confirms the attachment.

Pass absolute local paths in `destination_dir` and `file_path`. Media IDs may be
UUIDs; preserve the exact `media_id` returned by the list. If an upload fails
with an uncertain result, list the activity's media again before retrying to
avoid attaching it twice.

## Routes

Use MCP `list_routes` to discover saved routes and exact string IDs from My
Routes, including routes saved from others. Omit filters for all route types;
use `query`, `created_by` (`any`, `me`, `others`), `only_starred`, and
`route_types` to narrow the source search. Results include names, URLs, distance
and elevation in metres, ownership, private/starred state, and estimated time
when available. Do not infer public visibility when `private` is null.

The tool follows source cursors up to `max_pages` (default 20, 16 routes per
page). If `has_more` is true, continue with `next_cursor` as `cursor` and the
same filters. `count` describes returned unique routes, not the account's total.
Listing does not create or modify routes and does not require Route Builder
initialization.

Use MCP `get_route` with an exact `route_id` from `list_routes`. It returns the
complete `props.pageProps.route` object from Strava's route page unchanged:
original field names (such as `title`, `length`, `elevationGain`), nested
objects, arrays, and null values. Geometry, elevation data, segments, and
source-provided extra fields are included as supplied. Do not assume the
normalized field names from `list_routes` apply to `get_route`. A missing or
mismatched route is an error, not an empty object.

Use MCP `build_route(requests)` to compute geometry between explicit waypoint
pairs without saving a route. Each native request has exactly two `elements`
and complete `routePrefs` (`routeType`, `surfaceType`, `popularity`, `elevation`,
`straightLine`). The response is Strava's unchanged object containing
`buildRoute`, one result per requested leg. It does not generate waypoints from
a target distance. Resolve those points before calling; analysis and GeoJSON
conversion remain separate from the source response.

Use MCP `create_route(props, confirm=true)` to save previously built and
inspected geometry. `props` uses Strava's native write fields: `name`,
`description`, `visibility`, `starred`, `elements`, `legs`, and `routePrefs`.
This differs from the read object's field names. The service supplies the
current athlete ID; new routes default to `OnlyMe`. Build with MCP `build_route`; creation does not rebuild geometry.
Use the actual built elements, paths, and zero-based `startElement` indices.

Use MCP `update_route(route_id, patch, confirm=true)` for owned routes. Supply
only changed native write fields. It reads fresh editor state and preserves
omitted fields, merging supplied `routePrefs` keys. To replace geometry, supply
both `elements` and complete built `legs`. Neither operation rebuilds geometry.

Creation and updates verify metadata, preferences, waypoints, and saved polylines against
fresh editor data and return the unchanged `get_route` object. On
`write_unverified`, inspect `details.route_id` and current state before retrying.
If creation has no returned ID, use `list_routes` to check whether it succeeded;
do not blindly create another copy. Session renewal remains external.

Use MCP `delete_route(route_id, confirm=true)` only for an explicitly authorized
route deletion. It checks ownership, sends the deletion once, then requires
HTTP 404/410 on a fresh route-page read while the same account remains
authenticated. Success returns `route_id` and `deleted: true`. A login redirect,
403/500 response, or a still-readable page is not proof of deletion. An
uncertain result uses `write_unverified`; inspect current state before retrying.

Read [references/route-builder.md](references/route-builder.md) for endpoint and
payload semantics. Use `analyze_strava_build.py` to inspect returned geometry.

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
[references/route-quality.md](references/route-quality.md). Revise poor
candidates instead of suppressing the 15 percent distance guardrail.

Run `strava_build_route.py` with `--cookie-file`, the resolved start,
distance, shape, routing choices, and an output directory to build and inspect. Save through MCP `create_route` only when the user explicitly asked to create
or save the inspected route. New routes default to
`OnlyMe`; use `Everyone` only when explicitly requested. Report the verified
route URL, distance, elevation, surface uncertainty, shape, and material road
or traffic caveats.

## Boundaries

This plugin owns Strava session mechanics, route-builder payloads, activity
mutations, and readback verification. The caller owns personal route
preferences, candidate selection, maps, and final route or training decisions.

### Mute activity

Use MCP `update_activity` with `patch: {"mute": true}` and `confirm: true` to mute an activity in home feeds; use `false` to undo it. This is independent of visibility and Workout tags. The script preserves omitted fields and verifies `mute` from the fresh edit-form `activity[hide_from_home]` checkbox. An absent checkbox is unknown, not false; writes fail if it cannot be located.
