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

Resolve the source activity ID first. For “latest” or an ambiguous description,
search the relevant date range and verify the match. For a metadata question
about a known Intervals.icu ID, call `get_activity` with the needed
`includeFields`. Use `get_activity_intervals` for recorded interval rows.

For session analysis requiring fresh streams, call `get_activity(save_full=true)`
and `get_activity_streams` concurrently for the same ID. Use the returned
`full_activity_file` and `streams_manifest_file` paths to save and inspect
the local package. Pass the resulting `activity_dir` to the inspection helper.

```bash
package=$(python3 -B scripts/save_intervals_activity.py --activity-json "$full_activity_file" --streams-manifest "$streams_manifest_file") &&
python3 -B scripts/activity_inspect.py "$(jq -er .activity_dir <<< "$package")" --brief
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

- `--vt1-watts` and `--vt2-watts` require caller-established physiological
  anchors for the activity's date, not prescribed power targets. A plan's
  `target_power_w` is training intent and does not establish such an anchor.
  Leave these options unset when only training targets are known. Packet
  reference labels record supplied numbers, not independent physiological
  validation; power-exposure cutoffs likewise do not establish thresholds.
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

## Whole-Session Effort

Before subjective effort is known, describe measured workload and structure
without calling the experienced ride easy, comfortable or controlled. Low power,
heart rate or modeled load can support a low measured dose, but not felt ease or
successful recovery. Preserve that distinction in the opening verdict itself;
a later recovery caveat does not qualify an unqualified easy-session verdict.
If perceived effort could change the assessment, ask how the whole ride felt,
including breathing and legs, rather than only how its hard efforts felt.
For quality work followed by endurance work, include both parts when their
perceived effort could change the verdict or next-session consequence. Falling
HR or respiration during the extension does not establish felt ease.

For a ride with an optional aerobic extension, recover the main duration and
the decision point from the applicable prescription. Locate the actual finish
in the power trace. For structured work at a known endurance target, pass
`--steady-vt1-watts W` to the inspection alongside any hard-interval target.
It returns one sustained segment after harder work, or null when unresolved.
Cross-check the boundaries against the efforts, pauses and cooldown.

Give separate verdicts on the course of the steady work and on the added
minutes. Compare a settled early window with a late one for overall drift;
then compare the extension with an equal-duration window immediately before
it at similar watts. Anchor both to completed work in the trace, excluding
stops and cooldown. A stable finish can follow an earlier rise in cost.
Use any initial transition after intervals to describe recovery separately.

For a personal reference, find prior rides with similar sustained watts and
enough work to reach the same minutes of the block. Compare the same window
relative to each ride’s actual work onset. If a shorter ride only reaches the
pre-extension window, use it there; a longer ride may also cover the extension.
In the rider’s answer, identify the dates, work minutes, actual watts and the
most informative measured responses for today and the reference. Qualify
differences in cadence, preceding hard work or conditions when material.
If the boundary, streams or a credible reference are missing, state which
comparison is possible. Keep tolerability during the ride separate from the
recovery cost observed at the following quality session.

Narrative effort, breathing and leg reports are evidence even when numeric RPE
is null. Let a substantial reported burden affect the verdict; good leg feel or
moderate model difficulty cannot negate it. Keep experienced effort during the
ride distinct from unknown next-day recovery. With material context absent,
name the provisional consequence and ask the focused question that would change
it, rather than repeating an inventory of unknowns.

## Block Detection

When comparing repetitions, keep the recorded mean power, including observed
zeros. Before describing a fade, a weaker repetition or a rebound, inspect
the power trace within the effort. Compare equivalent portions of the work
intervals, check the transition into recovery, and establish how long the
difference lasted. If a few samples drive the mean, quantify their influence
when it changes the verdict. A median or a mean excluding those samples can
illustrate that influence. Describe a sustained fall when the trace shows it.
Use cadence and recording coverage to interpret interruptions, and leave their
cause open when the evidence is inconclusive.

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
  Report `power_coverage.valid_pct` for the recording. When the verdict is
  `power_pacing_unavailable`, explain the reported reason and assess other
  eligible signals and any supported windows separately.
- For pure indoor trainer VT1, inspect `indoor_vt1_quality` and pass
  `--vt1-watts`. Treat warm-up/cooldown as part of a selected workout unless
  explicitly modifying it. Report total moving minutes, the covered duration of
  matching WORK intervals, and the measured time within the stated working-power
  band separately. Inspect `work_interval_response` for each matching interval
  and the early/late comparison for comparable work. Recovery and intervening
  harder work fall outside the selected WORK intervals. When the full moving
  window is the fallback, require positive measured exposure and usable response
  windows before describing stability near the chosen watts.
- For threshold-like work, inspect `vt2_quality`. Pass `--vt2-watts` for
  intensity classification and, separately, `--prescribed-watts` when a common
  prescribed target is known. Without a valid anchor, intensity classification
  is unresolved. The VT2 pipeline (or `--vt2-work-series --brief`) includes
  every recorded WORK interval, including short or off-target efforts. Use
  `series_scope` to distinguish recorded laps, detected candidates and a
  series mapped to the prescription. Review duration, power, RPE, physiological
  response and subsequent recovery before progressing.
- When the historical prescription or a dated anchor can be verified, save
  reviewed inputs in `vt2-evidence.json` next to that ride's `activity.json`.
  Both the activity inspector and progression helper use these inputs. Example
  for three prescribed efforts with the last one lacking a mapped recording:

  ```json
  {
    "activity_id": "i123",
    "anchor": {"watts": 295, "valid_on": "2026-11-16", "source": "dated threshold assessment"},
    "prescription_source": "original workout",
    "prescribed_watts": 300,
    "series": [
      {"source_interval": 2, "duration_s": 1200},
      {"source_interval": 4, "duration_s": 1200},
      {"source_interval": null, "duration_s": 1200}
    ]
  }
  ```

  Omit unknown fields. `valid_on` is the local ride date for which the
  assessment applies. Supply each known target in `series[].watts` for a
  variable prescription. Interval numbers start at one in the full saved
  interval list, including recoveries. A null mapping preserves that effort
  as unobserved. Use the reviewed workout record to establish whether the
  athlete skipped it. Without a verified prescription, summarize the recorded
  laps and leave completion of the planned set open.
- Match each source recovery to its recorded WORK interval using
  `after_source_work_interval`. For a detected block, use its overlapping
  source interval IDs to check this association. A fixed post-work HR window
  is confirmed as recorded recovery only when its `recovery_context` is
  `recorded_recovery`. Compare like efforts, elapsed windows, and recovery
  modes and power. Use whole-pause BR and VE values descriptively.
- Standard output excludes beta diagnostics. Use `--brief --debug-beta` only
  for explicitly requested development/debugging. Do not use `beta_summary`,
  `beta_stability`, or `beta_vo2` as the basis of a coaching verdict or progression.

## Variable Outdoor Endurance

For a shorter first read of an outdoor inspection, generate a scoped packet:

```bash
python3 -B scripts/analysis_packet.py <inspection.json> --output <analysis-packet.json>
```

Before delivering the analysis, make a short internal completion check: does
it assess the established purpose, explain workload and qualified response,
use the athlete's report, preserve material timing/sensor limitations, and
justify the next-training consequence? Correct omissions without turning this
check into an extra user-facing checklist. With substantial interruptions,
state moving and total elapsed duration together. Recording gaps and source
non-moving duration need not reconcile; do not infer leftover stationary time
by subtracting them. The packet's `time_overview` groups these distinct facts.

Start with this packet, the athlete's report and the actual session intent;
open detailed inspection sections or raw data when needed. Missing fields in
this deliberately small packet do not establish missing source data.

When a numeric audit is requested, prepare the structured answer contract
shown in `scripts/analysis_packet.py` and validate it with `--answer <answer.json>`.
A passing check verifies declared numeric references, units, rounding and scope
labels only. It cannot verify that the prose uses those facts correctly or that
physiological interpretations are justified. Review those separately, then
present the ordinary prose rather than the audit JSON to the athlete.

With usable power data, prioritize measured work, duration and power
variation. Climbing is not an extra energetic load to add on top of measured
work. Use terrain only when it explains relevant cadence, coasting, posture
or cooling beyond the power record; elevation need not appear in every verdict.
When temperature affects interpretation, use `temperature_context` to identify
device/environmental proxies versus wearable core estimates. Preserve absent
core data; device temperature is not a substitute or proof of heat limitation.

Judge the actual ride against its established purpose. Group riding, solo
endurance and strict VT1 have different execution demands. An automatically
emitted `outdoor_vt1_pacing` score is a comparison to that anchor, not proof of
intent or a quality verdict for a group ride. A queued quality role is not the
prescription for the completed day.

Use `outdoor_evidence` for recording interruptions, chronological segments and
observed work accumulated before each segment. These segments are descriptive,
not prescribed intervals. A clock gap at unchanged distance supports a paused
recording; do not call it sensor failure or claim it invalidates Garmin's device
models without further evidence. Field-specific loss during recorded riding
still limits that sensor. Missing whole-ride coverage can coexist with usable
riding segments.

If strict stable windows are unavailable, inspect the chronological response
and `variable_work_comparison`. Its mechanically similar five-minute windows
match mean power, cadence, power distribution, variability, coasting and preceding
work. They are engineering diagnostics, not steady states or a validated durability
test. Preserve the reported limitations; do not loosen the criteria to obtain a
preferred result or treat unmatched segment means as drift. If no match exists,
retain the useful workload and response chronology without inventing deterioration.

When Garmin Performance Condition contributes, retain when its early level and
largest fall occurred. An early fall does not establish fatigue accumulated late
in the ride, and the model does not identify a physiological cause.

## Current Analysis And Source Precedence

Use the current inspection generated for this task as the source of calculated
values. Use raw activity metadata and streams to check source facts or recompute
a disputed value. Do not combine its windows or means with an older derived
`analysis.json`, cached report, or beta output found beside the raw files.

Generated inspections include `provenance`: format version, generation time,
input and calculation-script SHA-256 hashes, and effective options. To reuse a
cached inspection, verify that its inputs, scripts and relevant options match
this task. A timestamp or format version alone does not establish freshness.
If provenance is absent or mismatched, regenerate with the current helper;
if regeneration is unavailable, label the cached calculations unverified and
do not silently use them to replace current evidence. For supplied isolated
test packages, use the packaged scripts and inputs within the allowed scope.

## Reporting The Scope Of Measurements

For variable outdoor rides, start numeric interpretation with `analysis_overview`.
It distinguishes strict stable comparisons from variable-work comparisons, lists
the two selected windows separately from the number of eligible pairs, and binds
each exposure percentage to its watt threshold. Follow its detail paths for
quality and chronology; do not conclude that no comparison exists merely because
the strict stable method is unavailable.

For structured work, start with `work_block_overview`: each numbered entry
keeps its block mean, early/late window boundaries, window means and change
on the same record. Keep the block number attached when citing a value.
`block_mean` describes the analysis block; it is not the early window value.
Use `detail_path` to inspect the matching `work_blocks` entry for full quality
and comparison context. Null values remain unavailable, not zero. Source WORK
boundaries still determine recorded work duration separately from analysis blocks.

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

Recovery summaries use their own time scope. `hr_drop_start_to_min` is the
fall from the start to the minimum over the entire recovery block; use its
`start_s`, `end_s_exclusive`, and `duration_s`, and never call it a 60-second
fall. A `fixed_post_work_window` instead reports the fall from the last work
sample to the minimum within `window_s`; it is not necessarily the difference
at the exact window endpoint. Neither metric establishes whole-body recovery
or unusually fast recovery without suitable comparison context. Report a fixed-window
pulse drop only when the work-end sample connects to the first recovery sample and
valid heart-rate observations cover the full window. Read the reported reason
when coverage is incomplete.

For VT1 pacing, 30- and 60-second rolling power require continuous valid power
for the stated duration. Start a new window after a recording gap, invalid power
or pause. Both fixed-window checks credit each observation with at most the
recording's nominal sample period. An irregularly sampled stretch can therefore
have insufficient coverage even when the elapsed time is long enough.

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
  Preserve the source scale: do not append a denominator, percent sign or
  normalized score unless the source explicitly defines it. Xert Difficulty
  reported as 57 remains 57, not 57/100.
- Ask how the session felt when useful, but not when feel/RPE is already known.
- Save subjective feel/RPE remotely only when the user asks, using the owning
  source skill's write workflow.

## Xert 2.0 Beta for completed rides and training history

Start with the observed difference to explain. Select comparable rides or
blocks by recorded power, duration and work already completed. For a question
about recovery, also review the intervening training and the next quality session.

When a model estimate could change the interpretation, use
`summarize_activities_xert_2(activity_paths=[...])` for whole-ride comparisons,
in batches of up to ten. Use `analyze_activity_xert_2` for a single detailed
analysis. Request `save_series=true` when timing matters, for example to compare estimated
glycogen remaining or maximum power available at the start of two similar
climbs. Align the model series with the recorded climbs.

Across rides, check the model version, signature and settings before
attributing a difference to training. Interpret estimates alongside actual
execution, athlete feedback and recorded carbohydrate intake where relevant.
Muscle Glucose Uptake Rate describes modeled uptake. EatMyRide food-plan
entries can be prepared in advance or edited after a ride. Count them as
consumed when the athlete or a record of actual intake confirms them.
Otherwise report planned amounts as planned and leave actual intake unknown.

For a week or block review, compare standard XSS with Xert 2.0 XSS when the
choice of model could change the interpretation of the training dose. Check
`period_complete` in `list_activity_summaries` and `unavailable_count` in each
Beta batch. Match activities by their Xert activity path. If coverage
is incomplete or any ride lacks either score, report the coverage and label both
sums as subtotals for the same matched rides.

Sum each model's XSS separately. Reuse current activity summaries and identify
the rides that explain a material difference. Label the result as cumulative
XSS for the period. Use standard Xert for Training Load, Recovery Load, Form
and next-workout capacity.

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
- `quality_stimulus`: whether actual work warrants quality-recovery spacing;
- `quality_role_fulfilled`: whether actual work fulfills the quality role;
- `planned_workout_completed`: whether the complete prescribed workout was
  performed (`null` when the prescription or its completion is unknown);
- `progression_effect`: `advance`, `hold`, `consolidate`, or `none`;
- a concise reason and the analysis artifact paths used as evidence.

Read `scripts/plan_state.py context` first. Apply the classification through
`scripts/plan_state.py apply` only after the analysis is complete. Use the
Intervals.icu `start_date` as `started_at` and include `start_date_local` for
the activity's local calendar day. An explicitly
fulfilled quality role advances its matching queue step even when the planned
workout was shortened or progression is held. Judge role fulfillment from the
actual work, intended stimulus, athlete feedback, and plan context; neither a
missing final repetition nor an omitted endurance extension automatically
invalidates the quality role. Do not use a universal completion percentage.
A brief insufficient attempt may require recovery spacing without fulfilling
the role. Aerobic, recovery, cross-training, and sessions that do not fulfill
the queued role do not advance that step. Reapplying the exact same activity is
idempotent; a conflicting or out-of-order update must be resolved explicitly,
not hidden by a fallback.

Keep the achieved dose separate from the next prescription. Record supported
completion even when subsequent recovery is still unknown; qualify recovery
and the next dose in `last_result` and `next_step`. A provisional recommendation
to repeat is not a permanent progression requirement. When later athlete
feedback materially changes the assessment, review the stored conclusion and
reconcile any affected state through the supported correction workflow; do not
leave superseded advice as the current prescription or silently overwrite a
conflicting classification.

For corrections, preview `scripts/plan_state.py replay --checkpoint <state-json>
--classifications-file <json-array-file>` from a verified checkpoint immediately
before the affected activity. Include every subsequent activity in order. Add
`--write` only after reviewing the resulting compact context. Keep the previous
state and reviewed correction artifacts so the change can be audited.

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
- Never set `quality_role_fulfilled=true` or `progression_effect=advance` from
  Training Effect alone. Require agreement with the planned structure,
  mechanical execution, acute physiological response, athlete feel when
  available, and the plan's own progression criteria.
