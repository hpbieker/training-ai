---
name: intervals-icu
description: Use for Intervals.icu live activity lookup, date-bounded activity lists, streams, intervals, wellness and sickness events, subjective feel/RPE, ignore flags, original-file recovery, uploads, metadata updates, or other Intervals.icu write-safety workflows.
---

# Intervals.icu

Use this skill for Intervals.icu-specific source access, source semantics, and write safety. The plugin can fetch live data and perform cautious remote updates, but it does not own repo-level training analysis, plotting, readiness composition, or long-term storage.

## Task Routing

Choose the narrowest workflow that answers the request:

- Date-bounded tools use `start_date` and `end_date` for inclusive local
  calendar dates in `YYYY-MM-DD` format. They do not accept date-times.

- Today's or a bounded period's activities: call MCP `list_activities` first. Verify local date and activity identity before analysis.
- Latest activity when no date is implied: use MCP `list_activities` over an explicit lookback range and select the newest result.
- Text or tag search: call MCP `search_activities`; use `list_activities`
  instead when complete date-range coverage is required.
- Metadata or interval orientation only: call MCP `get_activity` for its compact
  summary. Set `save_full=true` when the complete source activity is needed by
  the repo persistence or analysis workflow.
- Metadata or interval orientation for several known activity ids: call MCP
  `get_activities` for compact summaries in one source request. Set
  `save_full=true` to save the complete source activities in one private batch
  envelope.
- Per-activity best power for explicit durations: call MCP
  `list_activity_power_curves`. Use `secs=[1]` for best one-second average
  power; do not describe it as a raw max-power metadata field.
- Per-activity best heart rate or pace: call `list_activity_hr_curves` with
  explicit durations or `list_activity_pace_curves` with explicit distances.
- Activities containing intervals within duration, intensity, and repetition
  bounds: call `search_activity_intervals`.
- Intervals.icu thresholds, zones, and sport-specific load configuration: call
  `list_sport_settings`.
- Readiness context: call MCP `list_wellness` and `list_events`; let the caller
  resolve source priority and compose readiness.
- Calendar events: call MCP `list_events` first, then use `create_event`,
  `update_event`, or `delete_event` on the exact event. Record sickness with
  `category=SICK`, never as a wellness comment.

## MCP Tools

- `list_athletes` lists athletes accessible to the authenticated account. Use it
  only when another athlete must be selected. `list_activities`, `get_activity`,
  `get_activities`, `get_activity_streams`, `list_activity_hr_curves`,
  `list_activity_pace_curves`, `search_activity_intervals`, and
  `list_sport_settings`, `list_wellness`, `list_events`,
  `list_activity_power_curves`, `get_activity_file`, and `search_activities`
  accept an optional `athlete`; omission, `me`, and `0` all mean the
  authenticated athlete and remain implicit in the response. An explicitly
  selected non-default athlete is validated against `list_athletes` and
  included in the response.
- `list_activities` lists every activity in an inclusive local-date range as
  compact identity summaries containing only `id`, `name`, and
  `start_date_local` by default. Use `includeFields` to add only selected
  allowed detail fields to each row; `search_activities` performs source text or tag
  search with the same compact rows and `includeFields` choices.
- `list_activities`, `search_activities`, `list_wellness`, and `list_events`
  accept closed `filters` (`field`, `op`, `value`), ordered `sort` keys, and a
  post-filter `limit` where applicable. Filters use AND; operators are `eq`,
  `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`, and `exists`.
  Inspect `source_count` and `matched_count`; searches are `source_limited`.
- `get_activity` returns a compact identity summary and accepts `includeFields`
  for selected inline detail fields. With
  `save_full=true`, it also saves the complete source activity in the standard
  activity envelope to a private temporary JSON file;
- `get_activities` follows the same compact-summary/full-file split for a
  non-empty list of unique activity ids and uses Intervals.icu's batch endpoint.
  Its `includeFields` selection affects only inline summaries; saved full files
  remain complete. Both inline summaries and saved full activities are ordered
  to match the requested `activity_ids`, independent of source response order;
  `get_activity_streams` saves selected streams to a private temporary file;
  `get_activity_file` saves the original upload or reconstructed FIT file to a
  private temporary file.
- `list_activity_power_curves` returns Intervals.icu's per-activity power-curve
  rows for explicit durations in an inclusive local-date range. Its `secs` and
  each curve's aligned `watts` array preserve source order. It supports the
  optional athlete selection described above and resolves the authenticated
  athlete internally when athlete is omitted.
- `list_activity_hr_curves` and `list_activity_pace_curves` follow the same
  date-bounded per-activity pattern for explicit durations and distances and
  support the optional athlete selection described above.
- `search_activity_intervals` passes explicit interval bounds to Intervals.icu's
  source search endpoint and returns compact activity summaries.
- `list_sport_settings` returns the selected athlete's source sport settings
  and resolves the authenticated athlete id internally when athlete is omitted.
- `update_activity` patches supported metadata, tags, subtype, color, fueling,
  strength load, and whole-activity ignore flags, and requires
  `confirm_overwrite=true` before replacing an existing non-empty value;
  `delete_activity` requires `confirm` to equal the exact activity id;
  `delete_activities` requires `confirm_activity_ids` to exactly match the
  ordered `activity_ids`, reads them once through the batch endpoint, deletes
  them individually, and verifies collective absence through the batch endpoint;
  `upload_activity` uploads one local activity file. Every completed write is
  verified with fresh source data.
- `list_wellness` reads the selected athlete's wellness rows; `update_wellness`
  patches the authenticated athlete's supported fields and requires
  `confirm_overwrite=true` for conflicting values.
- `list_events` reads the selected athlete's calendar events; `create_event`
  creates an all-day event for the authenticated athlete;
  `update_event` replaces its supported all-day state; `delete_event` requires
  `confirm` to equal the exact event id. Event writes use inclusive user dates,
  convert the stored end boundary to exclusive, and verify the result.

For a completed-activity analysis through MCP, use exactly this sequence:

1. `list_activities` with the requested inclusive local date.
2. Select and verify the exact activity id.
3. Call `get_activity(save_full=true)` and `get_activity_streams` for that id.
   These two calls may run concurrently after identity is resolved. Pass the
   returned `full_activity_file` and `streams_file` directly to the repo
   persistence helper.

When an activity has an `id` but no URL field, build the web link
as `https://intervals.icu/activities/<activity-id>`, for example
`https://intervals.icu/activities/i158694373`.

## Freshness And Data Handoff

- Fetch live data for same-day analysis, readiness, or post-workout evaluation unless the caller explicitly requests offline/cache-only work.
- After finding a newly completed activity, fetch that exact id and its streams
  through MCP, then let the caller persist the package before repo analysis.
- Keep source payloads and stream artifacts as inputs. Pass normalized or packaged output to the repo helper; do not make repo helpers call Intervals.icu directly.
- If live access fails, report which source call failed and whether the available local package predates the activity's latest sync. Do not silently present cached data as current.
- Wellness fields may be copied from connected systems. Preserve their source
  caveat and let the caller resolve source priority.

## Source Semantics

Read [references/field-semantics.md](references/field-semantics.md) before
interpreting activity load, stream fields, ignore flags, intervals, wellness,
or subjective fields.

## Remote Writes

Before renaming, uploading, deleting, changing wellness or sickness, or saving
subjective fields, read
[references/write-safety.md](references/write-safety.md). Mutate only what the
user authorized and verify every write with a fresh readback.

## Scope And Responsibilities

This plugin owns Intervals.icu transport, field interpretation, source quirks,
fetch helpers, and safe remote writes. The caller owns local persistence,
activity/work-block analysis, source composition, plotting, reports, and final
training decisions.
