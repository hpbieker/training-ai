# Daily Training Recommendations

## Resolve Context First

Before running helpers, resolve the local date, planned start or free window,
location/start anchor, available modalities, surface/bike intent, target event
and time horizon, and practical fueling defaults. Use the configured earliest
start and workout-placement preference when no time is supplied; if calendar
context exists, select a practical window that satisfies them. Resolve modality availability
from explicit user input or personal context, never from the repository.

When calendar context is used, classify events before calculating availability.
Apply the user's calendar semantics from personal context rather than treating
every returned event as a hard blocker. Keep confirmed/fixed appointments
blocking. Treat user-defined open blocks and tentative events as non-blocking,
and treat movable meal events as requirements that need practical time around
the workout rather than fixed-time blockers.

Before finalizing a calendar-backed workout time, run these checks:

- Resolve the user's setup and cleanup buffers from personal context, and test
   calendar availability against the complete occupied window: setup, workout,
   and cleanup. Keep the displayed workout start and duration distinct from the
   buffers.
- Verify that the workout was not delayed solely by an event that personal
   context defines as open, tentative, or movable.
- If the selected workout overlaps or otherwise relies on disregarding a
   tentative event, show a concise warning with the event's subject/title and
   scheduled time. Never replace the event name with only a generic phrase such
   as "tentative meeting".
- If selecting the workout requires moving a meal, state that assumption and
   preserve a practical meal window.
- Preserve the meal's scheduled duration when moving it is sufficient. If
   personal context permits shortening a meal, use that only when a concrete
   hard stop or explicit time constraint makes the normal duration impractical.
   State the shortened duration, name the constraint, and explain why moving the
   full-duration meal is insufficient.
- Calculate post-workout slack from the end of the cleanup buffer to the next
   confirmed fixed appointment. Show the slack, the appointment's subject/title
   and time, and label it as the hard stop. If no later hard stop exists in the
   planning day, state that explicitly.
- Compare the selected training dose with the usable window after setup and
   cleanup buffers. If the full dose does not fit, always show:
   - intended duration/dose;
   - maximum executable duration/dose;
   - the exact shortfall;
   - the named hard stop or other concrete constraint;
   - whether the remainder is dropped, moved, or conditionally split.
   Also show the smallest calendar change that would make the full dose fit:
   name every affected meeting/appointment, show its scheduled time, and state
   the required movement or alternative workout window. Present this as an
   optional resolution, not an assumed calendar mutation.
   For each proposed meeting move, give a concise movability estimate grounded
   in the user's personal calendar heuristics and available attendee data. Name
   the number of other participants used for the estimate. If attendee data is
   missing or incomplete, label the estimate uncertain.
   When applying a configured event-compatibility exception, name the event and
   time, show the evidence supporting the classification, and state the
   assumption explicitly.
   Do not silently compress or schedule an unexecutable remainder, and split a
   session only when doing so preserves its physiological purpose.
- Distinguish verified calendar conflicts from assumptions; do not describe a
   non-blocking event as unavailable time.

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

For every agent-driven recommendation, call the existing
`build_planning_context()` function programmatically and pass its validated
return value to `recommend_training.py`; never hand-author
`--planning-context-json`. Before calling it, derive `planned_at` and the
availability windows from the freshly read calendar by applying the configured
start boundary and workout-placement preference, classifying fixed, open,
tentative, and movable events, and applying the complete setup, workout, and cleanup window.
An existing calendar event that appears to reserve time for training is
calendar evidence, not an automatic choice of `planned_at`; select its start
only when the same placement calculation supports it.

Discover active files under `config/plans/` through the repo-local
`training-plan` skill and read `config/plan-state.json` before choosing
`intensity_goal` inside `--plan-selection-json`. Run `python3 -B scripts/plan_state.py pending`; inspect,
classify, and apply every newer activity chronologically before using the
state. Decide the day's plan role and translate it explicitly to `recovery`,
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

Fetch Intervals.icu wellness and calendar events through MCP `list_wellness`
and `list_events` before invoking the helper. Persist each complete MCP result
as normalized JSON and pass the paths as `intervals_wellness` and
`intervals_events` in `--source-overrides-json`. `recommend_training.py` must
not import the Intervals transport or invoke its CLI.

Apply the same persistence boundary to every live MCP result used as a source
override: write the result's `structuredContent`, without the surrounding MCP
transport envelope, to a date-scoped private temporary JSON file, build the
complete `--source-overrides-json` map from those paths, and verify that every
required override file exists before invoking `recommend_training.py`. Do not
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

For a complete recommendation, fetch Xert advice explicitly from the
planned-time `recommended-training` source, even when `planned_at` is close to
`now`. The faster current `/my-fitness` source does not expose the availability,
deficit, and progression fields required to explain the XATA planning dose.

## Capacity Before The Next Day's Workout

For every training recommendation, calculate and show how much training can be
performed at the recommended `planned_at` while still reaching Xert's fresh
boundary for the next day's workout. Keep this recovery-protection capacity
separate from XATA's recommended daily dose and from the final coaching dose.

The active plan selects the domain and structure; Xert `remainingXSS` (or
`targetXSS` before any same-day activity) is the dose input. Treat the
applicable recovery-protection capacity as the default upper limit. Direct
readiness evidence may impose an explicit lower cap, but aggregate Garmin
Training Readiness or Garmin Recovery Time alone must not do so. Do not replace
the resulting XSS dose with an agent-rounded duration: solve the complete
structure with the current Fitness Signature. If the next role is not explicit
in state, derive it only from an unambiguous active-plan queue; otherwise label
the capacity protection unresolved.

- Resolve the next day's plan role from the active plan and authoritative
   `config/plan-state.json`. Do not invent the next role from Xert advice.
- Resolve the next day's exact practical workout start from explicit user
   input or calendar context. Apply the configured earliest start, fixed-event
   conflicts, setup buffer, and the user's open/tentative/movable-event rules.
   Never run a capacity calculation against an unspecified horizon.
- Use Xert MCP `calculate_workout_capacity` with a fresh live state. Set `as_of`
   to today's recommended start and `fresh_at` to the next workout's resolved
   start. The result is three
   independent fresh-boundary capacities—Low, High, and Peak XSS—not three
   additive workout quotas.
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
   must respect every Low/High/Peak system it actually generates. Do not combine
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
   If the recommended dose exceeds the recovery-protection capacity, reduce the
   final recommendation or explicitly state that the next-day quality session
   is no longer protected.

Use `Capacity before the next workout` as the canonical section label and
translate it into the user's language. Explain that Xert's
fresh boundary is a model result rather than a guarantee of whole-body or
subjective readiness, so the next day's sleep, direct readiness signals,
soreness, and body feel must still gate quality work.

Use `planning-context.json` beside the recommendation packet only when an
auditable trace of resolved logistics is useful. It is LLM-authored context,
not a helper input contract.

## Readiness Composition

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
  Readiness forward as if they were observations for the future date.
- Use Xert recovery hours as the first model gate for low/high/peak load, then
  compare the corresponding Xert Recovery Load with Training Load. Use Xert
  target XSS as the remaining recommended dose when available.
- Preserve XATA's `xss_deficit`, `xss_goal`, availability restriction,
  Improvement Rate, source, phase, and historical-day basis as planning
  context. `targetXSS`/`remainingXSS` is the dose input; never replace it with
  the larger deficit or describe the deficit as today's physiological need.
- When `is_availability_restricted` is true, say that the XATA planning dose is
  constrained by available time. Do not automatically schedule the difference
  to `xss_deficit`, and do not let XATA phase, focus, or suitability replace the
  active plan's selected intensity role or workout structure.
- Treat rolling seven-day totals as descriptive context. Do not use a historical
  percentile unless its metric, coverage period, complete-window count, and
  validation status are explicit. Never mix XSS with Intervals or Garmin load.
- Separate historical/cumulative load from acute physiological response. A
  normal load does not make mixed acute signals disappear.

## Illness And Return

A structured current-day sickness event overrides model readiness: recommend no
training. If only the previous day is marked sick, ask whether symptoms remain
or this is the first healthy day; until clarified, offer rest or a provisional
very-easy return only.

Unless personal context defines another return protocol, default to two
intensity-free return days after the last sick day: day one is rest or 20–45
minutes very easy; day two is 30–60 minutes easy endurance. Cap candidate
duration/load to that ramp rather than merely describing it. Resume normal logic
from day three only if the athlete feels healthy.

## Dose And Intensity

- Use readiness to set the intensity ceiling. Within that ceiling, use the
  resolved goal and progression history to select the concrete domain; recent
  same-family hard work can reduce the selection to VT1.
- Do not use a predominantly low-XSS target split as evidence for choosing VT1
  over VT2. Both VT1 and subthreshold VT2 generate predominantly low XSS in
  Xert. Use high/peak XSS and the corresponding recovery only to reason about
  work over TP; distinguish VT1 from VT2 using readiness, the explicit training
  goal, progression history, recent stimulus, and the actual power prescription.
- Treat the recommendation packet as evidence. The final coaching decision must
  also account for goals, future sessions, logistics, weather, and body feel.
- A hard session requires agreement across the important direct signals; stale
  or conflicting data should reduce confidence before increasing intensity.
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
- Resolve the plan role and concrete workout format before converting Xert
  dose to duration. For recovery, VT1, or a quality workout with a flexible
  endurance extension, pass the current Xert signature, complete segment
  structure, and exactly one marked adjustable sub-TP segment through
  `recommend_training.py --endurance-structure-json`. The recommendation
  helper resolves the applicable post-guardrail low-XSS target and runs the
  offline endurance solver internally. The structure object accepts exactly
  `signature`, `segments`, `adjustable_segment_index`, and the optional fields
  `minimum_duration_seconds`, `maximum_duration_seconds`, and `tolerance_xss`;
  do not pass MCP-only names such as `absolute_tolerance`. Use
  `--endurance-workout-json '{"calculation": <normalized-result>}'` instead
  when an already calculated MCP or CLI solver result must be replayed exactly;
  the two inputs are mutually exclusive. Preserve fixed quality, warm-up,
  recovery, and cool-down segments. Never derive prescribed duration from
  XSS/minute across activities of mixed intensity domains, and never add
  high/peak work merely to match high/peak advice on a plan-selected VT1 day.
- For a structured quality session followed by easy volume, calculate the
  complete quality workout in Xert, including warm-up, recoveries, and
  cool-down, and pass the compact `workout-calculate --summary` JSON directly
  inside `--quality-workout-json` with status `planned` or `completed`. If the
  calculation is persisted, read the file first and pass its JSON content. Fill
  only the difference between the
  daily total-XSS target and the calculated complete-workout XSS. In the
  minimal model, estimate VT1 at 60 XSS/hour and expose that assumption in the
  packet. The summary must show Xert's original recommended dose, the chosen
  daily target, complete quality-workout XSS, VT1 filler, expected total, and
  any calendar-limited shortfall in both minutes and estimated XSS. If no
  explicit available windows were supplied, say that calendar fit was not
  verified.
- Treat the calculated quality workout as indivisible for scheduling. Its
  duration and XSS already include warm-up, work intervals, recoveries, and
  cool-down. If VT1 filler is continuous, start it after the calculated
  quality workout. If it is a separate session, include the easy ramp-in and
  easy finish inside the allocated VT1 minutes; do not add uncounted warm-up
  or cool-down time. Split guidance must name the quality domain for the first
  session and VT1 for the remainder, never describe both as easy VT1.
- Allocate divisible VT1 chronologically across every explicit available
  window, checking the actual capacity of each window. Emit structured
  sessions and segments with start, end, role, minutes, and estimated XSS.
  Do not create a standalone VT1 session shorter than the configured minimum,
  defaulting to 30 minutes; leave a smaller dose explicitly unscheduled unless
  it can be contiguous with the quality workout. Report the true unscheduled remainder after all windows have been
  evaluated, rather than assigning the whole remainder to the second window.
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
  but exclude its duration and XSS from the remaining plan and convert the
  entire Xert remaining dose to VT1 at 60 XSS/hour.

### Xert workout feasibility

For an ordinary designed quality workout, keep the plan responsible for the
training role and progression. When the selected Fitness Signature and complete
power structure are already known, use Xert MCP `calculate_strain` to estimate
low/high/peak XSS, Difficulty, Focus, MPA reserve, and feasibility. This
calculation does not fetch Xert data.

Use Xert MCP `calculate_workout` only when current Xert state, Designer row
resolution, or server-authoritative summary totals are required. Analyze an
existing verbose Calculate series with `xert_calculate_analyze.py`; do not fetch
the same series again merely to reproduce locally available model fields.

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

## Candidate Selection

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
  available window. If new information justifies a different recommendation,
  label it as a coaching override and state which packet input did not cover it.
- Start with the recommended session and best time.
- Present all three layers below as separate, named parts of every
  recommendation; reporting only the final session is not sufficient:
  - `Physiological scope`: report the readiness ceiling from
     `primary_decision.intensity_decision.readiness_ceiling` and the decisive
     direct recovery signals. Describe what intensity is physiologically
     allowed without treating it as the planned intensity.
  - `Training need`: report what the resolved goal, progression history,
     and recent same-family stimulus/load indicate. Ground this in
     `requested_goal`, `progression_status`, `progression_next_step`,
     `latest_same_family_date`, `days_since_same_family`, and the packet's recent
     load evidence when those fields are available. Name the selected active
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
- If both cycling modalities are available, provide one concrete indoor and one
  concrete outdoor option with duration, warm-up, watts/intensity, setup/route,
  and countable fueling actions.
- Explain briefly why the winner fits readiness, recent load, weather, calendar,
  goals, and reported body feel.
- When presenting Garmin Training Effect, preserve the numeric aerobic and
  anaerobic values plus the label and write it as a modeled expectation, for
  example: "Garmin estimates the primary stimulus as anaerobic capacity." Do
  not write that the session improved VO2max, threshold, tempo, speed, or
  anaerobic capacity as an observed fact; later performance and progression
  evidence are required to establish adaptation.
- When presenting Garmin Recovery Time, state that it estimates time to modeled
  full recovery for the next hard workout. Do not present it as required rest
  before all activity, and do not infer a Recovery Time value from Training
  Effect. Interpret the reported/projected value with direct readiness, recent
  session cost, body feel, and the planned intensity.
- Keep the chosen prescription distinct from reference watt anchors for other
  zones.
- State whether timing was user-provided or assumed and identify stale/missing
  inputs that materially limit confidence.
