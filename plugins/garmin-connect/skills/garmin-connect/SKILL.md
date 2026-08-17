---
name: garmin-connect
description: Use when working with Garmin Connect live health, readiness, Body Battery, HRV, sleep, stress, Training Status, activity metrics, saved courses/routes including upload and deletion, gccli access, or Garmin sync semantics.
---

# Garmin Connect

Use this skill for Garmin Connect access, Garmin-specific field interpretation,
sync/freshness behavior, and tightly scoped course writes. The plugin uses local
`gccli` for authentication and its primary transport boundary.

## Network Execution

Live Garmin Connect reads and writes require external network access. Run live
`garmin_connect_cli.py` commands with escalated network permission on the first
attempt; do not first try them in a network-isolated sandbox. Offline help,
local artifact inspection, and cache-only workflows do not require escalation.

## Choose The Narrowest Command

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py status
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> --profile readiness
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> --profile readiness --compact
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> --only <source>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py recent --days 7 --until <YYYY-MM-DD>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py recent --days 7 --until <YYYY-MM-DD> --only hrv
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activities --since <YYYY-MM-DD> --until <YYYY-MM-DD>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activity <garmin-id> --summary-only
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py courses
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py course <course-id>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py course-upload <course.json> --name "<new name>"
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py course-delete <course-id> --confirm-course-id <course-id>
```

- Use `day --profile readiness` for normal same-day readiness input.
- Add `--compact` when the caller needs stable normalized Training Readiness
  drivers and VO2max context. The compact output retains supporting daily
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
- Use repeated `--only` values when only selected daily sources are needed.
- Use `recent` when trend context across several days matters. Add
  `--only hrv` when the caller needs actual nightly HRV values without fetching
  unrelated daily sources or Body Battery history.
- Use `activities` to resolve an activity and `activity --summary-only` for
  compact Training Effect, load, Stamina, and performance metrics. The compact
  Stamina analysis resolves Garmin's per-activity descriptor indexes, which can
  vary between activities, and reports aligned coverage, start/end/minimum,
  minimum context, Available-versus-Potential gap, rebound, and Potential
  drawdown without returning the raw chart series. It may therefore fetch
  activity chart details internally even though `--summary-only` omits them
  from its output.
- Use `courses` to list saved Garmin Connect courses (routes), including course
  IDs, names, sport types, distances, elevation, start coordinates, and source
  applications.
- Use `course <course-id>` to fetch one saved course with its full Garmin
  payload. The `course.geoPoints` array contains the route geometry and normally
  includes latitude, longitude, elevation, cumulative distance, and timestamp.
  `coursePoints` contains Garmin course/navigation points when the source route
  provides them.
- Use `course-upload` for a metadata-preserving course copy. Its input may be a
  raw Garmin course object or the wrapper emitted by `course`. It posts Garmin's
  accepted save fields directly, then reads the new course back and reports
  geometry and named-point verification. Prefer this over GPX import when route
  points or named course points must survive.
- Use `course-delete` only for the exact course the user authorized. The command
  requires the same ID twice, reads the target before deletion, and verifies
  that the ID disappeared from the course list afterward.
- Courses are planned routes and must not be described or analysed as completed
  activities. Use Garmin's `course` terminology in source-specific code and
  translate it to “rute” in user-facing Norwegian.
- An Intervals.icu activity identifier is resolvable only when a saved local
  artifact contains Garmin's `external_id`. Creating that artifact belongs to
  the caller.

The CLI emits JSON and does not save files. Redirect large `day`, `recent`, full
activity, or full course responses to an explicit temporary file rather than
printing them into chat:

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> --profile readiness > /tmp/garmin-day.json
python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD> --local-timezone <IANA-timezone> --garmin-json /tmp/garmin-day.json
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py course <course-id> > /tmp/garmin-course.json
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
