# Wearable Thermal Sensing

Use this reference when an activity contains CORE, estimated core temperature,
skin temperature, Heat Strain Index, or another wearable thermal signal. Treat
wearable thermal data as context for the acute response to exercise, not as a
stand-alone diagnosis of heat limitation, heat illness, hydration status, or
training readiness.

## Measurement Meaning

CORE estimates body-core temperature from wearable inputs that include heat
flux and skin temperature, with heart rate used in applicable operating modes.
It does not directly measure temperature at an invasive core site. Describe the
stream as `CORE-reported temperature` or a `wearable core-temperature
estimate` when the distinction matters.

Skin temperature is a local surface measurement. It is influenced by airflow,
clothing, sweat, sensor placement, ambient conditions, and peripheral blood
flow, and must not be treated as core temperature.

Heat Strain Index is a product-derived composite. Preserve the product name and
scale, and do not reinterpret it as a direct physiological measurement or a
medical heat-risk classification.

## Evidence Boundary

Independent validation findings are mixed and protocol-dependent:

- Verdel et al. found acceptable repeatability during cycling but poor
  agreement with rectal temperature under the tested low-to-high heat loads;
  approximately half of paired observations differed by more than the study's
  predefined `0.3 C` validity threshold.
- Januario et al. found the Calera Research Sensor reproducible and valid
  relative to gastrointestinal temperature during a specific cycling protocol
  at `32 C` and `60%` relative humidity, with reported confidence limits of
  approximately `+/-0.36 C`.
- Later constant-load cycling evidence in heat reported systematic
  overestimation relative to rectal temperature.

These findings support cautious use of within-session and matched-session
patterns. They do not support treating a single decimal reading as exact across
athletes, environments, protocols, sensor generations, or reference sites.

## Signal Quality And Setup

Before allowing a thermal signal to affect the verdict, inspect or resolve:

- device model and firmware when available;
- placement and attachment stability;
- whether the operating mode had the expected heart-rate connection;
- coverage, gaps, frozen values, abrupt steps, and implausible transitions;
- warm-up duration and whether the sensor had time to settle;
- ambient temperature, humidity, airflow, fan setup, clothing, and direct sun;
- cooling, drinking, posture, and changes in exercise intensity;
- whether the comparison uses the same sensor, placement, and protocol.

Report material unknowns. A complete-looking stream does not prove correct
placement, operating mode, or absolute accuracy.

## Interpretation

Prefer patterns over isolated values:

- rate and direction of change;
- continued rise versus a stable plateau;
- response during matched work blocks;
- recovery or continued rise after work ends;
- alignment with heart-rate-per-watt, respiration, power fade, skin
  temperature, environment, and athlete-reported heat sensation.

An absolute value such as `38.0 C` or `38.3 C` is not, by itself, evidence that
the athlete was heat limited. A stable plateau can provide useful thermal
context but does not establish that heat caused the observed cardiovascular,
respiratory, or mechanical response.

Do not infer dehydration from temperature, Heat Strain Index, heart-rate drift,
or skin temperature alone. Hydration and fueling require their own evidence.

## Evidence-Graded Thermal Language

Use the following claim levels:

### `thermal_context_present`

Use when a credible wearable thermal stream or relevant environmental exposure
is present. This level permits descriptive reporting but no causal claim.

Examples:

- "CORE reported a stable plateau around 38.1 C."
- "The session included a progressive wearable temperature rise."
- "The warm environment provides relevant thermal context."

### `thermal_cost_supported`

Use only when multiple aligned observations support increased thermal cost,
such as a meaningful temperature trend, relevant environmental or cooling
conditions, rising physiological cost at matched power, and athlete-reported
heat strain. State the supporting observations and important confounders.

### `heat_limited`

Reserve this for cases where heat is supported as a material constraint on the
session, not merely present. Require several aligned signals, normally
including deterioration in mechanical execution or inability to sustain the
planned work, a credible thermal pattern and exposure, corroborating acute
physiology, and athlete report. A helper label, absolute temperature cutoff, or
high Heat Strain Index alone is insufficient.

## Medical And Safety Boundary

Do not use CORE or another wearable thermal estimate alone to diagnose heat
illness or declare an athlete medically safe. Symptoms, behavior, performance
deterioration, environmental exposure, and appropriate clinical assessment
take priority. When heat illness is plausible, stop performance interpretation
and give conservative safety guidance rather than reasoning from a wearable
threshold.

## Reporting Contract

When thermal data materially influence an activity analysis, report:

1. device and setup when known;
2. coverage and important quality limitations;
3. environment and cooling context;
4. the within-session trend or matched blocks used;
5. alignment or disagreement with power, heart rate, respiration, skin
   temperature, and athlete report;
6. the evidence grade: `thermal_context_present`, `thermal_cost_supported`, or
   `heat_limited`;
7. confidence and the main unresolved confounders.

Keep thermal observations separate from mechanical execution, modeled
stimulus, total training load, hydration, and the final progression decision.

## Sources

- [Verdel et al. 2021: Reliability and Validity of the CORE Sensor to Assess
  Core Body Temperature during Cycling Exercise](https://doi.org/10.3390/s21175932)
- [Januario et al. 2024: Validity and reproducibility of the CALERA Research
  Sensor during cycling exercise in the heat](https://doi.org/10.1016/j.jtherbio.2024.103907)
- [Validity of the CORE wearable sensor during constant-load cycling exercise
  in the heat](https://doi.org/10.1016/j.jtherbio.2025.104241)
- [CORE: Research validation study](https://corebodytemp.com/pages/research-validation-study)

Treat the CORE page as manufacturer documentation. Use the independent studies
for claims about validity, reproducibility, agreement, and limitations.
