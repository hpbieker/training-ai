# Muscle Oxygen Analysis

Use this reference when an activity contains Moxy or another wearable NIRS
muscle-oxygen stream, especially `smo2` or `thb`. The source registry and
evidence boundaries are in [sources.md](sources.md).

## Role In Training Analysis

Treat muscle oxygenation as a local, acute physiological response measured at
the tissue beneath the sensor. It complements, but does not replace:

- power, cadence, duration, and pacing for mechanical execution;
- heart rate and respiratory streams for systemic within-session response;
- Garmin or Firstbeat outputs for modeled stimulus and recovery context;
- Xert outputs for power-based strain, load, and capacity context;
- feel, RPE, soreness, and next-day response for athlete-level interpretation.

Do not use SmO2 or THb as a general readiness score, whole-body oxygen measure,
direct VO2 measurement, blood-lactate measurement, or stand-alone proof of an
adaptation or performance limiter.

## Signal Meaning

### SmO2

SmO2 is the percentage of oxygenated heme reported from the local tissue sampled
by the sensor. During exercise, interpret it as a proxy for the local balance
between oxygen delivery and oxygen utilization. A decrease can reflect greater
local extraction relative to delivery; an increase can reflect greater delivery
relative to utilization. The signal alone cannot determine which side of that
balance changed.

SmO2 is specific to the measured muscle, site, side, sensor setup, and exercise
mode. It is not arterial oxygen saturation and must not be generalized to the
whole athlete.

### Signal Representation

Identify the representation before comparing or interpreting SmO2:

- `absolute SmO2`: the device-reported percentage at a given time;
- `delta SmO2`: change from an explicitly defined baseline or reference window;
- `desaturation`: the fall from a stated baseline to a stated work-window value;
- `normalized SmO2`: a value rescaled to an individual or protocol-specific
  range, whose anchors and formula must be reported;
- `bilateral mean`: the average of simultaneous left- and right-side signals,
  after checking both signals separately for quality and asymmetry.

These representations are not interchangeable. Do not compare a normalized
desaturation curve, bilateral modeled response, or change score directly with
raw single-site Moxy percentages. If the source artifact does not establish the
representation, keep the observation descriptive and do not calculate a
cross-session effect.

### THb

Moxy THb is a secondary total-heme signal influenced by local blood volume,
myoglobin, blood hemoglobin concentration, adipose tissue thickness, optical
path, and device processing. Do not interpret its absolute value as a clinical
hemoglobin concentration.

Use THb primarily as a within-bout or within-session direction of change under
a stable sensor setup. Prefer `delta_thb`, slope, or a plainly described trend
over an absolute THb comparison. Do not compare absolute THb between athletes,
measurement sites, sensors, or sessions with uncertain placement.

Do not use resting or exercising SmO2 or Moxy THb to infer anemia, systemic
hemoglobin concentration, total hemoglobin mass, blood volume, or whole-body
oxygen-transport capacity. Local THb can covary with intravascular-volume
measures in a study sample without becoming a clinical or systemic blood
measurement.

## Measurement Context

Before making a cross-session comparison, resolve as much of this context as
the available artifacts provide:

- sensor make/model and, when available, sensor identity;
- measured muscle and anatomical placement;
- left or right side;
- attachment and light-shield use;
- sampling/update mode and smoothing;
- skin preparation and whether hair, lotion, or a tattoo could interfere;
- power, cadence, posture, cooling, temperature, and exercise protocol;
- whether the comparison uses the same sensor, site, and protocol.

Prefer comparisons from the same muscle, side, placement, device setup, and
protocol. If those conditions are not established, keep the comparison
descriptive and lower its confidence. Do not infer bilateral equivalence from
leg dominance. Treat a change of muscle, side, placement, sensor identity, or
device family as a broken comparison unless a protocol-specific validation
supports the transformation.

When two sensors are used bilaterally, inspect and report each side before any
average. Bilateral averaging can answer a protocol-specific whole-task question
and may reduce side-specific noise, but it can also conceal asymmetry, dropout,
or placement error. Do not substitute one leg for the other or reuse a
bilateral average as though it were a single-site absolute measurement.

State which bilateral feature is being combined or compared. Absolute level,
response amplitude, breakpoint location, time delay, time constant, and mean
response time have different agreement properties. Evidence that bilateral
averaging improves one protocol's breakpoint agreement does not validate an
average of timing kinetics or establish interchangeability with a systemic
threshold.

## Signal Quality

Assess signal quality before calculating or interpreting extrema, drift,
breakpoints, or recovery kinetics.

At minimum, inspect:

- coverage during the relevant work and recovery blocks;
- number and duration of gaps;
- frozen or repeated values;
- abrupt isolated steps or spikes that are not aligned with workload;
- implausible discontinuities present in SmO2 but absent from the other
  physiological and mechanical streams;
- loss of data at high movement or contraction intensity;
- whether interval boundaries and sensor timestamps are aligned.

Report a quality limitation explicitly when it could change the conclusion.
Do not turn a minimum, maximum, or half-drift value into evidence when it may be
driven by one sample, a dropout boundary, or an attachment artifact. Prefer
robust windowed or percentile estimates when available.

## Within-Session Interpretation

Align SmO2 and THb with power, cadence, heart rate, ventilation, breathing rate,
temperature, interval structure, and recovery duration.

For a work interval, useful descriptive features include:

- pre-work SmO2 baseline from a stable window;
- early and late work-window SmO2;
- SmO2 change and slope during the work interval;
- a robust low value rather than a single-sample minimum;
- whether the pattern repeats across equivalent intervals;
- THb direction of change under the same placement;
- physiological cost per watt when workload differs between intervals.

For a recovery interval, useful features include:

- SmO2 at recovery start;
- early reoxygenation slope;
- rise from a robust work nadir;
- time to a defined fraction of the recovery amplitude, such as 50% or 90%;
- the level reached at a fixed elapsed time;
- whether recovery kinetics slow across repeated equivalent intervals;
- THb direction during recovery.

Avoid using unrestricted recovery maximum as the main reoxygenation outcome:
it is sensitive to recovery duration, overshoot, and isolated samples. Compare
fixed windows or normalized recovery kinetics when possible.

Name the reoxygenation metric and its windows every time it materially affects
the conclusion. Acceptable examples include rise in percentage points during a
fixed interval, slope over a stated early-recovery window, time to a defined
fraction of the available recovery amplitude, or a fitted time constant with
its model and fitting window. These metrics answer different questions and must
not be called equivalent merely because all describe "reoxygenation." If two
activities use different definitions or recovery durations, do not rank their
reoxygenation speed.

Also match the preceding exercise intensity and measured muscle. Published
Moxy protocols show that recovery kinetics depend on workload and site, and
that the intensity relationship can flatten near maximal work. Do not compare
half-recovery time, a fixed 30-second slope, a fitted early-recovery rate, a
time constant, or time to an unrestricted maximum as though they were the same
outcome. A longitudinal change in any one of them is an observation, not an
adaptation, until repeated matched testing and performance or systemic evidence
support that interpretation.

When a fractional-recovery metric normalizes a work nadir to a recovery
maximum, inspect how both anchors were obtained. Do not use isolated or very
short extrema as anchors without a sensitivity check against robust windowed
values. Report the normalization formula, anchor windows, and available
recovery duration; a protocol-specific 50% recovery time is not a general
recovery score.

## Direction Is Not Value

Do not label lower SmO2, greater desaturation, faster reoxygenation, or a changed
THb trend as inherently better or worse. The same direction can reflect changed
work, pacing, cadence, posture, local extraction, oxygen delivery, superficial
tissue contribution, recovery duration, sensor conditions, training status,
local strength, or muscular endurance.

Before assigning training meaning, establish whether mechanical execution and
comparison conditions were matched, then check performance, systemic response,
feel/RPE, and subsequent recovery. State the observed direction first and the
plausible explanations second. A favorable or unfavorable adaptation claim
requires repeated matched evidence and cannot be inferred from direction alone.
Cross-sectional differences between athlete groups describe phenotype-linked
associations, not adaptation caused by training. Do not use greater
desaturation as a quality or fitness score.

## Cross-Session Comparison

Match the work before interpreting a changed SmO2 response. Prefer repeated
sessions or blocks with comparable:

- target power and actual power;
- cadence and posture;
- interval and recovery duration;
- prior work in the session;
- thermal and cooling conditions;
- fueling and hydration context;
- sensor placement and signal quality.

Treat a material cadence difference as a mechanical confounder even when power
is identical. Cadence can change local oxygenation and redistribute joint and
muscle work at the same external workload. If cadence or pedaling mechanics are
not matched, describe the SmO2 difference but do not quantify it as local
physiological drift or adaptation without corroboration.

For absolute cross-session comparisons, also establish comparable adipose
tissue thickness at the site and attachment pressure when that information is
available. A changed sensor family, compression garment, fixation method, or
meaningfully different pressure is a broken absolute comparison unless a
protocol-specific calibration validates it. Physiological calibration can make
some within-protocol changes more comparable; it does not make raw absolute
outputs from different devices interchangeable.

Use the athlete's repeated personal pattern rather than population-wide
absolute cutoffs. Published cycling studies report good relative reliability
but typical absolute error of several SmO2 percentage points and minimum
detectable changes that can reach the low-to-high teens. Therefore, a small
absolute difference between two days is not automatically physiological.

Published Moxy studies generally support useful test-retest reliability during
controlled cycling, but absolute agreement and reliability vary with exercise
intensity, placement, movement, and protocol. Reliability is not criterion
validity, correlation is not agreement or interchangeability, and face validity
during arterial occlusion is not validation of ordinary exercise
interpretations. None of these establishes that an absolute SmO2 value
identifies a training zone, threshold, adaptation, or physiological limiter.

Do not use a single universal SmO2 minimum or drift threshold to declare that
VT1, VT2, or VO2 intensity was exceeded. Any existing fixed thresholds in
analysis helpers are experimental heuristics and must remain subordinate to
signal quality, matched-work comparison, other physiology, feel/RPE, and
next-day response.

## Evidence And Model Validation

Classify a study claim before applying it:

- `association`: variables changed together in the observed sample;
- `model fit`: a model reproduced or explained the data used to construct it;
- `internal prediction`: predictions were tested within the same participants
  or data-generating protocol;
- `external validation`: a fixed method was prospectively tested in independent
  participants and conditions.

Do not describe association, model fit, or internal prediction as external
validation. Preserve sample, exercise mode, preprocessing, fitting window, and
validation design. In particular, do not substitute an ordinary workout SmO2
slope for CP/CV, W-prime/D-prime balance, or time-to-exhaustion testing merely
because a small controlled dataset produced a strong fit.

## Training-Domain Use

### Aerobic and VT1 work

Use SmO2 to describe stability or changing local cost during mechanically
steady work. A falling SmO2 pattern can be relevant when it repeats, exceeds
normal measurement variation, and aligns with rising HR-, BR-, or VE-per-watt,
heat strain, or worsening feel. It does not independently prove that the
athlete crossed VT1.

Treat progressive SmO2 drift during stable power as corroborating evidence of
changing local cost only when cadence, posture, cooling, sensor conditions, and
work structure remain comparable. Check whether systemic physiology, RPE, or
available lactate evidence also drifts. Do not transfer absolute drift values
from elite rowing, interrupted sampling protocols, or another sport into a
universal cycling rule.

### VT2 work

Use SmO2 and reoxygenation to compare equivalent repeats and progression steps.
Potentially useful patterns include progressively greater desaturation at the
same work, slower recovery kinetics, or failure to return toward the athlete's
normal between-interval level. Interpret these together with power stability,
HR/BR/VE per watt, breathing/RPE, environment, and next-day recovery.

Low SmO2 at the end of a hard but well-executed interval can be an expected
local response. It is not, by itself, evidence that the workout was excessive.

### VO2 and severe work

Movement artifact and data loss may increase at high intensity. Favor repeated
patterns and windowed kinetics over a single minimum. SmO2 can describe local
deoxygenation and recovery, but it does not replace respiratory VO2, nor does a
specific SmO2 value establish VO2max attainment.

A negative SmO2 slope has separated sustainable from unsustainable work in
small standardized constant-load or time-to-exhaustion protocols. Apply that
finding only when work rate and measurement conditions match the validated
protocol closely. In ordinary intervals or variable outdoor work, changes in
power, cadence, posture, recovery, temperature, and sensor contact prevent the
slope from independently classifying work as above CP or predicting W-prime
depletion.

### Threshold and graded tests

NIRS breakpoints can be used as supporting evidence in a standardized graded
test. Published work reports only moderate agreement with ventilatory
thresholds and indicates that breakpoint estimates may be biased. Do not write
an NIRS-derived breakpoint into the plan as VT1 or VT2 without corroboration
from the complete protocol and other threshold evidence.

State the threshold provenance explicitly:

- `SmO2-detected breakpoint`: the threshold was derived independently from the
  shape of the SmO2 signal using a defined algorithm;
- `SmO2 at an external threshold`: SmO2 was sampled or interpolated at a
  threshold first determined from lactate, gas exchange, power, or another
  method.

The second design describes SmO2 corresponding to an established threshold; it
does not validate SmO2 as an independent threshold detector. Do not collapse
the two designs in source summaries, comparisons, or training prescriptions.

Apply an evidence hierarchy to independently detected breakpoints. Evidence for
the first breakpoint is currently weaker and less repeatable than evidence for
the second: do not use MOT1/BP1 to set LT1 or VT1 without independent
corroboration. MOT2/BP2 can corroborate an upper threshold in a standardized
graded protocol, but group-level agreement does not make the individual values
interchangeable. Preserve the breakpoint algorithm, stage duration and size,
exercise mode, muscle, side handling, sensor, and tested population; do not
promote Exp-Dmax or any other best-performing method in one dataset to a
universal default.

An absolute cutoff derived inside one study sample is an internally fitted
classification, not an independently validated athlete threshold. Preserve how
the cutoff was derived, its sensitivity and specificity, the tested population,
and whether it was validated on separate participants. Do not transfer such a
cutoff to an individual workout or use it for precise intensity control.

## Limiter Claims

Do not infer a cardiac, pulmonary, oxygen-delivery, or muscle-utilization
limiter from one ordinary workout pattern. Such claims require a standardized
protocol, reliable placement, adequate signal quality, repeatability, and
appropriate corroborating measurements. Vendor limiter frameworks are useful
as hypotheses to test, not independent diagnoses.

Use manufacturer material for device semantics, placement, signal transport,
and the manufacturer's intended workflow. Treat claims about universal zones,
daily readiness, mitochondrial function, optimal interval duration, recovery
completion, or causal limiter identification as manufacturer hypotheses unless
independent evidence directly validates the same claim and use case.

Use cautious language:

- allowed: "local SmO2 fell more during the later matched intervals";
- allowed: "reoxygenation was slower than in the earlier matched recoveries";
- allowed: "the pattern is consistent with higher local oxygen extraction
  relative to delivery, but does not identify the cause";
- avoid: "oxygen delivery failed";
- avoid: "Moxy proves a cardiac or pulmonary limitation";
- avoid: "SmO2 establishes the lactate threshold".

## Reporting Contract

When Moxy data materially influence an activity analysis, report:

1. measurement site and setup when known;
2. signal coverage and important quality limitations;
3. signal representation, side handling, and any normalization;
4. the matched work or recovery windows being compared;
5. SmO2 pattern and the exact recovery-kinetics metric;
6. THb trend only when the setup is stable and the trend is interpretable;
7. alignment or disagreement with power, HR, respiration, temperature, and
   feel/RPE;
8. threshold provenance or model-validation level when either affects the
   interpretation;
9. confidence and the main unresolved confounders, including relevant athlete
   phenotype differences.

Keep observed local response separate from modeled stimulus, total training
load, readiness, and the final progression decision.
