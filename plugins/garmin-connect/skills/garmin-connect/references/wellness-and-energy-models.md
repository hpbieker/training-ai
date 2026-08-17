# Garmin Wellness And Energy Model Semantics

This document describes interpretation boundaries for Garmin sleep, Stress,
Body Battery, calories, and heartbeat-derived oxygen-consumption context. It
uses published Firstbeat methods as historical model-family evidence, not as a
claim that Garmin's current production equations are public or unchanged.

## Shared Upstream Evidence

Published Firstbeat models reuse combinations of beat-to-beat heart data,
heart rate variability, HRV-derived respiration, movement, personal profile,
estimated aerobic fitness, and activity history. These inputs support several
downstream estimates:

```text
heartbeat / RR + movement + profile + history
                   |
                   +-- HRV and respiration context
                   +-- physiological stress and recovery states
                   +-- sleep and sleep-stage classifications
                   +-- current aerobic oxygen consumption
                   +-- aerobic energy expenditure
                   +-- EPOC, Training Effect, and load context
```

Agreement between these outputs is useful context but not the same number of
independent physiological confirmations. Garmin does not disclose every shared
dependency, production branch, coefficient, or compensation mechanism.

## Sleep

Firstbeat's published 2019 wearable sleep method combines RR/HRV,
HRV-derived respiration, movement, time of day, and profile data. In 110 adults
and 780 hours of polysomnography it reported `66%` epoch-level stage agreement,
or about `69%` for a less resource-constrained offline implementation;
sleep-versus-awake sensitivity was `94%` and specificity `63%`.

Treat Garmin sleep stages as model classifications, not direct measurements of
brain activity. Prefer sleep duration, awakenings, subjective quality, and
multi-night trends; a small one-night REM, deep, or light-sleep change must not
determine a training decision. The historical vendor result does not establish
accuracy for every current Garmin device, population, or firmware version.

## Physiological Stress And Recovery

The published Firstbeat model first separates physical activity and recovery
from activity, then classifies remaining segments as recovery, physiological
stress, or unrecognized. Physiological stress is increased modeled activation;
it does not identify its cause or necessarily equal perceived psychological
stress.

Exercise, illness, pain, digestion, alcohol, stimulants, medication,
dehydration, heat, altitude, sleep loss, and positive or negative emotion can
produce related responses. Chronic conditions, heart-affecting medication, and
signal artifacts can limit interpretation. Use contextual evidence to explain
a stress pattern and leave the cause unresolved when that evidence is absent.

## Body Battery

Treat Body Battery as Garmin's modeled balance of body resources informed by
activity, stress, and recovery context. It is not measured metabolic energy,
glycogen, calorie balance, or guaranteed remaining exercise capacity.

Use the wake value as overnight recovery context and the current value as
modeled time-of-day body-resource context. Keep both diagnostic alongside HRV,
resting heart rate, sleep, stress, cumulative load, and body feel. Because these
signals share upstream evidence, Body Battery must not become an additional
independent vote after its related inputs have already been used.

## Calories And Energy Expenditure

The published Firstbeat energy method estimates aerobic oxygen consumption
before deriving energy expenditure. Its vendor validation in 32 healthy adults
across cycle-ergometer and selected real-life tasks reported `10.9%` MAPE. This
small historical study does not establish current all-day Garmin calorie
accuracy across sports, devices, or individuals.

Use Garmin calories as an uncertain model estimate, not a precise
intake-versus-expenditure ledger or exact fueling target. Short, highly
anaerobic work can be underrepresented because the published method does not
directly measure anaerobic energy production. Ground fueling in workout
duration and demands, observed external work when available, actual intake,
and practical response.

## Current Oxygen Consumption Versus VO2max

Firstbeat's published current-VO2 method estimates ongoing aerobic metabolism
from heart rate, RR-derived respiration, and on/off dynamics. In 32 healthy
adults its reported second-by-second MAE improved from `3.7` to
`1.9 ml/kg/min` versus an HR-only model.

Current estimated VO2 and VO2max are different outputs. Current VO2 describes
modeled aerobic metabolism during an activity; VO2max describes modeled maximal
aerobic capacity. Never substitute one for the other, and do not infer anaerobic
energy production from the current-VO2 estimate.

## Operational Rules

- Preserve timestamps, sync state, and source scope with every Garmin output.
- Do not count sleep, HRV, Stress, resting heart rate, and Body Battery as fully
  independent confirmations when they reflect the same recovery episode.
- Do not infer the cause of physiological stress without separate evidence.
- Do not use small single-night sleep-stage changes to change training.
- Do not convert Body Battery into calories, glycogen, or exercise minutes.
- Do not use Garmin calories as exact fueling or energy-balance targets.
- Keep current oxygen consumption and VO2max semantically separate.

## Sources

- [Firstbeat: Sleep Analysis Method Based on HRV](https://www.firstbeat.com/wp-content/uploads/2019/11/Firstbeat-Sleep-Solution_white-paper_short.pdf)
- [Firstbeat: Stress and Recovery Analysis Based on 24-hour HRV](https://www.firstbeat.com/wp-content/uploads/2015/10/Stress-and-recovery_white-paper_20145.pdf)
- [Firstbeat: Energy Expenditure Estimation](https://www.firstbeat.com/wp-content/uploads/2015/10/white_paper_energy_expenditure_estimation.pdf)
- [Firstbeat: Oxygen Consumption Estimation](https://www.firstbeat.com/wp-content/uploads/2015/10/white_paper_vo2_estimation.pdf)
- [Firstbeat: Health and Fitness Benefits of Physical Activity](https://assets.firstbeat.com/firstbeat/uploads/2018/03/Physical-activity-white-paper_FINAL2.0.pdf)

See [`sources.md`](sources.md) for evidence-strength limits and the complete
Garmin/Firstbeat source registry.
