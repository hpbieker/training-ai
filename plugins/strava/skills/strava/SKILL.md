---
name: strava
description: Use when reading or changing Strava activities, tags, visibility, routes, Route Builder state, GPX imports, or Safari-authenticated Strava data.
---

# Strava

Use this skill for authenticated Strava activity and route workflows. Prefer
the bundled helpers, keep authentication material ephemeral, and verify every
write from Strava's current state.

## Choose The Workflow

- For an activity's tag, trainer, visibility, or hidden-start state, use
  `plugins/strava/scripts/strava_activity_tags.py`.
- For a known Route Builder JSON body, use
  `plugins/strava/scripts/strava_route_api.py`.
- For a browser-copied build request, use
  `plugins/strava/scripts/replay_copied_build_route.py` so Cookie and CSRF data
  remain in memory.
- For response inspection and GeoJSON export, use
  `plugins/strava/scripts/analyze_strava_build.py`.
- For BRouter/OSM candidate checks, use
  `plugins/strava/scripts/score_brouter_vt1.py`.
- Use Safari in-page JavaScript only when a helper cannot express the required
  Route Builder request.

## Authentication

Use `curl-safari` for pages that require the user's logged-in Safari session.
Route-builder requests must originate from Strava state, and activity form
writes must keep the edit-page CSRF token and its resulting session cookie
together.

Never expose or persist Cookie, CSRF, or session headers. It is safe to persist
reviewed request bodies, redacted logs, and responses in temporary files.

## Activities

Read one activity's editable state with:

```bash
python3 -B plugins/strava/scripts/strava_activity_tags.py <activity-id> --read
```

Read [references/write-safety.md](references/write-safety.md) before changing
an activity tag, trainer flag, visibility, hidden start time, or any route.

## Routes

Read [references/route-builder.md](references/route-builder.md) before building,
importing, creating, or updating a route. Inspect Strava's returned geometry;
waypoints and a successful HTTP status are not sufficient verification.

Read [references/route-quality.md](references/route-quality.md) when assessing a
cycling route for surface, interruptions, road suitability, or steady pacing.
Apply caller-provided location, surface, and route preferences rather than
embedding personal route history in this skill.

Keep new routes private by default unless the user explicitly requests another
visibility.

## Boundaries

This plugin owns Strava session mechanics, route-builder payload semantics,
Strava activity mutations, and their verification. The caller owns personal
route preferences, saved-activity selection, cross-source analysis,
persistence, maps/reports, and final route or training decisions.
