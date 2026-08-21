---
name: xert
description: Use when working with Xert live data, Training Load, Recovery Load, Form or freshness, Training Status, Fitness Signature development (TP, HIE, PP), required XSS to build fitness, offline strain calculations, MPA and XSS semantics, activity or workout fields, workout rows, calendar notes, or Xert writes.
---

# Xert

Use this skill for Xert access, field interpretation, API quirks, and safe
writes. The plugin is stateless and returns normalized data to callers.

## Network Execution

Use MCP for the live operations and model calculations listed below. Offline
help and local artifact inspection do not require network access.

## MCP Read Access

Prefer the Xert MCP tools when they are available:

- `list_activities` returns compact identity summaries for an inclusive
  local-date range with only `path`, `name`, and `start_local` by default. Use
  `includeFields` to add selected details such as duration, distance, or source. Requesting
  `xss`, signature, Difficulty, focus, specificity, freshness, or XEP fields
  performs the heavier per-activity detail read; ordinary discovery does not.
- `list_activities`, `list_workouts`, `list_notes`,
  `list_recommended_workouts`, and `get_training_forecast` accept closed
  `filters` (`field`, `op`, `value`), ordered `sort` keys, and a post-filter
  `limit`. Filters use AND; operators are `eq`, `ne`, `gt`, `gte`, `lt`,
  `lte`, `in`, `not_in`, `contains`, and `exists`. Nested normalized fields
  such as `xss.low` use documented dotted names.
- `get_activity` always returns a compact activity summary. Set
  `save_full=true` to save the complete activity document to a private
  temporary JSON file. Set `save_session=true` only when Xert-specific
  second-by-second data are required; this performs the heavier session read
  and returns a separate private temporary JSON path.
- `list_workouts` lists or filters compact workout identity summaries containing
  only `path` and `name` by default; request duration and other details with
  `includeFields`. Its
  `name_keywords` value requires every supplied word to occur,
  case-insensitively. Use `includeFields` to add selected load, work-power,
  rating, or Difficulty fields to each row.
- `get_workout` uses `view=resolved` for the workout calculated with the current
  Fitness Signature and `view=editable` for authoritative editable workout
  rows, including repeats, slopes, and rest-in-between fields.
- `list_planner_events` returns Xert's mixed planned-workout and
  recorded-activity event stream for an inclusive local-date range.
- `create_planner_event` creates one source-native Planner event and reads it
  back. `update_planner_event` patches selected fields while preserving omitted
  fields and verifies the saved event. `delete_planner_event` reads the target,
  permanently deletes it, and verifies that it is absent. Use these write tools
  only when the user explicitly requests the corresponding write.
- `list_notes` lists non-empty calendar-note text in an inclusive local-date
  range. `get_note` reads one date and distinguishes an absent note from text.
- `set_note` sets the complete calendar-note text for one local date and reads
  it back. It overwrites existing text; an empty string clears the note. Use it
  only when the user explicitly asks for that write. It does not update weight,
  freshness, program, forecast, or training-plan fields.
- `get_training_state` returns current Xert state. Use `view=summary` for the
  normalized Fitness Signature, Training Load, Recovery Load, form, recovery
  hours, training status, and target XSS. Use `view=full` only when both source
  payloads or model parameters are required. It does not project a future state,
  fetch planned-time advice, or add activity-specific readiness context.
- `get_training_advice` returns Xert advice. Omit `at` for current advice from
  `/my-fitness`; supply an ISO date-time for planned-time advice from
  `/recommended-training`, resolved immediately before that planned start.
  Use `view=summary` normally and `view=full` only for the selected advice
  payload. Neither view returns recommended workouts.
  This tool does not add activity load or cross-source readiness.
- `list_recommended_workouts` returns XATA's ranked workout candidates. Omit
  `at` for recommendations now or supply the same planned-time ISO date-time
  used for advice. `limit` defaults to 10 and accepts 1 through 100. Output is
  restricted to `exerciseType == "Workout"` before the ranked limit is applied.
- `get_training_forecast` returns Xert forecast days in an inclusive local-date
  range. Use `view=summary` normally and `view=full` when source day fields are
  needed. It reads the forecast endpoint, not the mixed activity/Planner feed.
- `create_workout` saves a new Xert workout from complete, structured workout
  rows. Each row uses duration values in seconds, and repeat-row
  `rib_duration_seconds` is applied after every repetition, including the
  final one. Use it only when creation is explicitly requested; inspect its
  verified metadata and `timeline_summary` after the write.
- `delete_workout` permanently deletes the specified workout path. Use it only
  when deletion is explicitly requested. It reads target metadata first and
  verifies afterward that the path is absent from the workout library.
- `update_workout` patches `name` and/or `description`. Its optional `rows`
  array contains `update`, `insert`, and `remove` operations on workout rows;
  it never replaces the complete row array. Read `get_workout(view=editable)`
  immediately first. Every position refers to that original structure, all
  operations are validated before one atomic save, and fresh readback verifies
  the complete result.
- `calculate_workout_capacity` calculates independent Low, High, and Peak XSS
  capacity at `as_of` while requiring recovery to Xert's fresh boundary at
  `fresh_at`. Both timestamps are mandatory.
- `calculate_strain` performs the local Xert strain calculation for an explicit
  Fitness Signature and ordered power segments; it does not call Xert.
- `solve_segment_duration` changes exactly one selected segment duration to
  meet one Low, High, Peak, or total XSS target while preserving the rest.
- `project_load_model` projects Training Load, Recovery Load, Form, readiness,
  and marginal signature response to an explicit target time.
- `calculate_workout` sends a complete, unsaved workout structure to
  Xert Calculate. Signature overrides must supply TP, HIE, and PP together.

## Choose The Narrowest Command

- Use MCP `list_activities` and `get_activity` for activity discovery and
  details. Request `includeFields=["xss"]` for compact XSS history rather than
  looping over individual details.
- When a local strain calculation needs the current Fitness Signature, use MCP
  `get_training_state`, then pass its normalized TP, HIE, and PP to MCP
  `calculate_strain`. Do not call live `calculate_workout` solely to obtain a
  signature.
- Compose readiness in the repo-level training-analysis workflow from the
  narrow Xert MCP source calls. Do not add a source-plugin readiness score.
- Use MCP `list_planner_events` for the mixed Planner event stream. Use the
  corresponding create, update, or delete tool only for an explicitly requested
  Planner write and inspect its verified result.
- Use MCP `solve_segment_duration` after the plan role and complete workout format have
  been resolved. Mark exactly one sub-TP segment as adjustable and supply the
  applicable target low XSS. The solver preserves every fixed quality,
  warm-up, recovery, and cool-down segment and changes only the endurance
  duration. Pass its normalized result to the recommendation helper; do not
  convert XSS to minutes with a mixed-activity historical rate.
  Pass an explicit segment array and identify the adjustable segment with its
  zero-based `adjustable_segment_index`.
- Use MCP `calculate_workout_capacity` when asking how much Low/High/Peak XSS can be added at
  an explicit time while still arriving fresh at another explicit time. Require
  both `--as-of` and `--fresh-at`; there is deliberately no duration alternative
  or default horizon. The command projects the fresh live state to `--as-of`
  assuming no intervening training. The timestamps may be equal. Naive values
  use the machine timezone, while `Z` and explicit offsets are accepted.
- Use MCP `project_load_model` to project low/high/peak Training Load, capped Recovery
  Load, Form, star category, system readiness, and marginal TP/HIE/PP response.
  Require `--target-at`; values without an offset use the machine timezone,
  while `Z` and explicit offsets are accepted. There is deliberately no
  duration alternative or default horizon.
  Set `--workout-after-hours` explicitly when the XSS impulse occurs later than
  the current Xert state; it must fall within the resolved horizon.
  Add `--validate-history` to verify against pre-activity Fitness Measures
  states. The `--build-*` results are system-equivalent XSS requirements, not
  workout prescriptions. Add `--summary` for compact source/workout/target
  timing, current and no-training signatures, planned-dose projections, and
  required XSS; omit it when the complete model state is needed.
  For an absolute TP target over many workouts, use `--target-tp` with both
  `--distribution linear` and `--frequency daily`. The default first dose is
  the Low XSS that maintains current Low TL; override it with
  `--start-low-xss`. Treat the result as a mathematical ramp, not a training
  prescription, and resync it after completed activities.
- Read [references/training-load-model.md](references/training-load-model.md)
  whenever the task asks how training changes Training Load, Recovery Load,
  Form/freshness, TP, HIE, or PP; compares the lasting effect of different XSS
  splits; asks what is required to build a Fitness Signature component; or
  needs a multi-workout projection. Use its mental model for explanation and
  MCP `project_load_model` or `simulate_calendar_sequence` for numbers.
- Use MCP `list_recommended_workouts` when candidate workouts are needed.
- Use MCP `list_workouts(name_keywords=...)` to filter the freshly fetched
  workout library. All supplied words must occur in the name, in any order.
- Use MCP `get_workout(view=editable)` for editable workout structure,
  especially for repeat or slope rows.
- In a repeat row, Xert's `Rest in between` (`rib_duration`/`rib_power`) is
  appended after every work interval, including the final repetition. For
  example, `interval_count=4` with a five-minute RIB produces four work
  intervals and four five-minute recovery intervals. Do not add a separate
  recovery row after the repeat block unless an additional recovery is
  intentionally required.
- For a structural workout change, read the editable workout rows and pass an
  ordered operation array to `update_workout`. Each operation uses `method` =
  `update`, `insert`, or `remove`, with row fields directly in the operation.
  Row numbers always refer to the original freshly read structure. Multiple
  inserts at one position preserve operation-array order; conflicting changes
  to the same original row are rejected.
- Workout create/copy, update/replace/row operations, and calculate results
  include `timeline_summary`: a chronological expansion with numeric
  `start`/`end`/`duration` values in seconds and a compact text `power` value.
  Inspect it to verify repetitions, final RIB recovery, and transitions.
- For empirical Xert Calculate analysis, call MCP `calculate_workout` with
  `include_series=true` and save the returned JSON to a private temporary file.
  The result includes the
  Fitness Signature used by Xert and second-by-second `power`, `mpa`,
  `proximity`, `xssr`, cumulative `xss`, and `xds` fields, plus the raw
  calculation statistics containing Xert's system work and strain totals.
  Keep the verbose series out of terminal and chat output.
- For controlled cross-signature probes, pass all three of `signature_tp`,
  `signature_hie`, and `signature_pp`. They override the workout calculation form for
  the unsaved calculation only and do not change the user's Xert profile.
- Read [references/field-semantics.md](references/field-semantics.md), section
  `Xert Calculate Model`, when interpreting formulas, the HIE/TP
  floor, completed-activity MPA, or the evidence status of the model.
- Read [references/strain-model.md](references/strain-model.md) when explaining how
  XSS works, relating low/high/peak XSS to workout structure, comparing XSS
  profiles, or calculating a known workout without network access. Prefer the
  MCP `calculate_strain` whenever the segments can be resolved. If only
  the current signature is missing, obtain it with MCP `get_training_state` and continue
  locally; a missing signature alone is not a reason to use live Calculate. Its
  output is the analysis-ready local model result.

Credentials come from `username` and `password` in the user-owned
`~/.xert_mcp.json`. Explicit `XERT_USERNAME` and `XERT_PASSWORD` environment
variables override the config file for both the CLI and MCP transports.

## Load Reasoning Defaults

When no numerical projection is requested, reason directionally with three
parallel systems: Low XSS builds Low TL and the TP-linked component; High XSS
builds High TL and the HIE-linked component; Peak XSS builds Peak TL and the
PP-linked component. A workout raises both TL and RL. RL normally decays faster,
so recovery improves Form while retaining more TL. Signature response depends
on net change in the matching TL at the observation time, not raw XSS alone.

Do not equate training status with freshness: total TL controls stars/category,
while per-system RL and Recovery Demand control readiness. Describe exact
TP/HIE/PP outputs as marginal Training-Load-matched projections and keep
breakthrough, near-breakthrough, and private decay adjustments outside the
claimed model boundary.

## Planned-Time Advice

Use MCP `get_training_advice` without `at` for the faster current
`/my-fitness` advice. Supply `at` for planned-time `/recommended-training`
advice resolved immediately before that start. The orchestration layer must
compose this advice with `get_training_state` and any activity context needed by
the repo-level readiness packet; there is no Xert readiness CLI adapter.

## Session Data

Use session data only for Xert-specific time-series fields that are unavailable
from a better source. Always write it to an explicit temporary file and never
print it to chat or terminal output:

Use MCP `get_activity(save_session=true)`. It returns the normal compact summary
and persists the complete session to a private temporary JSON file.

## Semantics And Writes

- Read [references/sources.md](references/sources.md) before making evidence or
  validation claims about Xert, and use its claim boundaries when official
  product documentation and local empirical findings have different scopes.
- Read [references/field-semantics.md](references/field-semantics.md) before
  interpreting recovery, XSS, activity, forecast, workout, or calendar fields.
- Read [references/write-safety.md](references/write-safety.md) before any
  calendar-note, workout update, copy, calculation, or deletion operation.

## Boundaries

This plugin owns Xert authentication, live access, field interpretation, API
quirks, and write safety. The caller owns persistence, cross-source analysis,
plotting, reports, and user-specific training decisions or workout templates.
