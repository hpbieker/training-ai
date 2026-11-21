# Daily Training Recommendations

## Focused Readiness Questions

For a narrow question such as “am I ready now?”, use this path before the
full session-planning workflow below:

1. Resolve the current time and timezone, read relevant personal context, and
   check compact plan context/pending activities. Fetch fresh Garmin health and
   Xert state; persist MCP structured content unchanged in private temporary files.
2. Run `readiness_snapshot.py --summary` with explicit time/source JSON. Use the
   returned `latest_activity.activity_dir` to find activity reports; do not guess
   paths or read whole helper scripts to discover the normal workflow.
3. If assessing recovery after a completed workout, request Garmin
   `get_health_day(save_full=true)` and pass its `full_health_day_file` as the
   Garmin input. The helper accepts that saved wrapper and derives post-workout
   HR/stress windows locally. Compact responses omit these series.
4. If sleep/HRV appears absent despite a same-day valid-sleep/readiness record,
   inspect the saved full sleep/HRV summaries before calling it missing or
   requesting a device sync. Missing from a compact response is not proof of
   missing source data. Do not substitute aggregate drivers for overnight values.
5. Lead with the recommendation and relevant evidence. Distinguish completed
   overnight recovery, exercise-time observations and current recovery. State
   material missing current body feel or post-workout evidence. Model freshness
   times do not establish readiness for a hard session at that time.

Keep this packet focused on readiness. Calendar placement, dose solvers, capacity
and alternative sessions belong to a requested concrete training recommendation.

## Resolve Context First

Before running helpers, resolve the local date, planned start or free window,
location/start anchor, available modalities, surface/bike intent, target event
and time horizon, and practical fueling defaults. When the user has not
specified a time, use the workout-placement preference and any earliest-start
constraint in `config/coaching-preferences.md`. Resolve the plan role and its
complete workout before choosing `planned_at`. For a quality role, check
readiness and the relevant Xert recovery projections at candidate starts. If
recent execution, subsequent recovery and current body feel warrant a change, assess the appropriate
downgrade. Select one winning session. When both indoor and outdoor
cycling are available, retain one concrete alternative for the final answer
without letting it replace the winner. Resolve modality availability from
explicit user input or personal context, never from the repository.

For calendar-based planning, have the assistant classify each event and pass it
as a `planning_context.calendar.events` row (`subject`, `start`, `end`,
`classification`, optional `id`). Use the parser's classifications:
`fixed_blocker`, `open_training`, `tentative_nonblocking`, `movable_event`,
`flexible_appointment`, `indoor_overlap_candidate`, and `unknown`; unknowns
block time. Include local-offset `day_start`/`day_end` and setup/cleanup
buffers. For movable events, pass the minimum duration and whether shortening
is permitted; use the placement returned by the helper.

Consider the earliest feasible start in each availability window and any
later start called for by the user's placement preference. Evaluate each
`planned_at` independently, keeping its inputs and results together. Choose
among candidates whose complete, candidate-specific workout fits its window
using the user's placement preference. With no preference, choose the earliest
candidate that fits. Reject a candidate that does not fit and continue to the
next one without shortening the workout to fit it. Only after every candidate
window has been rejected may the recommendation reduce the dose or use
multiple windows.

Before finalizing a calendar-backed workout time, run these checks:

- Resolve the user's setup and cleanup buffers from personal context and apply
   them to every free interval: move its workout-window start forward by the
   setup buffer and its end backward by the cleanup buffer. Test calendar
   availability against the complete occupied window—setup, workout, and
   cleanup—while keeping the displayed workout start and duration distinct from
   the buffers. Evaluate recovery at the start of physical training. Base the
   earliest candidate on availability and actual readiness constraints. Round
   that time up to the next five-minute boundary if needed. A projected Xert
   recovery time alone does not require delaying the session.
- Verify that `availability.windows` includes every positive-duration interval
   after event classification, and that the workout was neither limited to the
   interval containing `planned_at` nor delayed solely by an event that personal
   context defines as open, tentative, or movable.
- Calculate post-workout slack from the end of the cleanup buffer to the next
   confirmed fixed appointment. Show the slack, the appointment's subject/title
   and time, and label it as the hard stop. If no later hard stop exists in the
   planning day, state that explicitly.

If a calendar event overlaps or constrains the recommended session, read
[calendar-conflict-resolution.md](calendar-conflict-resolution.md) before
finalising it.

Resolve one IANA location timezone. Pass it inside `--time-context-json` to
`readiness_snapshot.py` and as `local_timezone` inside
`recommend_training.py --planning-context-json`. The recommendation context
must use complete ISO-8601 `now`, `planned_at`, and availability-window
timestamps with explicit UTC offsets; it does not accept naive clock strings.
Availability windows inherit `local_timezone`; an optional window-level
`time_zone` is accepted only when it matches that top-level timezone.
The helpers keep absolute comparison and cutoff timestamps in UTC and use the
resolved timezone for local calendar semantics and display. Do not infer it
from the machine timezone or assume a mobile client timezone is available.

For every agent-driven recommendation, provide a complete
`--planning-context-json` that satisfies `recommend_training.py`'s validation.
Prefer a small persisted `planning-context.json` working file when the context
is assembled across several source reads. Before candidate evaluation, resolve
the plan role, classify the freshly read calendar into `calendar.events`, and
pass day boundaries and setup/cleanup buffers. The helper derives candidate
windows and applies the complete setup, workout, and cleanup window. Run it
per candidate with that candidate's explicit `planned_at` and Xert advice, then
once more with the selected `planned_at` to create the final recommendation
packet.
An existing calendar event that appears to reserve time for training is
calendar evidence, not an automatic choice of `planned_at`; select its start
only when the same placement calculation supports it.

Discover active files under `config/plans/` through the repo-local
[training-plan skill](../../training-plan/SKILL.md). For plan state, run `python3 -B scripts/plan_state.py
context` and `python3 -B scripts/plan_state.py pending`; do not print or read
the raw `config/plan-state.json` into LLM context. If pending activities are
returned, inspect, classify, and apply every one chronologically, then refresh
the compact context. Decide the day's plan role and translate it explicitly to `recovery`,
`vt1`, `vt2`, `vo2max`, `sprint`, or `mixed`. `mixed` is valid only when the
selected plan truly calls for mixed work; it is not a fallback for missing plan
selection. Plan files remain LLM-readable and must not be parsed by helper
scripts; the JSON state is the machine-readable current pointer.

Pass these choices explicitly to `recommend_training.py`. Its default
refresh mode `auto` reuses source snapshots within their TTL. Use
`--refresh-json` with mode `all`, `selected` plus a source array, or `none` only deliberately. An
explicit normalized source override in `--source-overrides-json` cannot be
combined with a refresh policy that forces its source group. Always pass the resolved intensity goal with the required
`intensity_goal` inside `--plan-selection-json`; the helper has no default training goal. The helper loads
`config/plan-state.json` by default and records its provenance. If the requested
goal differs from the state's `next_role`, pass a concrete
`role_mismatch_reason` in the same JSON object; otherwise the helper fails rather than silently
accepting a circular goal choice. Readiness still determines the highest
intensity the recommendation may select and may downgrade the session without
advancing or rewriting the queue.

Use the latest actual quality-role fulfillment separately from prescription
completion and progression. A held progression or an omitted final repetition
does not create a debt to repeat the same quality domain. If a recent substantial
session still appears queued solely because it was shortened, reconcile its
reviewed classification through the plan-state correction workflow before
selecting today's role. Queue advancement does not establish current readiness.

Fetch Intervals.icu wellness and calendar events through MCP `list_wellness`
and `list_events` before invoking the helper. Persist each complete MCP result
as normalized JSON and pass the paths as `intervals_wellness` and
`intervals_events` in `--source-overrides-json`. `recommend_training.py` must
not import the Intervals transport or invoke its CLI.

Apply the same persistence boundary to every live MCP result used as a source
override: write the result's `structuredContent`, without the surrounding MCP
transport envelope, unchanged to a date-scoped private temporary JSON file.
`recommend_training.py` normalizes supported source-specific MCP envelopes at
the override-file boundary and composes separate Xert state and planned-advice
overrides for readiness and dose resolution; the agent must not manually unwrap
or rebuild them.
Build the complete `--source-overrides-json` map from those paths and verify
that every required override file exists before invoking the helper. Do not
select refresh mode `none` until all source files required by refresh planning
are present.

Before composing the final recommendation, reject any source or recommendation
packet whose snapshot date/time is stale for the current run, whose local date
does not match the requested training date, or whose recorded plan provenance
disagrees with the freshly read `config/plan-state.json` and latest activity.
Do not repair such a packet from automation memory or older simulations; refresh
the affected sources or state explicitly and stop the recommendation if fresh
inputs cannot be obtained.

Treat `planned_at` as both the workout time and the latest possible data
boundary. Helpers derive `data_cutoff = min(now, planned_at)`: a future
recommendation can only use data available now, while a recommendation rerun
after its planned time must exclude activities and continuously changing source
points recorded after that time. Completed overnight signals such as sleep,
night HRV, resting HR, and Body Battery at wake remain usable when their
observation period ended by the cutoff.

For every candidate workout time, fetch planned-time Xert advice with MCP
`get_training_advice(at=<candidate_planned_at>)`. After the final time is
selected, the recommendation packet must use the advice fetched for that exact
`planned_at`. Do not use current advice for this: it lacks the availability,
deficit, and progression fields required to explain the XATA planning dose.

Review an athlete's report of unusual fatigue even with reassuring sleep, HRV
or soreness. Establish whether it persists today and how it compares with usual
fatigue at this point in training. If otherwise well, check perceived effort at
familiar easy power during warm-up and defer hard work if it still feels
unusually demanding. The helper's fatigue flag prompts this review. Choosing
watts or minutes requires additional evidence about the athlete and session.
A multiday cycling study supports tracking changes in perceived fatigue and
readiness together. [Ten Haaf et al.](https://pubmed.ncbi.nlm.nih.gov/27834554/)

## Illness And Return

If Intervals.icu contains a current/recent sickness event, or prior context
contains an unresolved illness episode, follow
[illness-and-return.md](illness-and-return.md) before selecting intensity or dose.
Pass the current evidence-based assessment through `--illness-return-json` to
both readiness and recommendation helpers when available. Calendar age or an
episode disappearing from a source window must not silently clear the return.

## Readiness Composition

- Before using HRV to reduce intensity or duration, fetch Garmin
  `get_health_day(date=<observed-date>, hrv_days=3)`. Save the complete
  `structuredContent` unchanged and use that file for both `garmin` and
  `garmin_hrv_history` in the source overrides, with the same `read_at` in a
  saved request. If using the full health-day archive as `garmin`, use the
  compact MCP response as `garmin_hrv_history`. If the installed tool lacks
  `hrv_days`, use `list_health_days(until=<observed-date>, days=3, sources=["hrv"])`
  for the history and save its response unchanged alongside the same-run health day.
  The helper computes the mean over three distinct, consecutive dates ending on
  the target day. Show last night and the mean separately. If history is unavailable
  or incomplete, disclose the single-night fallback; do not score missing nights
  negatively or reuse older nights as current.
- An isolated HRV, Sleep Score, or resting-HR deviation calls for caution and
  an execution/body-feel check, not automatic rejection of intensity or a fixed
  endurance-dose cap. A complete three-night HRV mean is the decision input;
  last night remains visible for review without independently overriding it.
  Several concordant adverse recovery signals can justify conservative
  intensity screening, but related Garmin signals remain one evidence family.
  The helper's numerical screening boundaries are heuristics, not validated
  personal physiological cutoffs. Explain any dose reduction using
  the combined recovery evidence, current symptoms or reported response, and
  the demands of the proposed session. Retain illness and poor-recovery rules.
  A heuristic risk score is not a measured physiological maximum; removing a
  cap does not by itself establish that the full XATA dose is appropriate.
- Read `primary_decision.readiness_evidence.review_required` and
  `target_resolution.readiness_dose_review`. When review is required, assess
  body feel, symptoms, recent execution/recovery and the planned session's
  demands before adopting the model dose. Explain why the chosen duration is
  appropriate separately from the intensity choice. No wearable score or
  combination of scores establishes a fixed maximum in minutes or XSS;
  retain illness and explicit recovery-session constraints; review model-capacity conflicts
  under their own documented rules. An explicit coaching dose remains subject
  to this review and must retain its evidence-based rationale in the answer.
- Attribute the final dose to XATA, next-workout capacity, calendar constraints,
  or an explicit coaching adjustment, and state the concrete reason for each
  adjustment. Use planned-time Xert recovery hours for modeled recovery;
  keep Training Load / Recovery Load diagnostic rather than translating an
  increasing ratio into increasing fatigue risk.
- Fetch volatile inputs through their source plugins and pass normalized JSON
  to repo helpers. Do not pass raw API payloads into readiness consumers.
- Group HRV relative to baseline, resting HR, and Sleep Score as related
  autonomic/recovery evidence rather than independent votes. Keep Body Battery
  and Garmin Stress as supporting model context because they reuse related
  upstream evidence. Compose that family with independent body feel, soreness,
  cumulative load, and recent workout response.
- Treat Garmin as a source of negative readiness signals that can downgrade an
  otherwise supported recommendation, not as a required permission source.
  Use a Garmin signal for downgrade only when it belongs to the target local
  day, is complete, and is fresh enough for its signal type. Exclude
  unavailable or stale signals rather than scoring them negatively; recommend
  a device sync without automatically reducing the training dose.
  Read `primary_decision.readiness_evidence` alongside the intensity ceiling.
  No observed blocker is not confirmation of recovery. If direct signals cannot
  be assessed, describe the plan/model support as provisional and identify the
  missing evidence; do not turn uncertainty alone into a dose reduction.
- Interpret Body Battery by time of day. Use the wake value as overnight
  recovery context and the current value as modeled body-resource context at
  its timestamp. It is not measured metabolic energy, glycogen, or calorie
  balance. A value concerning at wake may be normal later. Consider change
  since wake and intervening training; do not adjust the Xert dose from either
  value alone.
- Keep aggregate Training Readiness diagnostic-only. Do not separately weight
  it or yesterday's workout on top of the underlying direct signals.
- Project timestamped recovery estimates to the planned start when appropriate,
  assuming no intervening training and stating that assumption. For a future
  recommendation date, fetch the latest real Garmin day rather than the empty
  future day so its timestamped Recovery Time can be projected. Do not carry
  that day's HRV, sleep, resting HR, Body Battery, or aggregate Training
  Readiness forward as if they were observations for the future date. Describe
  those signals as pending until the relevant day or time has occurred. Report
  expected data as missing or stale when it should already have synced.
- Review remaining Xert hours for the systems relevant to the planned role.
  Weigh a conflict against actual recent load, subsequent recovery and current
  body feel before choosing to proceed, move or downgrade the session. Keep
  the planned role provisional when evidence is missing. For context,
  compare the corresponding Xert Recovery Load with Training Load. Use Xert
  target XSS as a model suggestion for comparison, never as the automatic prescription.
- Preserve XATA's `xss_deficit`, `xss_goal`, availability restriction,
  Improvement Rate, source, phase, and historical-day basis as planning
  context. `targetXSS`/`remainingXSS` is comparison data; never replace it with
  the larger deficit or describe the deficit as today's physiological need.
- When `is_availability_restricted` is true, say that the XATA planning dose is
  constrained by available time. Do not automatically schedule the difference
  to `xss_deficit`, and do not let XATA phase, focus, or suitability replace the
  active plan's selected intensity role or workout structure.
- Count completed activities through the earlier of the decision time and
  the planned start. Apply the same cutoff to rolling volume, XSS matches,
  the typical-day baseline and historical progression sessions. A workout in
  progress has yet to contribute its completed dose. Add the proposed
  remaining volume separately. For a historical replay use the plan state
  and source snapshots available at the time of the decision.
- Treat rolling seven-day totals as descriptive context. Do not use a historical
  percentile unless its metric, coverage period, complete-window count, and
  validation status are explicit. Never mix XSS with Intervals or Garmin load.
- Separate historical/cumulative load from acute physiological response. A
  normal load does not make mixed acute signals disappear.

## Preserve the origin of an adjusted dose

Select the dose explicitly from the session purpose, achieved progression,
recent response, current readiness and upcoming sessions. Pass
`--training-target-json` with `minutes`, `load`, `basis` (`duration` or `load`),
`reason` and a non-empty `evidence` list. Missing selection means dose assessment
is required; it must not produce a finished training recommendation.

For `basis: duration`, select minutes first and obtain `load` by calculating the
complete workout. Pass the complete native `calculate_strain` result in `--endurance-workout-json`
for endurance; the helper verifies that the duration is unchanged. For
`basis: load`, select total XSS and, for mixed workouts, `low_xss`; solve duration
for that selected low load. `minutes` is the expected duration, updated from the
solver. A solver result validates execution, not the reason for selecting a dose.

An endurance addition requires `endurance_extension: {reason, evidence}` in the
selection, justified separately from the quality workout. Without it, the
addition is zero. A gap to XATA advice is not a reason to add training.
For a duration-selected combined session, supply its complete fixed-duration
rows/signature/adjustable-row index through `--quality-workout-json` alongside
the separate quality-base calculation, and the complete combined calculation
through `--endurance-workout-json`. The helper checks the canonical timeline
against the selected total and the quality-base duration; it does not extend it.

Calculation binding is required at the recommendation CLI boundary. Supply
canonical rows/signature/adjustable-row index for a quality-only prescription.
For endurance-only work, pass `--endurance-workout-json` with both `calculation`
and an independent `structure` object containing `signature`, ordered `segments`
and `adjustable_segment_index`. Do not supply a planned quality-workout object
just to carry endurance structure. For a planned combined workout, the rows describe
the whole workout; the quality-base calculation must match the same structure
with only the adjustable endurance segment removed. For completed quality,
retain its original calculation inputs as historical evidence.

Pass the complete native `calculate_strain` or `solve_segment_duration` result,
including signature and ordered segments, unchanged inside `calculation`.
Summary-only live Calculate results cannot establish the input identity and are
not accepted as recommendation calculation evidence. The helper compares the
proposed structure with the result, permits only the selected solver segment's
duration to change, and independently recalculates XSS. Labels may change;
power, ramps, fixed durations, recovery segments, order and signature must match.
Use a fresh native calculation after changing these inputs. The output retains
`calculation_binding` with a fingerprint of the verified inputs.

Before passing a coaching-selected load or duration to a helper, state the
original XATA dose, the chosen dose and the concrete reason for the adjustment.
Explain why that amount fits the training purpose, including relevant evidence
against reducing it. Keep this rationale separate from the subsequent
calculation. A successful helper run verifies the proposed workout's modeled
load and execution; it does not independently establish that the selected dose
was necessary or optimal. In the final answer, retain coaching authorship of an
agent-supplied target even if a helper labels it explicit_user_or_cli_plan.

## Dose And Intensity

- Use readiness to set the intensity ceiling. Within that ceiling, use the
  resolved goal and progression history to select the concrete domain; recent
  same-family hard work can reduce the selection to VT1.
- Before selecting a quality dose, distinguish the achieved progression anchor
  from the latest reduced execution. Check whether the reason for a temporary
  reduction still applies today. Do not carry that reduction forward without
  current justification.
  A progression hold permits reassessing repetition of the achieved dose; it
  does not by itself require the most recent reduced dose. Preserve adverse
  recent responses as recovery evidence when reassessing the dose.
- Evaluate the marginal physiological value of the proposed dose in the context
  of recently completed training and its observed response. Do not subtract
  completed load from Xert `remainingXSS` again. A documented adverse response
  may nevertheless justify changing intensity or dose: name the response and
  explain its relevance today. Duration or XSS alone is not such a finding.
  Consider the actual intensity, duration, glycogen demand, mechanical work,
  local muscular response, and systemic response. Assess whether plausible
  residual effects, such as reduced carbohydrate availability, local muscular
  fatigue, or unresolved systemic or thermal strain, are likely to alter the
  execution of the next planned workout given its specific demands and the
  available recovery interval. Do not assume that a demanding workout must
  always be protected or that residual fatigue is acceptable before an easy
  workout. Use Garmin and Xert as supporting model evidence, not as substitutes
  for this physiological assessment.
- Do not use a predominantly low-XSS target split as evidence for choosing VT1
  over VT2. Both VT1 and subthreshold VT2 generate predominantly low XSS in
  Xert. Use high/peak XSS and the corresponding recovery only to reason about
  work over TP; distinguish VT1 from VT2 using readiness, the explicit training
  goal, progression history, recent stimulus, and the actual power prescription.
- Treat the recommendation packet as evidence. The final coaching decision must
  also account for goals, future sessions, logistics, weather, and body feel.
- For hard work, interpret the available direct signals together. Missing data
  limits confidence; conflicting observed signals need explicit resolution.
  Neither the absence of blockers nor complete data proves physiological readiness.
- When a relevant previous session was limited by breathing, legs or another
  observed response, place an execution check before the corresponding demand
  recurs. State what to assess and what changes if it recurs. A warm-up check or
  a later endurance check cannot replace a check before a problematic repetition.
- Inspect today's soreness before hard work. Missing soreness alone does not
  downgrade the session, but ask the user to record it; explicit zero counts as
  present.
- When cumulative load is normal but acute signals are cautious, prefer adding
  easy endurance duration over intensity when logistics and body feel permit.
- For long rides or deliberate late-session work, read
  [cycling-endurance-physiology.md](cycling-endurance-physiology.md). Treat fresh
  zone and threshold anchors as starting-state values: prescribe late-session
  intensity conservatively enough to accommodate possible durability loss, and
  require repeated matched evidence before creating a personal durability rule.
- Protect quality and long-session execution with adequate carbohydrate unless
  low availability is an explicit plan intervention. Do not prescribe `train
  low` automatically for easy training, and do not treat an omitted dose as
  carbohydrate or training debt to be repaid later.
- Treat planned heat exposure as an additional stress with an explicit purpose,
  dose, cooling choice, hydration plan, and stop conditions. Do not infer heat
  adaptation merely from completing a hot session.
- If offering a dose beyond a helper guardrail, label it as a conditional
  coaching override and use the configured breathing/HR/body-feel gate,
  defaulting to 15 minutes.
- Keep model-specific recovery, target-load, and capacity concepts distinct.
  Use source semantics rather than re-explaining private-model formulas here.
- Resolve the plan role and concrete workout format before converting each
  candidate's explicitly selected load to duration. For recovery, VT1, or a quality workout
  with a flexible endurance extension, describe the complete workout once as
  canonical Xert `rows` together with the current `signature` and exactly one
  `adjustable_row_index` inside `--quality-workout-json` for quality/composed
  work. Endurance-only work uses `structure` inside `--endurance-workout-json`
  as described above. With
  `--print-endurance-solver-request`, the helper expands repetitions, RIB, and
  ramps, uses the coach-selected Low-XSS target, and prints the
  MCP request. The quality-workout object also accepts the optional fields
  `minimum_duration_seconds`, `maximum_duration_seconds`, and `tolerance_xss`.
  Before choosing VT1 minutes, run `scripts/vt1_dose.py` with Python,
  `--role easy_aerobic|medium_aerobic|long_aerobic|vt1` and `--as-of` set to
  the decision cutoff with UTC offset. Use the plan state supplied for the
  recommendation. Pass `--watts` when today's chosen working power differs.
  Use `--activity-id` to examine a specific older ride of the same purpose.
  The output gives the three latest reviewed rides of that purpose, moving
  time, measured minutes in the stated power band, valid power time, athlete
  feedback and the next recorded quality outcome when available. Compare the
  late response separately from whole-ride RPE. A later quality result gives
  context and cannot establish the effect of the earlier ride on its own.
  Explain why today's role, response and upcoming quality favor repeating,
  shortening or extending the selected comparison. If none fits, explain the
  independent basis for the dose. Mixed-sport daily medians describe volume.
  In `--training-target-json`, set `vt1_role` if the queue does not specify
  today's aerobic purpose. When candidates exist, supply
  `"vt1_comparison":{"activity_id":"…","reason":"…"}`, omitting the ID only
  when the reason explains why none is representative.
  Use `progression.vt1.target_power_w` for the main step. To select another
  power, supply `"vt1_power_choice":{"watts":…,"reason":"…","evidence":["…"]}`.
  For a load-selected VT1 ride, pass the independent structure to print the
  solver request. Call MCP `solve_segment_duration` with that request. For
  the final run, include both `structure` and the full native `calculation`
  in `--endurance-workout-json`. A quality workout can instead supply its
  independent structure through the quality rows described above.
  Preserve fixed quality, warm-up, recovery, and cool-down segments. Never derive prescribed duration from
  XSS/minute across activities of mixed intensity domains, and never add
  high/peak work merely to match high/peak advice on a plan-selected VT1 day.
- For a structured quality session followed by easy volume, calculate the
  complete quality workout with MCP `calculate_strain`, including warm-up,
  recoveries, and cool-down, and pass its normalized result directly
  inside `--quality-workout-json` with status `planned` or `completed`. Preserve
  the complete native result rather than reducing it to a metrics summary. If the
  calculation is persisted, read the file first and pass its JSON content. For
  a flexible VT1 addition, explicitly justify and select the combined dose.
  Without a justified addition, prescribe only the complete quality workout.
  Do not fill the difference to XATA advice or automatically cap it to model
  recovery capacity. Use MCP
  `solve_segment_duration` with the current Fitness Signature and complete
  workout structure to convert the resulting Low-XSS dose to VT1 duration. The
  summary must show Xert's original recommended dose, the chosen daily target,
  complete quality-workout XSS, VT1 filler, expected total, and any
  calendar-limited shortfall in both minutes and estimated XSS. If no explicit
  available windows were supplied, say that calendar fit was not verified.
  Briefly justify the quality dose from plan/progression and the endurance
  addition from current response, dose and upcoming training separately.
  Retain the calculated dose when no concrete constraint justifies changing it;
  a low recent volume density alone does not justify extra training.
- Treat the complete calculated quality workout—including warm-up, work
  intervals, recoveries, and cool-down—as indivisible for scheduling. Move it
  intact to a later candidate window when necessary; never split, truncate, or
  distribute it across windows. If no window can contain it, report an explicit
  calendar conflict. A calendar-driven quality modification means choosing a
  different complete quality workout or an explicit downgrade, never shortening
  or splitting the selected quality work. For continuous filler, use the complete
  canonical solver timeline, including the explicitly placed final cool-down.
  `quality_base` and `vt1_filler` are load-accounting groups, not execution order.
  Present `primary_decision.executable_now.timeline` when complete; do not move
  or duplicate segments to match accounting labels. If filler is a separate session, include the easy ramp-in and
  easy finish inside the allocated VT1 minutes; do not add uncounted warm-up or
  cool-down time. Split guidance must name the quality domain for the first
  session and VT1 for the remainder, never describe both as easy VT1.
- On an endurance-only day, or for the flexible VT1 portion after an intact
  quality workout, consider multiple windows only after no single candidate
  window fits the complete applicable dose. Recalculate every separate
  endurance session with its own warm-up and cool-down, and allocate the
  sessions chronologically across the explicit available windows. Emit
  structured sessions and segments with start, end, role, minutes, and
  estimated XSS. Do not create a standalone VT1 session shorter than the
  configured minimum, defaulting to 30 minutes; leave a smaller dose explicitly
  unscheduled unless it can be contiguous with the quality workout. Report the
  true remaining shortfall in both minutes and estimated XSS after all windows
  have been evaluated.
- When the user explicitly requests a split, pass `split_preference` with
  `first_session_minutes` and an offset-aware `second_session_start`. For a
  solved VT1 structure, repeat the fixed easy start and finish around the second
  session and solve its adjustable endurance segment again; do not mechanically
  divide the unsplit duration.
- For composed sessions, expose executable quality and VT1 portions as separate
  `primary_decision.executable_now.segments`. The summary must render those
  segments, for example `53 min VO2MAX quality workout + 207 min VT1`; never
  label the complete composed duration as VO2max.
- On a same-day rerun after partial completion, prefer Xert `remaining_xss`
  over `target_xss`; preserve original and completed XSS for audit display and
  never subtract completed activity locally again. If the calculated quality
  workout has been verified as completed, pass
  `status: completed` inside `--quality-workout-json`. Keep its calculated metrics as evidence,
  but exclude its duration and XSS from the remaining plan. Use MCP
  `solve_segment_duration` with the current Fitness Signature and complete
  remaining VT1 structure to convert the newly selected remaining load to VT1
  duration. Completed quality never creates an automatic endurance addition.

### Xert workout feasibility

For an ordinary designed quality workout, keep the plan responsible for the
training role and progression. When the selected Fitness Signature and complete
power structure are already known, use Xert MCP `calculate_strain` to estimate
low/high/peak XSS, Difficulty, Focus, MPA reserve, and feasibility. This
calculation does not fetch Xert data.

Use Xert MCP `calculate_workout` only when current Xert state, workout-row
resolution, or server-authoritative summary totals are required. Do not fetch a
verbose Calculate series merely to reproduce locally available model fields.

- Accept `P < MPA` as the modeled feasibility domain and report the minimum
  positive reserve when it informs pacing or confidence.
- If any sample reaches `P >= MPA`, revise or reject the ordinary workout rather
  than treating Calculate's continued XSS as executable load. A deliberate
  maximal test requires explicit user intent.
- Use Calculate's compact summary as the authoritative planned XSS/Difficulty
  dose even when the exposed series has a small integration residual.
- Do not infer a breakthrough or a new Fitness Signature from a hypothetical
  Calculate crossing.
- Report the Xert strain result as model mechanics, then state the selected
  training domain separately from plan intent, power prescription, progression,
  and readiness. Do not let the dominant XSS system choose the domain.

## Capacity Before The Next Day's Workout

For every training recommendation, calculate and show how much training can be
performed at the recommended `planned_at` while still reaching Xert's fresh
boundary for the next day's workout. Keep this recovery-protection capacity
separate from XATA's recommended daily dose and from the final coaching dose.

The active plan and coaching assessment select the domain, structure and dose.
Xert advice and recovery capacity are separate model comparisons, not automatic
targets or limits. Calculate the selected complete structure with the current
Fitness Signature. If the next role is not explicit
in state, derive it only from an unambiguous active-plan queue; otherwise label
the capacity protection unresolved.

- Compare the actual complete workout's Low/High/Peak XSS with each corresponding
  model capacity. Report a conflict without changing the selected dose.
- Resolve a conflict explicitly: reduce the selected dose and recalculate;
  move the next workout and recalculate capacity for its new start; or justify
  why the model conflict is accepted. Pass `capacity_decision` with `action`
  (`reduce_dose`, `move_next_workout`, or `accept_model_conflict`), `reason`, and
  `evidence`. The first two require a new calculation demonstrating the conflict
  is resolved; a declaration alone is insufficient. Unresolved conflicts block
  a finished recommendation. Accepting one is a coaching decision, not evidence
  that Xert predicts freshness or that physiological readiness is guaranteed.

- Resolve the next day's plan role from the active plan and authoritative
   `config/plan-state.json`. Do not invent the next role from Xert advice.
- Resolve the next day's exact practical workout start from explicit user
   input or calendar context. Apply the configured earliest start, fixed-event
   conflicts, setup buffer, and the user's open/tentative/movable-event rules.
   Never run a capacity calculation against an unspecified horizon.
- Use Xert MCP `calculate_workout_capacity` with a fresh live state for every
   candidate. Set `as_of` to that candidate's start and `fresh_at` to the next
   workout's resolved start. The result is three
   independent fresh-boundary capacities—Low, High, and Peak XSS—not three
   additive workout quotas.
- Persist the complete `calculate_workout_capacity` `structuredContent`
   unchanged and pass it as `xert_workout_capacity` in
   `--source-overrides-json`. The helper compares capacity with the selected
   complete workout and requires a decision on conflicts. It does not copy
   capacity into the selected dose or change the solver target.
- Independently supply `next_workout_at` as an offset-aware timestamp in
   `--planning-context-json`, resolved from the actual plan/calendar rather than
   copied from the capacity result. The helper requires all three capacities to
   be finite nonnegative numbers and compares `as_of`/`fresh_at` in UTC with
   today's effective start and the next planned start. Moving either workout
   requires recalculation. Scheduling today's session into a later window also
   triggers this check before the final recommendation.
- If exact scheduled projection is unavailable and an equivalent-horizon
   approximation is justified, pass `capacity_approximation: {reason, evidence}`
   in the planning context. Both calculated timestamps may be shifted only if
   their interval exactly matches the planned recovery interval. The report
   labels this as an approximation; documentation cannot waive a changed interval.
- Align the capacity horizon with the interval from today's recommended
   `planned_at` to the next day's resolved workout start. When the current Xert
   state timestamp materially precedes today's `planned_at`, do not silently
   treat a capacity calculated at the current timestamp as exact. Use an exact
   scheduled-impulse projection when the source tooling supports it; otherwise
   shift the capacity horizon to preserve the same recovery interval and label
   the result an equivalent-horizon approximation. State the planned timestamps
   and the no-intervening-training assumption.
- Select the limiting system for the actual proposed workout and next-day
   role. A VT1 workout is normally constrained by Low XSS; a quality workout
   must be compared with every Low/High/Peak system it actually generates. Do not combine
   the independent capacity values into an arbitrary realizable XSS split.
- Convert the applicable capacity to duration only through the same current
   Fitness Signature and complete proposed workout structure used for the
   recommendation. For adjustable endurance, use Xert MCP
   `solve_segment_duration`; for fixed quality, calculate the complete structure and
   compare its Low/High/Peak XSS with the corresponding capacities. Never use a
   mixed-history XSS-per-minute ratio.
- Present both values explicitly:
   - `Recommended dose`: the final coaching prescription;
   - `Maximum compatible with next-day Xert freshness`: duration,
     watts/structure, limiting
     XSS capacity, next workout role, and next workout start.
   Also show the selected dose's reason and evidence, XATA suggestion, difference
   from that suggestion, and any capacity conflict with its explicit decision
   and consequences for the next session. Neither automatic filling nor an
   automatic cut follows from these comparisons.

Use `Capacity before the next workout` as the canonical section label and
translate it into the user's language. Explain that Xert's
fresh boundary is a model result rather than a guarantee of whole-body or
subjective readiness, so the next day's sleep, direct readiness signals,
soreness, and body feel must still gate quality work.

Use `planning-context.json` beside the recommendation packet only when an
auditable trace of resolved logistics is useful. It is LLM-authored context,
not a helper input contract.

## Candidate Selection

If local coaching preferences identify preferred indoor workouts by text in
their names, pass that text as `cycling.preferred_workout_name_contains` in
`--planning-context-json`. Matching ignores case. Rank all suitable workouts
by fit when there is no preference or no suitable match.

For `rest`, retain only rest or explicit recovery candidates within the cap.
For `easy_vt1`, retain recovery/endurance candidates within duration and load.
Suppressed harder workouts remain audit context, not normal options.

For every outdoor route candidate, keep calendar fit and dose fit separate.
Report the route's expected duration against the prescribed duration, the exact
shortfall or excess, and whether execution requires an extension, added VT1
time, shortening, or a turnaround. A route that fits inside an available window
does not thereby cover the prescribed training dose.

Also use expected route duration as a moderate ranking input when prescribed
duration is known. It may break ties between otherwise comparable routes, but
must not override a material surface mismatch or poor steady-endurance terrain.

Expose projected 14- and 21-day moving-time density after adding the selected
dose. Compare it with the active plan's or personal context's configured density
target. This is diagnostic evidence, not an automatic duration cap.

Use an existing suitable workout as-is when it fits; modify power, duration, or
repetitions only for a concrete readiness, time, load, or specificity reason.
Do not add warm-up outside a workout whose total already includes it.

## Recommendation Artifacts

For normal interactive recommendations, use separate unique private
`--output-dir` directories under `/private/tmp` for each candidate and the final
run. Write temporary source snapshots and intermediate data using ordinary file
I/O rather than `apply_patch`, so they do not generate Codex file-change cards.
Write persistent artifacts under `outputs/` only when explicitly requested or
required by an automation or later analysis. Do not link JSON packets in a
normal recommendation.

## Final Answer Contract

- A complete recommendation requires a successful `recommend_training.py`
  run and a valid recommendation packet for the requested date. If the helper
  fails, correct the input, source-persistence, or refresh problem and rerun it;
  do not silently bypass the helper and compose an ordinary recommendation
  directly from the source payloads. If a valid packet still cannot be
  produced after safe in-scope recovery attempts, stop and report the concrete
  blocker instead of issuing the recommendation.
- Follow `primary_decision.action` and `primary_decision.executable_now` as the
  default recommendation. Treat `remaining_after_completed_activities` as a
  remaining dose whose same-day activities are already accounted for; never
  subtract them again. Do not schedule an `unscheduled_remainder` without a real
  available window. If specific evidence justifies a different recommendation,
  label it as a coaching override and explain what the model decision did not
  account for. Relevant adverse response can already appear as narrative context
  in the packet; do not require it to be newly discovered or subtract load again.
- Start with the recommended session and best time. Include duration, warm-up,
  watts/intensity, route or setup, and practical fueling. Include only modalities
  available at the resolved location.
- Before sending, check the prescription against
  `primary_decision.executable_now.timeline`: write its segments in execution
  order, including the final cooldown after continuous filler. Accounting-group
  durations must not become separate sessions or introduce extra ramp-in/out.
  Show the computed total and its end time; distinguish an outdoor route's
  reference time from the prescribed duration and state any extension/shortfall.
  Explain what the quality work and additional aerobic volume each contribute;
  matching a model dose is not by itself a training-purpose explanation.
- Include a separate `Capacity before the next workout` section, translated into
  the user's language, following the capacity workflow above. Show the next
  workout role and exact start, limiting Low/High/Peak XSS capacity, and its
  conversion through the proposed structure to duration and watts. Keep this
  maximum distinct from the recommended dose.
- Present all three layers below as separate, named parts of every
  recommendation; reporting only the final session is not sufficient:
  - `Physiological scope`: report the model screening ceiling from
     `primary_decision.intensity_decision.readiness_ceiling` and the decisive
     direct recovery signals, together with `primary_decision.readiness_evidence`.
     Distinguish no observed restriction from evidence supporting recovery;
     never translate the ceiling into a guarantee of physiological readiness.
  - `Training need`: report what the resolved goal, progression history,
     and recent training load indicate. Use the reviewed plan state's
     `next_role`, `last_quality_session` and `aerobic_days_since_quality`
     for quality spacing. Historical candidates provide execution context.
     Use the requested goal, progression status and next step to explain the dose. Name the selected active
     plan and current plan role. If no applicable plan exists, state that the
     training need is unresolved instead of presenting a generic helper goal as
     a plan.
  - `Final recommendation`: report `selected_domain` plus the concrete duration,
     watts, structure, and route/setup after combining the first two layers with
     logistics, weather, and body feel.
  Translate these canonical labels into the user's language and always use the
  same translated wording in this order.
  Explicitly state when the physiological ceiling is higher than the selected
  plan. Explain why the final domain is preferable to the next harder and easier
  domain. These three parts are required even when readiness, load, or the
  recommendation has already been discussed elsewhere in the answer.
- If both cycling modalities are available, provide the selected winner and one
  concrete alternative, each with duration, warm-up, watts/intensity,
  setup/route, and countable fueling actions. State why the winner is preferred.
  If the alternative changes the plan role, state which quality role remains
  queued. A longer VT1 alternative is not a replacement quality stimulus.
  Give drink carbohydrate per bottle, number of bottles/refills, and countable
  food portions with their combined approximate grams/hour. Use known product
  values from personal context or source data; if unavailable, name the product
  assumption and give a grams-based portion, not an invented scoop or candy size.
- When outdoor riding is an option, apply the
  [route weather and road condition checks](outdoor-routes.md#weather-clothing-and-presentation)
  before choosing between indoor and outdoor training.
- Explain briefly why the winner fits readiness, recent load, weather, calendar,
  goals, and reported body feel.
- When presenting Garmin Training Effect, preserve the numeric aerobic and
  anaerobic values plus the label and write it as a modeled expectation, for
  example: "Garmin estimates the primary stimulus as anaerobic capacity." Do
  not write that the session improved VO2max, threshold, tempo, speed, or
  anaerobic capacity as an observed fact; later performance and progression
  evidence are required to establish adaptation.
- Use `recommendation_inputs.wellness.garmin_decision_evidence` and
  `garmin_signal_status` to distinguish available observations from missing data.
  Do not restore excluded raw values as negative signals. A sync attempt that
  still leaves sleep unavailable does not itself justify reducing training.
  If direct recovery data remain missing, explicitly ask the user to sync their
  device before training (unless already attempted), and ask for soreness/body
  feel when unknown. Keep the recommendation provisional without an automatic
  missing-data dose cut.
  Observed values still need comparison and context; availability is not an
  adverse finding or confirmation of good recovery.
- For Garmin timer arithmetic, use the readiness helper's
  `garmin_recovery_readiness.recovery_time_projection`. It keeps observation
  time and hours together with `planned.target_at`, elapsed hours, remaining
  hours and availability. Use `planned.remaining_hours` directly when status
  is `projected`; do not redo the countdown or substitute the now-value.
  If no valid projection is available, retain the uncertainty.
- When presenting Garmin Recovery Time, state that it estimates time to modeled
  full recovery for the next hard workout. Do not present it as required rest
  before all activity, and do not infer a Recovery Time value from Training
  Effect. Interpret the reported/projected value with direct readiness, recent
  session cost, body feel, and the planned intensity.
- Keep the chosen prescription distinct from reference watt anchors for other
  zones.
- State whether timing was user-provided or assumed and identify stale/missing
  inputs that materially limit confidence.
