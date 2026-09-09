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
envelope `{route_id, route, omitted_arrays}`. `route` preserves native field
names, nested objects, nulls and extra fields, except for a fixed set of arrays:
`elements`, `legs`, `segmentsOnRoute`, `segments`, `elevation`, `polyline`,
`distanceStream` and `routePolylineData.media`. These are omitted regardless of
size, even when empty. All other arrays remain unchanged. `omitted_arrays`
reports each removed array's JSON-pointer path, item count and UTF-8 JSON byte
size; size does not control inclusion.

Set `save_full=true` to save the complete source as `{route_id, route}` in a
private temporary JSON file. The response adds `full_route_file`,
`full_route_format` (`strava-route-v1`) and `full_route_byte_size`. Use this file
for geometry processing. No `includeFields` parameter is needed. Do not assume
the normalized field names from `list_routes` apply to `get_route`. A missing
or mismatched route is an error, not an empty object.

Use MCP `build_route(requests)` to compute geometry between explicit waypoint
pairs without saving a route. Each native request has exactly two `elements`
and complete `routePrefs` (`routeType`, `surfaceType`, `popularity`, `elevation`,
`straightLine`). The response is Strava's unchanged object containing
`buildRoute`, one result per requested leg. It does not generate waypoints from
a target distance. Resolve those points before calling; analysis and GeoJSON
conversion remain separate from the source response.

Use `build_route(requests, save_full=true)` for file-based processing. It saves
the complete unchanged build response as private temporary JSON (mode 0600)
and returns only `result_count`, `leg_count`, `full_build_file`,
`full_build_format` (`strava-build-v1`) and `full_build_byte_size`. The file is
directly accepted as a replacement by `prepare_route_update.py`. The default
`save_full=false` retains the inline native response.

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

To prepare a section update locally, run:

```bash
python3 -B plugins/strava/scripts/prepare_route_update.py \
  --route /absolute/path/full-route.json \
  --replacement /absolute/path/replacement.json \
  --from-element 4 --to-element 7 \
  --output-dir /private/tmp/prepared-route-update
```

The source is the full file from `get_route(save_full=true)`. Replacement JSON
contains native `elements` and already built `legs`, including both boundary
waypoints. Indices are zero-based source `elements` indices, inclusive, not
kilometres or polyline vertices. Boundary coordinates must match exactly.
The helper preserves original boundary metadata and all outside geometry,
adds source-omitted `elementType=Waypoint`, and renumbers `startElement`.
It writes private `update.json` (`route_id`, `patch`, `base_geometry_sha256`) and `report.json` files
to a new directory and prints only paths and counts. It does not set `confirm`,
access the network, build paths, or save a route. Metadata and preferences are
omitted from the patch so `update_route` preserves current values.
Pass `base_geometry_sha256` unchanged to `update_route`. It checks a fresh
detail read before writing and rejects an outdated source. For untouched legs,
the service retains fresh editor geometry and verifies each source against its
own fresh baseline. Geometry changes still must match the submitted proposal.

For a local change within one leg, use point mode:

```bash
python3 -B plugins/strava/scripts/prepare_route_update.py \
  --route /absolute/path/full-route.json \
  --replacement /absolute/path/replacement.geojson \
  --leg 15 --from-point 48 --to-point 74 \
  --output-dir /private/tmp/prepared-section-update
```

Point indices refer to decoded Google polyline vertices within the selected
zero-based leg. They are not waypoint indices or kilometres. Endpoints must
match the selected source coordinates at encoded precision by default.
Explicit `--max-join-gap-m 1.5` permits endpoint adjustments within 1.5 metres;
the default is zero. Original prefix and suffix coordinates are preserved.
Replacement accepts a GeoJSON LineString/Feature with longitude, latitude and
elevation in metres, native `{legs: [...]}`, or a `buildRoute` response whose
results are sequential sections. Each native leg must have exactly one path:
multiple paths may represent alternatives and are rejected, not concatenated.

For 2D GeoJSON supply `--elevation-profile /absolute/path/profile.json`, an
ordered array of `[distance_m, elevation_m]` covering the replacement from zero
to its complete distance. Missing heights fail rather than being invented.
GeoJSON surface type is Unknown. Distances and elevation gain/loss are computed;
grade-adjusted length is the geometric length, not a Strava grade model.
Old directions are cleared for rebuilt paths. Native elevation profiles are
trimmed and shifted along with retained geometry. Each edited leg is emitted
as one complete path so Strava cannot discard later sections as alternatives.

For multiple changes in one operation use a batch manifest:

```json
{
  "max_join_gap_m": 1.5,
  "edits": [
    {"leg": 15, "from_point": 79, "to_point": 116, "replacement_file": "ut.json"},
    {"leg": 26, "from_point": 115, "to_point": 134, "replacement_file": "retur.json"}
  ]
}
```

```bash
python3 -B plugins/strava/scripts/prepare_route_update.py \
  --route /absolute/path/full-route.json \
  --edits /absolute/path/edits.json \
  --output-dir /private/tmp/prepared-batch
```

Relative replacement paths resolve from the manifest directory. Each edit can
also specify `elevation_profile_file` for 2D GeoJSON. All indices address the
same original route, even when earlier edits change vertex counts. Changes
within one leg are assembled together; overlapping intervals are rejected.
Adjacent intervals may share their unchanged original boundary point.

The manifest tolerance defaults to zero and applies both to internal joins in
sequential native build results and to replacement endpoints. Internal joins
move the following section's start to the previous section's end. Outer joins
move replacement endpoints to the original route, never the other way around.
No straight connector is added. Distance-based profiles are rescaled after an
adjustment. `report.json` lists every adjustment with original/new coordinates,
gap in metres, edit index, and input file hashes. Tolerance does not establish
road identity: inspect the proposal before saving. An excessive gap or invalid
edit rejects the entire batch before output files are created. Batch options
cannot be combined with single-edit flags.

Inspect geometry before submitting. Pass the prepared file directly:

```json
{"route_id": "3532440438889330932", "patch_file": "/absolute/path/update.json", "confirm": true}
```

`update_route` accepts exactly one of `patch` and `patch_file`. The latter must
be an absolute path to the `prepare-update` envelope containing `route_id`,
`patch` and optional `base_geometry_sha256`. The caller's route ID must match
the file; its geometry fingerprint is carried into the normal stale-input
check. Conflicting explicit fingerprints are rejected. Confirmation remains
an explicit tool argument; the file cannot provide it. Unknown fields, invalid
patches and malformed JSON are rejected before network access. The input file
is not modified. The verified update response remains the native full route.

Creation and updates verify metadata and preferences, accept omitted versus null
waypoint metadata and waypoint shifts within 2 metres, and compare geometry in
both fresh editor and route-detail data. Verification requires two successful
readback rounds separated by two seconds, with at most three rounds (a further
three-second wait). Only reads are repeated; a write is never retried. This
checks observed stability, not an indefinite guarantee against future changes.
They return the full native source
route object; MCP `_meta.route_verification` carries the verification report.
Polyline comparison distinguishes `exact`, `equivalent_within_tolerance`,
`changed`, and `unresolved`. Non-exact comparisons preserve traversal order with
a bounded sampled comparison and a 2-metre tolerance. Geometric equivalence
does not establish road identity or legal access; nearby parallel ways can still
need map inspection. Changed leg structure and exhausted comparison limits are
unresolved, never automatically accepted.

On `write_unverified`, inspect `details.verification` for mismatched metadata,
affected legs and deviation coordinates, plus `details.route_id` and current
state before retrying. `write_acknowledged` distinguishes an acknowledged write
with a failed verification from an uncertain submission. No write is retried.
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
