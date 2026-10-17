# Activity Analysis

## Reference Roles And Reading Order

This file directs activity selection, inspection, interpretation, and plan-role
classification. Use the following reading order for both single-session
analysis and activity comparisons:

1. Start here to identify the actual session structure and available evidence.
2. Before interpreting physiological signals, read the
   [expected-response framework](physiological-response-synthesis.md#establish-the-expected-response)
   and [evidence-dependence rules](physiological-response-synthesis.md#group-dependent-evidence).
   These establish the domain-specific expectations and how to weigh agreement
   or disagreement between measurements.
3. Read the relevant specialist references below to qualify measurement quality,
   interpretation limits, and the corresponding session demands.
4. Apply [the synthesis](physiological-response-synthesis.md#synthesize-the-verdict)
   to the qualified findings, using its shared interpretation rules and reporting
   contract. Form one integrated verdict rather than separate sensor verdicts.

| When relevant | Reference and responsibility |
| --- | --- |
| BR, tidal volume, or minute ventilation | [respiration.md](respiration.md): respiratory measurement meaning, quality, and interpretation limits |
| SmO2 or THb | [muscle-oxygen.md](muscle-oxygen.md): local oxygenation measurement context, quality, and interpretation limits |
| CORE, estimated core or skin temperature, or Heat Strain Index | [thermal-sensing.md](thermal-sensing.md): thermal measurement quality and evidence required for thermal interpretations |
| Long rides, late-session work, early-versus-late comparisons, severe intervals, material cadence or power variability, heat, or fueling context | [cycling-endurance-physiology.md](cycling-endurance-physiology.md): session demands, durability, and cross-sensor context |

Read only the specialist references relevant to the question and available
evidence. Missing optional sensors do not require reading their references.
For a narrow mechanical question, use the relevant parts of this file without
expanding it into an integrated physiological assessment.

[sources.md](sources.md) documents the shared research basis and limits for
respiration, muscle oxygen, and physiological synthesis. Consult its relevant
topic when checking a claim's support, applicability, or uncertainty. Thermal
and endurance references carry their own source sections. Follow those source
links when the question requires checking the underlying research; source
registries supplement the analysis workflow rather than defining another one.

## Selection And Inspection

- Resolve and verify the exact source activity; treat “latest” as a discovery
  request. Fetch its metadata and streams through the source MCP, persist the
  package, then inspect it:

```bash
python3 -B scripts/save_intervals_activity.py --activity-json <mcp-activity-json> --streams-file <mcp-streams-file>
python3 -B scripts/activity_inspect.py <saved-activity-ref> --brief
```

- Repo analysis helpers must not call source APIs directly.
- Prefer `scripts/activity_inspect.py` over one-off analysis snippets.
- Use `--compact` or full output only when detailed per-block/per-sensor JSON is
  needed, `--no-intervals` when interval rows are irrelevant, and `--stdout`
  only when full terminal JSON is genuinely useful.

## Session Context And Analysis Flow

Establish the session's intended role, prescribed work and recoveries, applicable
physiological anchors, and actual completed structure separately. Resolve these
from the user's request and available workout/plan evidence; the activity name
is a clue to intent, not proof of the prescription or completed dose. Preserve
unknown values rather than substituting observed averages or an anchor.

Pass resolved inputs explicitly to the helper:

- `--vt1-watts` and `--vt2-watts` are physiological anchors for the activity's
  date, not prescribed power targets.
- `--prescribed-watts` is an explicitly known common power target for assessed
  VT2 blocks. Without it, target attainment remains unresolved even when an
  anchor is known. Do not use this common target for a session with different
  targets across blocks.
- `--target` selects blocks near a power level; it does not supply the
  prescription. Check source interval boundaries and completed duration too:
  power-based selection can omit interrupted or substantially off-target work.
- Resolve ERG use from explicit session evidence. Trainer status alone does not
  establish ERG. In confirmed ERG, stable power describes delivered load; it
  does not independently demonstrate athlete control, spare capacity, or ease.
- Use available feel/RPE and material cooling, fueling, illness, or prior-work
  context. Ask only when a missing fact could change the conclusion.

Inspect actual work and its measurement eligibility, interpret the response in
that session context, then state the supported consequence. A script score or
selected window does not replace this synthesis. Without comparable history,
assess this session without claiming an individual development trend.

## Block Detection

- Use a known target with `--target`, `--tolerance`, and `--min-block` when the
  intended structure is known.
- Use `--auto-blocks` for mixed or unclear structured indoor sessions. Do not
  infer outdoor VT1/VT2 intent from variable `WORK` segments without supporting
  activity name, workout structure, or user context.
- Exclude warm-up and cooldown from work-block metrics.

## Quality Sections

- For outdoor endurance, inspect `outdoor_vt1_pacing`. Pass the caller-resolved
  anchor with `--vt1-watts`; use `--outdoor-vt1` or
  `--no-auto-outdoor-vt1` only to override detection deliberately.
- For pure indoor trainer VT1, inspect `indoor_vt1_quality` and pass
  `--vt1-watts`. Treat warm-up/cooldown as part of a selected workout unless
  explicitly modifying it.
- For threshold-like work, inspect `vt2_quality`. Pass `--vt2-watts` for
  intensity classification and, separately, `--prescribed-watts` when a common
  prescribed target is known. Without a valid anchor, intensity classification
  is unresolved. Without a prescription, report descriptive stability rather
  than target attainment. Current VT2 diagnostics select blocks by observed
  power near the anchor; inspect the remaining work blocks before judging
  completion of the whole prescription.
- Standard output excludes beta diagnostics. Use `--brief --debug-beta` only
  for explicitly requested development/debugging. Do not use `beta_summary`,
  `beta_stability`, or `beta_vo2` as the basis of a coaching verdict or progression.

## Reporting The Scope Of Measurements

Use `statistics_scope` to distinguish whole-activity statistics, source WORK
intervals, and detected analysis segments. `change_scope` and the nested
`comparison` refer to selected windows only. Keep each average, maximum and
change attached to its actual period; a block mean is neither a session mean
nor a peak. State the period in the answer when otherwise ambiguous.

`source_work_intervals` preserves source-recorded boundaries separately from
`work_blocks`; `overlapping_source_interval_indices` connects detected segments
to source intervals without claiming they are identical. Use source boundaries
and the prescription when assessing completed work. A shorter detected stable
segment does not establish an interrupted or shortened prescribed interval.
Absent source intervals leave those boundaries unverified; do not substitute
detected segment duration as proof of full completion or a shortfall.

## Measurement Eligibility And Comparison Windows

Read each field's `data_quality` and each `comparison` before interpreting a
summary or change. Summaries use elapsed-time weighting. Missing coverage,
long gaps, or a missing/nonmonotonic clock can make a field
unavailable for that period without invalidating other fields or valid blocks.
Invalid measurements count as missing coverage; their presence alone does not
invalidate a series. Treat unavailable values as unknown, never as zero drift
or normal response. A field's `series_quality` applies to the supplied activity
or block, while `early_quality` and `late_quality` apply to selected windows.
Preserve the accompanying `quality_note` when these scopes differ.

`comparison` identifies contiguous stable work windows, their timestamps,
power and cadence, elapsed work within the detected work run, and per-field
eligibility. Blocks reuse the complete activity's window grid and work-run history. The selector excludes an initial transition period and checks
mechanical comparability; separate work runs also require comparable elapsed
work. Its window lengths and tolerances are engineering defaults, not validated
physiological boundaries or proof of a steady state. Check the actual workout
structure and context before using the selected windows. Short intervals or
variable work may have no suitable windows; use their work-recovery architecture
rather than forcing a steady-work drift comparison.

The elapsed-time clock is assumed to be shared by source streams; unknown
device lag is disclosed, not automatically corrected. Mechanical execution
scores are power-compliance heuristics only. Main VT1/VT2 diagnostics no longer
assign physiological response, recovery, or combined grades. Use the descriptive
observations and shared synthesis rules for cost, cause, and progression.
`per_watt_change_pct` is available only for HR, BR, and VE and is descriptive,
not an efficiency or cost measure. Temperature changes are in degrees Celsius;
SmO2 changes are percentage points.

## Interpretation

Apply the shared interpretation rules in
[physiological-response-synthesis.md](physiological-response-synthesis.md):

- [analysis dimensions](physiological-response-synthesis.md#keep-analysis-dimensions-separate)
  for execution, observed response, modeled stimulus, and recovery cost;
- [dependent evidence](physiological-response-synthesis.md#group-dependent-evidence)
  for correlated or conflicting signals;
- [response versus cost](physiological-response-synthesis.md#separate-response-from-cost)
  for acute responses and residual burden;
- [competing mechanisms](physiological-response-synthesis.md#explain-competing-mechanisms)
  for observations and possible causes;
- [comparison and adaptation](physiological-response-synthesis.md#compare-sessions-and-assess-adaptation)
  for matched windows, workload ratios, and claims of progress.

Use the following source- and sensor-specific requirements alongside those
shared rules:

- For respiration, read [respiration.md](respiration.md). Distinguish BR, VT,
  and VE; check coverage, fit/placement context, export scaling, and arithmetic
  consistency before interpreting them. Analyze what drives VE, prefer
  matched-work comparisons, and treat five-second rolling VE as a source-
  reported short-window estimate rather than laboratory peak ventilation. Do
  not use an absolute Tyme Wear value or universal threshold alone to classify
  intensity, establish VT1/VT2, or identify a limiter.
- For muscle oxygenation, read
  [muscle-oxygen.md](muscle-oxygen.md). Check signal quality before using
  extrema, drift, breakpoints, or recovery kinetics. Inspect SmO2 desaturation,
  recovery reoxygenation, relative THb trend, and alignment with power, cadence,
  HR, ventilation, temperature, and interval structure. Prefer matched-work and
  same-placement comparisons. Do not use an absolute SmO2 value or universal
  threshold alone to classify intensity or identify a limiter, and do not
  interpret absolute Moxy THb as a clinical hemoglobin concentration.
- For CORE, estimated core temperature, skin temperature, Heat Strain Index,
  or another wearable thermal stream, read
  [thermal-sensing.md](thermal-sensing.md). Treat an absolute wearable
  temperature or product-derived index as context, not proof of thermal cost
  or heat limitation. Require the reference's aligned evidence before allowing
  thermal data to change a verdict.
- For long rides, late-session work, or early-versus-late comparisons, read
  [cycling-endurance-physiology.md](cycling-endurance-physiology.md). Treat
  durability as the onset and magnitude of deterioration under accumulated
  work, not as ride duration or HR decoupling alone. Compare matched work and
  resolve thermal and fueling context before attributing a change to fitness.
- Keep CP, W prime, FTP, VT2, MLSS, and Xert Threshold Power distinct. Use
  CP/W-prime or Xert strain models as feasibility evidence, not as direct
  measurements of an energy store or a causal explanation for fatigue.
- When cadence or power variability can affect the verdict, apply the cadence,
  torque, and interval-architecture rules in
  [cycling-endurance-physiology.md](cycling-endurance-physiology.md). Do not
  equate matched average power or load with matched local or physiological
  stimulus.
- Use normalized source activity summaries for their own load and model
  perspectives. They supplement rather than replace stream/block analysis.
  For Garmin Training Effect, preserve both numeric scores and the label, use
  phrasing such as "Garmin estimates the primary stimulus as ...", and check
  heat, humidity, altitude, illness, incomplete recovery, sensor quality, and
  local muscular cost before interpreting an unexpectedly high or low value.
  The same Training Effect can represent different workout structures and does
  not prove total work, total recovery demand, or completed adaptation.
- When a normalized Garmin activity summary is available, pass it explicitly to
  `activity_inspect.py` with `--garmin-json`. Interpret Available Stamina under
  `modeled_stimulus` as intensity-sensitive pacing context and Potential Stamina
  under `total_cost_and_recovery` as the slower-changing modeled depletion.
  Link the Available minimum to its timestamp, power, heart rate, and work
  interval when possible. Describe rebound as recovery of Garmin's short-term
  estimate, never as measured fuel restoration.
- Always inspect the emitted `blind_spot_control` before using Garmin activity
  metrics in a verdict. Explicitly resolve local muscular fatigue or soreness,
  neuromuscular/strength cost, unfamiliar training or terrain, heat/humidity or
  dehydration, illness, and feel/RPE when they could alter the conclusion.
  `requires_context` and `requires_athlete_report` are unknowns, not normal findings.
- Interpret `training_effect_context` as graded evidence, never as causal proof.
  `not_assessed` means the necessary evidence is unavailable or no relevant
  context was detected; `context_present` means the factor exists without a
  demonstrated effect; `supported` requires multiple aligned signals, except
  for directly observed sensor-quality limitations. Preserve the evidence and
  confidence with every assessment. Do not translate `context_present` into
  wording such as "heat inflated Training Effect".
- Numeric difficulty should accompany a text difficulty rating when present.
- Ask how the session felt when useful, but not when feel/RPE is already known.
- Save subjective feel/RPE remotely only when the user asks, using the owning
  source skill's write workflow.

## Xert MPA And Point-Of-Failure

Use this only when the analysis specifically needs Xert model dynamics.

- If a Fitness Signature and power segments are already available, use Xert MCP
  `calculate_strain`. This models the strain path without fetching Xert data.
- If the Fitness Signature is the only missing input, first reuse a fresh,
  time-appropriate signature already in the source context; otherwise fetch it
  with Xert MCP `get_training_state`, then call `calculate_strain`. Do not use
  live Xert Calculate merely to discover the current signature.
- Fetch new Xert session data only when the question requires Xert's reported
  MPA or another source-specific series field that is not already available.
- Do not duplicate the source plugin's formulas in training-analysis.

- Treat reported activity MPA as authoritative; do not replace it with a local
  reconstruction during deep depletion.
- Report minimum positive `MPA-P`, its timestamp, and the first `P >= MPA` when
  present.
- Describe the crossing as Xert point-of-failure evidence. Do not call it a
  breakthrough unless Xert's completed-activity result independently confirms
  a breakthrough or Fitness Signature change.
- Keep mechanical execution, physiological observations, and Xert's modeled
  strain separate.
- Use Xert's activity summary for authoritative total/system XSS and Difficulty;
  use the time series to explain when and why model strain changed.
- Present Xert system allocation separately from the training-domain
  classification. Determine VT1, tempo, VT2, VO2max, sprint, or another role
  from the planned target, actual power structure, progression context, and
  available physiological evidence; do not derive the role from the dominant
  low/high/peak label alone.

## Plan-State Effect

When the activity belongs to the active plan's timeline, finish the analysis
with an explicit classification:

- `planned_role`;
- `completed_role`;
- `quality_completed`;
- `progression_effect`: `advance`, `hold`, `consolidate`, or `none`;
- a concise reason and the analysis artifact paths used as evidence.

Read `config/plan-state.json` first. Apply the classification through
`scripts/plan_state.py apply` only after the analysis is complete. Aerobic,
recovery, cross-training, incomplete, or downgraded sessions remain recorded
but do not advance the quality queue. Reapplying the exact same activity is
idempotent; a conflicting or out-of-order update must be resolved explicitly,
not hidden by a fallback.

Use Garmin Training Effect only as supporting evidence for role alignment:

- A planned easy aerobic/VT1 session with unexpectedly high aerobic Training
  Effect or a `TEMPO`, `LACTATE_THRESHOLD`, `VO2MAX`, or anaerobic label should
  trigger inspection of the actual power structure, physiological response,
  environment, and sensor context for evidence that the session was costlier
  than intended.
- A planned sprint or VO2max session with low corresponding Training Effect
  should trigger inspection of work intensity, duration, recoveries, power or
  speed data, and sensor quality before calling the quality stimulus incomplete.
- A long easy session with low Training Effect can still fulfill its planned
  volume, endurance-base, fatigue-resistance, or recovery purpose.
- Never set `quality_completed=true` or `progression_effect=advance` from
  Training Effect alone. Require agreement with the planned structure,
  mechanical execution, acute physiological response, athlete feel when
  available, and the plan's own progression criteria.
