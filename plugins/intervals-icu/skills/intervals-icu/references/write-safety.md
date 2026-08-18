# Intervals.icu Write Safety

Read this file before any Intervals.icu mutation.

## General

- Update only fields the user explicitly provided or confirmed.
- Use the plugin MCP, then fetch the affected activity, wellness day, or
  date-bounded list and verify the requested state.
- Do not overwrite an existing wellness value with a different value without
  explicit confirmation. Use `confirm_overwrite=true` only after that
  confirmation.

## Activity Metadata, Ignore Flags, And Subjective Fields

- Use MCP `update_activity` for names, descriptions, tags, subtype, color,
  whole-activity ignore flags, and subjective fields. Its closed patch supports
  `name`, `description`, `tags`, `sub_type`, `icu_color`, `carbs_ingested`,
  `kg_lifted`, `icu_ignore_time`, `icu_ignore_hr`, `icu_ignore_power`,
  `ignore_velocity`, `ignore_pace`, `feel`, and `icu_rpe`; only supplied fields
  change. Write `icu_rpe`; Intervals.icu
  derives `session_rpe` and rejects direct `session_rpe` writes. Require
  `confirm_overwrite=true` for an existing different value and verify by fresh
  readback.

## Upload, Delete, And Repair

- Delete only activities the user explicitly requested or activities selected
  by a confirmed narrow duplicate rule. Use MCP `delete_activity` with
  `confirm` exactly matching `activity_id`, or MCP `delete_activities` with
  `confirm_activity_ids` exactly matching the ordered `activity_ids`.
- Verify deletion with both a date-bounded activity list and, when relevant, a
  direct lookup. A direct lookup can briefly return an id absent from lists.
- Upload FIT, FIT.GZ, GPX, TCX, and similar files with MCP `upload_activity`.
  Intervals.icu can deduplicate uploads or reuse an id after delete/reupload;
  treat the response id as canonical and verify it plus the date-bounded list.
- A Strava-backed stub can contain `_note`/`note` saying the activity is not
  available through the API. Repair it only when a local export exists.
- Keep original and generated files distinct: MCP `get_activity_file` with
  `kind=original` is the provenance artifact; `kind=fit` is an Intervals-generated export that
  can omit device metadata and differ in summary values.

## Wellness And Sickness

- Use MCP `update_wellness` with a closed `updates` object for `soreness`,
  `fatigue`, `motivation`, or explicit user-provided `comments`. Only supplied
  fields change. Read first, require `confirm_overwrite=true` for an existing
  different value, and verify with a fresh readback.
- Record sickness through MCP calendar-event tools with `category=SICK`, not a
  wellness comment. Call `list_events` first and use the exact event id for an
  update or deletion. `create_event` and `update_event` accept an inclusive user
  end date but store an exclusive end boundary. Verify every result; deletion
  additionally requires `confirm` to match the event id.
