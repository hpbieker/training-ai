---
name: strava
description: Read and change Strava activities, tags, visibility, routes, Route Builder state, and authenticated Strava data with Python HTTP after a curl-safari session bootstrap. Use for activity or route inspection and mutation, or when creating a cycling route from a start location, target distance, route shape, direction, surface, elevation, popularity, and optional via points.
---

# Strava

Use `strava_session_from_safari.py` to visit the Strava training page through
`curl-safari`, export the reconstructed live cookie jar, and write the private
persistent session cache at `~/.strava/session.headers`. The remaining scripts
use that cache by default through Python's standard HTTP client.

## Network Execution

Live Strava reads and writes require external network access. Run the live
`plugins/strava/scripts/` commands with escalated
network permission on the first attempt; do not first try them in a
network-isolated sandbox. The bootstrap depends on the local curl-safari server
and its Safari cookie access. Offline help
and local response or artifact inspection do not require network escalation.

## Authentication

Follow the `curl-safari` skill completely. Safari must already be logged in.

Never print Cookie, Authorization, CSRF, or copied full cURL content. Retain
only the Cookie header in `~/.strava/session.headers` until it expires, is
replaced by a verified capture, or the user explicitly clears it. The
`~/.strava` directory must be mode 0700 and the files mode 0600. The cookie
value must not appear in command arguments. An optional `--header-file` may contain
non-secret browser headers, but never Cookie, Authorization, or CSRF. Keep
response bodies and redacted verbose logs in `/private/tmp`.

Verify authentication before other calls:

```bash
python3 -B plugins/strava/scripts/strava_route_api.py auth
```

Create the required private cookie file:

```bash
python3 -B plugins/strava/scripts/strava_session_from_safari.py
```

When curl-safari cannot provide a complete session, copy a live authenticated
request as cURL in Safari Web Inspector and import it without retaining the
complete cURL command:

```bash
python3 -B plugins/strava/scripts/strava_session.py import-curl
```

Use `strava_session.py status` to validate the cached session and
`strava_session.py clear` for explicit logout or credential cleanup. All
request scripts resolve the cookie file in this order: `--cookie-file`,
`STRAVA_COOKIE_FILE`, then `~/.strava/session.headers`.

### Why Not Curl Safari

Do not use Curl Safari for Strava authentication unless its open cookie-
completeness investigation proves the behavior fixed. On 2026-07-28, an
authenticated Safari request contained Strava session cookies including
`_strava4_session` and `_strava_idcf`, while Curl Safari's parsed disk-backed
jar omitted them and the same dashboard URL redirected to `/login`.

The root cause may be cookie-file/profile selection, binarycookies parsing, or
filtering rather than non-persistence. Do not encode a speculative fallback.
The live curl-safari jar is the source of truth for the active session; Python
HTTP is the transport after bootstrap. If curl-safari cannot provide
`_strava4_session` that Strava accepts for the training page, use
`browser-curl-replay` and
`strava_cookie_from_curl.py` as the fallback.

This is not credential login. Safari must already be logged in, and the Mac
must be unlocked for a new Web Inspector capture when the session expires.

## Activities

Read [references/write-safety.md](references/write-safety.md) before writes.
Use the user-oriented tools exposed by `strava_cli.py`: `list_activities`,
`get_activity`, `update_activity`, and `update_activities`. Inspect their
current MCP-like JSON schemas with `strava_cli.py tools` or
`strava_cli.py describe TOOL`. Session handling is internal and is not exposed
as a user-oriented tool.

Use `list_activities` for date-bounded discovery and visibility filtering:

```bash
python3 -B plugins/strava/scripts/strava_cli.py call list_activities \
  --json '{"since":"2026-08-01","visibility":"only_me"}'
```

Use the returned activity IDs for exact reads or writes. Pass one or more IDs
to `strava_activity_tags.py`. It supports activity name, primary tag, trainer flag,
visibility, hidden start time, and bike by exact ID or exact edit-form name.
Omitted fields are preserved; use `--tag none` only for an explicit tag clear.
Every operation reads back API state plus edit-page-only bike and start-time
state.

```bash
python3 -B plugins/strava/scripts/strava_cli.py call update_activity \
  --json '{"activity_id":123,"patch":{"tag":"Workout","visibility":"everyone"},"confirm":true}'
```

## Routes

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

Run `strava_create_route.py` with `--cookie-file`, the resolved start,
distance, shape, routing choices, and an output directory. Omit `--yes` to
build and inspect only. Creating a route is a Strava write; add `--yes` only
when the user explicitly asked to create or save it. New routes default to
`OnlyMe`; use `Everyone` only when explicitly requested. Report the verified
route URL, distance, elevation, surface uncertainty, shape, and material road
or traffic caveats.

## Boundaries

This plugin owns Strava session mechanics, route-builder payloads, activity
mutations, and readback verification. The caller owns personal route
preferences, candidate selection, maps, and final route or training decisions.
