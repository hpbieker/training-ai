---
name: intervals-icu
description: Use when working with Intervals.icu live API access, activity metadata, stream data, intervals, wellness fields, subjective feel/RPE fields, Intervals.icu ignore flags, or Intervals.icu write safety.
---

# Intervals.icu

Use this skill for Intervals.icu-specific source access, source semantics, and write safety. The plugin can fetch live data and perform cautious remote updates, but it does not own repo-level training analysis, plotting, readiness composition, or long-term storage.

## CLI

Use the local CLI when Intervals.icu access is needed:

```bash
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py latest
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py activity <activity-id>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py activity <activity-id> --summary-only
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py streams <activity-id> --output /tmp/intervals-streams.csv
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py search <query> --limit 10
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py named <name-fragment> --since <YYYY-MM-DD> --until <YYYY-MM-DD>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py wellness --since <YYYY-MM-DD> --until <YYYY-MM-DD>
```

The `activity` command fetches activity metadata and optional interval details;
it does not include stream samples. Download streams separately with
`streams <activity-id> --output <file>` when stream data is needed. Streams are
CSV artifacts and should be written to a file, not printed to console output.
Use `search <query>` for Intervals.icu's own activity search endpoint. Use
`named <fragment> --since ... --until ...` only when you specifically need a
date-bounded local name-fragment filter.

The normal CLI commands print JSON and do not write files unless `--output` is supplied. Use explicit file download commands only when a file is actually needed:

```bash
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py file <activity-id> --kind original --output /tmp/intervals-files/
```

Some Intervals.icu payloads are too large for chat or terminal review,
especially full `activity` responses with intervals and longer `wellness` or
activity-list ranges. Activity streams are CSV artifacts and must be written to
an explicit temporary input file with `--output`. Then inspect or pass that file
to the repo-level helper that asked for it:

```bash
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py activity <activity-id> --output /tmp/intervals-activity.json
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py streams <activity-id> --output /tmp/intervals-streams.csv
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py wellness --since <YYYY-MM-DD> --until <YYYY-MM-DD> --output /tmp/intervals-wellness.json
```

For remote updates:

```bash
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py rename <activity-id> "<new name>"
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py subjective <activity-id> --feel <value> --rpe <value>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py wellness-update <YYYY-MM-DD> --soreness <value> --fatigue <value> --motivation <value>
```

## Authentication

- API-key access should use `INTERVALS_ICU_API_KEY` in the repo-local `.env` by default.
- Other secret stores or process environment variables are acceptable for non-local callers, but do not hard-code keys in scripts or docs.
- API-key auth uses HTTP Basic Auth with username `API_KEY` and the API key as password.
- OAuth bearer tokens are supported by the API module for future callers.
- Web original-file downloads may need `INTERVALS_ICU_COOKIE`; use this only for explicitly requested file recovery when the normal API file endpoint is not enough.
- Do not print API keys, bearer tokens, or cookies.

## Source Semantics

Read `references/field-semantics.md` before interpreting Intervals.icu activity load, stream fields, ignore flags, intervals, wellness, or subjective fields.

## Writes

- Rename or metadata updates must use the plugin CLI/API when the user asks to change Intervals.icu itself.
- Update only fields the user has explicitly provided or confirmed.
- When saving RPE, write `icu_rpe`; Intervals.icu derives `session_rpe` and rejects direct writes to `session_rpe`.
- For daily wellness, do not overwrite an existing value with a different value without explicit confirmation. The CLI enforces this unless `--force` is supplied.
- Refresh/read back the activity or wellness day after updating when the result matters to the user-facing answer.

## Boundaries

This plugin owns:

- Intervals.icu API transport and auth conventions
- Intervals.icu field interpretation and source quirks
- cautious Intervals.icu activity and wellness writes
- activity, file, and wellness fetch helpers

The caller owns:

- deciding when to persist any explicitly requested artifacts
- writing large JSON responses to explicit temporary input files for downstream analysis
- activity inspection and interval/work-block analysis
- readiness composition with Xert, Garmin, EatMyRide, weather, and user preferences
- plotting and report generation
- final training recommendations
