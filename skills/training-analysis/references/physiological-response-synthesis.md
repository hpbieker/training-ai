# Physiological Response Synthesis

Use this reference to synthesize heart rate and multiple physiological streams
into one completed-activity interpretation. Use the device-specific references
for measurement semantics and quality limits. Do not turn the synthesis into a
numeric score or count correlated fields as independent evidence.

## Establish The Expected Response

Before interpreting a physiological signal:

1. Establish the intended session role and actual power-duration-recovery
   structure.
2. Resolve the athlete's applicable VT1, VT2, critical-power, or other anchor
   and preserve how it was established. Do not treat related anchors as
   interchangeable.
3. Identify the expected response for the actual intensity domain, interval
   duration, accumulated prior work, and recovery structure.
4. Compare the expected response with matched observed windows.

Use the athlete's actual anchor and these domain expectations. They describe
direction and behavior, not universal times or field cutoffs.

| Domain | Expected physiology | What field analysis may test | Important limit |
| --- | --- | --- | --- |
| Recovery or low aerobic | Small homeostatic disturbance; direct systemic signals should move toward a low, stable response after the transition | Whether power remains easy and HR, respiration, feel, and local response become controlled rather than progressively disproportionate | A low HR does not prove low muscular, biomechanical, or residual cost |
| Moderate, below the first threshold | Metabolic steady state is expected during continuous work; prolonged tolerance can eventually become more dependent on substrate availability and neuromuscular function than acute metabolite accumulation | Stable or equivalent elapsed-time windows; onset and magnitude of late deterioration under matched work | Field streams do not directly measure muscle metabolites, glycogen, or the threshold boundary |
| Heavy, above the first threshold but below CP | Greater metabolic disturbance and a VO2 slow component are expected, but a delayed steady state remains possible; exhaustive fatigue reflects combined metabolite, ionic, substrate, and excitation-contraction effects | Whether long work remains repeatable and eventually controlled, or whether internal response and execution deteriorate despite matched work | VT2, MLSS, FTP, CP, and Xert Threshold Power cannot be silently substituted for one another |
| Severe, above CP | No metabolic steady state; disturbance progresses as work above CP accumulates, and sufficiently sustained work can drive VO2 toward VO2max | Completed work-recovery architecture, repeatability, power loss, and progressive systemic/local response | High HR, ventilation, or low SmO2 does not prove VO2max attainment or identify the limiting mechanism |
| Sprint or very short maximal work | Immediate mechanical, phosphagen, glycolytic, and neuromuscular demands dominate each effort; systemic responses lag the work | Peak and mean power, duration, repetition loss, cadence/torque, and what is restored before the next effort | HR and ventilation cannot grade the quality or energetic contribution of each sprint |

For long or mixed sessions, analyze physiologically distinct blocks separately.
For late-session interpretation, apply
[cycling-endurance-physiology.md](cycling-endurance-physiology.md).

VT1 normally describes the moderate-to-heavy boundary. The second physiological
boundary separates heavy from severe exercise, but VT2, MLSS, critical power,
FTP, and Xert Threshold Power are not identical measurements. Describe the
actual anchor instead of silently substituting another.

## Interpret Heart Rate

- Treat heart rate as an integrated systemic cardiovascular response. It is
  shaped by central command, arterial and cardiopulmonary reflexes, cardiac
  parasympathetic and sympathetic influence, cardiac loading, thermoregulation,
  posture, and the preceding exercise state. It is not a direct measurement of
  VO2, muscular energy turnover, local demand, substrate use, or fatigue.
- Align heart rate with workload transitions, elapsed time, recovery structure,
  and accumulated prior work. Heart rate responds more slowly than power; do
  not interpret an immediate post-transition value as a settled response.
- Compare stable windows or equivalent elapsed-time windows in repeated bouts.
  Do not compare the beginning of one interval with the end of another.
- When power varies, prefer matched-work comparisons. Use HR/W as a descriptive
  workload-normalized response, not a direct measure of efficiency.
- During prolonged matched work, describe a progressive HR or HR/W increase as
  cardiovascular-drift evidence. Do not infer dehydration, heat limitation,
  threshold crossing, reduced fitness, or excessive cost from HR drift alone.
- Compare heart-rate recovery only across bouts with comparable ending heart
  rate, work intensity, recovery duration, recovery power, and prior work. A
  rapid fall does not prove complete metabolic, muscular, or modeled-capacity
  recovery.
- Interpret the early fall in HR after exercise mainly as cardiac-autonomic
  recovery behavior, with parasympathetic reactivation usually prominent. The
  later course also reflects slower sympathetic withdrawal and can be affected
  by metabolites, catecholamines, thermoregulation, active versus passive
  recovery, and posture. Preserve the exact elapsed recovery window instead of
  treating `HR recovery` as one protocol-independent value.
- Treat unexpectedly high or blunted heart rate as an observation requiring
  corroboration from power, environment, illness context, feel/RPE, and
  repeated matched personal evidence. Do not diagnose fatigue, illness,
  overreaching, or improved fitness from one response.
- A lower HR at the same nominal task can be compatible with aerobic adaptation
  or with acute accumulated strain. Favor either explanation only when task,
  execution, environment, timing, RPE or feel, and longitudinal personal
  evidence distinguish them.
- If in-exercise or immediate post-exercise HRV is available, apply the source
  protocol and quality constraints. Exercise intensity suppresses many HRV
  measures and non-stationarity makes short windows difficult to interpret. Do
  not use LF/HF as a direct measure of sympathetic-parasympathetic balance.
- Do not use heart rate alone to establish VT1, VT2, VO2max attainment, local
  muscular cost, training adaptation, or the cause of fatigue.

## Group Dependent Evidence

Group related outputs into evidence families before judging agreement:

1. `mechanical`: power, cadence, duration, sequence, and recovery architecture;
2. `systemic`: heart rate and the respiratory measurement family;
3. `local`: SmO2 and THb from the measured NIRS site;
4. `thermal_environmental`: wearable thermal pattern, ambient exposure, and
   cooling;
5. `subjective`: RPE, breathing sensation, local muscle feel, soreness, and
   symptoms;
6. `modeled`: Garmin, Xert, and other source-owned stimulus, strain, or recovery
   estimates.

Preserve these dependencies:

- BR, VT, and VE share one respiratory measurement chain. VE depends on BR and
  VT, so the three fields are complementary descriptions, not three independent
  confirmations.
- SmO2 and THb are derived from the same local optical NIRS measurement. Use
  them together to describe local oxygenation and heme-volume behavior, not as
  two independent sensors.
- Garmin aerobic Training Effect depends substantially on heart-rate-derived
  EPOC context. Anaerobic Training Effect also uses speed or power. Treat both
  as modeled stimulus, not independent confirmation of their inputs.
- A paired heart-rate signal can influence CORE sport-mode selection and data
  quality. Preserve wearable temperature as thermal evidence while disclosing
  this processing dependence when it matters.
- HR/W, BR/W, and VE/W share power as a denominator. Inspect both numerator and
  denominator because workload variation, coasting, window selection, or power
  error can make the ratios move together.
- Signals can share a physiological cause without sharing a sensor. Heat,
  accumulated work, posture, cadence, illness, or fueling can affect several
  streams together; aligned streams do not by themselves identify that cause.

Increase confidence primarily when distinct evidence families align in timing
and direction at matched work. Disagreement is information: report it and test
measurement quality, timing, expected domain response, and alternative
explanations before choosing a verdict.

## Separate Response From Cost

Do not use `high physiological response` and `high physiological cost` as
synonyms. Resolve four separate questions:

1. `response_magnitude`: how large the acute systemic, local, thermal, and
   subjective responses were;
2. `response_proportionality`: whether they were expected for the actual
   domain, work-recovery structure, and prior work;
3. `within_session_deterioration`: whether execution or internal response
   worsened during matched work;
4. `residual_cost`: what end-session feel, symptoms, soreness, and subsequent
   recovery evidence indicate after the acute work.

A large proportional response can be the purpose of severe intervals without
establishing excessive residual cost. A low HR can coexist with high local,
neuromuscular, or biomechanical cost. Do not infer residual cost solely from an
acute peak, source-model load, or Training Effect.

## Explain Competing Mechanisms

When the observed response differs materially from expectation:

1. State the observation without embedding a cause.
2. Identify which distinct evidence families changed together at matched work.
3. List no more than three mechanisms that fit the timing and session context.
4. For each mechanism, state the supporting observation, the necessary
   corroboration that is missing, and any observation that argues against it.
5. Rank each mechanism as `supported`, `plausible`, or `not_distinguishable`.
6. Preserve uncertainty when ordinary activity streams cannot separate the
   mechanisms.

Use `supported` only when distinct evidence families align and important
alternatives have been checked. Do not promote a mechanism merely because
several derived fields from one sensor chain agree. Prefer
`not_distinguishable` when two explanations predict the same observed field
pattern.

## Apply The Session Structure

Use these protocol-specific expectations after establishing the actual domain.
They do not override the athlete's anchors or the completed structure.

| Session structure | Primary analysis | Expected response | Common error to avoid |
| --- | --- | --- | --- |
| Continuous VT1 or moderate endurance | Stable matched-work windows plus late-session durability | Transition toward steady systemic response; later drift is possible with accumulated work | Treating all drift as threshold crossing, dehydration, or loss of fitness |
| Long heavy or subthreshold intervals | Within-interval development and equivalent late windows across repetitions | Delayed stabilization or a controlled slow rise; recovery may be incomplete without making the work severe | Calling every rise excessive, or assuming a nominal VT2/FTP target identifies the domain |
| Long severe or VO2 intervals | Complete work-recovery dose, repeatability, and progressive systemic/local response | Non-steady response; later repetitions can begin from an elevated baseline and accumulate more time at high internal response | Using peak HR, ventilation, SmO2, or a model label as proof of VO2max attainment |
| Short severe intervals or micro-intervals | Sequence, work-to-recovery ratio, power retention, and accumulated response across the set | Individual HR and respiratory responses lag; the set can maintain an elevated systemic response across repetitions | Grading each short repetition from HR or comparing it with a long-interval response |
| Sprint with long recovery | Peak/mean power, cadence/torque, repetition loss, and recovery duration | Large immediate mechanical demand with delayed HR/ventilation; longer recovery can restore more performance without proving complete recovery | Treating HR recovery as phosphocreatine, metabolite, or neuromuscular recovery |
| Over-under work | Time and power on each side of the individually resolved boundary, plus response across complete cycles | Response depends on excursion magnitude, duration, and recovery below the boundary; the average alone is insufficient | Classifying from average power or assuming every under segment restores homeostasis |
| Mixed outdoor ride | Separate sustained blocks, stochastic surges, coasting, terrain, and stops | Different blocks can occupy different domains and have different kinetics | Treating ride-average power, normalized power, or total load as one physiological exposure |
| Long ride with late quality | Compare the late block with matched fresh work after quantifying prior work | Fresh-state boundaries and response proportionality may not be preserved after substantial work | Calling deterioration a single limiter or forcing fresh target power late in the ride |

Recovery power and duration are part of the stimulus. Active recovery can keep
HR and VO2 elevated while reducing local reoxygenation or subsequent attainable
work; passive recovery can lower the starting systemic response yet permit
higher subsequent power. Therefore, compare intervals only when recovery
architecture is sufficiently matched, and never use the lowest recovery HR as
a general measure of the most complete physiological recovery.

## Synthesize The Verdict

Use this sequence:

1. **Actual session:** state what work was completed, independent of the title
   and modeled labels.
2. **Mechanical execution:** describe power, duration, pacing, interval and
   recovery structure, and target compliance.
3. **Expected response:** state what response was expected for the actual
   domain and dose.
4. **Observed response:** summarize response magnitude and proportionality from
   only the decisive physiological patterns, using matched windows and
   quality-controlled streams.
5. **Deterioration and residual cost:** state within-session deterioration
   separately from end-session or subsequent evidence of residual cost. Use
   `unknown` when the latter evidence is unavailable.
6. **Agreement and dependence:** identify which distinct evidence families
   agree, which conflict, and which outputs reuse the same measurements.
7. **Explanation:** distinguish observations from plausible contributors. Rank
   alternative explanations and state what remains unresolved.
8. **Classification:** classify acute response as `expected_and_controlled`,
   `expected_with_deterioration`, `unexpectedly_high_or_low`, or
   `uncertain_due_to_evidence`; classify residual cost separately as `low`,
   `moderate`, `high`, or `unknown`, and state confidence for each.
9. **Training consequence:** state achieved stimulus, supported residual cost,
   plan-role
   completion, progression effect, and the practical consequence for the rest
   of the day or next session.

Do not label a response excessive merely because it is high. High acute
response can be appropriate during severe work, and low acute response can be
appropriate during recovery or long low-intensity work. Judge proportionality
to the intended domain, completed dose, personal matched response, and
subsequent recovery evidence.

## Reporting Contract

For a normal request such as `analyser dagens økt`, report:

1. a direct one- or two-sentence verdict naming the actual session and whether
   it fulfilled its purpose at an appropriate cost;
2. mechanical execution and completed structure;
3. the integrated physiological response, not a sensor-by-sensor inventory;
4. what was expected, what materially differed, and the leading alternative
   explanations;
5. observed response separately from Garmin/Xert or other modeled stimulus and
   recovery outputs;
6. plan-role completion and the consequence for progression and subsequent
   training;
7. one targeted question only when missing feel, symptoms, setup, or intake can
   materially change the verdict.

When evidence is limited, give the best supported descriptive verdict and name
the uncertainty. Do not fill absent physiological evidence with a source-model
label or a generic zone interpretation.
