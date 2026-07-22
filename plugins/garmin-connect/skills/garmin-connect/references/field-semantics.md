# Garmin Connect Field Semantics

Garmin Connect contains data synced from a watch or head unit. Treat freshness
and sync state as part of every signal.

## Readiness And Recovery

- Training Readiness is Garmin's aggregate estimate, not an independent
  physiological measurement. Keep its score and level diagnostic; use the
  underlying numeric sleep, HRV, recovery, stress, and load inputs when making
  a decision.
- Enum and feedback fields are labels for numeric context. Do not turn a label
  into a decision weight when its associated number is missing.
- `recoveryTime` is minutes in the raw readiness payload. The compact output
  also exposes `recovery_time_hours`.
- Recovery time estimates time to the next hard workout. It is not a blanket
  ban on easy or moderate activity.
- For a later planned session, project recovery time forward from its timestamp
  assuming no intervening training, and state that assumption.

## Body Battery, Stress, And Heart Rate

- Body Battery is a 0-100 Garmin estimate. For same-day decisions expose both
  `at_wake` and `most_recent` when available; neither value alone describes the
  whole day's recovery state.
- `charged` and `drained` describe accumulated change, not current Body Battery.
- Body Battery, stress, and heart-rate series can change after every device
  sync. Use their timestamps rather than assuming the daily summary is current.
- Garmin series can contain negative placeholder values. Ignore them rather
  than treating them as physiological measurements.
- For a second-session decision, inspect sustained post-workout stress rather
  than only daily average stress. Sustained high stress suggests incomplete
  settling after the first session.
- For post-workout heart rate, prefer the lowest sustained five-minute average
  over latest HR or a broad average, which are movement- and timing-sensitive.
- End the immediate post-workout window at sleep onset. After sleep, use the
  new morning's resting HR, HRV, sleep, and Body Battery as the stronger context.

## HRV, Resting Heart Rate, And Sleep

- Interpret HRV status together with last-night average, weekly average, and
  Garmin's balanced baseline range. Prefer graded distance from the range over
  a hard `BALANCED` versus `UNBALANCED` cutoff.
- Compare resting HR with the athlete's own recent baseline, not a population
  norm.
- Use sleep duration and sleep score only when present. Do not infer absent
  Garmin sleep fields from another record.

## Training Status And Load

- `acute_load`, `chronic_load`, and `acwr` describe recent load state; keep the
  numeric values with any Garmin status or feedback label.
- Load-focus categories describe the recent distribution of low aerobic, high
  aerobic, and anaerobic load. Compare the numeric monthly loads with their
  target ranges; the feedback string alone is insufficient.
- Garmin activity Training Load, TSS, and IF are source-specific metrics. Do
  not treat them as interchangeable with another system's load score.

## Activity Metrics

- Training Effect contains numeric aerobic and anaerobic values plus category
  and message codes. Preserve the numeric values when describing the effect.
- `training_effect.label` is the broad category. Translate known labels into
  natural wording: `AEROBIC_BASE`, `ANAEROBIC_CAPACITY`, `LACTATE_THRESHOLD`,
  `RECOVERY`, `SPEED`, `TEMPO`, `VO2MAX`, and `UNKNOWN`.
- `aerobic_message` and `anaerobic_message` are more specific message codes,
  not category labels. Preserve the full raw code for field inspection. In
  prose, remove a final numeric resource suffix and translate the semantic
  prefix rather than treating the suffix as a measured value.
- Performance condition is a secondary within-activity trend. Comparability can
  change with power source, terrain, coasting, position, and environment.
- Stamina and potential stamina are Garmin model estimates. Use them as session
  context, not proof of remaining race capacity.
