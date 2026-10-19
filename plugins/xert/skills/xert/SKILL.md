---
name: xert
description: Use when working with Xert live data, Training Load, Recovery Load, Form or freshness, Training Status, Fitness Signature development (TP, HIE, PP), required XSS to build fitness, offline strain calculations, MPA and XSS semantics, activity or workout fields, workout rows, calendar notes, or Xert writes.
---

# Xert

Use this skill for Xert access, field interpretation, model calculations, and
safe writes. The plugin returns normalized data; the caller owns persistence,
cross-source analysis and final training decisions.

## Choose A Workflow

Use MCP for live access. Read the relevant sections of
[field-semantics.md](references/field-semantics.md) before interpreting fields.
Load only the references needed for the question.

| Task | Start with | Read when needed |
| --- | --- | --- |
| Completed workout or activity comparison | `list_activity_summaries`; `get_activity` for details or session series | [Activity fields](references/field-semantics.md#activity-and-workout-fields); [tool details](references/tool-workflows.md#mcp-read-access) |
| Readiness or today's/planned session dose | `get_training_state(view="summary")` and `get_training_advice(view="summary", at=...)` | [Recovery and advice](references/field-semantics.md#recovery-and-advice) |
| Known workout XSS or adjustable endurance duration | `calculate_strain` or `solve_segment_duration` | [Strain model](references/strain-model.md); [calculation workflow](references/tool-workflows.md#choose-the-narrowest-command) |
| Capacity, load development or signature projection | `calculate_workout_capacity` or `project_load_model` | [Load model](references/training-load-model.md); [tool arguments](references/tool-workflows.md#choose-the-narrowest-command) |
| Workout lookup or authorized edit | `list_workouts`, then `get_workout` | [Tool details](references/tool-workflows.md); [write safety](references/write-safety.md) |
| Calendar, Planner events or forecast | `list_notes`, `list_planner_events` or `get_training_forecast` | [Calendar semantics](references/field-semantics.md#forecast-and-calendar); [tool details](references/tool-workflows.md) |
| Empirical Calculate probe or model validation | Local strain model first; `calculate_workout` for a required live comparison | [Calculate boundaries](references/field-semantics.md#xert-calculate-model); [probe workflow](references/tool-workflows.md#choose-the-narrowest-command); [sources](references/sources.md) |

## Decision Rules

- Use `remaining_xss` once: it already accounts for completed load. Do not
  subtract completed XSS again. Keep it separate from `target_xss`, deficit,
  and workout capacity.
- Capacity is a model-specific ceiling for reaching the requested freshness
  boundary, not a target dose or proof that the athlete can tolerate it.
  Require explicit `as_of` and `fresh_at` timestamps.
- Xert status and recovery hours describe modeled cycling-load state. Positive
  Low recovery hours are context, not an automatic training ban. Combine them
  with session purpose, recent training, physiological and subjective signals.
- Low, High and Peak XSS are additive contributions, not exclusive intensity
  zones. Do not infer workout intensity from their percentage shares.
- Re-fetch live state after Xert processes an activity or changes model/profile
  inputs. Completed load is already in that state; do not apply it again.
- TP/HIE/PP projections are marginal model estimates, not promised adaptation.
  Read [sources.md](references/sources.md) before making validation claims.

## Common Read And Calculation Path

Use `list_activity_summaries` for completed-activity discovery, including Garmin
syncs. Xert's OAuth activity endpoints exclude automatically synced Garmin
activities. Both `list_activities` and `list_activity_summaries` use the
authenticated dashboard and include those rides. `get_activity` uses the standard
activity page and its authenticated MPA chart endpoint, including session series.
Callers do not need to choose transport based on Garmin origin. Saved documents
identify their web source and preserve chart field names in `session_data`.
See [Xert API activity access](https://www.xertonline.com/API.html)
for the upstream OAuth restriction.

Use compact summaries by default and `includeFields` for the extra list fields
needed. Check `period_complete` on activity-summary results before claiming
complete period coverage. The list and filter contracts are in
[tool-workflows.md](references/tool-workflows.md#mcp-read-access).

For planned-time advice, pass an ISO timestamp with an explicit UTC offset in
`at`; omit it for current advice. Fetch workout candidates separately with
`list_recommended_workouts`, using the same `at`. Advice is resolved immediately
before the planned start and must be composed with current state and activity
context by the caller. In training-ai, use the training-analysis workflow;
there is no Xert readiness CLI adapter.

For a known workout, use `calculate_strain` with explicit segments and Fitness
Signature. If only the signature is missing, fetch `get_training_state` rather
than calling live Calculate. For endurance-dose adjustment, resolve the plan
role and full workout first, then use `solve_segment_duration` on one sub-TP
segment while preserving fixed work, warm-up, recovery and cool-down. Do not
convert XSS to minutes using a mixed-activity historical rate.

`project_load_model` requires absolute `workout_at` and `target_at` timestamps
for a single XSS impulse. It computes the delay from its fetched source state;
do not supply a wall-clock offset. One call returns the planned dose at the
top level and `no_training_projection` from the same fetched inputs. Use these
for comparisons instead of making separate zero-dose and planned-dose calls.
It fetches its own model parameters; a prior state call is unnecessary.
`get_training_state(view="summary")` provides normalized state, not raw model
parameters; use `view="full"` only when inspecting those parameters.
Multi-workout simulation, daily ramps and history validation belong to local
analysis code described in the [load reference](references/training-load-model.md);
`simulate_calendar_sequence` is not an MCP tool. Do not pass CLI flags to MCP.

Use `get_activity(save_full=true)` for the complete activity document and
`save_session=true` only for needed Xert-specific time series. These return
private temporary file paths. Keep verbose session data out of chat and
terminal output.

## Writes And Access

Read [write-safety.md](references/write-safety.md) before calendar-note,
Planner or workout writes, or live workout calculations. Perform writes only
when explicitly requested. Read editable workout rows immediately before a
structural edit and inspect the verified result and `timeline_summary`.
Xert repeat-row recovery follows every repetition, including the final one.

Live operations require network access; local strain calculations and artifact
inspection do not. Credentials come from `username` and `password` in the
user-owned `~/.xert_mcp.json`; explicit `XERT_USERNAME` and `XERT_PASSWORD`
environment variables override that file for CLI and MCP transports.
