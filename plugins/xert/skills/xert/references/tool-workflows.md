# Xert Tool Workflows

Read only the tool entries relevant to the selected task. MCP argument names
below follow the plugin schema; local model functions are not MCP tools.

## MCP Read Access

Prefer the Xert MCP tools when they are available:

- `list_activity_summaries` returns activity summaries within an inclusive
  local-date range, newest first. Use `limit` for the N newest activities;
  omit it for the full period.
  Use `includeFields` to select signature, XSS, difficulty, XEP, focus,
  specificity, power, heart rate and cadence.
  `count` is the number of returned activities. Check `period_complete`
  to determine whether the result covers the full period.
  Signature fields `ftp`, `pp` and `ltp` use watts; `atc` uses joules.
- `list_activities` returns compact identity summaries for an inclusive
  local-date range with only `path`, `name`, and `start_local` by default. Use
  `includeFields` to add duration, distance, source, or map URL from the same
  activity-list response. Use `get_activity` when XSS, signature, Difficulty,
  focus, specificity, freshness, or XEP is required.
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
  hours, exact `fresh_at.low` and `fresh_at.all` timestamps, training status,
  and target XSS. Use `view=full` only when both source
  payloads or model parameters are required. Summary does not expose the raw
  model parameters. `project_load_model` fetches those itself, so a separate
  state read is not required merely to run a projection. It does not project a future state,
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
  details. Keep list discovery to fields supplied by the activity-list response;
  use `get_activity` for load, signature, and other calculated detail fields.
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
- Use MCP `calculate_workout_capacity(as_of=..., fresh_at=...)` when asking
  how much Low/High/Peak XSS can be added at one time while arriving fresh at
  another. Both timestamps are required; there is no default horizon. It
  projects the fresh live snapshot to `as_of` assuming no intervening training.
  The timestamps may be equal. Prefer explicit UTC offsets or `Z`; naive
  timestamps use the machine timezone.
- Use MCP `project_load_model(target_at=..., workout_at=...,
  low_xss=..., high_xss=..., peak_xss=...)` for a single planned XSS impulse.
  Both timestamps are required. Pass the absolute workout start as `workout_at`;
  the service computes elapsed time from the Xert state it fetches internally.
  Require source state <= workout start <= target, using explicit UTC offsets
  or `Z`. Do not calculate a delay from wall-clock now. The result preserves
  `source_state_as_of`, `workout_at`, and `target_at` for verification.
  Compare the top-level planned-dose result with `no_training_projection` from
  that same call. Both use the same fetched inputs; separate calls may observe
  different Xert states.
  For required system-equivalent XSS, supply `build_tp` (watts), `build_hie`
  (kJ), and/or `build_pp` (watts). These are desired marginal gains, not
  absolute signature targets or workout prescriptions.
  History validation, daily ramps, and multi-workout simulations are not
  exposed by this MCP tool; use the local-model workflow in the reference
  below when the module is available. Do not pass CLI flags as MCP arguments.
- Read [references/training-load-model.md](training-load-model.md)
  whenever the task asks how training changes Training Load, Recovery Load,
  Form/freshness, TP, HIE, or PP; compares the lasting effect of different XSS
  splits; asks what is required to build a Fitness Signature component; or
  needs a multi-workout projection. Use its mental model for explanation and
  MCP `project_load_model` for single-impulse numbers. The reference describes
  local module functions for multi-workout simulations; they are not MCP tools.
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
- Read [references/field-semantics.md](field-semantics.md), section
  `Xert Calculate Model`, when interpreting formulas, the HIE/TP
  floor, completed-activity MPA, or the evidence status of the model.
- Read [references/strain-model.md](strain-model.md) when explaining how
  XSS works, relating low/high/peak XSS to workout structure, comparing XSS
  profiles, or calculating a known workout without network access. Prefer the
  MCP `calculate_strain` whenever the segments can be resolved. If only
  the current signature is missing, obtain it with MCP `get_training_state` and continue
  locally; a missing signature alone is not a reason to use live Calculate. Its
  output is the analysis-ready local model result.

