# Strava Route Builder

## Transport

Use `strava_session_from_safari.py` to fetch Strava's authenticated training page through
curl-safari and create a mode-0600 `Cookie:` header file. Pass that path as
`--cookie-file`. Use the shared Python HTTP session for:

1. authenticated training-page read and athlete-ID discovery;
2. Route Builder GET with the same live browser session cookie;
3. fresh CSRF extraction;
4. API POST with the same runtime cookie and CSRF;
5. HTTP and JSON validation.

Do not store full copied cURL, Authorization, or CSRF values. Keep the temporary
cookie file only for the active workflow, then delete it. Keep only sanitized
templates, response bodies, and redacted logs. Do not use Curl Safari for
Strava until its cookie-completeness issue is resolved; its
disk-backed jar omitted `_strava4_session` from a session Safari demonstrably
used.

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
