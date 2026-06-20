---
name: garmin-connect
description: Use when working with Garmin Connect live data, gccli access, Garmin readiness semantics, Body Battery, Training Readiness, Training Status, Garmin activity metadata, or Garmin write/read safety.
---

# Garmin Connect

Use this skill for Garmin Connect-specific source access and source semantics. The plugin uses the local `gccli` command as the Garmin Connect transport boundary. It can fetch Garmin data and interpret Garmin-specific fields, but it does not own readiness decisions, cross-source training analysis, or plotting.

## Start Here

Use the local CLI when live Garmin Connect data is needed:

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py status
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py recent --days 7 --until <YYYY-MM-DD>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activity <garmin-id-or-saved-intervals-activity>
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activity <garmin-id-or-saved-intervals-activity> --summary-only
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activities --since <YYYY-MM-DD> --until <YYYY-MM-DD>
```

For `activity`, an Intervals.icu id/path is only resolvable when a saved local
activity artifact exists and its metadata contains Garmin's `external_id`.
Fetching or refreshing that artifact belongs to the caller/repo orchestration
layer, not the Garmin plugin.

The CLI prints JSON to stdout and does not write files by default. Some Garmin
payloads are too large for chat or terminal review, especially full `day`,
`recent`, and `activity` without `--summary-only`. For those commands, redirect
stdout to an explicit temporary input file, then inspect or pass that file to
the repo-level helper that asked for it:

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day <YYYY-MM-DD> > /tmp/garmin-connect-day.json
python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD> --garmin-json /tmp/garmin-connect-day.json
```

Garmin Connect authentication is managed outside this repository:

```bash
/opt/homebrew/bin/gccli auth login
```

The plugin prefers `/opt/homebrew/bin/gccli` and falls back to `gccli` on `PATH`.

## Source Semantics

Read `references/field-semantics.md` before interpreting Garmin readiness, Body Battery, HRV, stress, recovery time, Training Status, activity Training Effect, stamina, load, or performance condition.

## Writes

This plugin does not write to Garmin Connect.

## Boundaries

This plugin owns:

- Garmin Connect access through `gccli`
- Garmin-specific field interpretation
- Garmin Connect source quirks, freshness and sync caveats
- compact Garmin activity metric extraction

The caller owns:

- choosing whether to save one explicit JSON response for a downstream analysis step
- readiness composition with Xert, Intervals.icu, EatMyRide, weather, and user preferences
- plotting and report generation
- final training recommendations
