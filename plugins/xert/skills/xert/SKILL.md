---
name: xert
description: Use when working with Xert live data, recovery model semantics, activity/workout fields, Workout Designer rows, calendar notes, or Xert write-safety rules.
---

# Xert

Use this skill for Xert-specific source access and source semantics. The plugin is intentionally stateless: it can read from or write to Xert, but it does not own cross-source training analysis, readiness decisions, or plotting.

## Start Here

Use the local CLI when live Xert data is needed:

```bash
python3 -B plugins/xert/scripts/xert_cli.py activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py activity-loads <start-YYYY-MM-DD> <end-YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py activity <activity-path> [--summary-only|--session-data --output /tmp/xert-activity.json]
python3 -B plugins/xert/scripts/xert_cli.py training-info
python3 -B plugins/xert/scripts/xert_cli.py recovery-model
python3 -B plugins/xert/scripts/xert_cli.py readiness-input [--activity <activity-path>]
python3 -B plugins/xert/scripts/xert_cli.py readiness-input --advice-source auto --advice-at <ISO-local-datetime>
python3 -B plugins/xert/scripts/xert_cli.py readiness-input --advice-source recommended-training --advice-at <ISO-local-datetime>
python3 -B plugins/xert/scripts/xert_cli.py workouts [--contains "<text>"] [--summary]
python3 -B plugins/xert/scripts/xert_cli.py workout <workout-path>
python3 -B plugins/xert/scripts/xert_cli.py workout-rows <workout-path>
python3 -B plugins/xert/scripts/xert_cli.py workout-calculate --duration <MM:SS> --power-type relative_ftp --power <percent-of-TP>
python3 -B plugins/xert/scripts/xert_cli.py training-forecast
python3 -B plugins/xert/scripts/xert_cli.py calendar-notes
python3 -B plugins/xert/scripts/xert_cli.py recommended-training --date <YYYY-MM-DD>
```

For `activities`, pass the user's intended local calendar dates. The command treats
both dates as an inclusive local-date range on the machine running the command and
converts the boundaries to UTC timestamps for Xert.

Use `activity-loads` when a caller needs XSS history for dose/load decisions. It
lists activities and fetches compact detail rows with total/low/high/peak XSS,
duration, difficulty, XEP, focus and activity path while reusing one Xert token.
Prefer it over looping over `activity --summary-only` from the caller.

For activity analyses, prefer:

```bash
python3 -B plugins/xert/scripts/xert_cli.py activity <activity-path> --summary-only
```

This returns compact Xert load/context fields such as XSS split, XEP, focus,
specificity, difficulty, freshness and fitness signature. Use full `activity`
only when the raw Xert payload is needed.

Use `--session-data` only when Xert-specific time-series fields are specifically
needed and are not already available from a better source. The session payload
can include second-by-second fields such as Xert difficulty/MPA/model fields,
heart rate, power, speed, elevation and other activity streams. For routine
activity analysis, prefer Intervals.icu or Garmin streams when they already
contain the data needed, and do not call Xert `--session-data` just to duplicate
those time series.

When `--session-data` is needed, always write it to an explicit temporary file:

```bash
python3 -B plugins/xert/scripts/xert_cli.py activity <activity-path> --session-data --output /tmp/xert-activity.json
```

Do not print Xert session data to chat or terminal output.

Credentials are read from `.env`:

```text
XERT_USERNAME=your-email@example.com
XERT_PASSWORD=your-password
```

The plugin obtains any short-lived Xert session state from those credentials when needed.

Use `readiness-input` when a caller needs normalized Xert readiness context. It
returns a narrow JSON object with selected fields such as
`recovery.recovery_hours`, `recovery.training_load`, `recovery.recovery_load`,
`recovery.workout_capacity`, `training_advice.target_xss` and optional
`activity_loads`. Do not pass raw Xert API payloads to readiness consumers.

By default `readiness-input` uses `/my-fitness` for `training_advice` because it
is the faster source for Xert advice "now". When a caller needs Xert advice for
a planned time, prefer `--advice-source auto --advice-at <ISO-local-datetime>`.
Auto uses `/recommended-training` when the planned time is on another local date,
or when the planned time is later than now and current `/my-fitness` advice is
not fresh. It otherwise keeps the faster `/my-fitness` source. Use
`--advice-source recommended-training` to force planned-time advice. The plugin
mirrors Xert's UI behavior by sending the selected time minus one second as the
`date` query parameter. That response can include
`target_xss`, `remaining_xss`, `completed_xss`, `original_target_xss`,
`training_advice_as_of`, availability and daily-goal fields.

`readiness-input` includes `training_advice_debug` so callers can audit why
`/my-fitness` or `/recommended-training` was selected and compare current vs
planned-time target XSS when the values diverge.

`recovery.recovery_hours` always applies at the payload's top-level
`source_time_local`, including when `--advice-at` is supplied. `--advice-at`
selects planned-time `training_advice` and also adds
`recovery.recovery_hours_at_advice_time`, a deterministic projection that
assumes no intervening training. Keep `recovery.recovery_hours` as the auditable
raw state at `source_time_local`; use the projected field for decisions at the
requested advice time.

For `/recommended-training`, keep `recent=true` for normal recommendations.
Only use `recent=false` when the caller explicitly wants repeat suggestions from
older activities beyond the recent window. Keep `additional=false` for primary
training advice; `additional=true` is for allowing extra/additional training and
should be explicit.

`training_advice.target_xss` maps Xert `targetXSS`: `xlss` to `low`, `xhss` to
`high`, and `xpss` to `peak`. Treat this as Xert's current or planned-time target /
recommended XSS dose for the training advice context. It reflects activities
Xert has already accounted for. It is not a recovery target, historical activity
load, workout-library XSS, `workout_capacity`, or a repo-calculated "remaining
XSS after today's completed rides" value.

## Writes

Writes must be explicit and verified. Do not perform a write unless the user has clearly asked for it.

```bash
python3 -B plugins/xert/scripts/xert_cli.py calendar-note-set <YYYY-MM-DD> "<note>" --yes
python3 -B plugins/xert/scripts/xert_cli.py workout-update <workout-path> --match-name "<row>" --set-duration <MM:SS> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-update <workout-path> --match-name "<row>" --set-duration <MM:SS> --yes
python3 -B plugins/xert/scripts/xert_cli.py workout-update <workout-path> --match-name "<row>" --set-row-name "<new row name>" --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-update <workout-path> --match-name "<row>" --set-interval-count <N> --set-rib-duration <MM:SS> --set-rib-power <value> --set-rib-power-type <type> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-delete <workout-path> --yes
```

Use `workout-calculate` for synthetic, non-persistent XSS probes. It creates a
new unsaved Workout Designer calculation and returns low/high/peak XSS without
saving a workout. Use `--dry-run` for Workout Designer validation when the user
is exploring a change to an existing workout. Use `--yes` only when the user has
confirmed persistence.

After any successful write, read back the affected object with the relevant command:

- `python3 -B plugins/xert/scripts/xert_cli.py calendar-notes` after `calendar-note-set`
- `python3 -B plugins/xert/scripts/xert_cli.py workout-rows <workout-path>` after `workout-update`
- `python3 -B plugins/xert/scripts/xert_cli.py workouts --summary` after `workout-update` or `workout-delete`

## Source Semantics

Read `references/field-semantics.md` relative to this skill file, i.e.
`plugins/xert/skills/xert/references/field-semantics.md`, before interpreting
Xert recovery, activity, workout, calendar, or Workout Designer fields.

## Boundaries

This plugin owns:

- Xert authentication and live API/web access
- Xert field interpretation
- Xert API quirks
- Xert write-safety rules

The caller owns:

- local persistence
- cross-source analysis with Garmin, Intervals.icu, EatMyRide, weather, or user preferences
- plotting and report generation
- user-specific workout construction templates
