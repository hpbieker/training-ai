---
name: xert
description: Use when working with Xert live data, recovery and XSS semantics, activity or workout fields, Workout Designer rows, calendar notes, or Xert writes.
---

# Xert

Use this skill for Xert access, field interpretation, API quirks, and safe
writes. The plugin is stateless and returns normalized data to callers.

## Choose The Narrowest Command

```bash
python3 -B plugins/xert/scripts/xert_cli.py activities <start-date> <end-date>
python3 -B plugins/xert/scripts/xert_cli.py activity-loads <start-date> <end-date>
python3 -B plugins/xert/scripts/xert_cli.py activity <path> --summary-only
python3 -B plugins/xert/scripts/xert_cli.py readiness-input [--activity <path>]
python3 -B plugins/xert/scripts/xert_cli.py readiness-input --advice-source auto --advice-at <ISO-local-datetime>
python3 -B plugins/xert/scripts/xert_cli.py recommended-training --date <YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py workouts --summary
python3 -B plugins/xert/scripts/xert_cli.py workout <path>
python3 -B plugins/xert/scripts/xert_cli.py workout-rows <path>
python3 -B plugins/xert/scripts/xert_cli.py training-forecast
python3 -B plugins/xert/scripts/xert_cli.py calendar-notes
```

- Use `activities` for activity discovery. Pass the intended inclusive local
  calendar dates; the CLI handles UTC conversion.
- Use `activity-loads` for compact XSS history. Do not loop over individual
  activity details from the caller.
- Use `activity --summary-only` for normal activity analysis. It includes the
  XSS split, XEP, focus, specificity, difficulty, freshness, and fitness
  signature.
- Use `readiness-input` for normalized recovery and training-advice context.
  Do not pass raw Xert payloads to readiness consumers.
- Use `recommended-training` when candidate workouts or activities are needed,
  and filter workout selection to `exerciseType == "Workout"`.
- Use `workout-rows` for editable Workout Designer structure, especially for
  repeat or slope rows. The resolved OAuth workout can be incomplete for these.

Credentials come from `XERT_USERNAME` and `XERT_PASSWORD` in `.env`.

## Planned-Time Advice

For advice now, the default `readiness-input` source is the faster
`/my-fitness`. For a planned time, use `--advice-source auto --advice-at`; auto
switches to planned-time advice when needed. Force
`--advice-source recommended-training` only when the caller specifically needs
that source.

The payload keeps `recovery.recovery_hours` at `source_time_local` and adds
`recovery.recovery_hours_at_advice_time` when a planned time is supplied. The
latter is a no-intervening-training projection. Use the projected value for the
planned decision while preserving the raw value for auditability.

Keep `recent=true` and `additional=false` for normal primary advice. Change
them only when the caller explicitly wants older repeat candidates or extra
training.

## Session Data

Use session data only for Xert-specific time-series fields that are unavailable
from a better source. Always write it to an explicit temporary file and never
print it to chat or terminal output:

```bash
python3 -B plugins/xert/scripts/xert_cli.py activity <path> --session-data --output /tmp/xert-activity.json
```

## Semantics And Writes

- Read [references/field-semantics.md](references/field-semantics.md) before
  interpreting recovery, XSS, activity, forecast, workout, or calendar fields.
- Read [references/write-safety.md](references/write-safety.md) before any
  calendar-note, workout update, copy, calculation, or deletion operation.

## Boundaries

This plugin owns Xert authentication, live access, field interpretation, API
quirks, and write safety. The caller owns persistence, cross-source analysis,
plotting, reports, and user-specific training decisions or workout templates.
