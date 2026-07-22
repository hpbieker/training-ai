---
name: garmin-connect
description: Use when working with Garmin Connect live health, readiness, Body Battery, HRV, sleep, stress, Training Status, activity metrics, gccli access, or Garmin sync semantics.
---

# Garmin Connect

Use this skill for Garmin Connect access, Garmin-specific field interpretation,
and sync/freshness behavior. The plugin is read-only and uses local `gccli` as
its transport boundary.

## Choose The Narrowest Command

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py status
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> --profile readiness
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> --only <source>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py recent --days 7 --until <YYYY-MM-DD>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activities --since <YYYY-MM-DD> --until <YYYY-MM-DD>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activity <garmin-id> --summary-only
```

- Use `day --profile readiness` for normal same-day readiness input.
- Use repeated `--only` values when only selected daily sources are needed.
- Use `recent` when trend context across several days matters.
- Use `activities` to resolve an activity and `activity --summary-only` for
  compact Training Effect, load, stamina, and performance metrics.
- An Intervals.icu activity identifier is resolvable only when a saved local
  artifact contains Garmin's `external_id`. Creating that artifact belongs to
  the caller.

The CLI emits JSON and does not save files. Redirect large `day`, `recent`, or
full activity responses to an explicit temporary file rather than printing them
into chat:

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> --profile readiness > /tmp/garmin-day.json
python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD> --garmin-json /tmp/garmin-day.json
```

Authentication is managed outside the repo with
`/opt/homebrew/bin/gccli auth login`. The plugin prefers that binary and falls
back to `gccli` on `PATH`.

## Semantics

Read [references/field-semantics.md](references/field-semantics.md) before
interpreting readiness, recovery time, Body Battery, HRV, sleep, stress,
Training Status, load, Training Effect, stamina, or performance condition.

Always consider the measurement timestamp and device-sync state. If expected
same-day data is absent or stale enough to change the decision, report that and
ask for a device sync before relying on it.

## Boundaries

This plugin owns Garmin access, compact extraction, field interpretation, and
sync caveats. The caller owns persistence, cross-source composition, plotting,
reports, and final training decisions.
