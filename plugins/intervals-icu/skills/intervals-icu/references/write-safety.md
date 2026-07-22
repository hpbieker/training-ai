# Intervals.icu Write Safety

Read this file before any Intervals.icu mutation.

## General

- Update only fields the user explicitly provided or confirmed.
- Use the plugin CLI/API, then fetch the affected activity, wellness day, or
  date-bounded list and verify the requested state.
- Do not overwrite an existing wellness value with a different value without
  explicit confirmation. The CLI enforces this unless `--force` is supplied.

## Activity Metadata And Subjective Fields

- Use `rename <activity-id> "<new name>"` for renames.
- Use `subjective <activity-id> --feel <value> --rpe <value>` for subjective
  fields. Write `icu_rpe`; Intervals.icu derives `session_rpe` and rejects
  direct `session_rpe` writes. Fetch the activity afterward and verify
  `feel`/`icu_rpe`.

## Upload, Delete, And Repair

- Delete only activities the user explicitly requested or activities selected
  by a confirmed narrow duplicate rule. Use
  `delete-activity <activity-id> --confirm <activity-id>`.
- Verify deletion with both a date-bounded activity list and, when relevant, a
  direct lookup. A direct lookup can briefly return an id absent from lists.
- Upload FIT, FIT.GZ, GPX, TCX, and similar files with `upload-activity <file>`.
  Intervals.icu can deduplicate uploads or reuse an id after delete/reupload;
  treat the response id as canonical and verify it plus the date-bounded list.
- A Strava-backed stub can contain `_note`/`note` saying the activity is not
  available through the API. Repair it only when a local export exists.
- Keep original and generated files distinct: `file <id> --kind original` is
  the provenance artifact; `--kind fit` is an Intervals-generated export that
  can omit device metadata and differ in summary values.

## Interval Boundaries

- Read boundaries from `GET /api/v1/activity/<id>/intervals`.
- For updates, send a JSON array containing only intended `WORK` intervals with
  desired indices/times. Do not send the full GET object, an
  `{"icu_intervals": [...]}` wrapper, or `RECOVERY` intervals.
- Fetch first, dry-run/diff, require explicit confirmation, update, then fetch
  again. Intervals.icu regenerates recovery intervals and may change ids.
- Adjust boundaries one sample/second at a time. Preserve genuine work across
  short low-power patches; trim only tails that are clearly outside the effort.

## Wellness And Sickness

- Use `wellness-update <date> --soreness ... --fatigue ... --motivation ...`
  only for confirmed values.
- Record sickness as a calendar event with `category=SICK`, not a wellness
  comment. `sick-set` accepts an inclusive user end date but stores an exclusive
  end boundary. Verify the resulting event.

## Authentication

- Use `INTERVALS_ICU_API_KEY` from the repo-local `.env`; never print or
  hard-code API keys, bearer tokens, or cookies.
- Use `INTERVALS_ICU_COOKIE` only for explicitly requested original-file
  recovery when normal API access is insufficient.
