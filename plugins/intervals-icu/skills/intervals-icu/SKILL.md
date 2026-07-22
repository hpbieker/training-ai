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

The `activity` command fetches activity metadata and optional interval details;
it does not include stream samples. Download streams separately with
`streams <activity-id> --output <file>` when stream data is needed. Streams are
CSV artifacts and should be written to a file, not printed to console output.
Use `save-activity <activity-id>` when a repo-level analysis helper needs a
local activity package; it saves `activity.json` and `streams.csv` under
`outputs/intervals/activities/<date>_<activity-id>/`. This keeps Intervals.icu
download/API access in the plugin while letting repo helpers analyze local
artifacts only.
Use `save-latest` before same-day or next-morning recommendations when recent
activity load matters and the repo-level helper will read the latest local
Intervals artifact. This refreshes the local metadata and streams instead of
letting stale `outputs/intervals/activities/...` data drive readiness context.
Use `activities --since ... --until ...` as the first choice for date-bounded
activity lists, recent-week summaries, and "what workouts did I do" questions.
Use `search <query>` for Intervals.icu's own activity search endpoint. Use
`named <fragment> --since ... --until ...` only when you specifically need a
date-bounded local name-fragment filter.
When the API payload has an activity `id` but no URL field, build the web link
as `https://intervals.icu/activities/<activity-id>`, for example
`https://intervals.icu/activities/i158694373`.

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
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py upload-activity /path/to/activity.fit
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py rename <activity-id> "<new name>"
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py delete-activity <activity-id> --confirm <activity-id>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py subjective <activity-id> --feel <value> --rpe <value>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py wellness-update <YYYY-MM-DD> --soreness <value> --fatigue <value> --motivation <value>
python3 -B plugins/intervals-icu/scripts/intervals_icu_cli.py sick-set --since <YYYY-MM-DD> --until <YYYY-MM-DD> --confirm <START:END>
```

## Authentication

- API-key access should use `INTERVALS_ICU_API_KEY` in the repo-local `.env` by default.
- Other secret stores or process environment variables are acceptable for non-local callers, but do not hard-code keys in scripts or docs.
- API-key auth uses HTTP Basic Auth with username `API_KEY` and the API key as password.
- OAuth bearer tokens are supported by the API module for future callers.
- Web original-file downloads may need `INTERVALS_ICU_COOKIE`; use this only for explicitly requested file recovery when the normal API file endpoint is not enough.
- Do not print API keys, bearer tokens, or cookies.

## Source Semantics

Read `references/field-semantics.md` relative to this skill file, i.e.
`plugins/intervals-icu/skills/intervals-icu/references/field-semantics.md`,
before interpreting Intervals.icu activity load, stream fields, ignore flags,
intervals, wellness, or subjective fields.

## Writes

- Rename or metadata updates must use the plugin CLI/API when the user asks to change Intervals.icu itself.
- Activity deletion must use `delete-activity <activity-id> --confirm <activity-id>`, which fetches the activity first and verifies the delete afterward by default. Only delete activities that the user explicitly asked to remove or that have been identified by a confirmed, narrow duplicate rule.
- Deleting an activity can remove it from date-bounded activity lists while a direct `activity <id>` lookup can still return the id for a while. Verify deletion or replacement with both the date-bounded `activities --since ... --until ...` list and, when relevant, direct lookups for the deleted id and replacement id.
- Activity uploads use `upload-activity <file>` and post the file as multipart form-data field `file` to Intervals.icu. FIT, FIT.GZ, GPX, TCX, and similar activity files can be accepted when Intervals supports the format.
- Intervals.icu may deduplicate uploads and return an existing `i...` activity id instead of creating a new id. It may also reuse an id after delete+reupload. Treat the upload response id as the canonical result, then fetch that id and the date-bounded activity list to verify.
- When repairing Strava API-unavailable stubs, direct Strava-backed activity lookups can return only a stub with `_note`/`note` such as `STRAVA activities are not available via the API`. If a local export file is available, upload it and verify whether the old stub disappears from date-bounded lists. If the export has no file, there may be nothing to repair via API upload.
- Keep original files and Intervals-generated FIT exports separate:
  - `file <activity-id> --kind original` downloads the original uploaded file that Intervals has stored for the activity. This can be byte-identical to a Garmin Connect download or a Strava export file after decompression, and is the right artifact for provenance, duplicate, device-metadata, and byte-hash comparisons.
  - `file <activity-id> --kind fit` downloads an Intervals-generated FIT export. It can omit original device metadata, contain fewer FIT messages, use Intervals as the file creator, and differ in summary fields such as elevation. Do not use this artifact to decide whether two original recordings are the same file.
- Update only fields the user has explicitly provided or confirmed.
- When saving RPE, write `icu_rpe`; Intervals.icu derives `session_rpe` and rejects direct writes to `session_rpe`.
- Activity interval boundaries can be read from `GET /api/v1/activity/<activity-id>/intervals`, which returns `icu_intervals` and `icu_groups`.
- To update activity interval/lap boundaries, use `PUT /api/v1/activity/<activity-id>/intervals` with a JSON array containing only the intended `WORK` intervals and their desired `start_index`/`end_index` (or corresponding time fields). Do not send the full GET response object, `{"icu_intervals": [...]}`, or an array containing `RECOVERY` intervals.
- Intervals.icu regenerates recovery intervals automatically between supplied `WORK` intervals and may regenerate interval ids. Always fetch the intervals before writing, dry-run/diff the old and new boundaries, require explicit confirmation, then fetch again to verify the result.
- When trimming an interval boundary, adjust start and end one second/sample at a time. Trimming can shorten or lengthen an interval: remove tails that are much lower than the interval's intended steady power or average, but also extend the boundary when genuine work starts just before the current start or continues just after the current end. Check single samples as well as short rolling windows: if only the final sample is low after a genuine finishing effort, trimming exactly that one sample can be appropriate. Also check the opposite case: do not trim away genuine work after a temporary low-power patch if power returns to the interval level. Prefer preserving the whole intended effort over making the average look cleaner.
- For daily wellness, do not overwrite an existing value with a different value without explicit confirmation. The CLI enforces this unless `--force` is supplied.
- Record sickness as a calendar event with `category=SICK`, not as a wellness comment. The event end is exclusive; `sick-set` accepts an inclusive user-facing end date and verifies the write.
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
