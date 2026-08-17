---
name: garmin-connect
description: Use when working with Garmin Connect live health, readiness, Body Battery, HRV, sleep, stress, Training Status, activity metrics, saved courses/routes including upload and deletion, gccli access, or Garmin sync semantics.
---

# Garmin Connect

Use this skill for Garmin Connect access, Garmin-specific field interpretation,
sync/freshness behavior, and tightly scoped course writes. The plugin uses local
`gccli` for authentication and its primary transport boundary. Health, activity,
and course operations are exposed through MCP.

## Network Execution

Live Garmin Connect reads and writes require external network access. Use the
Garmin Connect MCP tools for health, activity, and course operations. Offline
help, local artifact inspection, and cache-only workflows do not require
external access.

## Choose The Narrowest Command

```bash
get_health_day(date=<YYYY-MM-DD>)
list_health_days(until=<YYYY-MM-DD>, days=7, sources=["hrv"])
list_activities(since=<YYYY-MM-DD>, until=<YYYY-MM-DD>)
get_activity(activity_id=<garmin-id>)
list_courses()
get_course(course_id=<course-id>)
create_course(course=<get-course-result>, name=<new-name>)
delete_course(course_id=<course-id>, confirm_course_id=<course-id>)
```

- Use `get_health_day` for normal same-day readiness input. Its stable compact
  output includes normalized Training Readiness drivers and VO2max context and retains supporting daily
  source signals needed for readiness composition and preserves all normalized
  readiness observations so a historical cutoff can select the correct row.
  Compact VO2max preserves Garmin's `cycling` and `generic` categories; it does
  not guess that `generic` means running or infer a VO2max source device from
  the separate Training Status device context.
- For a future-day training recommendation, fetch the latest day that has
  actually occurred and project its timestamped Recovery Time to the planned
  start. Do not fetch the empty future day as the only Garmin input, and do not
  carry the latest day's HRV, sleep, resting HR, Body Battery, or aggregate
  Training Readiness forward as future observations.
- Use `sources` when only selected daily sources are needed.
- Use `list_health_days` when trend context across several days matters. Pass
  `sources=["hrv"]` when the caller needs actual nightly HRV values without fetching
  unrelated daily sources or Body Battery history.
- Use `list_activities` to resolve an activity from compact identity summaries.
  Use `includeFields` to add only selected Garmin training details to each row;
  moving duration and account or profile fields are not part of the default.
  Use `get_activity` for
  compact Training Effect, load, Stamina, and performance metrics. The compact
  Stamina analysis resolves Garmin's per-activity descriptor indexes, which can
  vary between activities, and reports aligned coverage, start/end/minimum,
  minimum context, Available-versus-Potential gap, rebound, and Potential
  drawdown without returning the raw chart series. It may therefore fetch
  activity chart details internally even though the MCP result omits them
  from its output.
- Use `list_courses` to list saved Garmin Connect courses (routes) as compact
  identity rows containing course ID, name, sport type, distance, and source.
  Use `includeFields` for selected elevation, start-point, timing, ownership,
  privacy, or source details.
- Use `get_course` to fetch one saved course with its full Garmin
  payload. The `course.geoPoints` array contains the route geometry and normally
  includes latitude, longitude, elevation, cumulative distance, and timestamp.
  `coursePoints` contains Garmin course/navigation points when the source route
  provides them.
- Use `create_course` for a metadata-preserving course copy. Its input may be a
  raw Garmin course object or the wrapper emitted by `get_course`. It posts Garmin's
  accepted save fields directly, then reads the new course back and reports
  geometry and named-point verification. Prefer this over GPX import when route
  points or named course points must survive.
- Use `delete_course` only for the exact course the user authorized. The tool
  requires the same ID twice, reads the target before deletion, and verifies
  that the ID disappeared from the course list afterward.
- Courses are planned routes and must not be described or analysed as completed
  activities. Use Garmin's `course` terminology in source-specific code and
  translate it to “rute” in user-facing Norwegian.
- An Intervals.icu activity identifier is resolvable only when a saved local
  artifact contains Garmin's `external_id`. Creating that artifact belongs to
  the caller.

The MCP tools return structured content and do not own persistence. When a repo
helper needs Garmin data, persist the normalized MCP result explicitly and pass
that file as a source override:

```bash
python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD> --local-timezone <IANA-timezone> --garmin-json /tmp/garmin-day.json
```

Authentication is managed outside the repo with
`/opt/homebrew/bin/gccli auth login`. The plugin prefers that binary and falls
back to `gccli` on `PATH`.

Before uploading or deleting a course, read
[references/course-write-safety.md](references/course-write-safety.md).

## Semantics

Read [references/field-semantics.md](references/field-semantics.md) before
interpreting readiness, recovery time, Body Battery, HRV, sleep, stress,
Training Status, load, Training Effect, stamina, or performance condition.
For model reasoning about Training Effect, Stamina, or Recovery Time, also read
[references/training-effect-and-stamina-models.md](references/training-effect-and-stamina-models.md).
For model reasoning about aggregate Training Readiness or running/cycling
VO2max, also read
[references/readiness-and-vo2max-models.md](references/readiness-and-vo2max-models.md).
For model reasoning about sleep, physiological stress, Body Battery, calories,
or heartbeat-derived oxygen consumption, also read
[references/wellness-and-energy-models.md](references/wellness-and-energy-models.md).
Use [references/sources.md](references/sources.md) when a claim needs provenance,
evidence-strength qualification, or a primary-source link.

Always consider the measurement timestamp and device-sync state. If expected
same-day data is absent or stale enough to change the decision, report that and
ask for a device sync before relying on it.

## Boundaries

This plugin owns Garmin access, compact extraction, field interpretation,
course upload/deletion, and sync caveats. The caller owns persistence,
cross-source composition, plotting, reports, and final training decisions.
