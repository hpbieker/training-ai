# Garmin Connect Field Semantics

Use the relevant sections for units, field meaning, timestamps and missing-data
handling. Model inputs, interpretation and evidence limits belong to the linked
model references, not to this field contract.

## Readiness And Recovery

- Preserve the six disclosed drivers with the aggregate score: last night's
  Sleep Score, current Recovery Time, HRV Status, Acute Load, three-night Sleep
  History, and three-day Stress History. Do not infer undisclosed weights or
  reconstruct the score.
- Interpret Garmin's score bands as labels: `1-24` Poor, `25-49` Low, `50-74`
  Moderate, `75-94` High, and `95-100` Prime. A threshold crossing is not by
  itself evidence of a material physiological change.
- Enum and feedback fields are labels for numeric context. Do not turn a label
  into a decision weight when its associated number is missing.
- `recoveryTime` is minutes in the raw readiness payload. The compact output
  also exposes `recovery_time_hours`.
- Recovery time estimates time to the next hard workout. It is not a blanket
  ban on easy or moderate activity.
- For a later planned session, project recovery time forward from its timestamp
  assuming no intervening training, state that assumption, and floor the
  elapsed timer at zero hours. For a future-day recommendation, use the latest
  available real Garmin day as the Recovery Time source; do not request the
  empty future day and conclude that Recovery Time is unavailable.

For interpretation, read [the model reference](readiness-and-vo2max-models.md#training-readiness).

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
- For post-workout heart rate, the local analysis convention prefers the lowest
  sustained five-minute average over latest HR or a broad average to reduce
  sensitivity to brief movement. This is a summary choice, not a Garmin-defined
  recovery metric or a validated cutoff. Preserve the selected period and its
  coverage; it does not describe the entire post-workout period.
- End the immediate post-workout window at sleep onset. After sleep, use the
  new morning's resting HR, HRV, sleep, and Body Battery as the stronger context.

For interpretation, read [the model reference](wellness-and-energy-models.md).

## HRV, Resting Heart Rate, And Sleep

- Garmin daily fields reset or change day context before the first complete
  watch sync. A zero-like sleep value, an HRV value from the previous date, or
  a same-date resting-HR summary without complete current-day sleep/HRV is not
  evidence of poor recovery. Mark it unavailable rather than scoring it.
- A daily signal may be used for same-day downgrade decisions only when it
  belongs to the target local date and is complete. Complete sleep requires a
  positive duration plus start and end timestamps. Current-day resting HR
  requires evidence of a completed morning sync from valid sleep or HRV.
- Once validated, sleep, overnight HRV, resting HR, and Body Battery at wake
  remain valid daily context. Continuously changing Body Battery, stress, and
  heart-rate points require a current-day timestamp. The local readiness
  workflow treats points older than 90 minutes as stale for now-state use.
  This is an operational freshness limit, not a Garmin expiry rule or a
  physiological transition. Preserve the actual observation time; crossing
  the limit makes current state uncertain, not automatically worse.
- For a recommendation evaluated after its planned time, cap continuously
  changing series and timestamped readiness records at
  `min(now, planned_at)`. Completed sleep, overnight HRV, resting HR, and Body
  Battery at wake remain valid only when their observation period ended by that
  cutoff. Do not let later activity or sync points leak into the historical
  decision.
- Previous-day values may inform historical trends, but never stand in for
  today's negative readiness signal. Missing or stale daily values should
  prompt a sync recommendation without automatically downgrading training.
- Interpret HRV status together with last-night average, weekly average, and
  Garmin's balanced baseline range. Prefer graded distance from the range over
  a hard `BALANCED` versus `UNBALANCED` cutoff.
- `BALANCED` means the rolling seven-day average is within the personal
  baseline. `UNBALANCED` can mean either above or somewhat below it, `LOW`
  means substantially below it, and `POOR` means the learned baseline itself is
  below Garmin's age-referenced health range. Never translate every
  `UNBALANCED` value into "low HRV" or "poor recovery".
- Compare resting HR with the athlete's own recent baseline, not a population
  norm.
- Use sleep duration and sleep score only when present. Do not infer absent
  Garmin sleep fields from another record.

For interpretation, read [the model reference](readiness-and-vo2max-models.md#hrv-status).

## Training Status And Load

- `acute_load`, `chronic_load`, and `acwr` describe recent load state; keep the
  numeric values with any Garmin status or feedback label.
- Load-focus categories describe the recent distribution of low aerobic, high
  aerobic, and anaerobic load. Compare the numeric monthly loads with their
  target ranges; the feedback string alone is insufficient.
- Garmin activity Training Load, TSS, and IF are source-specific metrics. Do
  not treat them as interchangeable with another system's load score.
- Activity/Exercise Load is Garmin's EPOC-based estimate for one activity.
  Acute Load is weighted and must not be reconstructed by summing recent
  activities; Chronic Load is the longer-term weighted context. Preserve
  Garmin's reported Load Ratio and status rather than hard-coding one boundary.

For interpretation, read [the model reference](readiness-and-vo2max-models.md#training-status-and-load-balance).

## VO2max

- Garmin VO2max is a modeled sport-specific estimate of maximal aerobic
  capacity, not measured respiratory-gas exchange. Keep running and cycling
  estimates separate.
- Preserve the estimate, sport, observation timestamp, source device when
  available, and recent same-sport trend. Do not present a one-point change as
  established physiological improvement or decline.
- `max_met_category` is an undocumented numeric field in Garmin's private
  Training Status response. No public Garmin or Firstbeat mapping was found;
  preserve it only as opaque provenance and never convert it to METs, a fitness
  band, or decision weight.

For interpretation, read [the model reference](readiness-and-vo2max-models.md#vo2max).

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
- Compact Stamina analysis must resolve `directAvailableStamina` and
  `directPotentialStamina` through each activity's `metricDescriptors`; their
  numeric indexes are not stable across activities.
- Preserve coverage and aligned timestamp/power/heart-rate context with compact
  Stamina results. When the descriptors or samples are absent, report the
  series as unavailable rather than turning absence into a physiological zero.

For interpretation, read [the model reference](training-effect-and-stamina-models.md).

For Performance Condition, preserve coverage, extrema context, thirds and
peak-to-later-trough decline; see [its summary conventions](training-effect-and-stamina-models.md#performance-condition).
For Fitness Age, preserve device/model generation and use
[the model reference](readiness-and-vo2max-models.md#fitness-age).
For calories and estimated oxygen consumption, use
[the wellness and energy reference](wellness-and-energy-models.md).
