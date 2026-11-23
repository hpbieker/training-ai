# CORE, CORE 2, and Calera temperature sensing

Source inventory prepared 2026-11-23 for a new review of wearable temperature
measurement. It includes the three studies already cited in the project, the
additional studies identified in the search, and manufacturer documentation
that helps distinguish device models. Notes are preliminary. A local PDF is
available for review wherever one is linked.

## Starting conclusions for the review

- Track the actual device, firmware when reported, reference method,
  exercise phase, and environmental conditions. Several papers say CORE
  without specifying a generation. The studies identified here include the
  original CORE and the separately calibrated Calera Research Sensor. This
  search did not identify an independent cycling criterion study explicitly
  testing the retail CORE 2.
- Evaluate repeatability, agreement in absolute temperature, and tracking of
  changes separately. The available studies report errors in both directions.
  Consider workload transitions, airflow, clothing, acclimation, and
  reference measurement when comparing findings.
- Give cycling studies first weight for cycling decisions. The hockey,
  treadmill, passive-heat, and cold-water protocols help identify conditions
  that may affect the estimate. Check transfer to cycling and CORE 2 before
  using those results to change temperature interpretation.

## Cycling and device comparisons

| Source | Device and access | Protocol and initial finding | Limits and relevance |
| --- | --- | --- | --- |
| [Verdel et al. 2021: Reliability and validity during cycling](https://doi.org/10.3390/s21175932) | Original CORE. Previously cited. [Local PDF](papers/core/verdel-2021-core-cycling-reliability-validity.pdf). | Rectal comparison during steady cycling under two heat loads (about 19 °C and 31 °C). Repeatability between equivalent rides was acceptable. Roughly half of paired measurements differed by more than 0.3 °C. | Helps separate repeatability from criterion agreement. Both studies involved men and specific lab conditions. |
| [Daanen et al. 2023: Heat-flux sensor comparison](https://doi.org/10.1016/j.jtherbio.2023.103480) | Original CORE, compared alongside 3M SpotOn and Medisim Temple Touch. [Local PDF](papers/core/daanen-2023-heat-flux-sensor-comparison.pdf). | Nine recreationally active participants exercised on a cycle ergometer at 18 °C. CORE tended to overestimate rectal temperature during exercise. | Small lab study with device dropouts. The direction differs from some hot-environment protocols. |
| [Januário et al. 2024: Reproducibility during cycling in heat](https://doi.org/10.1016/j.jtherbio.2024.103907) | Calera Research Sensor. Previously cited. Publisher abstract and manufacturer study summary. | Compared the Calera estimate with ingestible temperature measurements during cycling at different intensities in the heat. | Prioritize full-text retrieval to assess individual error, trial phases and calibration. |
| [McLaughlin et al. 2025: Constant-load cycling in heat](https://doi.org/10.1016/j.jtherbio.2025.104241) | Reported as CORE. Previously cited. Publisher abstract and article preview. | Twenty-four participants cycled for 60 minutes at 60% of maximal aerobic power at roughly 36 °C. Against rectal temperature, CORE overestimated temperature in the last two quarters of the ride. Local subcutaneous fat thickness was associated with the late bias. | Keep the validity result tied to this constant-load protocol. Confirm generation, firmware and agreement by phase from full text before applying it to retail CORE 2. |
| [Richard et al. 2025: CORE and SlateSafety during cycling](https://doi.org/10.1123/ijspp.2025-0034) | Reported as CORE. Publisher abstract and [published correction](https://pubmed.ncbi.nlm.nih.gov/40639800/). | Eight eumenorrheic women cycled for 60 minutes in heat-trapping clothing. CORE underestimated rectal temperature at rest and overestimated it late in exercise. | Small sample and specific clothing protocol. Consult the correction and full text before carrying forward numerical results. |
| [Vasquez-Bonilla et al. 2026: Cross-country marathon mountain biking](https://doi.org/10.3390/jfmk11040446) | Reported as CORE Body Temperature Sensor (CORE Sense). [Local PDF](papers/core/vasquez-bonilla-2026-core-mountain-bike-racing.pdf). | Exploratory field case series with continuous wearable temperature during mountain-bike races. | Illustrates field use. No independent temperature reference was recorded. |

## Other protocols and measurement limitations

| Source | Device and access | Protocol and initial finding | Limits and relevance |
| --- | --- | --- | --- |
| [Goods et al. 2023: Elite field hockey in heat](https://doi.org/10.1080/17461391.2023.2193953) | Original CORE, firmware 0.3.18. [Local PDF](papers/core/goods-2023-core-field-hockey-heat.pdf). | Compared with BodyCap during one training session and three simulated matches in the heat in 19 elite women. CORE underestimated temperature on average and 41–60% of observations per session differed by more than 0.3 °C. | Field comparison against ingestible temperature. The protocol differs from cycling in workload and airflow. |
| [Xu et al. 2025: Prolonged indoor heat with and without a fan](https://doi.org/10.1016/j.buildenv.2025.113288) | Reported as CORE. Publisher abstract and article preview. | Thirty-eight participants experienced prolonged passive heat and humidity with and without strong airflow. CORE underestimated rectal temperature in the fan condition. | Relevant to airflow as a variable. Protocol was eight hours of passive exposure, so the result supplies no correction factor for an indoor ride. |
| [Goulet et al. 2026: Internal cooling from cold water at rest](https://doi.org/10.3390/s26165042) | Original CORE purchased in April 2021. [Local PDF](papers/core/goulet-2026-core-cold-water-hyperhydration.pdf). | Compared with a calibrated ingestible sensor after cold-water hyperhydration. CORE registered smaller temperature changes. | Resting protocol with gastrointestinal temperature as the comparison. Check capsule timing and local cooling before interpreting the discrepancy. |
| [Brevik-Persson et al. 2026: Calera during interval running](https://doi.org/10.1016/j.jesf.2026.200529) | Calera Research Sensor, firmware 0.6.2, paired heart rate. [Local PDF](papers/core/brevik-persson-2026-calera-interval-running.pdf). | Thirty trained women, half pregnant, performed up to five five-minute treadmill intervals. Calera differed most from rectal temperature in the first intervals of the session, with opposite average bias in the two groups. | Offers evidence about tracking changes in a running protocol. The device and populations matter when interpreting the direction and magnitude of bias. |

## Manufacturer documentation

- [Calibration and model comparison](https://corebodytemp.com/pages/compare-core-2-vs-calera)
  distinguishes the retail CORE 2 from the individually factory-calibrated
  Calera Research Sensor.
- [Research validation](https://corebodytemp.com/pages/research-validation-study)
  and [publication highlights](https://corebodytemp.com/pages/research-publication-highlights)
  describe and index research on Calera, including Januário et al.
- [CORE 2 product documentation](https://corebodytemp.com/products/core2)
  records the intended product use and model identity. Evidence about the
  magnitude and direction of error comes from the device and protocol in each
  comparison above.

## Review brief and baseline before changes

Check the previously cited cycling studies alongside the new comparisons.
Page numbers count from the start of each PDF. Return **keep**, **change**,
or **insufficient evidence**, with the supporting passage and the smallest
warranted change to the research note, skill, script, or plan. Identify the
device model and exercise phase behind each conclusion.

| Decision | Baseline behavior | First passages to check |
| --- | --- | --- |
| Whole-activity temperature flag | [Training Effect context](../../scripts/activity_inspect.py#L784) reports low-confidence heat context if the estimate reaches 38.5 °C, independently of ambient triggers. The function assigns no heat effect on that basis. Would persistence or coverage improve the flag, and should the maximum still be visible as an observation? | [Verdel 2021](papers/core/verdel-2021-core-cycling-reliability-validity.pdf#page=5), pp. 5–11, lab comparison, repeatability and validity. [Daanen 2023](papers/core/daanen-2023-heat-flux-sensor-comparison.pdf#page=2), pp. 2–5, mild lab conditions and error profile. [McLaughlin 2025](https://pubmed.ncbi.nlm.nih.gov/40876129/) and [Richard 2025](https://pubmed.ncbi.nlm.nih.gov/40537134/), cycling phase results in the abstracts. |
| Matched-work change and thermal attribution | The [thermal reference](../../.agents/skills/training-analysis/references/thermal-sensing.md#thermal_cost_supported) requires aligned conditions and corroboration. [Existing tests](../../tests/test_physiological_evidence.py#L17) check window-local environment and separate thermal context from mechanical deterioration. What does the estimate add if airflow, workload transition, or missing environment limits interpretation? | [Januário 2024](https://pubmed.ncbi.nlm.nih.gov/38950497/), Calera cycling protocol. [Goods 2023](papers/core/goods-2023-core-field-hockey-heat.pdf#page=5), pp. 5–8, original CORE during field exercise. [Brevik-Persson 2026](papers/core/brevik-persson-2026-calera-interval-running.pdf#page=3), pp. 3–7, Calera setup and interval-time disagreement. [Xu 2025](https://doi.org/10.1016/j.buildenv.2025.113288), airflow under passive heat. [Goulet 2026](papers/core/goulet-2026-core-cold-water-hyperhydration.pdf#page=4), pp. 4 and 7–9, original CORE and ingestible reference during cooling at rest. |

### Baseline output on synthetic inputs

The earlier Training Effect context helper ran on 600 one-second samples with
constant power and stable HR and breathing. Ambient sensor values were
absent, so any heat flag in these examples came from the CORE field.

| CORE input | Observed heat context |
| --- | --- |
| Entirely absent. | **Not assessed**, no confidence, evidence or effect. |
| One recorded sample of 38.6 °C at second 300. | **Context present**, low confidence, evidence reports the high temperature, no effect. |
| Complete trace rising gradually from 37.1 to approximately 38.81 °C. | **Context present**, low confidence, evidence reports the higher maximum, no effect. |

## Review outcome and application

- The Training Effect report preserves the observed wearable maximum and
  available sample and time coverage. CORE alone flags low-confidence heat
  context after at least 60 unbroken seconds of recorded coverage at or
  above 38.5 °C. Below-threshold samples and gaps interrupt the run. The
  60-second requirement is a data-quality policy to reject transient
  readings. Ambient triggers remain independent. The flag describes
  context and carries no attributed Training Effect or planning consequence.
- The matched-work guidance still requires aligned workload and environment,
  known cooling or an explicit gap in that context, and corroboration that
  does not merely reuse inputs to the wearable estimate. The reviewed papers
  establish no retail CORE 2 correction factor or training-plan rule.
