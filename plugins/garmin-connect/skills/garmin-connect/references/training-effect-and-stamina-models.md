# Garmin Training Effect, Stamina, and Recovery Models

Use this reference to explain Garmin's activity models and to decide how their
outputs may contribute to a training analysis. Use
[`field-semantics.md`](field-semantics.md) for API fields, units, freshness, and
missing-data behavior. Use [`sources.md`](sources.md) for provenance and
evidence strength.

## Evidence boundary

Garmin and Firstbeat describe model inputs, intended meanings, and qualitative
behavior, but they do not publish the complete current production equations.
Therefore:

- treat Garmin's reported values as authoritative outputs of Garmin's model;
- do not reverse-engineer missing values or claim numerical equivalence with a
  local formula;
- distinguish public model description from independent validation;
- describe expected stimulus and modeled depletion, not observed adaptation,
  measured fuel stores, muscle damage, or guaranteed performance capacity.

## Analysis dimensions

Keep Garmin outputs in separate dimensions:

| Output | Primary analysis dimension | What it contributes | What it cannot decide alone |
| --- | --- | --- | --- |
| Aerobic Training Effect | `modeled_stimulus` | Expected aerobic/cardiorespiratory stimulus | Total work, total recovery demand, or completed adaptation |
| Anaerobic Training Effect | `modeled_stimulus` | Expected stimulus from meaningful high-intensity bouts | Whether planned intervals were executed correctly |
| Exercise/Activity Load | `total_cost_and_recovery` | EPOC-based impact of one activity | Mechanical work, XSS/TSS equivalence, or local muscular cost |
| Acute/Chronic Load and Load Ratio | `total_cost_and_recovery` | Recent load magnitude and change relative to training history | Readiness, injury risk, or the next workout role |
| Available Stamina | `modeled_stimulus` / pacing context | Short-term, intensity-sensitive limitation and recovery toward Potential | Measured glycogen restoration or actual remaining race capacity |
| Potential Stamina | `total_cost_and_recovery` | Slower-changing modeled depletion across the session | Complete muscular or systemic recovery demand |
| Performance Condition | `acute_physiological_response` | Deviation from the athlete's VO2max-based performance baseline | A measured VO2max change or standalone readiness decision |
| Recovery Time | readiness context | Time until Garmin expects readiness for the next hard workout | A ban on easy or moderate activity |

No Garmin value may set `quality_completed=true` or advance plan progression
without agreement from planned structure, mechanical execution, direct
physiological response, athlete feel when available, and the plan's criteria.

## Aerobic Training Effect

The public Firstbeat model estimates EPOC from heartbeat-derived exercise data.
Training Effect maps the session's peak modeled EPOC to a 0-5 scale that is
individualized by fitness/activity context. Garmin's current public explanation
also describes aerobic Training Effect as EPOC accumulated during exercise and
mapped relative to fitness level and training habits. Preserve both descriptions
without inventing an exact current equation.

Consequences:

- Training Effect is not duration, energy expenditure, mechanical work, TSS,
  XSS, or another source's load score.
- Additional easy work or cooldown can add useful volume without increasing a
  peak-driven score.
- The same score can arise from different power structures and cannot describe
  force demands, fatigue resistance, economy, or local muscular cost.
- A score of 5 represents an overreaching-sized modeled stimulus. It is not a
  diagnosis of overtraining.
- Phrase the result as "Garmin estimates ..." or "Garmin models ...", never as
  proof that the predicted adaptation occurred.

## Anaerobic Training Effect

Garmin describes Anaerobic Training Effect as analysis of heart rate together
with speed or cycling power to estimate the anaerobic contribution to EPOC.
The Firstbeat white paper describes detection of physiologically meaningful
high-intensity bouts with attention to intensity, duration, recovery, and
fatigue.

Interpret it with:

- actual work power or speed;
- duration and number of repetitions;
- recovery duration and response;
- accumulated fatigue and sensor quality.

High heart rate alone does not prove anaerobic work. A low score after planned
sprints or VO2max intervals triggers inspection of execution and data quality;
it does not automatically make the workout unsuccessful. The examples and
case comparisons in the Firstbeat paper are useful illustrations but are not a
complete independent validation of the current Garmin implementation.

## Exercise Load and longer-term load

Garmin describes Exercise Load (also exposed for an activity as Activity
Training Load) as a numeric EPOC-based estimate of the impact of one activity.
It is related to Training Effect through the upstream EPOC model, but answers a
different question: modeled physiological load and recovery demand rather than
the expected adaptation category.

The published Firstbeat EPOC model updates from the previous modeled EPOC,
current intensity as a percentage of VO2max, and elapsed sample time:

```text
EPOC(t) = f(EPOC(t-1), exercise_intensity(t), delta_t)
```

The complete function is not public. At high intensity EPOC accumulates; during
rest or sufficiently low intensity it can decline within the activity. The 2012
vendor white paper reports a cycle-ergometer validation in 32 adults with
`r²=0.79` against measured EPOC and pooled mean absolute error of `13.7 ml/kg`.
This validates an older upstream estimate in a limited protocol, not today's
complete Garmin Exercise Load implementation across devices and sports.

Garmin's longer-term hierarchy is:

- **Acute Load:** weighted recent Exercise Load. Garmin describes it as a
  weighted seven-day perspective; newer public material also explains that an
  activity's influence gradually expires and is normalized to a seven-day
  window. It cannot be reproduced by simply adding recent activity values.
- **Chronic Load:** weighted average of Acute Load across 28 days.
- **Load Ratio:** Acute Load divided by Chronic Load, describing how recent
  load compares with the athlete's established load.
- **Load Focus:** recent Exercise Load allocated to low aerobic, high aerobic,
  and anaerobic categories and compared with Garmin's personalized targets.

Interpretation rules:

- preserve Garmin's numeric values and reported status rather than recreating
  the proprietary weighting;
- do not equate Activity Load with mechanical work, calories, TSS, or Xert XSS;
- do not turn Load Ratio into an injury prediction or readiness score;
- do not let Load Focus choose the next workout ahead of the active plan;
- account for device-generation differences and do not hard-code one universal
  Load Ratio boundary when Garmin documentation differs at the upper edge of
  the optimal range;
- retain local muscular, strength, environment, illness, and sensor-quality
  blind spots documented below.

## Performance Condition

Performance Condition is Garmin's real-time estimate of current performance
relative to the athlete's learned VO2max-based baseline. For cycling Garmin
lists power, heart rate, HRV, and VO2max context as inputs. Values range from
`-20` to `+20`; one point is approximately one percent of the baseline VO2max,
not a measured change in VO2max itself.

Separate two meanings in the same series:

1. the first stable value, normally available after Garmin begins scoring at
   roughly 6-20 minutes, is the best available session-start condition context;
2. the later trend describes whether internal cost is changing relative to
   external performance as the session progresses.

The compact summary should preserve:

- coverage and median reporting interval;
- median of the first reported minute as `early_stable`;
- start, end, first-to-last change, average, minimum, and maximum;
- first, middle, and final thirds of the reported samples;
- the largest peak-to-later-trough drop;
- elapsed time, power, heart rate, and temperature at extrema when available.

Interpret the early level separately from the within-session slope. Align later
changes with work and recovery blocks before attributing fatigue. Check device
learning state, VO2max baseline changes, heart-rate source, power source and
calibration, terrain, wind, position, coasting, temperature, and sensor gaps.
A positive early value does not authorize hard training by itself, and a
negative late value does not prove poor starting readiness, glycogen depletion,
or failure of the workout.

No public Firstbeat white paper, complete equation, or outcome-specific
independent validation for Performance Condition was located in the reviewed
sources. Treat Garmin's description as authoritative product semantics, not as
an accuracy guarantee.

## Real-Time Stamina

Garmin exposes two related estimates:

- **Available Stamina** combines broader fatigue/resource depletion with the
  temporary limitations created by hard efforts. It normally falls faster
  during work above the sustainable aerobic range and can rebound toward
  Potential when intensity falls.
- **Potential Stamina** focuses on broader, slower-changing fatigue and resource
  depletion. It is the better Garmin context for session-wide modeled
  depletion and moderate-intensity capacity.

Interpret these features dynamically:

- the Available minimum should be aligned with elapsed time, power, heart rate,
  and the relevant work interval;
- the Available-Potential gap describes how much of Garmin's current limitation
  is short-term and intensity-sensitive;
- rebound describes recovery of Garmin's short-term estimate, not measured
  lactate clearance, glycogen replacement, or tissue recovery;
- Potential drawdown adds useful context but does not replace load, subjective
  fatigue, fueling, or later recovery evidence;
- zero or near-zero values are model outputs, not direct physiological
  measurements.

Stamina accuracy depends on individualized inputs. Garmin requires heart rate
and a current VO2max estimate and recommends cycling power-curve data for the
best cycling estimate. Preserve sensor and coverage information with every
compact Stamina summary.

## Recovery Time

Recovery Time estimates when the athlete should be ready to gain maximum
benefit from the next hard, fitness-improving workout. Garmin describes the
base calculation as activity strain interpreted through current fitness and
recent training history, with EPOC-based training load and adjustments that can
include remaining recovery, VO2max trend, acute-to-chronic load, sleep, stress,
and light daily activity on compatible devices.

Operational rules:

- do not infer Recovery Time directly from Training Effect;
- do not add timers from multiple activities; Garmin re-evaluates the state;
- project a timestamped timer forward only under the explicit assumption of no
  intervening training and floor it at zero;
- use it to gate the next hard workout, not all movement;
- combine it with direct wellness signals, athlete feel, recent stimulus, and
  plan role.

## Context and blind spots

Heart-rate-derived models can be affected by the context in which the same
external work is performed. Inspect heat, humidity, altitude, illness,
incomplete recovery, and sensor quality when Training Effect is surprising.
Use graded context assessments:

| Status | Meaning |
| --- | --- |
| `not_assessed` | Required evidence is unavailable or no relevant context was detected |
| `context_present` | The factor exists, but its effect on Training Effect is not demonstrated |
| `supported` | Multiple aligned signals support likely influence; this is not causal proof |

Directly observed sensor gaps can support a sensor-quality limitation without a
second physiological signal. High temperature alone is only context; combine it
with a relevant response before saying influence is supported.

Garmin activity models can underrepresent or omit:

- local muscular fatigue and soreness;
- neuromuscular and strength-oriented cost;
- unfamiliar movement or terrain;
- dehydration and fueling problems;
- illness not visible in the activity data;
- subjective effort and pain.

Unknown context must remain unknown. Never translate missing athlete reports
into "normal" or use low Training Effect/high Stamina to prove freshness.
