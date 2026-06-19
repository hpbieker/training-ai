---
name: xert
description: Use when working with Xert live data, recovery model semantics, activity/workout fields, Workout Designer rows, calendar notes, or Xert write-safety rules.
---

# Xert

Use this skill for Xert-specific source access and source semantics. The plugin is intentionally stateless: it can read from or write to Xert, but it does not own local caching, cross-source training analysis, readiness decisions, or plotting.

## Start Here

Use the local CLI when live Xert data is needed:

```bash
python3 -B plugins/xert/scripts/xert_cli.py activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py activity <activity-path> [--session-data]
python3 -B plugins/xert/scripts/xert_cli.py training-info
python3 -B plugins/xert/scripts/xert_cli.py recovery-model
python3 -B plugins/xert/scripts/xert_cli.py readiness-input [--activity <activity-path>]
python3 -B plugins/xert/scripts/xert_cli.py workouts [--contains "<text>"] [--summary]
python3 -B plugins/xert/scripts/xert_cli.py workout <workout-path>
python3 -B plugins/xert/scripts/xert_cli.py workout-rows <workout-path>
python3 -B plugins/xert/scripts/xert_cli.py training-forecast
python3 -B plugins/xert/scripts/xert_cli.py calendar-notes
python3 -B plugins/xert/scripts/xert_cli.py recommended-training --date <YYYY-MM-DD>
```

For `activities`, pass the user's intended local calendar dates. The command treats
both dates as an inclusive local-date range on the machine running the command and
converts the boundaries to UTC timestamps for Xert.

Credentials are read from `.env`:

```text
XERT_USERNAME=your-email@example.com
XERT_PASSWORD=your-password
```

The plugin obtains any short-lived Xert session state from those credentials when needed.

Use `readiness-input` when a caller needs normalized Xert readiness context. It
returns a narrow JSON object with selected fields such as
`recovery.recovery_hours`, `recovery.training_load`, `recovery.recovery_load`,
`recovery.workout_capacity` and optional `activity_loads`. Do not pass raw Xert
API payloads to readiness consumers.

## Writes

Writes must be explicit and verified. Do not perform a write unless the user has clearly asked for it.

```bash
python3 -B plugins/xert/scripts/xert_cli.py calendar-note-set <YYYY-MM-DD> "<note>" --yes
python3 -B plugins/xert/scripts/xert_cli.py workout-update <workout-path> --match-name "<row>" --set-duration <MM:SS> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-update <workout-path> --match-name "<row>" --set-duration <MM:SS> --yes
python3 -B plugins/xert/scripts/xert_cli.py workout-delete <workout-path> --yes
```

Use `--dry-run` for Workout Designer validation when the user is exploring a change. Use `--yes` only when the user has confirmed persistence.

After any successful write, read back the affected object with the relevant command:

- `python3 -B plugins/xert/scripts/xert_cli.py calendar-notes` after `calendar-note-set`
- `python3 -B plugins/xert/scripts/xert_cli.py workout-rows <workout-path>` after `workout-update`
- `python3 -B plugins/xert/scripts/xert_cli.py workouts --summary` after `workout-update` or `workout-delete`

## Source Semantics

Read `references/field-semantics.md` before interpreting Xert recovery, activity, workout, calendar, or Workout Designer fields.

## Boundaries

This plugin owns:

- Xert authentication and live API/web access
- Xert field interpretation
- Xert API quirks
- Xert write-safety rules

The caller owns:

- local persistence/cache
- cross-source analysis with Garmin, Intervals.icu, EatMyRide, weather, or user preferences
- plotting and report generation
- user-specific workout construction templates
