# Xert Field Semantics

## Recovery And Advice

- `recovery.recovery_hours` is the recovery state at `source_time_local`.
- `recovery.recovery_hours_at_advice_time` projects that state to the requested
  time by subtracting elapsed time and assuming no intervening training.
- Express recovery in hours. Zero is Xert's fresh threshold; negative values
  are on the fresh side of that threshold.
- Treat positive low-system recovery hours as the first gate against more
  cycling load. Use high and peak recovery hours to judge readiness for work
  over threshold power (TP).
- Do not use per-activity `summary.progression.rl` as current Recovery Load.

`training_advice.target_xss` maps Xert `targetXSS`: `xlss` to `low`, `xhss` to
`high`, and `xpss` to `peak`. It is Xert's recommended dose for the advice
context and already reflects activity Xert has accounted for. It is not a
recovery target, historical activity load, workout-library XSS,
`workout_capacity`, or a caller-calculated remaining dose.

Planned-time advice may also include `remaining_xss`, `completed_xss`,
`original_target_xss`, `training_advice_as_of`, availability, and daily-goal
fields. Historical-date responses can represent completed load plus a
post-activity remaining recommendation rather than the original full-day
target.

`workout_capacity` is the load that can be added now while still arriving just
fresh for the next planned Xert workout. It is not a generic estimate of total
absorbable training. Select the relevant low/high/peak capacity according to
what must be trainable next. Low high/peak capacity does not by itself mean
poor high/peak recovery; check the corresponding recovery hours.

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

## Activity And Workout Fields

- XEP is Xert Equivalent Power. Use it for Xert-specific load context rather
  than as a replacement for ordinary average or normalized power.
- `focus` describes the power-duration focus of the load; `specificity`
  describes how concentrated the load is around that focus.
- Always include numeric `difficulty` when summarizing an activity or workout;
  the text rating alone is too coarse.
- Treat `freshness` or status as Xert model context, not as a substitute for
  current physiological signals.
- Fitness signature values are time-specific model inputs. Do not assume a
  workout resolved with one signature has identical watts under another.
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
- `rib_duration` and `rib_power` define the recovery inserted between repeats.
- With `interval_count=2`, one recovery separates the two work intervals.
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
