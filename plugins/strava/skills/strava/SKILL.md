---
name: strava
description: Use when working with Hans Petter's Strava routes, route builder, GPX imports, Safari-authenticated Strava pages, or creating/updating private Strava routes from BRouter/OSM-derived candidates. Covers learned Strava API endpoints, Safari session mechanics, and VT1 route-scoring rules that penalize interruptions and G/S shortcuts.
---

# Strava

Use this skill when the user asks to inspect, create, update, or troubleshoot Strava routes or activities, especially when logged-in Strava state or Safari cookies are required.

## Default Access Pattern

- Prefer Safari-authenticated workflows for logged-in Strava pages and route writes.
- Use `curl-safari` for authenticated HTML/page fetches when possible, especially route pages such as `https://www.strava.com/routes/<route_id>`.
- Prefer `plugins/strava/scripts/strava_route_api.py` for route-builder API calls when the request body is known. It fetches a fresh CSRF token from Strava, uses Safari cookies through `curl-safari`, and avoids storing Cookie or CSRF headers.
- For route-builder API calls, run JavaScript inside the logged-in Safari tab on `https://www.strava.com/maps/create...`. Relative Strava API paths only work from the Strava origin; if the active Safari tab is on another site, API calls will return unrelated 404s.
- For activity tag/visibility writes, prefer `plugins/strava/scripts/strava_activity_tags.py`; it keeps the edit-page CSRF token and Strava session cookie in the same temporary cookie jar.
- Do not expose cookies, CSRF values, or session headers in chat or saved reusable files.
- For writes, keep routes private by default (`visibility: "OnlyMe"`) unless the user explicitly asks otherwise.

## Activity Reads and Tag Writes

Use `curl-safari` for activity reads and writes; do not expose Cookie headers or
CSRF tokens. The training-list endpoint reads recent activity state:

```bash
/Users/hanspetterbieker/sources/curl-safari/bin/curl-safari -L \
  -H 'Accept: application/json, text/javascript, */*; q=0.01' \
  -H 'X-Requested-With: XMLHttpRequest' \
  -H 'Referer: https://www.strava.com/athlete/training' \
  'https://www.strava.com/athlete/training_activities?page=1&perPage=20' \
  -o /private/tmp/strava_training_activities.json
```

For one activity, `GET /athlete/training_activities/<activity_id>` returns the
current quick-edit model, including `visibility`, `private`, `trainer`,
`selected_tag_type`, and `tags`.

For activity tag writes, the fragile part is session continuity:

1. `GET https://www.strava.com/activities/<activity_id>/edit` with `-c <jar>`.
2. Build a normal `application/x-www-form-urlencoded` body from the edit form.
3. Include React-rendered tag fields manually:
   - `activity[tags][]=`
   - `activity[tags][]=Workout` or another tag value
   - `activity[trainer]=0`
   - `activity[trainer]=1` when indoor/trainer should be set
4. `POST https://www.strava.com/activities/<activity_id>` with the same jar via
   `-b <jar> -c <jar>`.
5. Verify with `GET /athlete/training_activities/<activity_id>`.

Do not split the edit-page GET and form POST across separate cookie state.
Strava may set a fresh `_strava4_session` when serving the edit page; if the
POST uses the old Safari cookie instead of the jar cookie that matches the
edit-page CSRF token, Strava redirects to `/dashboard` and silently changes
nothing.

Preferred helper:

```bash
python3 -B plugins/strava/scripts/strava_activity_tags.py 19135334849 --read
python3 -B plugins/strava/scripts/strava_activity_tags.py 19135334849 \
  --tag Workout --trainer true --visibility everyone --start-time-hidden true
```

Observed tag mapping:

| UI label | Form value | API state |
|---|---|---|
| Løp | `Race` | `selected_tag_type=1`, `tags["1"]=true` |
| Treningsøkt | `Workout` | `selected_tag_type=2`, `tags["2"]=true` |
| Pendling | `Commute` | `selected_tag_type=3`, `tags["3"]=true` |
| For en god sak | `ForACause` | `selected_tag_type=14`, `tags["14"]=true` |
| Restitusjon | `Recovery` | `selected_tag_type=12`, `tags["12"]=true` |
| Med barn | `WithKid` | `selected_tag_type=16`, `tags["16"]=true` |
| Med kjæledyr | `WithPet` | `selected_tag_type=13`, `tags["13"]=true` |
| Innendørs sykling | `activity[trainer]=1` | `trainer=true`, `tags["6"]=true` |

`Innendørs sykling` is not a normal `activity[tags][]` tag. It is controlled by
`activity[trainer]` and appears in the training API as `tags["6"]=true`. On an
indoor trainer activity, Strava may ignore attempts to unset `trainer`; always
verify after writes.

## Known Strava Route Builder Endpoints

These were verified from Strava's web route-builder bundles and Safari session behavior.

- GPX import/convert:
  - `POST /frontend/routes/file`
  - `multipart/form-data` fields: `file`, `data_type=gpx`, `route_type=<Ride|Run|...>`
  - The UI posts the same endpoint after local GPX type detection.
  - Safari-authenticated fetch can pass auth, but Strava may still return `500 {"message":"error"}` for GPX files it dislikes. Treat GPX import failure as parser/schema sensitivity, not automatically as login failure.
- Build route legs:
  - `POST /api/next/data/routes/build-route`
  - JSON body: `{ "requests": [ { "elements": [<start>, <end>], "routePrefs": <prefs> } ] }`
  - Response has `buildRoute[].legs[]`. Each returned leg can be used in create/update payloads after adding `startElement`.
- Create new route:
  - `POST /api/next/data/routes/create-route`
  - JSON body: `{ "props": { name, description, visibility, starred, elements, legs, routePrefs, athleteId } }`
  - Success response observed: `{ "createRoute": "<route_id>" }`.
- Update existing route:
  - `POST /api/next/data/routes/update-route`
  - JSON body: `{ "props": { routeId, name, description, visibility, starred, elements, legs, routePrefs } }`
  - Success response observed: `200 OK` with `{ "updateRoute": null }`.

## Route Payload Shapes

Element shape:

```json
{
  "elementType": "Waypoint",
  "waypoint": {
    "point": { "lat": 59.956069, "lng": 10.687537 },
    "metadata": { "title": "Dagaliveien 17B" }
  }
}
```

Route preferences that are useful for VT1 road-biased cycling:

```json
{
  "routeType": "Ride",
  "surfaceType": "Paved",
  "popularity": 0,
  "elevation": 0,
  "straightLine": false
}
```

Notes:

- `popularity: 0` is more direct; `0.5` is Strava's popular/follow route behavior.
- `surfaceType: "Paved"` discourages unpaved choices but does not by itself prevent cycleways.
- Use more waypoints than a normal Google Maps link when trying to prevent Strava from snapping back to G/S shortcuts.
- For each returned leg from `build-route`, add `startElement: <zero-based leg index>` before create/update.

## Safari In-Page Execution Pattern

Use this only when the route-builder request body is not available. If the user
has copied a `build-route` request, strip the request down to its JSON body and
use the curl-based workflow below instead.

1. Open Strava route builder in Safari:

```applescript
tell application "Safari" to set URL of document 1 to "https://www.strava.com/maps/create?sport=Ride&style=standard&terrain=false&labels=true&poi=true&cPhotos=true&3d=false"
```

2. Verify the current tab is on Strava before API calls:

```applescript
tell application "Safari" to do JavaScript "document.location.href + ' | ' + document.title" in document 1
```

3. Read and run a generated JavaScript file in the page:

```applescript
set jsfile to POSIX file "/private/tmp/strava_build_route.js"
set js to read jsfile as «class utf8»
tell application "Safari" to do JavaScript js in document 1
```

4. Poll a result variable:

```applescript
tell application "Safari" to do JavaScript "JSON.stringify(window.__codexStravaBuild)" in document 1
```

Use a JS file instead of shell-quoting long JavaScript through `osascript -e`. AppleScript string escaping is easy to get wrong, especially with nested quotes and large base64 GPX content.

## VT1 Route Scoring Preference

For Hans Petter's VT1 route work, do not optimize only for shortest or "nice bicycle route". Penalize interruption and ambiguity hard:

- Footway/path/pedestrian segments: very hard penalty.
- For road/landevei routes, reject `surface=dirt`, `surface=gravel`, `surface=ground`, `surface=unpaved`, or similar unpaved surfaces unless the user explicitly asks for gravel/mixed surface.
- Treat missing/unknown surface as skeptical for landevei. It is not as bad as known gravel/dirt, but it should be reported and checked before accepting the route.
- In Strava `surfaceTypeOffsets`, count both `Unknown` and `Unpaved` as skeptical surface. `Unknown` should trigger manual inspection, especially on paths, unnamed connectors, or forest/edge roads.
- Treat `foot=designated` on cycleway/path/footway as a warning sign for road VT1, even when the surface is paved; it often means shared G/S flow rather than road flow.
- Cycleway/G/S path: moderate to hard penalty, especially in dense areas with driveways, pedestrians, blind turns, or frequent crossings.
- Crossings without clear priority, uncontrolled crossings, traffic signals, barriers, kerbs, and traffic calming: hard penalty because they create stop/start and micro-intervals.
- Major fast roads without good shoulder: hard penalty even if they remove G/S paths.
- Motorway/trunk candidates are normally invalid for cycling, even if a car-biased router gives 0 km G/S.
- Smooth 4-5% climbs are acceptable or even useful if they have flow and limited crossings.

Practical scoring script: use `plugins/strava/scripts/score_brouter_vt1.py <route.geojson> ...` to compare BRouter candidates. Treat the score as decision support; inspect the route class mix before finalizing.

Observed example from Dagaliveien 17B to Liertoppen:

- Original trekking/direct candidate: about 31.8 km, 16.6 km G/S-like (`cycleway` + `footway` etc.), 122 crossing-like nodes. Too much G/S for strict VT1.
- Strava/BRouter road-biased v2 using BRouter `fastbike`: about 31.7 km in BRouter, about 32.5 km after Strava build, G/S-like reduced to about 6.1 km, but crossings increased. This was the better compromise than a car profile, because the car profile hit trunk/motorway-like roads and many big intersections.

## Safe Route Creation Workflow

1. Prefer Strava as the route generator. Build multiple Strava candidates by changing a few deliberate, named anchor points rather than by blindly densifying a BRouter line.
2. Use `build-route` first and inspect Strava's actual response:
   - HTTP status is 200.
   - returned leg count equals waypoint count minus one.
   - total meters roughly match the expected candidate.
   - `paths[].polyline` is the actual Strava geometry; do not assume the straight line between waypoints is acceptable.
   - `paths[].directions` reveals road names and odd detours.
   - `paths[].surfaceTypeOffsets` is useful but too coarse to replace OSM inspection.
3. Export the actual Strava polyline with `analyze_strava_build.py --geojson-out ...` and inspect/map-match that line for `cycleway`, `footway`, `path`, `foot=designated`, unknown surface, and unpaved surfaces.
4. Reject or revise candidates with high `snapUncertainty`, odd out-and-back legs, or generated points that are far away from their neighboring points.
5. For landevei routes, reject candidates with unpaved surfaces near the route line. Do not densify a bad baseline; dense points will only force Strava to preserve the bad shortcut.
6. Use BRouter/OSM as quality control and explanation, not as the primary source of truth for the Strava route.
7. Only then call `create-route` or `update-route`.
8. Verify the route page with `curl-safari` or Safari page text. For update, `200 OK` with `{ "updateRoute": null }` is a success signal.

## Curl-Based Build Replay

When the user supplies a copied Strava `build-route` cURL request, do not save or
reuse the pasted Cookie or CSRF headers. Extract only the JSON after `--data-raw`
into a request body file and run:

```bash
python3 -B plugins/strava/scripts/strava_route_api.py build /private/tmp/body.json \
  --out /private/tmp/strava_build_response.json \
  --verbose-log /private/tmp/strava_build_verbose.log
python3 -B plugins/strava/scripts/analyze_strava_build.py \
  /private/tmp/strava_build_response.json \
  --geojson-out /private/tmp/strava_build_response.geojson
```

The verbose log redacts Cookie and CSRF headers. The response contains Strava's
actual generated geometry and route metadata for the requested legs.

If `curl-safari` cannot authenticate the API host, use the copied browser cURL as
the auth source at runtime instead. Keep the copied cURL in the clipboard and run:

```bash
python3 -B plugins/strava/scripts/replay_copied_build_route.py \
  --out /private/tmp/strava_build_response.json \
  --verbose-log /private/tmp/strava_build_verbose.log \
  --body-out /private/tmp/strava_build_body.json
python3 -B plugins/strava/scripts/analyze_strava_build.py \
  /private/tmp/strava_build_response.json \
  --geojson-out /private/tmp/strava_build_response.geojson
```

This stores only the request body, redacted verbose log, and response. Cookie and
CSRF are extracted from the clipboard in memory and not written to the repo.

## Helper Scripts

- `plugins/strava/scripts/score_brouter_vt1.py`: summarize BRouter GeoJSON route classes and VT1 interruption score.
- `plugins/strava/scripts/make_strava_route_js.py`: create Safari-executable JavaScript for build/create/update from a waypoint JSON file.
- `plugins/strava/scripts/strava_route_api.py`: call Strava route-builder APIs with `curl-safari` and fresh CSRF without storing cookies.
- `plugins/strava/scripts/replay_copied_build_route.py`: replay a browser-copied `build-route` request from clipboard when Strava requires browser-copied Cookie+CSRF.
- `plugins/strava/scripts/analyze_strava_build.py`: summarize `build-route` responses, report `Unknown`/`Unpaved` Strava surface lengths, and export the actual Strava polyline as GeoJSON.

These scripts are intentionally local helpers. They do not manage cookies and should be run only with an already logged-in Safari page for Strava write operations.
