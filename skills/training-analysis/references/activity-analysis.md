# Activity Analysis

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
- For threshold-like work, inspect `vt2_quality`. Pass `--vt2-watts` for a
  known indoor target; omit it for variable outdoor work so the result remains
  a control/cost diagnostic rather than exact target compliance.
- Keep `beta_stability`, `beta_vo2`, and experimental VT1 metrics as
  development evidence. Do not present them as threshold diagnoses or let them
  override the main score without a clear pattern. Prefer `beta_summary` for
  tabular summaries and preserve separate parts in mixed sessions.

## Interpretation

- Read
  [physiological-response-synthesis.md](physiological-response-synthesis.md)
  before combining heart rate or multiple physiological streams into the final
  verdict. Establish the expected response for the actual intensity domain and
  group dependent outputs into evidence families rather than counting fields.
- Keep these four dimensions explicit and separate when their evidence is
  available:
  1. `mechanical_execution`: power, duration, interval structure, recoveries,
     pacing, and target compliance;
  2. `acute_physiological_response`: heart rate, respiration, SmO2, temperature,
     drift, and other direct within-session responses;
  3. `modeled_stimulus`: source-owned estimates such as Garmin aerobic and
     anaerobic Training Effect, described as expected stimulus rather than
     observed adaptation;
  4. `total_cost_and_recovery`: source-specific load/recovery models, subjective
     feel, soreness, and subsequent recovery evidence.
- Report mechanical execution separately from physiological cost. A variable
  ride can be mechanically uneven yet physiologically tolerable, and a tightly
  controlled interval can still have excessive physiological cost. Do not let
  a modeled-stimulus label collapse these dimensions into one verdict.
- Briefly name the primary and strong secondary adaptation systems stimulated
  by the actual dose, and explain why. Distinguish likely training signals from
  adaptations proven to have occurred.
- When power varies, prefer HR/BR/VE-per-watt drift over raw drift. Raw
  physiology can fall while cost per watt rises.
- Use relevant available sensors, not power and HR alone. Check data quality and
  continuous gaps before calculating averages, extremes, or drift.
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
