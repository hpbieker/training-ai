---
name: intervals-icu
description: Use for Intervals.icu live activity lookup, date-bounded activity lists, streams, intervals, wellness and sickness events, subjective feel/RPE, ignore flags, original-file recovery, uploads, metadata updates, or other Intervals.icu write-safety workflows.
---

# Intervals.icu

Use this skill for Intervals.icu-specific source access, source semantics, and write safety. The plugin can fetch live data and perform cautious remote updates, but it does not own repo-level training analysis, plotting, readiness composition, or long-term storage.

## Task Routing

Choose the narrowest workflow that answers the request:

- Today's or a bounded period's activities: call MCP `list_activities` first. Verify local date and activity identity before analysis.
- Latest activity when no date is implied: use MCP `list_activities` over an explicit lookback range and select the newest result.
- Text or tag search: call MCP `search_activities`; use `list_activities`
  instead when complete date-range coverage is required.
- Metadata or interval orientation only: call MCP `get_activity`; omit intervals only when they are not needed.
- Readiness context: call MCP `list_wellness` and `list_events`; let the caller
  resolve source priority and compose readiness.
- Calendar events: call MCP `list_events` first, then use `create_event`,
  `update_event`, or `delete_event` on the exact event. Record sickness with
  `category=SICK`, never as a wellness comment.

For a completed-activity analysis through MCP, use exactly this sequence:

1. `list_activities` with the requested inclusive local date.
2. Select and verify the exact activity id.
3. Call `get_activity` and `get_activity_streams` for that id. These two calls
   may run concurrently after identity is resolved.

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
