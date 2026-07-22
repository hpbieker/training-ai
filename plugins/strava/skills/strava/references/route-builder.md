# Strava Route Builder

## Known Endpoints

- `POST /frontend/routes/file` imports GPX as multipart form data with `file`,
  `data_type=gpx`, and `route_type`.
- `POST /api/next/data/routes/build-route` builds legs from a JSON `requests`
  array containing waypoint elements and `routePrefs`.
- `POST /api/next/data/routes/create-route` creates a route from `props` with
  name, description, visibility, starred state, elements, legs, preferences,
  and athlete ID.
- `POST /api/next/data/routes/update-route` updates a route from equivalent
  props plus `routeId`.

A waypoint element has this shape:

```json
{
  "elementType": "Waypoint",
  "waypoint": {
    "point": {"lat": 59.9, "lng": 10.7},
    "metadata": {"title": "Anchor"}
  }
}
```

Common road-cycling preferences are:

```json
{
  "routeType": "Ride",
  "surfaceType": "Paved",
  "popularity": 0,
  "elevation": 0,
  "straightLine": false
}
```

`surfaceType: "Paved"` is a preference, not a guarantee. `popularity: 0` is
more direct while higher values favour popular routing. Add `startElement` with
the zero-based leg index to each returned leg before create/update.

## Build And Inspect

```bash
python3 -B plugins/strava/scripts/strava_route_api.py build /tmp/body.json \
  --out /tmp/strava-build.json --verbose-log /tmp/strava-build.log
python3 -B plugins/strava/scripts/analyze_strava_build.py /tmp/strava-build.json \
  --geojson-out /tmp/strava-build.geojson
```

Before accepting the candidate, verify:

- HTTP success and one returned leg per waypoint gap.
- plausible total distance and no odd out-and-back legs.
- low `snapUncertainty` and sensible generated points.
- actual `paths[].polyline`, directions, and `surfaceTypeOffsets`.
- exported geometry against the required surface and road constraints.

Do not densify a bad baseline route: extra waypoints can preserve an unwanted
shortcut. Prefer a few deliberate, named anchors and rebuild.

GPX import can return a server error for files Strava rejects even when
authentication succeeded. Treat that as possible parser/schema sensitivity and
inspect the file before diagnosing login failure.

## Browser-Copied Requests

Do not save pasted Cookie or CSRF headers. Keep the copied request in the
clipboard and replay it through:

```bash
python3 -B plugins/strava/scripts/replay_copied_build_route.py \
  --out /tmp/strava-build.json \
  --verbose-log /tmp/strava-build.log \
  --body-out /tmp/strava-build-body.json
```

The helper stores only the cookie-free body, redacted log, and response.

## Safari Fallback

When in-page JavaScript is required, first verify that the active tab is on
`https://www.strava.com/maps/create`. Relative API paths must run from the
Strava origin. Generate JavaScript with `make_strava_route_js.py`, save it to a
temporary file, and read that file from AppleScript rather than shell-quoting a
large script.
