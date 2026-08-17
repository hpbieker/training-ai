# Xert Field Semantics

## Recovery And Advice

For the conceptual model, projection equations, signature response, and the
workflow for solving required XSS, read
[training-load-model.md](training-load-model.md). This file remains the field
interpretation and edge-case authority.

For source provenance and the boundary between official product semantics and
locally validated behavior, read [sources.md](sources.md).

- `recovery.recovery_hours` is the recovery state at `source_time_local`.
- `recovery.recovery_hours_at_advice_time` projects that state to the requested
  time by subtracting elapsed time and assuming no intervening training.
- Express recovery in hours. Zero is Xert's fresh threshold; negative values
  are on the fresh side of that threshold.
- Treat positive low-system recovery hours as the first gate against more
  cycling load. Use high and peak recovery hours to judge readiness for work
  over threshold power (TP).
- Do not use per-activity `summary.progression.rl` as current Recovery Load.
- `recovery_offset` is the current Recovery Demands model input. A larger value
  is more conservative and lengthens modeled recovery; a smaller value permits
  earlier modeled recovery. Do not apply the opposite direction described for
  the older `Freshness Feedback` control.
- Status and Form summarize recorded cycling load, not how the athlete feels or
  complete whole-body readiness. Gaps in power/XSS history can underestimate
  TL and distort status; non-cycling load needs separate context.

For historical modeling, Fitness Measures rows hold the pre-activity TL/RL
state and that row's activity XSS. Apply the previous row's XSS impulse, then
decay over the exact elapsed time. The per-system EWMA gain is
`1-exp(-1/tau)`. Forecast-AI Recovery Load is capped after decay:

```text
RL = max(classic_EWMA_RL, TL*exp(-1/tau_RL))
```

The `ftp-cap`, `hie-cap`, and `pp-cap` fields expose this floor.

For completed activities, the impulse timestamp is the activity start. Exact
start-to-start recurrence reproduces all historical TL/RL transitions within
the validation tolerance; neither activity end nor upload time is the model
timestamp.

For future scenarios, decay the current state to the explicit workout time,
apply the system-XSS impulse there, then decay to the requested projection
horizon. Do not describe an impulse applied at the start as occurring at the
horizon.

`training_advice.target_xss` maps Xert `targetXSS`: `xlss` to `low`, `xhss` to
`high`, and `xpss` to `peak`. It is Xert's recommended dose for the advice
context and already reflects activity Xert has accounted for. It is not a
recovery target, historical activity load, workout-library XSS,
`workout_capacity`, or a caller-calculated remaining dose.

Treat `targetXSS` as XATA's constrained planning/progression dose. It can be
lower than `xss_deficit` when available time restricts the recommendation, so
it is not the total deficit, physiological need, maximum absorbable dose, or a
recovery prescription. Preserve `xss_deficit`, `xss_goal`, `availability`,
`is_availability_restricted`, Improvement Rate, `targets_source`,
`training_advice_as_of`, `based_on_day`, phase, and focus when available.

XATA's rolling historical window can make deficit change abruptly when an old
activity leaves the comparison period. Do not tell the athlete to chase a zero
deficit; interpret the target together with Xert's current progression and
on-track context.

Workout suitability labels are relative to the requested XSS, Difficulty, and
Focus. `Productive` therefore means suitable for Xert's improvement target, not
proven superior adaptation. `XSSR Preference` controls how densely XSS is
delivered within available time; it is neither Difficulty Score nor readiness.

Planned-time advice may also include `remaining_xss`, `completed_xss`,
`original_target_xss`, `training_advice_as_of`, availability, and daily-goal
fields. Historical-date responses can represent completed load plus a
post-activity remaining recommendation rather than the original full-day
target.

When completed and planned training share a day, keep three quantities
separate. `completedXSS` contains only completed activity load. `remainingXSS`
is already Xert's post-completion dose and must not have completed load
subtracted again. A later Planner event does not reduce `remainingXSS`; at its
start, only that event's XSS is added as a new TL/RL impulse on top of the live
state that already contains the completed activity. `completedXSS` resets on
the next calendar day, while its effect remains in TL/RL.

Every forward model run must start from a fresh Xert snapshot. Once Xert
processes a completed activity or changes profile/model state, discard any
locally propagated state and refetch signature, TL, RL, current `tau`/`k1`, and
Recovery Demands before projecting again.

`workout_capacity` is the load that can be added now while still arriving just
fresh for the next planned Xert workout. It is not a generic estimate of total
absorbable training. Select the relevant low/high/peak capacity according to
what must be trainable next. Low high/peak capacity does not by itself mean
poor high/peak recovery; check the corresponding recovery hours.

For an explicit capacity question, use `workout-capacity` with the exact
`--as-of` and `--fresh-at` timestamps. Never silently substitute a duration or
default horizon when either timestamp is unknown. The timestamps may be equal
for a zero-horizon freshness-boundary calculation.

The existing workout-capacity equation is also the inverse of the freshness
Train/Recover equation. At a zero-day horizon, capacity `= 0` is the exact
per-system freshness boundary: positive capacity is on the fresh side and
negative capacity is on the tired side. Low crossing that boundary produces
Very Tired; High or Peak crossing it while Low remains fresh produces Tired.
Fresh versus Very Fresh is a separate RL-cap test and cannot be inferred from
workout capacity alone.

## XSS Systems

- `lo` or `low`: low XSS from cycling activity up to and including the
  low-system contribution of work above TP.
- `hi` or `high`: additional load from work over TP.
- `pk` or `peak`: additional peak-power-relevant load from work over TP.

Low, high, and peak XSS are additive system loads, not mutually exclusive
buckets. High and peak values are normally small in absolute terms relative to
low XSS, even in hard workouts. Judge their absolute values against comparable
workouts and the intended stimulus; do not classify intensity from their share
of total XSS.

Treat the model as follows for interpretation: low XSS rises toward TP and its
rate is effectively capped there; above TP, high and peak XSS can accumulate in
addition to low XSS. This is a reasoning model, not a claim about Xert's exact
private formula.

## Workout Designer Calculate Model

Read [strain-model.md](strain-model.md) for the full qualitative model, equations,
offline calculation workflow, evidence hierarchy, and primary sources. The
rules below are the compact field-interpretation boundary.

Interpretation and authority rules:

- Treat Xert staff material as authoritative for qualitative semantics and the
  local equations as Calculate-validated rather than published Xert formulas.
- Use `xert_strain_cli.py` for offline calculations; do not recreate formulas in a
  caller or training-analysis helper.
- Mark the first `P >= MPA` as point-of-failure and reject an ordinary designed
  workout as feasible for that signature.
- Treat post-failure Calculate XSS and Difficulty as a hypothetical numerical
  continuation, not as proof of executable physiological work.
- Never call a Calculate crossing a breakthrough or infer a new Fitness
  Signature from it.
- Treat `P > PP` as invalid workout-design input. Calculate can accept it
  algebraically and produce a negative high-system allocation.
- Treat Calculate `calculation_stats` as authoritative for summary XSS and
  Difficulty when summing the exposed time series leaves a small integration
  residual.
- For completed activity session data, use Xert's reported MPA as authoritative.
  The exported Wexp and summary signature may not reconstruct deeply depleted
  activity MPA even though reported-MPA XSSR remains internally consistent.

## Activity And Workout Fields

- XEP is Xert Equivalent Power. Use it for Xert-specific load context rather
  than as a replacement for ordinary average or normalized power.
- `focus` describes the power-duration focus of the load; `specificity`
  describes how concentrated the load is around that focus.
- Always include numeric `difficulty` when summarizing an activity or workout;
  the text rating alone is too coarse.
- Treat `freshness` or status as Xert model context, not as a substitute for
  current physiological signals.
- Historical `tsbColor` validates the status boundary: brown after more than
  seven days without recorded activity; red when Low recovery time is
  positive; yellow when High or Peak recovery time is positive; green when all
  three Recovery Loads equal their minimum caps; otherwise blue. Recovery
  Demands shifts each system's Train/Recover boundary through the exposed
  recovery formula; higher values require more recovery.

### Multiple planned exercises on one day

Controlled Planner probes show that `/recommended-training` sums the XSS from
all planned exercises on a local calendar day, then applies that combined
impulse at the time of the last exercise. Model Planner forecasts with
`simulate_calendar_sequence(..., same_day_policy="aggregate_last")` (the
default). Use `same_day_policy="all"` only for completed activities or an
explicit hypothetical sequence.

### Controlled build-response probe

A Planner probe confirmed that the full load and Fitness Signature impulse is
visible immediately after the planned start time: the exact start timestamp is
still the pre-event state and one second later includes the impulse. Nothing is
applied again at the planned end time. A separate one-day target probe solved
per-system XSS from current TL, `tau1`, and `k1`; its larger immediate gains
decayed to exactly +1.000 W TP, +0.500 kJ HIE, and +5.000 W PP after 24 hours.
These are system-equivalent XSS amounts, not a claim that an arbitrary workout
can realize that exact split.
- Fitness signature values are time-specific model inputs. Do not assume a
  workout resolved with one signature has identical watts under another.
- Current production prediction uses system Training Load and athlete-specific
  `k1` responsiveness; exposed `k2` is currently zero. Anchor projections to
  the current signature and use `k1*delta_TL`, while retaining decay and
  breakthrough adjustments as production-only limitations.
- Since the late-2023 tracking change, Xert describes every decay method as
  Training-Load matched after an initial offset. Slow/Optimal/Aggressive differ
  mainly in convergence speed toward roughly 5% below the No-Decay estimate.
  In the cleaned history, synthetic daily rows have nearly zero residual while
  remaining adjustments concentrate on activity rows. Do not model decay as a
  separate fixed watt or percent subtraction per calendar day.
- The current frontend maps decay values as `1 = None - Training Load Matched`,
  `1.03 = Small`, `1.1 = Optimal - Default`, and `1.2 = Aggressive`. These are
  selector enum values, not a published decay equation. The calculation behind
  `/my-fitness/decay_method` is server-side.
- In Fitness Measures history, calculate the residual as actual signature
  change minus current `k1*delta_TL`. Call it an unclassified production
  adjustment, not automatically decay. Historical `atc` is HIE in joules and
  must be converted to kJ for comparison with HIE `k1`. The observed `medal`
  field is constant and cannot classify breakthroughs.
- A Fitness Measures row with `manual: true` marks a manually supplied/locked
  Fitness Signature. Exclude the transition into that row from signature and
  decay error statistics; it is an override, not model prediction error. The
  following row may still be evaluated from the manual signature as its anchor.
- Fitness Measures `medal` is not the achievement medal. Use activity detail
  `summary.breakthrough` to exclude breakthrough events from prediction-error
  statistics. Fitness Measures `pmcb` marks both breakthrough and
  near-breakthrough events and can exclude all such history rows without
  fetching every activity detail. Rows with
  `sig.error = "No BT yet. Using first signature"` do not have a valid prior
  signature anchor and must also be excluded.
- On a completed breakthrough, the Fitness Measures row signature matches the
  new signature saved on the activity, and the row's system XSS matches the
  activity XSS recalculated under that signature. Exclude the breakthrough
  signature transition from marginal `k1*delta_TL` validation, but retain the
  saved activity XSS in subsequent TL/RL recurrence. Once Xert has processed
  the activity, its new signature and XSS are authoritative forward state.
- Activity Dashboard `flag: true` means the breakthrough was marked invalid;
  the flag is absent from the OAuth activity summary. Exclude both the
  signature transition into that activity and the next transition from its
  invalid anchor. Do not automatically remove its XSS from TL/RL history:
  flagged activities remain `enabled`, and Xert retains that load impulse.
- Historical rows are a verification corpus, not a target for fitting old
  parameter regimes. New projections must snapshot current live `tau`, `k1`,
  Recovery Demands, signature, TL, and RL. Anchor marginal signature changes
  to the live signature; do not reconstruct it from `p0` or `stl`.
- `path` is the Xert activity or workout identifier. For activities it forms
  `https://www.xertonline.com/activity/<path>`.
- `map_url` on activity list rows is a ready-made PNG map image. Do not confuse
  it with an Intervals.icu activity URL.

## Forecast And Calendar

- Calendar notes are separate from forecast and training-plan fields.
- In forecast state, `high_intensity` means planned work over TP that generates
  high and/or peak XSS; still inspect the actual XSS split.
- Do not present `xss_target` as a placeholder workout's XSS unless its meaning
  has been verified. Use `xss`, `xlss`, `xhss`, and `xpss` for the planned
  placeholder load.
- Describe planned XSS relative to current Xert training load or forecast
  `tls`, not with an unsupported absolute size label.
- `training-forecast` can return `{}` even when a workout remains editable.
  Do not use forecast alone to decide whether a workout exists.

## Workout Designer

Workout Designer may encode repeated blocks in one row:

- `interval_count` is the repeat count.
- `rib_duration` and `rib_power` are Xert's `Rest in between` fields. Despite
  that label, Xert appends this recovery after every repeated work interval,
  including the final repetition.
- With `interval_count=2`, Xert produces two work intervals and two recovery
  intervals; the second recovery follows the final work interval.
- With `interval_count=4`, a five-minute RIB produces four five-minute
  recoveries. Do not add a separate following recovery row unless the workout
  deliberately requires extra recovery after the final RIB.
- A separate following row may still belong to the same visible set.

Preserve repeat rows when editing. If a new row is required, append a minimal
row with a new `sequence` and blank `DT_RowId`.

Known slope row types are `t_slope_pp`, `t_slope_mmp`, `t_slope_w`, and
`t_slope_absolute`. For relevant slope rows, `power.second_value` is slope
percent. A verified absolute-power example is:

```json
{"value": 350, "second_value": 4, "type": "t_slope_absolute"}
```

The OAuth workout endpoint can return HTTP 500 for a valid saved workout with
some slope variants. Verify those workouts through `workout-rows` and
`workouts --summary`.

## Access Quirks

- Xert data is split between OAuth API calls and authenticated web endpoints;
  some fields are only available through the latter.
- Planned-time recommendation calls mirror the Xert UI by sending the selected
  time minus one second.
- `/recommended-training` includes recommendation candidates; the adaptive
  training-advisor response supplies advice/status fields but not that list.
- Endpoint response shapes that have not been exercised by the plugin are
  unknown. Do not infer them from frontend route names.
