# Garmin and Firstbeat Model Sources

This source registry supports
[`training-effect-and-stamina-models.md`](training-effect-and-stamina-models.md)
and [`readiness-and-vo2max-models.md`](readiness-and-vo2max-models.md).
It records what each source can establish and where its authority stops. It is
not a general bibliography for every Garmin health feature.

## Evidence hierarchy

Use sources in this order:

1. Current official Garmin technology pages and support documentation for the
   meaning and current product behavior of Garmin outputs.
2. Firstbeat white papers for the physiological rationale and historical model
   description.
3. Garmin owner manuals for device-specific presentation and compatibility.
4. Peer-reviewed independent validation for accuracy claims about the exact
   outcome being discussed.

Do not treat a vendor white paper as independent validation. Do not assume an
older Firstbeat model description reproduces Garmin's current production
implementation. Where Garmin discloses only qualitative behavior, preserve that
uncertainty rather than filling it with an inferred equation.

## Core sources

| Source | Supports | Strength and limitation |
| --- | --- | --- |
| [Garmin: Training Effect](https://www.garmin.com/en-IE/garmin-technology/running-science/physiological-measurements/training-effect/) | Current 0-5 scale; aerobic EPOC framing; fitness individualization; anaerobic use of heart rate plus speed/power; illustrative workout patterns | Current official product description. Qualitative and proprietary; not independent validation |
| [Firstbeat: EPOC Based Training Effect Assessment](https://www.firstbeat.com/app/uploads/2015/10/white_paper_training_effect.pdf) | Peak EPOC plus activity class in the published Training Effect method; historical scale and intended cardiorespiratory interpretation | Vendor white paper, published 2005 and updated 2012. Useful model foundation, not proof of today's exact Garmin implementation or realized adaptation |
| [Firstbeat: Indirect EPOC Prediction Method Based on Heart Rate Measurement](https://assets.firstbeat.com/firstbeat/uploads/2015/10/white_paper_epoc.pdf) | Heart-rate-based EPOC estimation rationale, construction, and reported validation | Vendor white paper about the upstream EPOC estimate. Evaluate its study design separately from Garmin product accuracy |
| [Rusko et al.: Pre-Prediction of EPOC](https://assets.firstbeat.com/firstbeat/uploads/2015/10/rusko_et_al_acsm_2003_congress-1.pdf) | Original ACSM 2003 report behind the published EPOC validation: 48-study construction basis, separate `n=32` validation set, pooled `r=0.889` and MAE `0.96 l`, with weaker maximal-test performance | One-page conference abstract from the Firstbeat development environment, not a full peer-reviewed paper or validation of current Garmin Exercise Load |
| [Saalasti: Neural Networks for Heart Rate Time Series Analysis](https://jyx.jyu.fi/bitstream/handle/123456789/13267/951391707X.pdf?sequence=1) | Academic foundation for neural-network interpretation of heartbeat time series, RR-derived physiology, exercise-intensity estimation, and continuous EPOC modeling | 2003 doctoral dissertation from the University of Jyväskylä. Technical model-family evidence, not today's Garmin production equations |
| [Firstbeat: Interpreting Training Data](https://www.firstbeat.com/en/professional-sports/learning-center/interpreting-training-data/) | Current qualitative explanation of dynamic EPOC estimation using intensity, time, heart rate, HRV-derived respiration, and on/off kinetics; distinction from monotonically accumulating load measures | Detailed vendor education material. Useful for current Firstbeat semantics, not independent outcome validation |
| [Garmin: Training Load](https://www.garmin.com/en-US/garmin-technology/running-science/physiological-measurements/training-load/) | Exercise Load, weighted Acute Load, EPOC basis, gradual expiry, and Load Focus | Current official product description; weights and current complete equations remain proprietary |
| [Garmin: Training Status](https://www.garmin.com/en-AU/garmin-technology/running-science/physiological-measurements/training-status/) | Current use of VO2max trend, Acute Load, HRV Status, and situational Load Focus; meanings of categorical states | Current official product description. Qualitative and proprietary; does not disclose equations or validate the states against outcomes |
| [Garmin Support: Training Load](https://support.garmin.com/en-SG/?faq=SEkNpdGyhR917js0qQL3Q6) | Acute Load, 28-day Chronic Load, Load Ratio, device-generation differences, and operational display behavior | Current official support; boundary wording can differ between pages and devices |
| [Firstbeat Sports: Training Status](https://www.firstbeat.com/en/blog/training-status-the-firstbeat-sports-premium-feature/) | Separate Firstbeat Sports `0-100` model using TRIMP Acute Load, ACWR, and recent Quick Recovery Tests | Vendor product explanation, not Garmin's Training Status. Useful mainly to prevent a same-name model collision |
| [Firstbeat Sports: Acute vs. Chronic Training Load](https://www.firstbeat.com/en/blog/interpreting-acute-vs-chronic-training-load-a-firstbeat-sports-feature/) | Separate team-sport TRIMP seven-day Acute Load and 28-day Chronic Load/ACWR implementation | Vendor product explanation. Do not transfer its TRIMP scale, personalized zones, or injury-risk thresholds to Garmin's EPOC-based load model |
| [Garmin and Firstbeat: Ask the Expert — Training Load](https://www.garmin.com/en-CA/blog/fitness/ask-expert-training-load/) | Firstbeat co-founder Aki Pulkkinen's explanation that the personalized optimal range depends primarily on VO2max plus the athlete's supported training history | Official vendor interview from 2019. Helpful rationale, not a technical specification or validation study |
| [Garmin: Performance Condition](https://www.garmin.com/en-US/garmin-technology/cycling-science/physiological-measurements/performance-condition/) | Cycling inputs, 6-20 minute onset, approximate 1% per point, and within-session trend meaning | Current official qualitative semantics; no public equation or independent validation |
| [Garmin Support: Performance Condition](https://support.garmin.com/en-IN/?faq=A28UA4k16v1qjjGuvSFgo8) | `-20` to `+20` range, running/cycling input distinction, and chest-strap recommendation | Current operational support; not an accuracy study |
| [Firstbeat Analytics feature registry](https://www.firstbeatanalytics.com/en/features/) | Confirms Real-Time Performance Condition and Training Load as Firstbeat Analytics features | Product registry only; supplies no model detail or validation |
| [Firstbeat: Anaerobic Training Effect Assessment](https://assets.firstbeat.com/firstbeat/uploads/2015/11/white_paper_anaerobic_5-2017.pdf) | Physiological rationale and method description for aerobic/anaerobic Training Effect; importance of bouts, recovery, and fatigue | Vendor white paper from the earlier Firstbeat implementation. Its examples are illustrative and validation coverage is limited |
| [Garmin: Real-Time Stamina introduction](https://www.garmin.com/en-US/blog/outdoor/introducing-the-garmin-real-time-stamina-feature/) | Available versus Potential behavior, intensity-sensitive gap/rebound, depletion interpretation, time/distance to exhaustion | Official launch explanation from 2022. Detailed qualitative semantics, but no complete equations or independent validation |
| [Garmin Support: What Is Real-Time Stamina?](https://support.garmin.com/en-IE/?faq=c4T7cNaLf59MLnCEuEJJaA) | Current input requirements and user-facing meanings; heart rate, VO2max, and cycling power-curve guidance | Current official support source. Product semantics, not accuracy validation |
| [Garmin: Recovery Time](https://www.garmin.com/en-US/garmin-technology/running-science/physiological-measurements/recovery-time/) | Readiness for the next hard workout; EPOC-based load and fitness/history context; sleep, stress, and daily-activity adjustments | Current official model overview. Inputs and intent are public; weights and equations are proprietary |
| [Garmin Support: Recovery Time](https://support.garmin.com/en-IE/?faq=8ImmxVkZMh4EYYq5Zp2bR8) | Timer range, recalculation after activities, live device updates versus Connect sync | Current operational support. Device compatibility and behavior can vary |
| [Firstbeat: Recovery Analysis for Athletic Training Based on HRV](https://www.firstbeat.com/wp-content/uploads/2015/10/Recovery-white-paper_15.6.20153.pdf) | General Firstbeat recovery/HRV rationale and distinction between training load and recovery | Vendor white paper from 2015. It does not document Garmin Recovery Time's current production equation |
| [Firstbeat: Stress and Recovery Analysis Based on 24-hour HRV](https://www.firstbeat.com/wp-content/uploads/2015/10/Stress-and-recovery_white-paper_20145.pdf) | Historical state-classification rationale for physiological stress, recovery, physical activity, and modeled body-resource accumulation/depletion; heartbeat-derived HRV, respiration, VO2, EPOC, and movement inputs | Vendor white paper from 2014. Physiological stress does not identify its cause or equal perceived stress; chronic conditions, medication, artifacts, and many lifestyle/environmental factors limit interpretation. It is model-family evidence, not the current Garmin Body Battery equation or validation |
| [Firstbeat: Sleep Analysis Method Based on HRV](https://www.firstbeat.com/wp-content/uploads/2019/11/Firstbeat-Sleep-Solution_white-paper_short.pdf) | Historical wearable sleep detection and stage classification from RR/HRV, HRV-derived respiration, movement, time of day, and profile data; `n=110`, 780 PSG hours, `66%` epoch-level stage agreement (`69%` offline), sleep/wake sensitivity `94%` and specificity `63%` | Vendor white paper from 2019. Useful uncertainty boundary for sleep-stage interpretation, not proof of accuracy for every current Garmin device, firmware version, or production implementation |
| [Garmin: Sleep Tracking](https://www.garmin.com/en-IE/garmin-technology/health-science/sleep-tracking/) | Current Sleep Score inputs: age-contextualized duration, sleep architecture, HRV-derived stress, interruptions, awake time, and restlessness | Current official product description. It does not disclose weights, the complete equation, or independent validation of the final score |
| [Chinoy et al.: Performance of Seven Consumer Sleep Trackers](https://academic.oup.com/sleep/article/44/5/zsaa291/6055610) | Independent PSG comparison in 34 healthy young adults across three nights; older Garmin devices had high sleep sensitivity but low wake specificity and variable stage estimates | Peer-reviewed independent validation of Fenix 5S and Vivosmart 3, not current Garmin Sleep Score or every current device |
| [Firstbeat: Energy Expenditure Estimation](https://www.firstbeat.com/wp-content/uploads/2015/10/white_paper_energy_expenditure_estimation.pdf) | Historical heartbeat-derived aerobic energy-expenditure model using estimated VO2, respiration, on/off kinetics, metabolic context, and personal parameters; vendor validation in 32 healthy adults reported `10.9%` MAPE | Vendor white paper published 2007 and updated 2012. Small controlled/sample-task validation, not independent evidence for current all-day Garmin calorie accuracy; short anaerobic work may be underestimated |
| [Firstbeat: Oxygen Consumption Estimation](https://www.firstbeat.com/wp-content/uploads/2015/10/white_paper_vo2_estimation.pdf) | Historical second-by-second aerobic VO2 estimation from heart rate, RR-derived respiration, and on/off dynamics; in 32 healthy adults MAE improved from `3.7` to `1.9 ml/kg/min` versus an HR-only model | Vendor white paper published 2005 and updated 2012. This is current oxygen-consumption estimation, not VO2max; it depends on personal parameters and does not measure anaerobic energy production |
| [Firstbeat: Health and Fitness Benefits of Physical Activity](https://assets.firstbeat.com/firstbeat/uploads/2018/03/Physical-activity-white-paper_FINAL2.0.pdf) | Relative-to-fitness versus absolute intensity; historical Firstbeat Physical Activity Index/Score personalization by VO2max, profile, intensity, duration, and activity history | Vendor white paper from 2018 describing Firstbeat-specific scores and then-current activity guidelines. It does not establish Garmin Intensity Minutes, Fitness Age, or another current Garmin feature's exact formula |
| [Garmin: Training Readiness](https://www.garmin.com/en-US/garmin-technology/running-science/physiological-measurements/training-readiness/) | Six disclosed drivers, morning and intraday update behavior, overload interpretation, and distinction from performance readiness | Current official product semantics. Garmin does not disclose weights, interactions, or the complete equation |
| [Garmin: HRV Status](https://www.garmin.com/en-GB/garmin-technology/health-science/hrv-status/) | Three-week personalization, dynamic personal baseline, seven-day average, and meanings of Balanced, Unbalanced, Low, and Poor | Current official product semantics. No public equation for baseline bounds or status thresholds, and no outcome validation of the composite status |
| [Garmin Support: HRV Status](https://support.garmin.com/en-US/?faq=HnFAR4oFRF4kHeqYme3bU6) | Initial wear frequency, baseline expiry, morning sync behavior, and factory-reset consequences | Current operational support; behavior and compatibility can vary by device |
| [Garmin Owner Manual: Training Readiness](https://www8.garmin.com/manuals/webhelp/GUID-31D23DBB-57C2-4DF7-A0C9-8D1A00AB4BE7/EN-US/GUID-C21BE0C8-A08E-4DA1-B6C6-2E0E2DDDB372.html) | Score bands and public time windows for Sleep History and Stress History | Current device manual; presentation and compatibility can vary by device |
| [Garmin: Cycling VO2max](https://www.garmin.com/en-GB/garmin-technology/cycling-science/physiological-measurements/vo2-max/) | Heart-rate versus cycling-power model framing, meaningful-segment selection, environmental context, and downstream Garmin uses | Current official qualitative description; no public equation or accuracy result |
| [Garmin: Fitness Age](https://www.garmin.com/en-US/garmin-technology/health-science/fitness-age/) | Device-dependent VO2max interpretation versus newer multifactor model using activity intensity, resting HR, and body fat or BMI | Current official product description. Does not publish the complete equation, reference distributions, or outcome validation |
| [Firstbeat: What's Your Fitness Age?](https://www.firstbeat.com/en/blog/whats-your-fitness-age-vo2max-reveals-it/) | Historical Firstbeat concept mapping VO2max to the same-sex population-average value at another age | Vendor educational article, not a white paper or validation of Garmin's newer multifactor implementation |
| [Garmin Support: VO2max Estimate](https://support.garmin.com/en-US/?faq=lWqSVlq3w76z5WoihLy5f8) | General eligibility requirements, profile importance, sport-specific estimates, and third-party activity processing | Current operational support; exact requirements vary by device |
| [Firstbeat: Automated Fitness Level (VO2max) Estimation](https://www.firstbeat.com/wp-content/uploads/2017/06/white_paper_VO2max_30.6.2017.pdf) | Historical segment-selection method, HRmax sensitivity, and vendor running/cycling/walking validation claims | Vendor white paper updated in 2017, not current Garmin disclosure or independent validation; its cycling accuracy statements are internally inconsistent |
| [Firstbeat: Scientific Publications Related to VO2max](https://www.firstbeat.com/en/science-and-physiology/white-papers-and-publications/oxygen-consumption-and-maximal-oxygen-consumption-vo2max/) | Current Firstbeat registry reports `7.7-8.7% MAPE`, `r=0.84-0.86`, and `n=29` for its cycling validation and indexes other Firstbeat-related studies | Current vendor research registry. It clarifies the older white-paper summary but remains vendor-curated, not independent validation |
| [Molina-Garcia et al.: INTERLIVE systematic review](https://pmc.ncbi.nlm.nih.gov/articles/PMC9213394/) | Independent synthesis of wearable VO2max validity and reporting of Firstbeat's vendor claims as 5% running, 8% cycling, and 6% walking MAPE | Peer-reviewed systematic review; included independent Garmin studies evaluated running, not cycling |
| [Kinnunen: Validation of a Cycling Indirect VO2max Test](https://jyx.jyu.fi/handle/123456789/52750) | Original 29-person cycling validation, average bias, correlations, and wide limits of agreement for laboratory and field estimates | University thesis linked to the Firstbeat development evidence; small sample and not a validation of every current Garmin device/model |
| [Doherty et al.: Readiness, Recovery, and Strain](https://doi.org/10.1515/teb-2025-0001) | Review of 14 composite health scores including Garmin Training Readiness and Body Battery; compares inputs, timeframes, transparency, and validation evidence | Peer-reviewed 2025 review based on public documentation and literature. It evaluates evidence and transparency, not the undisclosed Garmin equation against a physiological reference standard |
| [Engel et al.: Garmin VO2max in Moderately vs. Highly Trained Athletes](https://pubmed.ncbi.nlm.nih.gov/40770433/) | Two Garmin running estimates in 35 endurance athletes; overall `7.2-7.9% MAPE`, lower error in moderately trained athletes, and `9.4-10.4% MAPE` with systematic underestimation in highly trained athletes | Independent peer-reviewed running validation. Supports population-dependent uncertainty but cannot establish cycling accuracy or every current Garmin model |
| [Passler et al.: Wrist-Worn Trackers for VO2max and Energy Expenditure](https://pmc.ncbi.nlm.nih.gov/articles/PMC6747132/) | Garmin Forerunner 920XT VO2max against spirometry in 24 healthy adults; reports about `7.3% MAPE` with chest-strap heart rate and individual agreement limits | Independent peer-reviewed validation of an older running-capable device and protocol; not direct evidence for current cycling estimates |
| [Firstbeat white-paper and publication index](https://www.firstbeat.com/en/science-and-physiology/white-papers-and-publications/) | Canonical discovery page for Firstbeat white papers and related publication lists | Useful registry; inclusion does not itself establish independent validation |

## Claim-to-source map

Use this map to avoid overstating what the sources establish:

| Claim | Minimum source basis | Allowed wording |
| --- | --- | --- |
| Aerobic Training Effect uses EPOC and individual fitness context | Current Garmin Training Effect page | "Garmin models expected aerobic stimulus from EPOC in individualized context" |
| Published Firstbeat Training Effect uses peak EPOC | Firstbeat Training Effect white paper | "The published Firstbeat method uses peak modeled EPOC"; do not claim the complete current Garmin equation is known |
| Anaerobic Training Effect uses HR plus speed/power | Current Garmin Training Effect page, supported by Firstbeat anaerobic paper | "Garmin analyzes heart rate and external speed/power during high-intensity bouts" |
| Available Stamina can rebound toward Potential | Garmin Stamina introduction | "Garmin's short-term estimate rebounds"; never "fuel was restored" |
| Potential Stamina represents broader depletion | Garmin Stamina introduction/support | "Garmin models broader, slower-changing depletion"; never present it as measured glycogen or muscle damage |
| Recovery Time targets the next hard workout | Garmin Recovery Time technology/support pages | "Time to modeled readiness for the next hard workout"; not "time until any exercise is allowed" |
| Exercise Load is EPOC-based activity impact | Garmin Training Load page and Firstbeat EPOC white paper | "Garmin estimates EPOC-based physiological activity load"; do not equate it with mechanical work or another load system |
| Acute and Chronic Load can be reconstructed by summing activities | No supporting source; Garmin explicitly says Acute Load is weighted | Do not reconstruct; preserve Garmin's reported values and status |
| Performance Condition is approximately percent deviation from baseline VO2max | Garmin Performance Condition page/support | "Garmin estimates deviation from its VO2max-based baseline"; never call it measured VO2max change |
| Training Readiness independently measures readiness or predicts race performance | No supporting source; Garmin describes an aggregate training-benefit aid and explicitly separates it from performance readiness | Use it as a diagnostic aggregate, inspect its disclosed drivers, and do not double-count it |
| Training Readiness component weights or exact equation | No public supporting source | State that the six drivers are disclosed but their weights and interactions are proprietary |
| Training Readiness has six independent physiological inputs | Garmin's public component descriptions show repeated HRV, sleep, stress, activity, and recovery context | Describe overlapping driver families; do not infer the undisclosed equation or count aligned contributors as independent confirmations |
| Garmin and Firstbeat Sports Training Status are interchangeable | The two current vendor descriptions disclose different inputs, load metrics, scales, and outputs | Keep the product family explicit; never import Firstbeat Sports' TRIMP, QRT, `0-100`, or threshold logic into Garmin Connect |
| Balanced Load Focus means equal load in all three categories or overrides periodization | Garmin describes personalized target ranges and explicitly allows focus toward the demands of an ambition or training phase | Use balance as general foundation context; let the active plan and phase define the desired distribution |
| Fitness Age measures biological age or independently validates fitness improvement | Garmin describes a device-dependent interpretation using VO2max or lifestyle/profile factors, without an outcome-validation claim | Call it motivational context; inspect VO2max, performance, body composition, resting HR, and activity trends separately |
| Garmin Stress identifies psychological stress or its cause | No supporting source; the Firstbeat model classifies physiological activation that can have many physical, environmental, medical, and emotional causes | Say "modeled physiological stress/activation" and name plausible context only when separately evidenced |
| Body Battery measures energy, glycogen, or remaining exercise capacity | No supporting source; Firstbeat's published model family describes a modeled balance that rises during recovery and falls during stress | Say "modeled body-resource balance"; never convert it to calories, glycogen, or guaranteed performance capacity |
| Garmin sleep stages are directly measured or precise enough for one-night training decisions | Firstbeat's 2019 vendor validation reported only moderate stage agreement against PSG | Call stages wearable classifications; prioritize duration, awakenings, subjective quality, and trends over small single-night stage changes |
| Sleep Score is independently validated because its sleep stages were tested | Published Firstbeat and independent studies validate selected upstream classifications, not Garmin's proprietary final score | Call it a composite summary; inspect components and do not present its `0-100` scale as a validated physiological interval scale |
| `UNBALANCED` HRV Status always means HRV is low | Garmin explicitly states that the seven-day average can be above or below the personal baseline | Preserve direction and numeric context; never infer low HRV from the label alone |
| `POOR` HRV Status is simply a worse short-term deviation than `LOW` | Garmin defines `POOR` using the learned baseline relative to age-referenced health standards | Distinguish chronic baseline classification from a short-term seven-day drop |
| `maxMetCategory` has a known public mapping to METs or fitness bands | No public Garmin or Firstbeat definition was found | Preserve as an opaque raw field only; do not interpret, display, or score it |
| Garmin calories provide an exact fueling or energy-balance target | No supporting source; the historical Firstbeat aerobic EE model has meaningful error and limited validation scope | Use calories as an uncertain model estimate and ground fueling in workout demands, duration, intake, and practical response |
| Heartbeat-derived current VO2 and VO2max are interchangeable | Firstbeat documents separate a current aerobic oxygen-consumption model from the VO2max capacity model | Preserve the distinction; never use estimated current VO2 as a VO2max observation or vice versa |
| Cycling VO2max is directly measured or supplies precise workout watts | No supporting source; Garmin describes an estimate based on heart rate and cycling power | Call it a sport-specific modeled capacity estimate and use observed power capacity for prescription |
| Garmin cycling VO2max is 95% accurate | Firstbeat white paper is internally inconsistent; Firstbeat's registry reports `7.7-8.7% MAPE` in only 29 cyclists | Do not use this claim; describe meaningful individual uncertainty and name evidence scope |
| One VO2max validation error applies to every Garmin athlete and sport | Independent studies show population- and protocol-dependent agreement, and independent Garmin evidence is predominantly from running | Name fitness level, sport, protocol, and sensors; never transfer running accuracy directly to cycling |
| Heat or altitude altered Training Effect | Activity-specific aligned evidence plus Garmin environmental context | Use `context_present` or `supported`; do not claim causation from environment alone |
| A Garmin metric is validated as accurate for this athlete/use | Relevant independent validation study | Name population, protocol, outcome, and uncertainty; vendor descriptions are insufficient |

## Known evidence gaps

- Garmin does not publish the complete current equations, coefficients, or all
  device-specific branches for Training Effect, Stamina, Recovery Time,
  Training Load, Performance Condition, Training Readiness, or VO2max.
- No public validation of Garmin's aggregate Training Readiness score against a
  reference standard was found in the reviewed sources. Evidence for individual
  inputs does not validate the undisclosed composite or its thresholds.
- Training Readiness contributors reuse related source evidence. Public
  descriptions establish overlap but not whether or how Garmin compensates for
  it internally; do not infer extra double-counting inside the proprietary
  equation.
- Public Firstbeat material shows shared upstream heartbeat, HRV, respiration,
  activity, and profile evidence across stress/recovery, sleep, oxygen
  consumption, energy expenditure, and training models. It does not disclose
  every dependency or current Garmin production branch, so agreement between
  outputs must not automatically be counted as independent confirmation.
- Firstbeat's 2019 sleep validation reported moderate sleep-stage agreement in
  110 adults. No reviewed source establishes that the same accuracy applies to
  every current Garmin device, sensor configuration, population, or firmware.
- No reviewed source independently validates Garmin's final Sleep Score or its
  thresholds. Validation of sleep duration, wake detection, stages, or HRV does
  not validate their undisclosed composite weighting.
- Garmin documents HRV Status behavior but not the baseline-range equation,
  exact `UNBALANCED`/`LOW` boundaries, age-health reference, or independent
  validation of the categorical status.
- `maxMetCategory` appears in Garmin's private Training Status payload but has
  no reviewed public definition. Its proximity to VO2max does not establish
  that it is a MET value, Cooper category, or Fitness Age input.
- The historical Firstbeat energy-expenditure and oxygen-consumption studies
  each used 32 healthy adults. They do not establish current all-day Garmin
  calorie accuracy, anaerobic energy cost, or precise individual fueling need.
- Firstbeat's cycling VO2max white paper describes only 29 cyclists and reports
  both `92%` accuracy and `MAPE ~5%`. Preserve the contradiction; do not silently
  select the more favorable number. Firstbeat's current registry reports
  `7.7-8.7% MAPE`; the underlying study's wide individual limits of agreement
  still prevent treating small changes as established physiological change.
- Independent Garmin VO2max studies are mainly running studies and show that
  agreement can differ by fitness level and protocol. They strengthen general
  uncertainty rules but do not independently validate current cycling output.
- The Firstbeat EPOC white paper reports an older cycle-ergometer validation in
  32 adults (`r²=0.79`, pooled MAE `13.7 ml/kg`). It does not validate current
  Garmin Exercise Load across sports, environments, and device generations.
- The underlying ACSM 2003 report is a one-page conference abstract. Its pooled
  correlation was stronger than its maximal-test correlation, and the model
  underestimated EPOC at the lowest tested intensity. Treat it as limited
  upstream evidence rather than broad product validation.
- No public Firstbeat white paper or outcome-specific independent validation
  for Performance Condition was found in the reviewed sources.
- No dedicated Firstbeat Fitness Age white paper or independent validation of
  Garmin's complete Fitness Age output was found. Validation of VO2max or an
  individual input does not validate the proprietary age mapping or composite.
- Firstbeat Sports and Garmin reuse names such as Training Status, Acute Load,
  and Load Balance for materially different product models. Public Firstbeat
  Sports TRIMP/ACWR documentation is not evidence for Garmin's EPOC-based load
  equations or categorical Training Status.
- The public Stamina material explains intended behavior but does not provide a
  peer-reviewed validation study for Available/Potential values as direct
  measures of remaining performance capacity.
- The anaerobic Training Effect white paper provides useful physiological and
  algorithmic rationale, but its empirical examples do not justify strong
  claims across all sports, devices, interval structures, or athletes.
- Training Effect predicts expected stimulus; the sources do not prove that an
  individual athlete completed the predicted adaptation after one session.
- Local muscular damage, soreness, neuromuscular cost, pain, hydration, and
  fueling require evidence outside these Garmin outputs.

## Maintenance

When a Garmin page changes materially:

1. prefer the current Garmin meaning for current product behavior;
2. retain older Firstbeat documents as historical model foundations;
3. update the claim-to-source map rather than silently merging incompatible
   descriptions;
4. record independent validation separately from vendor documentation;
5. keep device compatibility out of general model claims unless the analysis
   names a specific device.
