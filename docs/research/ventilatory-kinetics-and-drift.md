# Ventilatory kinetics, drift, and recovery

Reviewed 2026-11-23. This note records the assessment behind possible future
changes to cycling analysis and training planning. The starting literature
list was [VTCheck's science page](https://vtcheck.com/science), supplemented by
its [introductory article](https://vtcheck.com/blog/what-is-vtcheck) and
[drift-model article](https://vtcheck.com/blog/drift-part-i-drift-model-ramp-up-speed-and-slow-component-start).
Its [user guide](https://vtcheck.com/guide) describes the product's classification
method.

## Practical conclusions

- **During steady work, check whether breathing settles or keeps rising.**
  Compare breathing rate, tidal volume, reported minute ventilation (VE), and
  heart rate at similar power, cadence, prior workload, cooling, and sensor
  setup. Use perceived exertion to interpret the pattern. For recovery, also
  match the preceding effort and the duration and power of the break.
- **Use the wearable observations to describe the response.** The evidence
  for the shape of exercise and recovery responses comes mainly from
  laboratory measurements of oxygen uptake (VO₂). Using VitalPro VE drift or
  a 60-second recovery drop to identify VT1 or VT2 would require direct
  validation in the cycling protocol where we intend to use it.
- **At block review, interpret pulse and HRV alongside performance.** Take
  repeatable performance, perceived fatigue, and the response to easing the
  load into account before drawing a conclusion from lower working heart
  rate or higher HRV.

## What does drift at the same power tell us?

**Takeaway.** On a mechanically steady cycling block, compare the timing and
shape of BR, tidal volume, source-reported minute ventilation (VE), and pulse.
Distinguish the response to starting or changing power from a later rise
that levels off or continues to the end of the block. Interpret such a rise
using matched power, cadence, prior work, sensor setup, cooling, and
perceived exertion. A flat or rising wearable signal describes the observed
response. The exercise domain still requires corroboration.

- Controlled step-exercise studies show a delayed pulmonary VO₂ component
  above the first transition, with a delayed steady state possible in heavy
  exercise and no metabolic steady state above critical power in the severe
  domain. Critical power, VT2, and the rider's working target describe
  different measurements. The cited kinetics concern measured pulmonary VO₂
  and controlled protocols. See Özyener et al. (7), Poole & Jones (9), and the
  critical-power reviews (5–6).
- Colosio et al. (8) studied eight men in constant-load cycling trials. Their
  adjusted oxygen-equivalent cost stabilized after the initial phase in heavy
  exercise, consistent with a shift toward aerobic supply. It continued to
  rise in severe exercise. This supports describing the shape and considering
  more than one mechanism before attributing a rise to reduced efficiency,
  recruitment of particular fibres, or fatigue (8, 10).
- In Davies et al., induced muscle damage increased VE during moderate
  cycling. A separate experiment found a lower gas-exchange threshold without
  a corresponding shift in the lactate profile. Recent eccentric work and
  soreness therefore matter when judging an unusual ventilatory response.
  The magnitude of the response after an ordinary strength session remains
  uncertain (14–15).
- Cardiovascular drift can increase pulse while stroke volume falls; heat can
  amplify the change and raise relative physiological demand at fixed watts.
  Cooling and exposure provide additional evidence when judging the cause
  of a pulse rise in a specific session (16–18).

## What can recovery after an interval tell us?

**Takeaway.** Compare BR and VE recovery between equivalent efforts with the
same recovery duration and pause mode. Preserve the preceding effort, recovery
power, recording coverage, and sensor smoothing. A fixed-window drop is a
description of the observed respiratory response.

Özyener et al. measured pulmonary VO₂ during controlled cycling in six men.
Heavy exercise showed a slow component at exercise onset while the recovery
curve was adequately described by a single exponential. Some harder
conditions needed a second component in recovery. In a separate study of
eight trained male swimmers, maximal 200 m exercise and subsequent recovery
were both adequately fitted by single exponentials. Together these findings
make the preceding intensity and protocol important to the model choice.
Applying those VO₂ fits to wearable VE or using a 60-second interval to
classify cycling intensity would need separate validation (7, 9, 11).

## Which threshold methods transfer to a wearable?

**Takeaway.** Keep thresholds determined from a laboratory ramp, the wearable
test's own estimates, and drift during steady work as distinct observations.
Preserve the ramp protocol and the measurement that established each estimate.

Beaver et al. derive a gas-exchange breakpoint using VCO₂ relative to VO₂.
Hwang et al. compare automated VT1 and VT2 estimates from expired-gas
measurements with expert readings in 109 maximal cycle tests. Contreras-
Briceño et al. use respiratory rate from a distinct wearable and a specified
segmented regression during ramp testing. Whipp et al. show what can be
estimated from a laboratory cycling ramp. These protocols support specific
measurement methods. A conclusion about VitalPro or VTCheck's combination of
reference ventilation, drift, CUSUM, and a recovery score would require
validation against an appropriate reference under that product's own
protocol (1–3, B2).

## When does a change in pulse or HRV matter for planning?

**Takeaway.** When reviewing a training block, interpret lower working pulse
or higher HRV together with repeatable performance, perceived fatigue, achieved
work, and the response after easing the load.

Le Meur's experimental overload studies link autonomic or cardiac changes to
measured performance impairment in triathletes. Bellenger found that
post-exercise parasympathetic reactivation could increase during overload
while running performance and subjective tolerance worsened. The consensus
statement reinforces the limited specificity of individual markers. The
protocols distinguish resting HRV, post-exercise HRV, and the cardiac
response to a maximal test. Keep those signals separate when using them in a
block review (4, 12–13, 19).

## Application in training-ai

- Activity inspection reports matched changes per signal and groups recorded
  work intervals of similar duration for descriptive power comparisons. Linked
  recovery intervals provide context for judging repeatability.
- The analysis references define which respiratory observations are
  comparable across efforts and which uses require device and protocol
  validation. The planning reference interprets lower working heart rate and
  higher HRV at the existing block reviews.
- A middle window within the same long, steady effort could help distinguish
  a plateau from a continuing rise. That would need its own comparison
  method and checks for per-signal coverage.

## Sources

Numbers 1–19 follow VTCheck's science page. B1 and B2 trace the two additional
blog citations. Availability below refers to the archive. The assessment
used full text where accessible and original abstracts otherwise. Check the
full text, including the protocol and limitations, before using a study to
introduce an operational rule.

| Ref. | Publication | Archive |
| --- | --- | --- |
| 1 | Contreras-Briceño et al. (2024). Estimation of ventilatory thresholds during exercise using respiratory wearable sensors. [DOI](https://doi.org/10.1038/s41746-024-01191-9) | [Full-text XML](papers/respiration/contreras-briceno-2024-wearable-ventilatory-thresholds.xml) |
| 2 | Beaver, Wasserman & Whipp (1986). A new method for detecting anaerobic threshold by gas exchange. [DOI](https://doi.org/10.1152/jappl.1986.60.6.2020) | [PDF](papers/beaver-1986-v-slope.pdf) |
| 3 | Hwang et al. (2021). Novel computerized method for automated determination of ventilatory threshold and respiratory compensation point. [DOI](https://doi.org/10.3389/fphys.2021.782167) | [PDF](papers/hwang-2021-automated-ventilatory-thresholds.pdf) |
| 4 | Le Meur et al. (2013). Evidence of parasympathetic hyperactivity in functionally overreached athletes. [PMID 24136138](https://pubmed.ncbi.nlm.nih.gov/24136138/) | No local copy |
| 5 | Poole et al. (2016). Critical power: an important fatigue threshold in exercise physiology. [DOI](https://doi.org/10.1249/MSS.0000000000000939) | [Author manuscript PDF](papers/poole-2016-critical-power.pdf) |
| 6 | Jones et al. (2010). Critical power: implications for determination of VO₂max and exercise tolerance. [DOI](https://doi.org/10.1249/MSS.0b013e3181d9cf7f) | [PDF](papers/jones-2010-critical-power-exercise-tolerance.pdf) |
| 7 | Özyener et al. (2001). Influence of exercise intensity on the on- and off-transient kinetics of pulmonary oxygen uptake in humans. [PMC2278649](https://pmc.ncbi.nlm.nih.gov/articles/PMC2278649/) | [PDF](papers/ozyener-2001-oxygen-uptake-on-off-kinetics.pdf) |
| 8 | Colosio et al. (2020). Bioenergetics of the VO₂ slow component between exercise intensity domains. [PMC7476983](https://pmc.ncbi.nlm.nih.gov/articles/PMC7476983/) | [PDF](papers/colosio-2020-vo2-slow-component-bioenergetics.pdf) |
| 9 | Poole & Jones (2012). Oxygen uptake kinetics. [DOI](https://doi.org/10.1002/cphy.c100072) | [PDF](papers/poole-jones-2012-oxygen-uptake-kinetics.pdf) |
| 10 | Poole & Gaesser (2025, published online 2024). Oxygen uptake slow component: enigma of the ‘excess’ oxygen used during heavy and severe exercise. [PMC11689364](https://pmc.ncbi.nlm.nih.gov/articles/PMC11689364/) | [PDF](papers/poole-gaesser-2025-oxygen-uptake-slow-component.pdf) |
| 11 | Sousa et al. (2011). VO₂ off transient kinetics in extreme intensity swimming. [PMID 24150631](https://pubmed.ncbi.nlm.nih.gov/24150631/) | [PDF](papers/sousa-2011-oxygen-uptake-recovery-swimming.pdf) |
| 12 | Meeusen et al. (2013). Prevention, diagnosis and treatment of the overtraining syndrome. [European Journal of Sport Science DOI](https://doi.org/10.1080/17461391.2012.730061) | [PDF](papers/meeusen-2013-overtraining-consensus.pdf) |
| 13 | Bellenger et al. (2021). The impact of functional overreaching on post-exercise parasympathetic reactivation in runners. [DOI](https://doi.org/10.3389/fphys.2020.614765) | [PDF](papers/bellenger-2021-overreaching-parasympathetic-reactivation.pdf) |
| 14 | Davies, Rowlands & Eston (2009). Effect of exercise-induced muscle damage on ventilatory and perceived exertion responses to moderate and severe intensity cycle exercise. [DOI](https://doi.org/10.1007/s00421-009-1094-6) | No local copy |
| 15 | Davies et al. (2011). Eccentric exercise-induced muscle damage dissociates the lactate and gas exchange thresholds. [DOI](https://doi.org/10.1080/02640414.2010.526626) | No local copy |
| 16 | Coyle & González-Alonso (2001). Cardiovascular drift during prolonged exercise: new perspectives. [DOI](https://doi.org/10.1097/00003677-200104000-00009) | [PDF](papers/coyle-gonzalez-alonso-2001-cardiovascular-drift.pdf) |
| 17 | Souissi et al. (2021). A new perspective on cardiovascular drift during prolonged exercise. [DOI](https://doi.org/10.1016/j.lfs.2021.120109) | No local copy |
| 18 | Wingo, Ganio & Cureton (2012). Cardiovascular drift during heat stress: implications for exercise prescription. [DOI](https://doi.org/10.1097/JES.0b013e31824c43af) | No local copy |
| 19 | Le Meur et al. (2014). Maximal exercise limitation in functionally overreached triathletes: role of cardiac adrenergic stimulation. [DOI](https://doi.org/10.1152/japplphysiol.00191.2014) | No local copy |
| B1 | Burnley & Jones (2007). Oxygen uptake kinetics as a determinant of sports performance. [DOI](https://doi.org/10.1080/17461390701456148) | No local copy |
| B2 | Whipp et al. (1981). A test to determine parameters of aerobic function during exercise. [DOI](https://doi.org/10.1152/jappl.1981.50.1.217) | No local copy |

VTCheck's first citation has the correct title and DOI but attributes it to
Zignoli et al. The publication record names Contreras-Briceño et al. and
identifies it as article 198. Its Sousa link resolves to the 2011 swimming
paper. The local Meeusen copy is the parallel publication of
the same consensus statement in Medicine & Science in Sports & Exercise
([DOI](https://doi.org/10.1249/MSS.0b013e318279a10a)).
