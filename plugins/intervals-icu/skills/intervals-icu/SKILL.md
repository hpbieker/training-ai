---
name: intervals-icu
description: Use for Intervals.icu live activity lookup, date-bounded activity lists, local activity packages and streams, intervals, wellness and sickness events, subjective feel/RPE, ignore flags, original-file recovery, uploads, metadata updates, or other Intervals.icu write-safety workflows.
---

# Intervals.icu

Use this skill for Intervals.icu-specific source access, source semantics, and write safety. The plugin can fetch live data and perform cautious remote updates, but it does not own repo-level training analysis, plotting, readiness composition, or long-term storage.

## Task Routing

Choose the narrowest workflow that answers the request:

- Today's or a bounded period's activities: run `activities --since ... --until ...` first. Verify local date and activity identity before analysis.
- Latest activity when no date is implied: run `latest`; use `save-latest` only when a downstream helper needs a local package.
- Workout analysis: resolve the activity id, run `save-activity <id>`, then pass the returned `activity_dir` to the repo analysis helper. Do not analyze metadata alone when streams are available and relevant.
- Metadata or interval orientation only: run `activity <id> --summary-only`; use full `activity` only when the extra fields are needed.
- Raw stream export without a package: run `streams <id> --output <file>`; never print streams to the terminal.
- Readiness context: fetch bounded `wellness` and `events`; let the caller compose readiness. Prefer Garmin Connect for current Garmin HRV, resting HR, sleep, stress, Training Readiness, and Body Battery.
- Subjective follow-up: read current activity fields first; write only user-confirmed `feel` or RPE and verify afterward.
- Any remote mutation: read `references/write-safety.md` first and perform a fresh readback.

## CLI

Use the local CLI when Intervals.icu access is needed:

```bash
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py latest
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py activities --since <YYYY-MM-DD> --until <YYYY-MM-DD>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py activity <activity-id>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py activity <activity-id> --summary-only
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py save-activity <activity-id>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py save-latest
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py streams <activity-id> --output /tmp/intervals-streams.csv
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py search <query> --limit 10
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py named <name-fragment> --since <YYYY-MM-DD> --until <YYYY-MM-DD>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py wellness --since <YYYY-MM-DD> --until <YYYY-MM-DD>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py events --since <YYYY-MM-DD> --until <YYYY-MM-DD> --category SICK
```

The `activity` command fetches metadata and intervals, not stream samples.
`save-activity <activity-id>` saves `activity.json` and `streams.csv` under
`outputs/intervals/activities/<date>_<activity-id>/` and returns the canonical
`activity_dir` for repo helpers. Prefer it over separate metadata and stream
calls for normal workout analysis. Refresh the selected activity package when
the live activity has just synced or changed; do not blindly rewrite unrelated
cached packages because their mtimes can invalidate route-analysis caches.

Use `activities --since ... --until ...` for date-bounded lists and recent-load
checks. Treat `latest` as a source-selection convenience, not proof that an
activity belongs to the user's requested local day. Use `search <query>` for
Intervals.icu's search endpoint, and `named <fragment> --since ... --until ...`
only for a deliberate date-bounded name filter.
When the API payload has an activity `id` but no URL field, build the web link
as `https://intervals.icu/activities/<activity-id>`, for example
`https://intervals.icu/activities/i158694373`.

Normal commands print JSON. Write large activity, wellness, stream, or original
file payloads to explicit temporary paths with `--output`; never print streams
or secrets to the terminal.

## Freshness And Handoff

- Fetch live data for same-day analysis, readiness, or post-workout evaluation unless the caller explicitly requests offline/cache-only work.
- After finding a newly completed activity, save that exact id before running repo analysis; do not assume an older local `latest` package updated itself.
- Keep source payloads and stream artifacts as inputs. Pass normalized or packaged output to the repo helper; do not make repo helpers call Intervals.icu directly.
- If live access fails, report which source call failed and whether the available local package predates the activity's latest sync. Do not silently present cached data as current.
- Intervals.icu wellness can contain copied Garmin values, but it is not the preferred live source for Garmin Body Battery or other Garmin-specific readiness signals. Expose those through the Garmin source layer and let the repo-level training skill combine them with Intervals activity/load context.

## Source Semantics

Read `references/field-semantics.md` relative to this skill file, i.e.
`plugins/intervals-icu/skills/intervals-icu/references/field-semantics.md`,
before interpreting Intervals.icu activity load, stream fields, ignore flags,
intervals, wellness, or subjective fields.

## Writes

Before renaming, uploading, deleting, editing intervals, changing wellness or
sickness, saving subjective fields, or recovering original files, read
`references/write-safety.md`. Mutate only what the user authorized and verify
every write with a fresh readback.

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
- cross-source readiness composition and final training decisions
- plotting and report generation
- final training recommendations
