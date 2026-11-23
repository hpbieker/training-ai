# Training Analysis Sources

This is the shared source registry for reference files owned by the
`training-analysis` skill. Organize each subject under its own clearly named
topic section, with a separate claim-to-source map and known evidence gaps when
the topic needs them. It currently covers
[muscle-oxygen.md](muscle-oxygen.md),
[respiration.md](respiration.md), and
[physiological-response-synthesis.md](physiological-response-synthesis.md).
Cycling durability, CP/W-prime, thermal-strain, and fueling-context evidence is
maintained in
[cycling-endurance-physiology.md](cycling-endurance-physiology.md). Do not merge
claims from unrelated model families merely because they are used in the same
activity analysis.

The physiological-response section owns evidence for heart-rate interpretation,
intensity-domain response expectations, and dependence between measurement or
model outputs. It does not duplicate device-specific validity evidence already
registered under muscle oxygen or respiration.

## Evidence Hierarchy

Use sources in this order:

1. Peer-reviewed independent validation or reliability studies for accuracy,
   repeatability, agreement, and measurement limitations.
2. Peer-reviewed physiology studies for associations and protocol-specific
   applications.
3. Current manufacturer technical documentation for device outputs,
   transmission, placement, and intended operation.
4. Manufacturer training material for hypotheses and practical frameworks.

Do not treat manufacturer education as independent validation. Name conflicts
of interest or manufacturer involvement when it materially affects the weight
of a claim. Preserve the tested population, muscle, sport, protocol, and device
when transferring a result to training analysis.

Register a research article as a source only after its full text has been
read. An abstract, citation record, search-result extract, or another paper's
description of it can identify a candidate source but cannot support a rule in
this skill. If full text is unavailable, omit the article and narrow or remove
the dependent claim.

## Integrated Physiological Response

Use this section for heart-rate kinetics, cardiovascular drift,
intensity-domain response expectations, and dependence between physiological
signals or modeled outputs. Use the device-specific sections below for
measurement accuracy, reliability, placement, and field semantics.

| Source | Supports | Strength and limitation |
| --- | --- | --- |
| [Bearden and Moffatt 2001: VO2 and heart-rate kinetics during cycling transitions](https://doi.org/10.1152/jappl.2001.90.6.2081) | Heart rate and VO2 respond dynamically after workload transitions; response kinetics depend on exercise baseline and prior work | Peer-reviewed controlled cycling study. Supports allowing for transition kinetics and comparing equivalent windows; does not provide one universal settling time for field analysis |
| [Michael et al. 2017: Cardiac autonomic responses during exercise and recovery](https://doi.org/10.3389/fphys.2017.00301) | Autonomic regulation across exercise intensity; fast and slow phases of post-exercise heart-rate recovery; effects of intensity, duration, modality, posture, and recovery protocol on HRV and recovery | Peer-reviewed physiology review. Strongest here for autonomic mechanisms and methodological limits of HRV; it does not make ordinary exercise HR a direct measure of sympathetic activity, metabolic recovery, or whole-body readiness |
| [Schneider et al. 2018: Contextualizing heart-rate monitoring](https://doi.org/10.3389/fphys.2018.00639) | Separation of strain, fatigue, recovery, fitness, and adaptation; need for standardized individual comparisons and multivariate context | Peer-reviewed technology report focused on longitudinal monitoring in team sports. Supports contextual interpretation and matched personal baselines, not a cycling-specific causal diagnosis from one session |
| [Coyle and Gonzalez-Alonso 2001: Cardiovascular drift during prolonged exercise](https://doi.org/10.1097/00003677-200104000-00009) | Classic cardiovascular drift can occur without dehydration; interactions among heart rate, stroke volume, core temperature, and blood volume; dehydration and hyperthermia can amplify drift | Peer-reviewed short mechanistic review drawing heavily on experiments from the same research group. Useful for mechanism and definitions, but insufficient for identifying the cause of ordinary field drift |
| [Watanabe et al. 2020: Dehydration, cardiac filling, and stroke volume](https://doi.org/10.14814/phy2.14433) | Dehydration-related reduction in stroke volume and cardiac output during prolonged cycling in heat | Peer-reviewed mechanistic study in eight trained participants during approximately two hours of cycling in 35 degrees C, with approximately 4% body-mass loss in the dehydration condition. Protocol-specific and insufficient for attributing ordinary field drift to dehydration without corroborating evidence |
| [Black et al. 2017: Fatigue across cycling intensity domains](https://pmc.ncbi.nlm.nih.gov/articles/PMC5429469/) | Distinct metabolic and neuromuscular behavior in moderate, heavy, and severe cycling domains | Peer-reviewed experimental physiology. Supports domain-dependent response expectations; boundaries require individual physiological anchors |
| [Meyler et al. 2023: Variability in responses to threshold- and percentage-based prescription](https://pmc.ncbi.nlm.nih.gov/articles/PMC10103872/) | Threshold-based prescription reduced variability in exercise completion and, during severe intervals, blood lactate and modeled W-prime depletion compared with percentage-of-VO2max prescription | Peer-reviewed crossover study in ten participants. It did not show lower variability in heart-rate or VO2 responses; supports individualized domain placement, not universal response cutoffs |
| [Schoenmakers et al. 2021: Recovery intensity during cycling HIIT](https://doi.org/10.1007/s00421-020-04535-x) | Recovery intensity changes subsequent attainable power, recovery HR and VO2, local oxygenation, and perceived session cost; similar high-VO2 exposure can arise from different recovery responses | Peer-reviewed crossover study in fourteen well-trained cyclists using self-paced 6 x 4-minute and 3 x 8-minute protocols. Supports treating recovery architecture as part of the stimulus, not one universally optimal recovery mode |
| [Garmin: About Training Effect](https://www8.garmin.com/manuals/webhelp/d2charlie/EN-US/GUID-7275629E-743A-4658-A284-C84F42A66AE5.html) | Aerobic Training Effect uses heart rate and accumulated EPOC context; anaerobic Training Effect uses heart rate plus speed or power | Official product documentation. Establishes input dependence and intended model meaning, not independent physiological validation |
| [Firstbeat: EPOC Based Training Effect Assessment](https://www.firstbeat.com/app/uploads/2015/10/white_paper_training_effect.pdf) | Heart-rate-derived EPOC and Training Effect model structure; effects of illness, environment, and altered physiological responses on model output | Manufacturer white paper. Useful for model provenance and confounding, not independent proof of adaptation or recovery cost |
| [CORE: Data Quality](https://help.corebodytemp.com/hc/en-us/articles/35510068959250-Data-Quality) | Paired heart rate influences sport-mode selection and thermal-data quality assessment | Official product documentation. Supports dependence between HR and CORE processing; it does not disclose the full temperature-estimation algorithm |

### Integrated Response Claim-To-Source Map

| Claim | Minimum source basis | Allowed interpretation |
| --- | --- | --- |
| Heart rate at the start of an interval represents the interval's physiological demand | Cycling kinetics evidence shows a delayed response after workload transitions | Align HR with elapsed time and workload history; compare stable or equivalent interval windows rather than immediate post-transition values |
| Exercise heart rate directly measures metabolic energy turnover, muscular demand, or oxygen uptake | Autonomic reviews describe HR as an integrated cardiovascular response shaped by feedforward command, reflexes, parasympathetic and sympathetic influence, cardiac loading, and thermoregulation | Use HR as one systemic response to the task; do not translate it directly into local demand, VO2, substrate use, or metabolic cost |
| A lower HR at the same nominal submaximal task proves improved fitness or acute fatigue | Monitoring evidence shows that similar HR changes can reflect adaptation, accumulated training strain, recovery state, environment, or other context | Require a standardized task, matched execution and environment, RPE or feel, and a longitudinal personal pattern before favoring adaptation or fatigue |
| Rising HR at stable power proves declining fitness or excessive training cost | Cardiovascular-drift studies support several possible mechanisms | Describe cardiovascular drift and assess magnitude, timing, environment, hydration, prior work, and athlete feel; do not infer the cause from HR alone |
| HR drift proves dehydration | Dehydration studies show that dehydration can increase cardiovascular strain, not that drift uniquely identifies dehydration | Treat dehydration as a hypothesis requiring fluid, body-mass, thermal, or subjective evidence |
| Rapid HR recovery proves complete recovery between intervals | No supporting source establishes complete metabolic, muscular, or W-prime recovery from HR alone | Use HR recovery descriptively across matched recoveries; do not equate it with complete recovery |
| One recovery-HR value identifies autonomic state regardless of protocol | Autonomic recovery depends on preceding intensity and on active versus passive recovery, posture, elapsed time, and other methodological choices | Compare the same elapsed recovery window under matched ending load, recovery activity, and posture; describe early HR recovery primarily as cardiac-autonomic behavior, not total recovery |
| Moderate, heavy, and severe cycling should show the same time course if power is controlled | Intensity-domain studies show qualitatively different metabolic and physiological behavior | Judge response relative to the individually anchored domain and the expected kinetics for that domain |
| A progressive response during VT2 or severe work is necessarily abnormal | Heavy and severe domains can produce delayed steady state or non-steady-state responses | Decide whether the response is expected for the domain, dose, and accumulated work before calling it excessive |
| High HR, BR, VE, or low SmO2 proves that a VO2 session achieved VO2max | No field stream alone directly measures VO2max attainment | Describe a severe-intensity response and assess completed mechanical dose; reserve VO2max attainment for direct or appropriately validated evidence |
| Several aligned fields always provide several independent confirmations | BR, VT, and VE share one respiratory chain; SmO2 and THb share one NIRS chain; modeled outputs reuse HR or power | Group related fields into evidence families and increase confidence primarily when distinct families align |
| HR/W, BR/W, and VE/W are independent evidence | The ratios share power as a denominator and can co-move because of workload variation or power error | Use them as complementary descriptions; inspect the underlying numerator and denominator before treating alignment as corroboration |
| Garmin Training Effect independently confirms the observed HR or power response | Garmin documents HR and power or speed as model inputs | Treat Training Effect as modeled stimulus derived partly from the observed streams, not independent confirmation |
| CORE temperature is independent of HR whenever both streams are present | CORE documents HR-dependent sport-mode and data-quality processing | Preserve the thermal signal as a distinct measurement family but disclose processing dependence when paired HR is used |
| The recovery with the lowest HR proves the most complete recovery | HR recovery, local oxygenation, metabolic restoration, and subsequent attainable power are distinct outcomes; recovery intensity changes them differently | Describe HR recovery and subsequent execution separately, preserving recovery power and duration; do not infer complete metabolic or neuromuscular recovery |

### Integrated Response Known Evidence Gaps

- There is no universal settling time after a workload transition that applies
  to every athlete, intensity domain, prior-work state, and field protocol.
- There is no universal HR, HR/W, BR/W, VE/W, SmO2, or combined-signal cutoff
  that proves excessive physiological cost.
- Ordinary activity streams cannot uniquely distinguish cardiovascular,
  respiratory, local muscular, thermal, nutritional, motivational, or
  measurement causes of an altered response.
- VT1, VT2, MLSS, and critical power are related physiological anchors but are
  not interchangeable values. Expected response must use the athlete's actual
  anchor and the protocol by which it was established.
- Field evidence does not establish a validated numerical method for counting
  correlated sensors or assigning independent statistical weights to evidence
  families.
- A personally unusual high or blunted heart-rate response requires repeated
  matched evidence and corroboration; one session does not diagnose fatigue,
  illness, overreaching, or improved fitness.
- Garmin, Firstbeat, CORE, Tyme Wear, and NIRS processing are partly
  proprietary. Public documentation can establish known inputs and intended
  semantics but not every dependency inside the algorithms.

## Moxy, SmO2, And THb

Use [Muscle Oxygen Analysis](muscle-oxygen.md) for routine interpretation.
The [muscle oxygenation research note](../../../../docs/research/muscle-oxygenation.md)
contains the study inventory, source assessments, and known evidence gaps.

## Tyme Wear, BR, VT, And VE

| Source | Supports | Strength and limitation |
| --- | --- | --- |
| [Tyme Wear: VitalPro product description](https://www.tymewear.com/pages/vitalpro-strap) | Current manufacturer claim that VitalPro reports breathing rate, tidal volume, minute ventilation, and heart rate | Official product semantics only. It does not establish independent accuracy, physical-unit agreement, or threshold validity |
| [Tymewear: Setup your VitalPro](https://www.tymewear.com/blogs/startup-guides/setup-your-tymewear-vitalpro) | Current manufacturer placement: heart-rate pod centered in front, breathing sensor behind below the shoulder blades, stable strap tension, and breathing sensor outside cycling-bib braces | Official operational guidance. Establishes intended setup, not measurement accuracy or the athlete's actual setup in a completed activity |
| [Tymewear: Threshold Test](https://www.tymewear.com/blogs/startup-guides/threshold-test) | Current indoor cycling protocol, clothing/posture repeatability, `70 W` start, `20 W` increments, three-minute stages, VE-inflection method, manual result validation, and 6-8 week retest recommendation | Official product workflow. The complete detection algorithm and expert-review criteria are not disclosed, and the protocol is not equivalent to laboratory gas-exchange testing |
| [Tymewear: Garmin bike computers](https://www.tymewear.com/blogs/connectivity/garmin-bike-computers) | Separate HR and breathing-sensor connections, Connect IQ recording into Garmin activities, developer-field limits, current device setup, manually entered threshold values, and recommendation to display `VE (30s MA)` | Current official connectivity documentation. Operational behavior can vary with Garmin device, firmware, Connect IQ version, and available developer fields |
| [Tymewear: Recording activities](https://www.tymewear.com/blogs/startup-guides/recording-activities) | App-versus-device recording paths, onboard breathing-pod storage, absence of external-sensor data from pod-only storage, synchronization, and FIT import | Current official data-flow documentation. It explains transport and persistence, not physiological accuracy |
| [Tymewear: Updated Training Zones](https://www.tymewear.com/blogs/recent-product-updates/updated-training-zones-in-tymewear) | February 2026 naming migration: former `VT1` to `Endurance`, former `Balance Point` to current `VT1`, with `VT2` retained; detection and target values unchanged | Current official naming semantics. Stored historical metadata can retain old labels, so name and value must be interpreted together with schema/version context |
| [Tyme Wear 2026: VitalPro versus Cosmed K5](https://www.tymewear.com/blogs/validation-studies/tymewear-internal-validation-study-of-breathing-metrics) ([local HTML](../../../../docs/research/papers/respiration/tymewear-2026-vitalpro-cosmed-k5-manufacturer-validation.html)) | Manufacturer study in 26 athletes during an indoor three-minute-stage cycling ramp: BR MAE of 1.2 breaths/min and pooled VE correlation of `r=0.973`; BR processing discarded two of every five breaths, VE used a three-breath moving average, the series were aligned at maximum VE, and a common interpolated time axis was created | Unpublished manufacturer validation with no reported participant-level errors, VE bias, limits of agreement, absolute VE error, test-retest reliability, or threshold-result comparison. The reported age of `27 ± 21 years` also warrants clarification. Correlation and aligned/interpolated series do not establish agreement in liters per minute, and the presented results do not substantiate the page's threshold-accuracy claim |
| [Colgate et al. 2026: VitalPro ventilation and respiratory-rate validation](https://doi.org/10.13140/RG.2.2.29027.72485) | Independent conference poster in 16 participants during `5 x 5 min` cycling: strong RR agreement, moderate VE correlation, poor VE agreement, and explicit warning that reported volume was not comparable to true L/min | Conference poster rather than a peer-reviewed full paper. Directly relevant current-device evidence, but protocol, sample, and available method detail are limited |
| [Gouw et al. 2022: Tyme Wear Smart Shirt threshold reliability and validity](https://pmc.ncbi.nlm.nih.gov/articles/PMC8835019/) ([local PDF](../../../../docs/research/papers/respiration/gouw-2022-tymewear-threshold-validity.pdf)) | Two treadmill graded tests in 19 recreationally active adults, with 15 retained after equipment error or data loss; similar threshold reliability but lower validity than TrueOne gas exchange; tendency to underestimate VT1/VT2 workload and HR, wide individual agreement limits, and larger errors in some fitter participants | Peer-reviewed device-specific evidence for the older Smart Shirt and its then-current proprietary threshold algorithm. The investigators could not compare Tyme Wear and TrueOne VE in physical units or separate sensor error from algorithm error. Do not transfer the result unchanged to VitalPro or treat cohort reliability as individual agreement |
| [Innocenti et al. 2024: Tyme Wear respiratory-frequency validity during soccer](https://pmc.ncbi.nlm.nih.gov/articles/PMC11280907/) ([local PDF](../../../../docs/research/papers/respiration/innocenti-2024-tymewear-respiratory-frequency-soccer.pdf)) | Raw 25 Hz respiratory waveform from the older Tyme Wear vest in 15 male amateur soccer players; custom breath-detection algorithm versus a validated thermistor mask during paced breathing, ball work, shuttle intervals, and cooldown. Overall BR MAPE was `8.65%` breath by breath and `3.27%` over 30-second windows | Peer-reviewed direct device evidence for BR, not VT, VE, threshold detection, VitalPro processing, or exported fields. Overall breath-by-breath limits of agreement were wide (`-0.30 ± 15.66 breaths/min`), high BR above 60 breaths/min was mildly underestimated, individual error varied, and algorithm prominence materially changed false negatives and error |
| [Greco et al. 2024: Tyme Wear respiratory-frequency validity during cycling](https://www.jsc-journal.com/index.php/JSC/article/view/937) ([local PDF](../../../../docs/research/papers/respiration/greco-2024-tymewear-respiratory-frequency-cycling.pdf)) | Raw 25 Hz waveform from the older Tyme Wear vest versus a Cosmed respiratory signal in six male cyclists during `10 x 10 s/50 s` intermittent work and a `30 W/min` ramp; custom-algorithm BR MAE/MAPE were `1.30 breaths/min`/`3.77%` second by second and `0.49 breaths/min`/`1.55%` over 30-second windows | Three-page conference abstract with a very small male sample, no participant-level agreement table, and poorer signal-to-noise ratio during sprints. It validates the investigators' BR extraction from the old vest's raw waveform, not VitalPro, VT/VE, Tymewear's proprietary processing, or the Intervals.icu export path |
| [Caretti et al. 1994: RIP tidal volume during exercise](https://doi.org/10.1080/15428119491018411) | Respiratory inductance plethysmography versus flowmeter during cycling and treadmill exercise; calibration and band slippage as error sources; semi-quantitative VT conclusion | Independent method-family evidence in eight healthy subjects, not Tyme Wear-specific and based on older RIP technology |
| [Leutheuser et al. 2017: Reference-free RIP adjustment during exercise](https://doi.org/10.1109/TBME.2017.2675941) | Importance of calibration/adjustment, benefit of thoracic plus abdominal sensing, and residual VT error during exercise | Peer-reviewed method-family evidence in incremental running, not direct validation of Tyme Wear's single-location hardware or proprietary processing |
| [Nicolò et al. 2018: Respiratory frequency during exercise](https://pmc.ncbi.nlm.nih.gov/articles/PMC5732209/) ([local PDF](../../../../docs/research/papers/respiration/nicolo-2018-respiratory-frequency-exercise.pdf)) | Evidence synthesis that respiratory frequency changes rapidly with effort and is influenced differently from tidal volume; relevance to training monitoring and wearables | Peer-reviewed perspective, not a Tyme Wear accuracy study or proof that BR is a pure measure of effort. Much of the applied evidence was cycling-based, and voluntary breathing, locomotor coupling, modality, motion artifacts, and sensor algorithms remain relevant confounders |
| [Nicolò and Sacchetti 2023: Differential control of respiratory frequency and tidal volume](https://pubmed.ncbi.nlm.nih.gov/36326866/) | Model in which respiratory frequency is strongly influenced by central command and muscle afferent feedback while tidal volume is more influenced by metabolic inputs | Peer-reviewed physiology review. Useful interpretation framework, not proof that one workout pattern identifies a causal limiter |
| [Cannon et al. 2009: Respiratory-frequency thresholds in trained cyclists](https://pubmed.ncbi.nlm.nih.gov/19130393/) | Quantitative BR-breakpoint analysis versus gas-exchange VT and RCP during graded cycling; 15 of 36 cyclists were excluded for low signal-to-noise ratio or early-hyperventilation pseudo-threshold risk, and retained comparisons had wide agreement limits (`±50.2 W` for VT and `±26.9 W` for RCP) | Peer-reviewed direct threshold evidence, but the full article was not openly retrievable in this review. The published results directly oppose treating a BR breakpoint as an interchangeable individual VT/RCP estimate |
| [Rothschild et al. 2025: BR and HR decoupling versus VT1 durability](https://pmc.ncbi.nlm.nih.gov/articles/PMC12479576/) ([local PDF](../../../../docs/research/papers/respiration/rothschild-2025-respiratory-decoupling-vt1-durability.pdf)) | Secondary analysis of 51 trained cyclists from four controlled prolonged-cycling studies: loss of VT1 power correlated with HR decoupling (`r_rm=-0.76`) and BR decoupling (`r_rm=-0.40`), but not VE decoupling (`r_rm=-0.25`, `p=0.136`) | Supports BR drift as one candidate durability marker during controlled, matched work, not a universal field cutoff or causal diagnosis. Protocols were primarily around 90% of initial VT1, nutrition was controlled, later time points had few observations, and the prediction model still requires external validation |
| [Stevenson et al. 2024: ventilatory parameters at VT1 after prolonged cycling](https://pmc.ncbi.nlm.nih.gov/articles/PMC10786968/) ([local full-text XML](../../../../docs/research/papers/respiration/stevenson-2024-prolonged-exercise-ventilatory-parameters.xml)) | Fourteen endurance-trained cyclists and triathletes completed a five-stage VT1 assessment before and after two fasted hours at 90% of initial VT1. VT1 power fell `10 ± 6%`, while laboratory VE at VT1 changed `-4 ± 8%` (`p=0.075`, within-subject CV `5.4%`); the same VE was produced with BR `+16 ± 11%` and VT `-16 ± 7%` | Peer-reviewed mechanistic durability evidence that BR and VT at the moderate-to-heavy transition can shift in opposite directions while true VE is comparatively stable. It used indirect calorimetry, 13 men and one woman, no feeding, a short submaximal staged reassessment, and only two hours of initially moderate continuous work. It does not validate wearable VE, a universal VE boundary, intermittent riding, or ordinary fueled field use |
| [Contreras-Briceño et al. 2024: wearable respiratory-rate threshold estimation](https://pmc.ncbi.nlm.nih.gov/articles/PMC11282229/) ([local full-text XML](../../../../docs/research/papers/respiration/contreras-briceno-2024-wearable-ventilatory-thresholds.xml)) | A mouth/nose temperature-flow wearable and a prespecified 30-second-smoothed trilinear RR regression estimated two breakpoints in 17 healthy active adults during an `80 s/20 W` cycling ramp; a separate uncontrolled cohort of 107 recreational cyclists produced plausible population-average threshold distributions | Peer-reviewed proof of concept for protocol-specific VT estimation from wearable RR, not Tyme Wear or thoracic RIP validation. The field cohort had no individual criterion comparison, laboratory validation was small and convenience-sampled, individual dispersion remained material, the triphasic model may fail in low-fitness or clinical populations, code was unavailable, and two authors were company co-founders/equity holders with a related patent application |
| [Cross et al. 2012: breathing-pattern breakpoints at gas-exchange thresholds](https://doi.org/10.1007/s00421-011-2055-4) | In a published analysis of 28 recreational cyclists, five were excluded for low signal-to-noise ratio or pseudo-threshold risk. Among 23 retained participants, two BR accelerations showed small bias and relatively narrow agreement with two gas-exchange thresholds; a VT plateau was absent near the first threshold in nine and near the second in five | Peer-reviewed direct graded-cycling evidence, but the full article was not openly retrievable in this review and no repository copy was available. The published abstract supports feasibility only after signal-quality exclusions; it is not sufficient to define an implementation, validate Tyme Wear, or assume that two usable breakpoints exist in every athlete |
| [Carey et al. 2005: respiratory-rate breakpoint reliability in competitive cyclists](https://pmc.ncbi.nlm.nih.gov/articles/PMC3899665/) ([local full-text HTML](../../../../docs/research/papers/respiration/carey-2005-respiratory-rate-anaerobic-threshold.html)) | Fifteen competitive male cyclists performed two `25 W/min` maximal cycling tests. Computer-selected BR, VE, and VE/VO2 breakpoints did not differ significantly, but BR threshold repeatability was poorer (`SEM 35.3 W`, `CV 12.2%`, `r=0.800`) than VE (`19.4 W`, `6.7%`, `r=0.872`) and VE/VO2 (`21.5 W`, `7.4%`, `r=0.811`) | Peer-reviewed direct cycling evidence that a BR breakpoint can correspond to a group-level threshold while remaining too noisy to detect the small changes expected in trained athletes. It was a small all-male sample, called the compared breakpoint an anaerobic threshold, used an older computer segmentation method, and did not assess modern wearables or individual agreement against a gas-exchange gold standard |
| [Elliot et al. 2019: Hexoskin validity and reliability in elite cyclists](https://pubmed.ncbi.nlm.nih.gov/28759538/) | Ten elite male cyclists completed two `25 W/min` ramps. Against MetaMax 3B, Hexoskin had typical errors of `1.3-6.2%` for BR but `9.5-19.6%` for VE; moderate-intensity test-retest error was `2.5-3.2%` for BR and `5.3-7.9%` for VE. Its seven-breath output averaging delayed rapid changes, and torso/garment movement worsened high-intensity signal quality | Peer-reviewed method-family evidence, not Tyme Wear or VitalPro validation. The small male sample, low statistical power, proprietary device algorithm, two-sensor Hexoskin design, outlier removal, stage averaging, and sport-specific movement effects prevent direct transfer of its error estimates; the accessible indexed author copy was read, but a valid downloadable repository copy was not available |

### Respiratory Claim-To-Source Map

| Claim | Minimum source basis | Allowed interpretation |
| --- | --- | --- |
| Tyme Wear directly measures metabolic gas exchange | No supporting source; the device senses thoracic movement | Say it reports respiratory movement-derived BR, VT, and VE; do not call it measured VO2, VCO2, or metabolic-cart gas exchange |
| Tyme Wear BR is useful during cycling | Current manufacturer and independent device validation | Use as an effort-responsive breathing-rate signal after quality checks; retain protocol and device-generation limits |
| Tyme Wear VE is accurate in absolute L/min because correlation is high | Correlation does not establish agreement; the independent 2026 poster reports poor VE agreement | Call it source-reported or relative VE unless physical-unit agreement is verified for the exact device and processing path |
| BR, VT, and VE are interchangeable measures of respiratory response | Exercise physiology shows differential control; VE is their product | Report each separately and state whether a VE change was driven by rate, depth, or both |
| High BR is a direct measure of lactate or metabolic acidosis | No supporting source | Describe BR as effort-responsive and multi-determined; do not convert it to lactate or gas-exchange values |
| Tyme Wear-derived VT1/VT2 equals laboratory gas-exchange thresholds | The 2022 Smart Shirt study found lower validity and underestimation | Use as supporting evidence from a standardized protocol, with greater caution in highly fit athletes |
| Rising VE/W proves worsening ventilatory efficiency | Clinical ventilatory efficiency normally requires gas-exchange context such as VE/VCO2 | Call VE/W a workload-normalized descriptive response, not clinical ventilatory efficiency |
| A high VE or falling VT diagnoses respiratory limitation | No supporting source | Describe the pattern and seek corroborating respiratory, clinical, environmental, and athlete-report evidence |

### Respiratory Known Evidence Gaps

- No reviewed peer-reviewed full paper independently validates the current
  VitalPro's absolute VT and VE across the user's cycling intensities and field
  conditions.
- Manufacturer VitalPro results report strong VE correlation without the bias,
  limits of agreement, or absolute error needed to establish interchangeability
  with a metabolic cart.
- The 2026 independent VitalPro evidence is currently a conference poster and
  reports that volume estimates are not comparable to true L/min.
- The favorable 2024 old-vest studies validated BR extracted from raw waveforms
  with research algorithms. They do not validate VitalPro's proprietary live
  BR, VT, or VE fields, nor the Garmin-to-Intervals.icu export chain.
- Device generation, firmware, fit, posture, processing, and export scaling can
  change respiratory outputs. Older Smart Shirt threshold results must not be
  silently transferred to VitalPro.
- There is no public universal BR, VT, VE, BR/W, or VE/W threshold that validly
  establishes VT1, VT2, VO2max attainment, readiness, or excessive training
  cost across athletes.
- Tyme Wear does not provide the gas concentrations required for standard
  ventilatory-equivalent, V-slope, respiratory-compensation, or clinical
  ventilatory-efficiency analyses.
- Evidence is insufficient to diagnose pulmonary, respiratory-muscle, or
  metabolic limitations from ordinary wearable respiratory streams alone.

## Maintenance

When adding evidence:

1. record the exact device, generation, measurement site or fit, population,
   exercise mode, and protocol;
2. distinguish reliability from validity, correlation from agreement, and
   association from diagnosis;
3. keep manufacturer claims separate from independent validation;
4. update the applicable topic's claim-to-source map when a source materially
   changes an allowed interpretation;
5. do not turn a group-average research threshold into a personal analysis
   rule without athlete-specific validation.
