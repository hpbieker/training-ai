# Garmin Readiness, Training Status, VO2max, And Fitness Age Models

Use this document for physiological model behavior and interpretation. Use
[`field-semantics.md`](field-semantics.md) for API fields, freshness, and
missing-data rules, and [`sources.md`](sources.md) for provenance and evidence
strength.

## Training Readiness

Training Readiness is Garmin's proprietary aggregate estimate of when the
athlete is likely to benefit from training, particularly a hard workout. It is
not an independent measurement and is not designed to predict race-day
performance.

Garmin discloses six inputs:

| Input | Public time context | Interpretation |
| --- | --- | --- |
| Sleep Score | Last night | Most recent sleep quantity, quality, and recovery context |
| Recovery Time | Current countdown | Residual recovery demand from recent activity, dynamically adjusted |
| HRV Status | Seven-day average relative to personal baseline | Longer recovery and autonomic context |
| Acute Load | Recent weighted load | Recent activity load in Garmin's model |
| Sleep History | Previous three nights | Accumulated sleep context that one good night does not erase |
| Stress History | Previous three awake days | Recent non-training physiological stress context |

Garmin does not publish component weights, interaction terms, the complete
equation, or device-specific branches. Never reverse-engineer a missing score
from these inputs or assign invented weights.

### Overlapping driver families

The six displayed contributors are not six independent physiological
observations. Garmin's public descriptions show overlapping source signals:

- Sleep Score already includes autonomic recovery evidence derived from HRV,
  while HRV Status uses a seven-day HRV average directly.
- Sleep Score and Sleep History describe overlapping nightly sleep evidence at
  different time horizons.
- Recovery Time can be adjusted by sleep quality, stress, and daily activity,
  which also appear elsewhere in Training Readiness.
- Acute Load and Recovery Time both incorporate recent recorded activity.

This establishes source overlap, not Garmin's undisclosed weighting or
interaction equation. Group the contributors into related driver families when
explaining a score: autonomic/lifestyle context (sleep, HRV, and stress) and
load/recovery context (Acute Load and Recovery Time). Do not treat several
aligned contributors as the same number of independent confirmations.

### Dynamic behavior

- The largest routine update occurs after waking, when last night's sleep, HRV,
  and history values update.
- The score can rise during the day as Recovery Time expires.
- A recorded activity reduces it according to new modeled recovery demand;
  light activity usually has less effect than hard activity.
- Compare values only with timestamps and sync context. A morning score and a
  later score answer different now-state questions.

### Decision boundary

Use the aggregate as a diagnostic summary and explanation aid. Use the direct
numeric components, athlete feel, recent stimulus, and plan role for the actual
training decision. Do not add Training Readiness as another weighted signal
after those same inputs have already been used.

Low readiness is not an automatic veto. During deliberate overload it can
correctly reflect high load and residual Recovery Time. Sleep, HRV, stress,
illness symptoms, or an unexpected multi-signal deterioration may justify a
different decision even when planned overload explains part of the score.

## HRV Status

Garmin measures overnight HRV and compares the rolling seven-day average with a
personal baseline. Around three weeks of regular overnight wear is required to
activate the status, with at least four nights per week during initial
personalization. Longer history can strengthen the baseline, which then moves
slowly with the athlete's normal values rather than remaining fixed.

The status labels are asymmetric. `Balanced` means within the personal range;
`Unbalanced` can be above or somewhat below it; `Low` is substantially below
it. `Poor` is different: Garmin applies it when the personal baseline itself
falls below an age-referenced health range and may stop displaying the baseline.
Accordingly, status plus the last-night average, seven-day average, and baseline
bounds are needed for interpretation.

This is trend context, not a diagnosis or causal classifier. Overnight PPG HRV
inherits sensor and sleep-window uncertainty, and independent validation of one
device's nocturnal HRV does not validate Garmin's proprietary baseline range or
status thresholds. Use sustained within-athlete change with corroborating
context; never compare absolute HRV scores as a leaderboard.

## Training Status And Load Balance

Garmin Training Status connects longer-term fitness change with recent training
load. The current public model uses VO2max trend, Acute Load, and, on compatible
devices, HRV Status; Load Focus can add context in specific situations. Treat
the categorical status as an explanation of those trends, not as a separate
vote after its inputs have already been considered.

Acute Load is Garmin's EPOC-based weighted recent load: a new activity enters at
full value, its influence expires over ten days, and the result is normalized to
a seven-day scale. Chronic Load is a weighted 28-day context, while Load Ratio
is Acute divided by Chronic. Load Focus is different again: it describes four
weeks of low-aerobic, high-aerobic, and anaerobic load relative to personalized
targets. A balanced distribution is a general foundation, not a requirement
that every training phase contain equal amounts of all three categories.

Firstbeat uses the same feature names in more than one product family. The
published Firstbeat Sports Training Status is a `0-100` team-sport score based
on TRIMP acute load, TRIMP ACWR, and recent Quick Recovery Tests. Its Acute Load
is a seven-day TRIMP sum, unlike Garmin's weighted EPOC-based Acute Load. Never
import its `30/70` thresholds, TRIMP scale, QRT logic, or injury-risk claims into
Garmin Connect interpretation.

## VO2max

VO2max is maximal oxygen consumption. Garmin reports a modeled relative value
in `ml/kg/min`; it does not measure inspired and expired gases. Running and
cycling estimates are sport-specific because they use different muscle groups
and external-work inputs.

For cycling, Garmin relates the physiological response from heart rate to
external work from a power meter and selects data segments it considers
meaningful. Current Garmin support generally requires heart rate, power, a
steady effort, and at least 20 qualifying minutes, but exact operational rules
can vary by device. Treat requirements as device-specific when eligibility is
the question.

### Interpretation

- Prefer a repeated same-sport trend under reasonably comparable sensor and
  environmental conditions over an isolated estimate.
- Preserve profile and sensor context. Incorrect maximum heart rate can
  materially bias a submaximal estimate; body weight changes the relative
  `ml/kg/min` value; heart-rate or power error changes the modeled relationship.
- Inspect heat, humidity, altitude, illness, recovery, position, terrain, and
  sensor changes when the trend moves unexpectedly.
- Do not convert VO2max directly into workout watts. Use observed cycling power
  capacity and the plan's progression for prescription.

VO2max is upstream context for several Garmin features, including Performance
Condition, Training Effect, Recovery Time, individualized load ranges, Training
Status, and Stamina. This makes a stale or biased estimate relevant when several
Garmin outputs shift together, but does not make VO2max a same-day readiness
measurement.

### Accuracy boundary

The historical Firstbeat method segments an activity, evaluates segment
reliability, and estimates VO2max from the heart-rate relationship to speed or
cycling power. It is useful model-family evidence, not disclosure of every
current Garmin production detail.

The published cycling evidence is limited. Firstbeat's white paper describes 29
cyclists and contains an internal inconsistency: it reports `92%` accuracy and
also `MAPE ~5%`. Firstbeat's current publication registry resolves the study
summary to `7.7-8.7% MAPE`, consistent with the approximately `8%` reported in
an independent systematic review and arithmetically consistent with `92%`
accuracy. The underlying field validation had small average bias but wide
individual limits of agreement.

Independent Garmin running studies also show that error is population- and
protocol-dependent. A 2025 study of moderately-to-highly trained endurance
athletes reported better agreement in the moderately trained subgroup and
substantially larger underestimation and percentage error in the highly trained
subgroup. Running evidence cannot validate cycling accuracy directly, but it
does show why one global error percentage must not be applied to every athlete.
Therefore:

- do not claim that Garmin cycling VO2max is `95% accurate`;
- do not use the group-average bias as an individual error bound;
- describe the value as a useful trend estimate with meaningful individual
  uncertainty;
- name the population, fitness level, sport, protocol, and sensor setup when
  making an accuracy claim;
- distinguish correlation, group-average bias, and individual agreement. Good
  ranking or a small group bias does not establish a precise individual value.

## Fitness Age

Fitness Age is a consumer-facing translation of fitness and lifestyle context,
not another independent physiological measurement. Firstbeat's original
description maps estimated VO2max to the age whose same-sex population average
has a similar value. This inherits both the uncertainty of the VO2max estimate
and the limitations of the chosen population reference.

Garmin now documents two device-dependent implementations. One remains a
VO2max-based interpretation. Newer compatible watches instead use age, vigorous
activity, resting heart rate, and body fat percentage or BMI; Garmin uses body
fat from a compatible Index scale when available. Consequently, values from
different device generations are not necessarily comparable, and a Fitness Age
change does not identify which physiological or profile input caused it.

Use the metric for understandable, broad lifestyle feedback. Do not treat it as
measured biological aging, a validated morbidity or mortality prediction, a
same-day readiness signal, or a reason by itself to alter the training plan.

## Sleep Score

Garmin describes Sleep Score as a `0-100` summary of sleep duration and quality.
The published Firstbeat model family uses duration, sleep stages, HRV-derived
stress and recovery, movement-based restlessness, awakenings, and sleep
continuity. Age-based recommendations contextualize duration, but Garmin does
not publish the current production weights or complete equation.

The published validation evidence applies to sleep/wake and stage
classification, not to the final Sleep Score against an independent reference
standard. Input errors can propagate into the composite, particularly when
quiet wake is classified as sleep or stages are unstable. Treat the score as a
useful summary: inspect duration, awakenings, stress/recovery, subjective sleep,
and trends before letting one night's score change the plan.

Sleep Score overlaps with HRV Status, stress, Sleep History, and the aggregate
Training Readiness score. After those components are used, the score is not an
additional independent recovery observation.
