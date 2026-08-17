---
name: xert
description: Use when working with Xert live data, Training Load, Recovery Load, Form or freshness, Training Status, Fitness Signature development (TP, HIE, PP), required XSS to build fitness, offline strain calculations, MPA and XSS semantics, activity or workout fields, Workout Designer rows, calendar notes, or Xert writes.
---

# Xert

Use this skill for Xert access, field interpretation, API quirks, and safe
writes. The plugin is stateless and returns normalized data to callers.

## Network Execution

Use MCP for the live operations listed below. The remaining model and Planner
CLI commands require external network access; run them with escalated network
permission on the first attempt. Offline help and local artifact inspection do
not require escalation.

## MCP Read Access

Prefer the Xert MCP tools when they are available:

- `list_activities` returns compact identity summaries for an inclusive
  local-date range. Use `includeFields` to add selected details. Requesting
  `xss`, signature, Difficulty, focus, specificity, freshness, or XEP fields
  performs the heavier per-activity detail read; ordinary discovery does not.
- `get_activity` always returns a compact activity summary. Set
  `save_full=true` to save the complete activity document to a private
  temporary JSON file. Set `save_session=true` only when Xert-specific
  second-by-second data are required; this performs the heavier session read
  and returns a separate private temporary JSON path.
- `list_workouts` lists or filters compact workout identity summaries. Its
  `name_keywords` value requires every supplied word to occur,
  case-insensitively. Use `includeFields` to add selected load, work-power,
  rating, or Difficulty fields to each row.
- `get_workout` uses `view=resolved` for the workout calculated with the current
  Fitness Signature and `view=editable` for authoritative Workout Designer
  rows, including repeats, slopes, and rest-in-between fields.
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
- `create_workout` saves a new Xert workout from complete, structured Designer
  rows. Each row uses duration values in seconds, and repeat-row
  `rib_duration_seconds` is applied after every repetition, including the
  final one. Use it only when creation is explicitly requested; inspect its
  verified metadata and `timeline_summary` after the write.
- `delete_workout` permanently deletes the specified workout path. Use it only
  when deletion is explicitly requested. It reads target metadata first and
  verifies afterward that the path is absent from the workout library.
- `update_workout` patches `name` and/or `description` and can atomically
  replace the complete Designer row set. For structural changes, first read
  `get_workout(view=editable)`, construct the complete desired rows, then pass
  all rows to `update_workout`; omitted metadata is preserved. Saved changes
  are read back and verified. There are no separate MCP row-edit tools.

The CLI exposes only model calculations, mixed Planner-event operations, the
readiness composition adapter, and unsaved Workout Designer Calculate, which
have not been added to MCP. It is not a fallback for MCP-covered operations.

## Choose The Narrowest Command

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-capacity --as-of <ISO-datetime> --fresh-at <ISO-datetime>
python3 -B plugins/xert/scripts/xert_cli.py readiness-input [--activity <path>]
python3 -B plugins/xert/scripts/xert_cli.py readiness-input --advice-source auto --advice-at <ISO-local-datetime>
python3 -B plugins/xert/scripts/xert_cli.py load-model --target-at <ISO-datetime> --workout-after-hours <H> --low-xss <XSS> --high-xss <XSS> --peak-xss <XSS>
python3 -B plugins/xert/scripts/xert_cli.py calendar-events <YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py calendar-event <path> --date <YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py workout-calculate --row-json '<designer-row-json>'
python3 -B plugins/xert/scripts/xert_strain_cli.py calculate --signature-tp <W> --signature-hie <J> --signature-pp <W> --segment <MM:SS@W>
python3 -B plugins/xert/scripts/xert_strain_cli.py solve-endurance --input <plan-structure.json>
python3 -B plugins/xert/scripts/xert_strain_cli.py solve-endurance --input <designer-rows.json> --adjustable-row <one-based-row> --target-low-xss <XSS> --signature-tp <W> --signature-hie <J> --signature-pp <W>
```

- Use MCP `list_activities` and `get_activity` for activity discovery and
  details. Request `includeFields=["xss"]` for compact XSS history rather than
  looping over individual details.
- When a local strain calculation needs the current Fitness Signature, use MCP
  `get_training_state`. Map TP, HIE, and PP from its normalized signature into
  `xert_strain_cli.py calculate`. Do not call live `workout-calculate` solely to
  obtain a signature.
- Use `readiness-input` for normalized recovery and training-advice context.
  Do not pass raw Xert payloads to readiness consumers.
- Use `solve-endurance` after the plan role and complete workout format have
  been resolved. Mark exactly one sub-TP segment as adjustable and supply the
  applicable target low XSS. The solver preserves every fixed quality,
  warm-up, recovery, and cool-down segment and changes only the endurance
  duration. Pass its normalized result to the recommendation helper; do not
  convert XSS to minutes with a mixed-activity historical rate.
  It also accepts the JSON array returned by `workout-rows`; select the
  adjustable Designer row with the one-based `--adjustable-row` option and pass
  the target and signature flags explicitly. Designer LTP power is derived as
  `TP - HIE(J) / 400` from that signature.
- Use `workout-capacity` when asking how much Low/High/Peak XSS can be added at
  an explicit time while still arriving fresh at another explicit time. Require
  both `--as-of` and `--fresh-at`; there is deliberately no duration alternative
  or default horizon. The command projects the fresh live state to `--as-of`
  assuming no intervening training. The timestamps may be equal. Naive values
  use the machine timezone, while `Z` and explicit offsets are accepted.
- Use `load-model` to project low/high/peak Training Load, capped Recovery
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
  `load-model`/`simulate_calendar_sequence` for numbers.
- Use MCP `list_recommended_workouts` when candidate workouts are needed.
- Use MCP `list_workouts(name_keywords=...)` to filter the freshly fetched
  workout library. All supplied words must occur in the name, in any order.
- Use MCP `get_workout(view=editable)` for Workout Designer structure,
  especially for repeat or slope rows.
- In a repeat row, Xert's `Rest in between` (`rib_duration`/`rib_power`) is
  appended after every work interval, including the final repetition. For
  example, `interval_count=4` with a five-minute RIB produces four work
  intervals and four five-minute recovery intervals. Do not add a separate
  recovery row after the repeat block unless an additional recovery is
  intentionally required.
- For a structural workout change, read the complete editable rows, change the
  desired row locally, and submit the complete final row array to MCP
  `update_workout`. It replaces all rows atomically and verifies fresh readback.
- Workout create/copy, update/replace/row operations, and calculate results
  include `timeline_summary`: a chronological expansion with numeric
  `start`/`end`/`duration` values in seconds and a compact text `power` value.
  Inspect it to verify repetitions, final RIB recovery, and transitions.
- For empirical Workout Designer analysis, pass
  `workout-calculate --series-output /tmp/<name>.json`. The file includes the
  Fitness Signature used by Xert and second-by-second `power`, `mpa`,
  `proximity`, `xssr`, cumulative `xss`, and `xds` fields, plus the raw
  calculation statistics containing Xert's system work and strain totals.
  Keep the verbose series out of terminal and chat output.
- For controlled cross-signature probes, pass all three of `--signature-tp`,
  `--signature-hie`, and `--signature-pp`. They override the Designer form for
  the unsaved calculation only and do not change the user's Xert profile.
- Analyze a saved Calculate series with
  `python3 -B plugins/xert/scripts/xert_calculate_analyze.py /tmp/<name>.json`.
  Its default output is a concise analysis summary. Add `--detailed` for
  equation residuals, empirical recovery residuals, and full validation
  diagnostics. Treat its summary-integration XSS and
  reconstructed-Difficulty residuals as open diagnostics, not as reasons to
  alter the validated per-sample MPA or XSSR equations.
- For MPA feasibility, read the analyzer's `feasibility.valid`, minimum positive
  reserve, first failure index/reserve, and `validity` fields together. Reject
  an ordinary workout design that reaches `P >= MPA` under the supplied
  signature. The analyzer can model Calculate's continued series, but that
  continuation is hypothetical and is not a detected breakthrough or a new
  Fitness Signature.
- Read [references/field-semantics.md](references/field-semantics.md), section
  `Workout Designer Calculate Model`, when interpreting formulas, the HIE/TP
  floor, completed-activity MPA, or the evidence status of the model.
- Read [references/strain-model.md](references/strain-model.md) when explaining how
  XSS works, relating low/high/peak XSS to workout structure, comparing XSS
  profiles, or calculating a known workout without network access. Prefer the
  offline `xert_strain_cli.py` whenever the segments can be resolved. If only
  the current signature is missing, obtain it with MCP `get_training_state` and continue
  locally; a missing signature alone is not a reason to use live Calculate. Its
  default output is the analysis-ready summary; add `--detailed` only when
  segment diagnostics or model limitations are needed.

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

For advice now, the default `readiness-input` source is the faster
`/my-fitness`. For a planned time, use `--advice-source auto --advice-at`; auto
switches to planned-time advice when needed. Force
`--advice-source recommended-training` only when the caller specifically needs
that source.

The payload keeps `recovery.recovery_hours` at `source_time_local` and adds
`recovery.recovery_hours_at_advice_time` when a planned time is supplied. The
latter is a no-intervening-training projection. Use the projected value for the
planned decision while preserving the raw value for auditability.

Keep `recent=true` and `additional=false` for normal primary advice. Change
them only when the caller explicitly wants older repeat candidates or extra
training.

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
