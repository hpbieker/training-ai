# Respiratory Analysis

Use this reference when an activity contains Tyme Wear or another wearable
respiratory stream, especially breathing rate (`respiration`), tidal volume
(`tidal_volume`), or minute ventilation (`tidal_volume_min`). The source
registry and evidence boundaries are in [sources.md](sources.md).

## Role In Training Analysis

Treat wearable respiratory data as an acute within-session physiological
response. It complements, but does not replace:

- power, cadence, duration, and pacing for mechanical execution;
- heart rate and muscle oxygenation for other within-session responses;
- gas exchange for laboratory VO2, VCO2, and ventilatory-threshold assessment;
- Garmin or Firstbeat outputs for modeled stimulus and recovery context;
- Xert outputs for power-based strain, load, and capacity context;
- feel, breathing sensation, RPE, soreness, and next-day response.

Do not call Tyme Wear a metabolic cart. It measures thoracic movement and uses
device processing to report breathing rate and volume-related signals; it does
not directly measure respiratory gas concentrations, VO2, VCO2, blood lactate,
or arterial gases.

## Measurement And Validation Chain

Keep four distinct layers separate when deciding what published validation
supports:

1. thoracic movement recorded by the physical sensor;
2. BR extracted from the raw respiratory waveform by a stated algorithm;
3. Tyme Wear's proprietary live or exported BR, VT, and VE fields;
4. the downstream Garmin FIT and Intervals.icu streams used in this repository.

Validation at one layer does not automatically validate the following layers.
The favorable 2024 old-vest studies applied research algorithms to the raw
25 Hz waveform. They support the feasibility of extracting BR from that signal,
but do not independently validate VitalPro processing, absolute VT or VE, or the
Garmin-to-Intervals.icu export path. Resolve the device generation, field,
algorithm, averaging window, unit, and transport path before transferring an
error estimate or validation conclusion to an activity.

## Signal Meaning

### Breathing rate

Breathing rate (BR, respiratory frequency, or `respiration`) is breaths per
minute. It is the most directly observable Tyme Wear respiratory output and has
the strongest device-specific validation. During exercise, BR responds rapidly
to changes in effort and can align closely with perceived exertion. It is not a
pure metabolic measure: central command, muscle afferent feedback, voluntary
breathing, speech, emotion, and exercise transitions can also change it.

### Tidal volume

Tidal volume (VT or `tidal_volume`) represents the amount of air associated
with one breath. Tyme Wear estimates it from chest expansion rather than
measuring airflow at the mouth. Strap fit, position, thoracic-versus-abdominal
breathing, posture, movement, calibration, and device processing can affect the
reported value.

Treat Tyme Wear VT as a source-reported volume estimate or relative depth-of-
breathing signal unless the exact device, export, unit, and calibration have
been verified against a flow-based reference. Do not interpret it as a clinical
spirometry result.

### Minute ventilation

Minute ventilation (VE or `tidal_volume_min`) is conceptually the product of BR
and VT. For normalized Tyme Wear streams, verify internal consistency with the
exported scaling; the current Intervals.icu mapping is expected to approximate:

```text
VE = BR * VT
```

where the stored VT scaling may require conversion before multiplication.
Internal arithmetic consistency does not validate the absolute volume. Recent
device-specific evidence supports the shape of the VE signal more strongly than
agreement in true liters per minute. Use source-reported VE primarily for
within-athlete trends, matched-work comparisons, and response timing.

The current manufacturer study does not close this evidence gap. It discarded
two of every five breaths in its BR processing, smoothed VE over three breaths,
aligned device series at maximum VE, interpolated them onto a common time axis,
and reported VE mainly by pooled correlation. Without bias, limits of agreement,
absolute error, and participant-level results, this cannot establish agreement
in liters per minute or interchangeable threshold detection. Independent
VitalPro conference evidence likewise reports poor absolute VE agreement and
states that the volume output is not comparable to true liters per minute.

## Measurement Context

Before comparing sessions, resolve as much of this context as the available
artifacts provide:

- device generation, such as Tyme Wear Smart Shirt or VitalPro;
- firmware, app, data-field, and processing version when available;
- strap or garment size, tension, vertical position, and orientation;
- whether fit or placement changed during the session;
- cycling posture, hand position, and time out of the saddle;
- cadence, speech, deliberate breathing, coughing, drinking, and movement;
- protocol, power, cooling, temperature, altitude, and prior work;
- stream sampling, smoothing, gaps, and export scaling.

Prefer comparisons made with the same device generation, fit, placement,
posture, exercise mode, and processing path. When this cannot be established,
keep absolute VT and VE comparisons descriptive and lower confidence.

## VitalPro Setup And Recording

For the Tymewear VitalPro, use the manufacturer's current setup as the default
expected measurement configuration unless the activity context says otherwise:

- heart-rate sensor centered on the front of the chest and upright;
- breathing sensor on the back, below the shoulder blades;
- strap tight enough to remain stable but still comfortable;
- breathing sensor outside cycling-bib braces so the braces do not constrain or
  distort its movement;
- comparable strap tension, clothing, and riding position across sessions that
  will be compared.

The breathing sensor and heart-rate sensor are separate devices. Heart rate can
use standard ANT+ or Bluetooth pairing. Garmin receives the breathing sensor
over Bluetooth through the Tymewear Connect IQ data field, which writes the
respiratory developer fields into the FIT activity. The breathing pod can store
its own respiratory data when the phone is out of range, but it does not store
external power, pace, or heart-rate streams from other sensors.

For Garmin live guidance, Tymewear recommends `VE (30s MA)` rather than
instantaneous VE. Treat this as a display and pacing choice that reduces
short-term noise; it does not validate the absolute VE unit. Garmin Connect IQ
field limits can prevent the Tymewear fields from being recorded when too many
other developer data fields are active. A flat respiratory stream usually
indicates that the breathing sensor was not connected, not true zero breathing.

## VitalPro Threshold Test

The manufacturer's preferred cycling threshold test is an indoor trainer ramp
recorded only with the Tymewear App:

- reproduce normal clothing, strap setup, and riding position;
- warm up easily for 10-15 minutes;
- default first stage `70 W`;
- increase by `20 W` every `180 seconds`;
- continue until voluntary exhaustion;
- collect 2-3 stages below the first detected threshold and at least 2-3 stages
  above the second threshold when possible.

Tymewear identifies inflection points in its source-reported VE curve. The
complete algorithm is proprietary, and submitted tests are individually checked
by a Tymewear expert before results are released. Treat the approved threshold
set as a Tymewear product result with its own protocol and version, not as a
transparent laboratory gas-exchange determination.

The manufacturer recommends repeating the test every 6-8 weeks. Do not infer a
real threshold change merely because a later test differs: first check protocol,
strap tension, clothing, posture, environmental conditions, completeness, and
the size and direction of the change.

## Signal Quality

Assess signal quality before calculating peaks, drift, breakpoints, or
breathing-pattern changes.

At minimum, inspect:

- coverage during the relevant work and recovery blocks;
- number and duration of gaps;
- frozen or repeated values;
- abrupt isolated changes not aligned with workload or breathing rate;
- whether `VE` remains arithmetically consistent with `BR * VT` after applying
  the known export scaling;
- implausible BR values or sudden halving/doubling consistent with missed or
  double-counted breaths;
- strap movement, posture change, speech, drinking, or standing transitions;
- whether interval boundaries and respiratory timestamps are aligned.

Report quality limitations explicitly when they could change the conclusion.
Use rolling windows rather than single-sample extrema. A five-second rolling VE
value may be useful for short hard efforts, but it is not equivalent to a
laboratory breath-by-breath maximum if the source applies smoothing or breath
rejection.

Choose the averaging window for the question. Direct old-vest validation found
substantially lower BR error over 30-second windows than breath by breath or
second by second, so use 30-second or longer stable windows for matched-work
levels, drift, and cross-session comparison. Shorter windows may describe the
timing of rapid work-recovery transitions only when coverage and signal quality
are adequate. Averaging reduces random and breath-detection error, but can hide
brief responses; it does not improve the underlying sensor or validate a
different processing/export chain.

Also resolve the source's output delay before interpreting transitions. A
comparison RIP garment reported one-second values averaged from the last seven
completed breaths, which delayed rapid breathing changes relative to a
breath-by-breath reference. At high cycling intensity, torso movement and
garment movement also increased signal error. Do not assume a displayed or
exported timestamp represents an instantaneous response: document any known
breath averaging or filtering, allow for its lag, and avoid using short
work-recovery transitions for threshold or recovery timing when the effective
window is unknown. These Hexoskin findings establish a method-family risk, not
the exact delay or error of VitalPro.

## Within-Session Interpretation

Analyze BR, VT, and VE separately before combining them.

For a work interval, useful descriptive features include:

- stable-window BR, VT, and VE averages;
- early and late values at matched power;
- BR-, VT-, and VE-per-watt change when workload differs;
- whether rising VE is driven mainly by deeper breaths, faster breaths, or
  both;
- whether VT plateaus while BR continues to rise;
- response lag after workload transitions;
- repeatability across equivalent intervals;
- alignment with HR, SmO2, temperature, RPE, and breathing sensation.

For recovery, inspect the fall in BR and VE, the time course rather than only
the minimum, and whether recovery slows across matched repeats. Do not call a
rapid fall proof of complete metabolic recovery.

## Cross-Session Comparison

Match the work and measurement setup before interpreting respiratory drift.
Prefer sessions or blocks with comparable:

- target and actual power;
- cadence, posture, and interval structure;
- duration and prior accumulated work;
- temperature, cooling, humidity, and altitude;
- fueling, hydration, illness, and congestion;
- device fit, processing version, and signal quality.

Use BR/W and VE/W as workload-normalized descriptions, not physiological
efficiency constants. A higher VE/W at matched work can be consistent with
higher respiratory cost, heat, fatigue, prior work, illness, altered breathing
strategy, or measurement change; it does not identify the cause by itself.

Do not use a single universal BR, VT, VE, BR/W, or VE/W threshold to declare
that VT1 or VT2 was crossed or that a session was excessive. Existing fixed
thresholds in analysis helpers are experimental heuristics and must remain
subordinate to matched-work comparison, source quality, other physiology,
feel/RPE, and next-day response.

## Training-Domain Use

### Aerobic and VT1 work

Use BR, VT, and VE to describe respiratory stability during mechanically steady
work. A repeated rise in BR/W or VE/W can support a finding of higher late cost
when aligned with HR/W, temperature, SmO2, or worsening feel. It does not
independently prove that VT1 was crossed.

During prolonged controlled cycling, BR decoupling at fixed work has shown a
moderate association with loss of power at laboratory VT1, whereas VE
decoupling was not significantly associated. Use BR/W drift as a personal
durability candidate only in matched, stable work alongside HR/W, power,
temperature, fueling, hydration, and feel. The evidence does not supply a
universal percentage cutoff, identify a cause, or validate the published
prediction model for this athlete or ordinary field sessions.

Do not equate a late rise in BR with movement farther above VT1. In one
controlled study, power at laboratory VT1 fell after two hours while BR at VT1
rose, VT fell by a similar proportion, and true VE at VT1 remained
comparatively stable. Describe this combination first as a shift toward faster,
shallower breathing. It can coexist with reduced durability, but BR or VT drift
alone does not locate the current moderate-to-heavy transition.

The stable VE finding is a physiological hypothesis for true, flow-measured VE,
not validation of wearable VE. It came from indirect calorimetry in a small,
mostly male cohort during a fasted continuous protocol. Do not use a historical
laboratory VE-at-VT1 value as a VitalPro pacing boundary unless the exact
wearable and export path have shown adequate physical-unit agreement and
personal repeatability. Source-reported VitalPro VE remains a relative trend
signal under the validation limits above.

### VT2 work

Compare equivalent repeats and progression steps. Rising VE/W or BR/W, greater
BR reliance after VT stops rising, or slower recovery can be useful evidence of
increasing cost. Interpret the pattern with power stability, environment,
SmO2, RPE, and next-day recovery. Do not infer respiratory limitation merely
because ventilation is high.

### VO2 and severe work

BR can respond rapidly and may track effort well, while VT and VE estimates can
be more sensitive to movement and processing. Use rolling and repeated patterns
rather than a single peak. High BR or VE does not prove VO2max attainment.

### Threshold and graded tests

Tyme Wear-derived thresholds may be used as supporting evidence from a
standardized graded protocol. The older Smart Shirt validation found similar
reliability but lower validity than laboratory gas exchange and a tendency to
underestimate VT1/VT2 work rate, with larger individual errors among some
highly fit participants. Four of 19 participants were excluded after equipment
error or data loss, individual agreement was wide, and the investigators could
not separate sensor error from the proprietary algorithm. Cohort-level
test-retest reliability therefore does not establish individual threshold
agreement or transfer unchanged from the old shirt to VitalPro.

Respiratory-breakpoint detection is protocol and algorithm specific. One
peer-reviewed proof of concept estimated two thresholds from a mouth/nose
temperature-flow sensor using an `80 s/20 W` cycling ramp, a 30-second
Savitzky-Golay filter, and trilinear segmented regression. Its separate
107-person field cohort had plausible population averages but no individual
gas-exchange reference. This supports testing a prespecified RR-breakpoint
method in a standardized ramp; it does not validate visual breakpoint selection
in an ordinary activity, another smoothing window, Tyme Wear's algorithm, or
automatic transfer of population agreement to an individual.

The valid output set is zero, one, or two supported respiratory breakpoints.
Do not force two thresholds. Published graded-cycling work excluded participants
for low signal-to-noise ratio and pseudo-threshold risk, and a VT plateau was
not universal, especially near the first gas-exchange threshold. Before
accepting a candidate, require adequate coverage, a response spanning both
sides of the breakpoint, plausible ordering and separation, stability to small
changes in the fitted window, and corroboration from the standardized protocol
and other physiology. If those conditions fail, report that no reliable
respiratory threshold, or only one, was identifiable.

A current VitalPro manufacturer study reports low BR error and strong VE
correlation, but does not present threshold-result agreement and cannot
substantiate threshold accuracy from correlation alone. A 2026 independent
conference study reported strong BR agreement but poor absolute VE agreement.
Separate research on trained cyclists also found BR-breakpoint estimates too
individually imprecise to substitute for gas-exchange VT or respiratory
compensation point.

Keep manufacturer and independent evidence explicitly separated. Current
independent device-specific evidence supports breathing rate more strongly than
absolute tidal volume or minute ventilation, so do not generalize a favorable
vendor validation result to every respiratory field, protocol, device
generation, or export path.

Treat a Tyme Wear-derived threshold as a product-generated hypothesis tied to
its exact device, protocol, algorithm, and naming version. Do not write it into
the plan as authoritative VT1 or VT2 without the complete standardized protocol
and corroboration from power, HR, breathing/RPE, repeated response, and any
available laboratory evidence. When corroboration disagrees, retain the
disagreement rather than averaging the thresholds or silently selecting the
Tyme Wear value.

## Limiter And Efficiency Claims

Do not infer pulmonary disease, ventilatory constraint, respiratory-muscle
fatigue, poor oxygen delivery, or metabolic inefficiency from Tyme Wear alone.
The device does not measure flow-volume loops, gas exchange, arterial gases, or
work of breathing.

Use cautious language:

- allowed: "BR and source-reported VE rose at matched power";
- allowed: "the later interval relied more on breathing frequency while the
  reported VT changed little";
- allowed: "the pattern supports higher respiratory cost, but does not identify
  the cause";
- avoid: "ventilatory efficiency fell" unless efficiency is explicitly defined
  as a descriptive source ratio rather than clinical VE/VCO2;
- avoid: "Tyme Wear proves VT1/VT2";
- avoid: "high VE proves pulmonary or respiratory-muscle limitation".

## Reporting Contract

When Tyme Wear data materially influence an activity analysis, report:

1. device and fit/placement context when known;
2. signal coverage, export scaling, and important quality limitations;
3. the matched work or recovery windows being compared;
4. BR, VT, and VE separately, including what drove a change in VE;
5. whether values are source-reported estimates or verified physical units;
6. alignment or disagreement with power, HR, SmO2, temperature, and feel/RPE;
7. confidence and the main unresolved confounders.

Keep observed breathing response separate from measured gas exchange, modeled
stimulus, total training load, readiness, and the final progression decision.
