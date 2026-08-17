---
name: xert
description: Use when working with Xert live data, Training Load, Recovery Load, Form or freshness, Training Status, Fitness Signature development (TP, HIE, PP), required XSS to build fitness, offline strain calculations, MPA and XSS semantics, activity or workout fields, Workout Designer rows, calendar notes, or Xert writes.
---

# Xert

Use this skill for Xert access, field interpretation, API quirks, and safe
writes. The plugin is stateless and returns normalized data to callers.

## Network Execution

Live Xert reads and writes require external network access. Run live
`xert_cli.py` commands with escalated network permission on the first attempt;
do not first try them in a network-isolated sandbox. Offline help and local
artifact inspection do not require escalation.

## MCP Read Access

Prefer the Xert MCP tools when they are available:

- `list_activities` lists an inclusive local-date range. Keep `view=summary`
  for discovery; use `view=loads` only when compact Low/High/Peak XSS details
  are required because it fetches every activity detail.
- `get_activity` reads one activity path. Use `view=summary` normally,
  `view=full` for source fields, and `view=session` only for Xert-specific
  second-by-second data; session view returns a private temporary JSON path.
- `list_workouts` lists or filters the workout library. Its `name_keywords`
  value requires every supplied word to occur, case-insensitively.
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
  Use `view=summary` normally and `view=full` only for the selected raw source
  payload. This tool does not add activity load or cross-source readiness.
- `create_workout` saves a new Xert workout from complete, structured Designer
  rows. Each row uses duration values in seconds, and repeat-row
  `rib_duration_seconds` is applied after every repetition, including the
  final one. Use it only when creation is explicitly requested; inspect its
  verified metadata and `timeline_summary` after the write.

The CLI remains the development/fallback interface and exposes Xert operations
that have not yet been added to MCP. Both transports call the same Python
service for activities, workouts, calendar notes, state, and advice.

## Choose The Narrowest Command

```bash
python3 -B plugins/xert/scripts/xert_cli.py activities <start-date> <end-date>
python3 -B plugins/xert/scripts/xert_cli.py activity-loads <start-date> <end-date>
python3 -B plugins/xert/scripts/xert_cli.py activity <path> --summary-only
python3 -B plugins/xert/scripts/xert_cli.py training-info
python3 -B plugins/xert/scripts/xert_cli.py workout-capacity --as-of <ISO-datetime> --fresh-at <ISO-datetime>
python3 -B plugins/xert/scripts/xert_cli.py readiness-input [--activity <path>]
python3 -B plugins/xert/scripts/xert_cli.py readiness-input --advice-source auto --advice-at <ISO-local-datetime>
python3 -B plugins/xert/scripts/xert_cli.py load-model --target-at <ISO-datetime> --workout-after-hours <H> --low-xss <XSS> --high-xss <XSS> --peak-xss <XSS>
python3 -B plugins/xert/scripts/xert_cli.py recommended-training --date <YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py workouts [--name <name-keywords>] [--summary]
python3 -B plugins/xert/scripts/xert_cli.py workout <path>
python3 -B plugins/xert/scripts/xert_cli.py workout-rows <path>
python3 -B plugins/xert/scripts/xert_cli.py workout-row-add <path> <row-number> --duration <MM:SS> --power <watts> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-row-update <path> <row-number> --power <watts> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-row-remove <path> <row-number> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-replace <path> --rows-json <rows.json> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py training-forecast
python3 -B plugins/xert/scripts/xert_cli.py calendar-events <YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py calendar-event <path> --date <YYYY-MM-DD>
python3 -B plugins/xert/scripts/xert_cli.py calendar-notes
python3 -B plugins/xert/scripts/xert_strain_cli.py calculate --signature-tp <W> --signature-hie <J> --signature-pp <W> --segment <MM:SS@W>
python3 -B plugins/xert/scripts/xert_strain_cli.py solve-endurance --input <plan-structure.json>
python3 -B plugins/xert/scripts/xert_strain_cli.py solve-endurance --input <designer-rows.json> --adjustable-row <one-based-row> --target-low-xss <XSS> --signature-tp <W> --signature-hie <J> --signature-pp <W>
```

- Use `activities` for activity discovery. Pass the intended inclusive local
  calendar dates; the CLI handles UTC conversion.
- Use `activity-loads` for compact XSS history. Do not loop over individual
  activity details from the caller.
- Use `activity --summary-only` for normal activity analysis. It includes the
  XSS split, XEP, focus, specificity, difficulty, freshness, and fitness
  signature.
- Use `training-info` as the narrow first choice when a local strain calculation
  needs the current Fitness Signature and no fresh, time-appropriate signature
  is already available. Map `signature.ftp` to TP, convert `signature.hie` from
  kJ to J, and map `signature.pp` to PP. Then pass all three values to
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
- Use `recommended-training` when candidate workouts or activities are needed,
  and filter workout selection to `exerciseType == "Workout"`.
- Use `workouts --name <name-keywords>` to filter the freshly fetched workout
  library by case-insensitive keywords. All supplied words must occur in the
  name, in any order.
- Use `workout-rows` for editable Workout Designer structure, especially for
  repeat or slope rows. The resolved OAuth workout can be incomplete for these.
- In a repeat row, Xert's `Rest in between` (`rib_duration`/`rib_power`) is
  appended after every work interval, including the final repetition. For
  example, `interval_count=4` with a five-minute RIB produces four work
  intervals and four five-minute recovery intervals. Do not add a separate
  recovery row after the repeat block unless an additional recovery is
  intentionally required.
- Use `workout-row-add`, `workout-row-update`, or `workout-row-remove` for one
  structural row operation. Row numbers are one-based. Add and update expose
  the same row field options; add requires duration and power, while update
  leaves every omitted field unchanged.
- Use `workout-replace` when the complete workout structure changes. Calculate
  one complete row array with `--dry-run`, then save the same file once with
  `--yes`; the command replaces all rows atomically and verifies fresh readback.
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
  the current signature is missing, obtain it with `training-info` and continue
  locally; a missing signature alone is not a reason to use live Calculate. Its
  default output is the analysis-ready summary; add `--detailed` only when
  segment diagnostics or model limitations are needed.

Credentials come from `XERT_USERNAME` and `XERT_PASSWORD` in `.env`.

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

```bash
python3 -B plugins/xert/scripts/xert_cli.py activity <path> --session-data --output /tmp/xert-activity.json
```

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
