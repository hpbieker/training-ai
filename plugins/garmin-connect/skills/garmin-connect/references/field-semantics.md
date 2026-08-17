# Garmin Connect Field Semantics

Garmin Connect contains data synced from a watch or head unit. Treat freshness
and sync state as part of every signal.

For physiological model behavior and interpretation boundaries, see
[`training-effect-and-stamina-models.md`](training-effect-and-stamina-models.md)
and [`readiness-and-vo2max-models.md`](readiness-and-vo2max-models.md).
For source provenance and evidence strength, see [`sources.md`](sources.md).

## Readiness And Recovery

- Training Readiness is Garmin's aggregate estimate, not an independent
  physiological measurement. Keep its score and level diagnostic; use the
  underlying numeric sleep, HRV, recovery, stress, and load inputs when making
  a decision.
- Preserve the six disclosed drivers with the aggregate score: last night's
  Sleep Score, current Recovery Time, HRV Status, Acute Load, three-night Sleep
  History, and three-day Stress History. Do not infer undisclosed weights or
  reconstruct the score.
- The six contributors overlap. Group sleep, HRV, and stress as related
  autonomic/lifestyle context and Acute Load plus Recovery Time as related
  load/recovery context. Do not treat aligned contributors as six independent
  confirmations or penalties.
- Interpret Garmin's score bands as labels: `1-24` Poor, `25-49` Low, `50-74`
  Moderate, `75-94` High, and `95-100` Prime. A threshold crossing is not by
  itself evidence of a material physiological change.
- The largest routine recalculation occurs after waking. The value then changes
  during the day as Recovery Time expires and new activities add recovery
  demand. Compare timestamped observations rather than treating the morning
  value as fixed.
- Training Readiness estimates how likely the athlete is to benefit from
  training, especially a hard workout; it is not a race-performance forecast.
  Low readiness during planned overload can be expected. Inspect the driver
  pattern before changing the plan, and do not count the aggregate again after
  using its components.
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

## Body Battery, Stress, And Heart Rate

- Body Battery is a 0-100 Garmin estimate. For same-day decisions expose both
  `at_wake` and `most_recent` when available; neither value alone describes the
  whole day's recovery state.
- Treat Body Battery as a modeled balance of body resources derived from
  activity, stress, and recovery context. It is not measured metabolic energy,
  glycogen, calorie balance, or proof of remaining exercise capacity.
- Garmin Stress describes modeled physiological activation, not its cause and
  not necessarily perceived psychological stress. Exercise, illness, pain,
  digestion, alcohol, stimulants, medication, dehydration, heat, altitude,
  sleep loss, and positive or negative emotion can produce related responses.
- Body Battery, Stress, sleep, HRV, and resting heart rate share upstream
  heartbeat and autonomic evidence. Do not count agreement between them as the
  same number of independent physiological confirmations.
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
  heart-rate points require a current-day timestamp and are stale as now-state
  after 90 minutes.
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
- Garmin requires about three weeks of regular overnight data to establish HRV
  Status; its support guidance specifies at least four nights per week during
  initial personalization. The baseline can use months of history, shifts
  gradually, and can expire after prolonged sparse overnight wear.
- `BALANCED` means the rolling seven-day average is within the personal
  baseline. `UNBALANCED` can mean either above or somewhat below it, `LOW`
  means substantially below it, and `POOR` means the learned baseline itself is
  below Garmin's age-referenced health range. Never translate every
  `UNBALANCED` value into "low HRV" or "poor recovery".
- Overnight HRV and its status do not identify a cause. Interpret deviations
  with training, illness symptoms, alcohol, sleep, nutrition, travel, heat,
  medication, and subjective response; do not compare absolute HRV between
  athletes.
- Compare resting HR with the athlete's own recent baseline, not a population
  norm.
- Use sleep duration and sleep score only when present. Do not infer absent
  Garmin sleep fields from another record.
- Sleep Score is a proprietary `0-100` composite of duration and modeled sleep
  quality. Garmin and Firstbeat disclose sleep architecture, HRV-derived
  stress/recovery, awakenings, awake time, movement/restlessness, and age-based
  duration context, but not the complete current equation or weights.
- Do not count Sleep Score independently after using the same night's duration,
  stages, stress/HRV, or awakenings. Use the score as a summary and inspect its
  component feedback when it materially influences a training decision.
- Sleep stages are wearable model classifications, not direct measurements of
  brain activity. Prefer sleep duration, awakenings, subjective sleep quality,
  and repeated trends; do not let a small one-night change in REM, deep, or
  light sleep determine a training decision.
- The published 2019 Firstbeat sleep model reported `66%` epoch-level sleep
  stage agreement with polysomnography (`69%` for a less resource-constrained
  offline version) in 110 adults. This historical vendor validation does not
  establish the accuracy of every current Garmin device or production model.

## Calories And Estimated Oxygen Consumption

- Garmin calories and energy expenditure are model estimates, not a precise
  intake-versus-expenditure ledger. Do not use them as exact fueling targets or
  proof of an energy deficit without independent dietary and workload context.
- The published Firstbeat energy-expenditure method first estimates aerobic
  oxygen consumption from heartbeat-derived inputs. It reported `10.9%` MAPE
  in 32 healthy adults across cycle-ergometer and selected real-life tasks; this
  vendor result must not be generalized to all-day Garmin accuracy, sports, or
  devices.
- Heartbeat-derived oxygen consumption during activity and VO2max are different
  outputs. The former estimates current aerobic metabolism; the latter estimates
  maximal aerobic capacity. Never substitute one for the other.
- The published Firstbeat oxygen-consumption and energy methods do not measure
  anaerobic energy production directly. Short, highly anaerobic work can be
  underrepresented, and the estimates depend on accurate personal parameters.

## Training Status And Load

- Garmin Training Status is a longitudinal interpretation of fitness trend
  relative to recent load and load composition; compatible devices also use
  HRV Status. It is not a same-day readiness score and should not replace the
  underlying VO2max trend, Acute Load, HRV Status, and Load Focus context.
- Do not confuse Garmin Training Status with the separate Firstbeat Sports
  feature of the same name. Firstbeat Sports publishes a `0-100` score based on
  TRIMP-derived acute load, ACWR, and Quick Recovery Tests; Garmin publishes
  categorical states based on VO2max, EPOC-based load, HRV, and in some cases
  Load Focus. Their names do not make their equations or thresholds portable.
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

## Fitness Age

- Garmin Fitness Age is a motivational interpretation, not a biological-age
  measurement, longevity prediction, or training-readiness input.
- Preserve the device/model generation. Older implementations reinterpret
  estimated VO2max against sex- and age-referenced norms; newer compatible
  watches use chronological age, vigorous-activity history, resting heart rate,
  and body fat percentage or BMI. Do not assume that every Fitness Age value is
  derived from VO2max alone.
- Body fat from a compatible Garmin Index scale replaces BMI when available in
  the newer model. A change in profile, weight, BMI, body-fat source, resting-HR
  history, vigorous minutes, or device can therefore change Fitness Age without
  proving a matching change in aerobic capacity.
- Use Fitness Age and Garmin's achievable-age/action guidance as broad behavior
  feedback only. For endurance progression, inspect same-sport VO2max trends,
  completed training, and performance evidence directly.

## VO2max

- Garmin VO2max is a modeled sport-specific estimate of maximal aerobic
  capacity, not measured respiratory-gas exchange. Keep running and cycling
  estimates separate.
- Preserve the estimate, sport, observation timestamp, source device when
  available, and recent same-sport trend. Do not present a one-point change as
  established physiological improvement or decline.
- Accuracy is population- and protocol-dependent. Keep correlation,
  group-average bias, and individual agreement distinct, and do not transfer a
  validation result between fitness levels or from running to cycling.
- Cycling VO2max uses heart rate relative to external cycling power and selects
  data Garmin considers meaningful. Its quality depends on heart-rate and
  power coverage plus an accurate profile, especially maximum heart rate and
  body weight.
- For a surprising cycling estimate, inspect maximum-heart-rate settings,
  heart-rate source, power source/calibration, qualifying steady coverage,
  environment, illness, and recovery before interpreting it as fitness change.
- Heat, humidity, and altitude can alter the heart-rate-to-power relationship.
  Compatible Garmin devices may compensate for some environmental effects, but
  do not assume identical support across devices or historical observations.
- Use VO2max as capacity and model context. It helps individualize Garmin
  Performance Condition, Training Effect, Recovery Time, load ranges, and
  Training Status, but it is not a same-day readiness signal or a direct source
  of cycling watt targets.
- `max_met_category` is an undocumented numeric field in Garmin's private
  Training Status response. No public Garmin or Firstbeat mapping was found;
  preserve it only as opaque provenance and never convert it to METs, a fitness
  band, or decision weight.

## Activity Metrics

- Training Effect contains numeric aerobic and anaerobic values plus category
  and message codes. Preserve the numeric values when describing the effect.
- Describe Training Effect as Garmin's modeled estimate of the session's
  expected fitness stimulus, not proof that a physiological adaptation occurred.
- Aerobic Training Effect is based primarily on the peak modeled EPOC reached
  during the activity, scaled to the athlete's modeled fitness and training
  context. It is not total work, duration, energy expenditure, or a substitute
  for another source's load metric. Cooldown or low-intensity periods can add
  useful work without increasing the peak-based score.
- Anaerobic Training Effect models physiologically meaningful high-intensity
  bouts using heartbeat dynamics and, when available, external speed or cycling
  power. Interpret it with the actual work duration, intensity, recoveries, and
  accumulated fatigue; high heart rate alone does not establish anaerobic work.
- The same Training Effect can result from sessions with different mechanical
  work, fatigue resistance, force/economy demands, and local muscular cost.
  Training Effect is one modeled stimulus dimension, not a complete account of
  the session's value or recovery demand.
- Heat, humidity, altitude, illness, and incomplete recovery can elevate heart
  rate or respiration and therefore modeled EPOC/Training Effect at the same
  external workload. Treat an unexpectedly high value as physiological cost
  that requires context, not automatically as a more successful adaptation.
- Training Effect can underrepresent local muscular fatigue, soreness,
  neuromuscular cost, and strength-oriented work. Do not use a low value to
  prove that the athlete is fresh or that a long easy session was unproductive.
- A value of `5.0` means an overreaching-sized modeled stimulus. It does not by
  itself diagnose overtraining; repeated high load, inadequate recovery, and a
  sustained performance decline require separate evidence.
- `training_effect.label` is the broad category. Translate known labels into
  natural wording: `AEROBIC_BASE`, `ANAEROBIC_CAPACITY`, `LACTATE_THRESHOLD`,
  `RECOVERY`, `SPEED`, `TEMPO`, `VO2MAX`, and `UNKNOWN`.
- `aerobic_message` and `anaerobic_message` are more specific message codes,
  not category labels. Preserve the full raw code for field inspection. In
  prose, remove a final numeric resource suffix and translate the semantic
  prefix rather than treating the suffix as a measured value.
- Performance condition is a secondary within-activity trend. Comparability can
  change with power source, terrain, coasting, position, and environment.
- Separate Performance Condition's early stable level from its later trend.
  Each point is approximately one percent deviation from Garmin's learned
  VO2max-based baseline, not a measured VO2max change. Preserve coverage,
  extrema context, thirds, and largest peak-to-later-trough drop when available.
- Stamina and potential stamina are Garmin model estimates. Use them as session
  context, not proof of remaining race capacity.
- Compact Stamina analysis must resolve `directAvailableStamina` and
  `directPotentialStamina` through each activity's `metricDescriptors`; their
  numeric indexes are not stable across activities. Interpret Available
  Stamina as the more intensity-sensitive pacing estimate and Potential
  Stamina as the broader, slower-changing model estimate. A rebound in
  Available toward Potential is model context, not measured fuel restoration.
- Preserve coverage and aligned timestamp/power/heart-rate context with compact
  Stamina results. When the descriptors or samples are absent, report the
  series as unavailable rather than turning absence into a physiological zero.
