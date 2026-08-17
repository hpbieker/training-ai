# Xert Strain Model

Use this reference to explain XSS, reason about workout structure, or run local
XSS calculations without contacting Xert. Keep training-domain selection in the
calling training-analysis workflow; this reference explains Xert's model.

## Evidence hierarchy

Use sources in this order:

1. Official Xert/Baron Biosystems material authored by Armando Mastracci or
   Scott Steele.
2. Xert Community Forum explanations written by Armando (`xertedbrain`) or
   Scott (`ManofSteele`) in their Xert roles.
3. Controlled, unsaved Workout Designer Calculate probes preserved in
   `docs/research/xert-model-research.md`.
4. Other forum posts only as questions or examples, never as model authority.

The qualitative semantics below come primarily from levels 1-2. Exact equations
marked `Calculate-validated` come from level 3 because Xert has not published
their implementation as formulas.

## The causal model

Reason chronologically:

```text
power
-> instantaneous low/high/peak work allocation
-> HIE expenditure or recovery
-> MPA
-> strain coefficient from power's proximity to MPA
-> low/high/peak XSS
-> Difficulty, Focus, and Specificity
```

Armando describes this as a second-by-second process: Fitness Signature
determines MPA, strain depends on power and proximity to MPA, each second is
separated into low/high/peak strain, and accumulated strain is normalized by
the Fitness Signature. One unfatigued hour at TP is 100 XSS for every athlete.

This immediately rules out several shortcuts:

- XSS is accumulated modeled strain, not a power zone.
- Low/high/peak are additive system contributions, not mutually exclusive
  labels for an entire workout.
- Total XSS is not Difficulty.
- XSS composition alone does not identify VT1, tempo, VT2, VO2max, or sprint.
- A workout can feel hard for reasons XSS does not directly model, including
  central fatigue, glycogen availability, hydration, heat, and duration.

## Work allocation

`Calculate-validated` for instantaneous power `P`:

```text
when P <= TP:
  P_low  = P
  P_high = 0
  P_peak = 0

when P > TP:
  excess = P-TP
  span   = PP-TP
  P_low  = TP
  P_peak = excess^2/span
  P_high = excess-P_peak
```

Consequences:

- Every modeled sample at or below TP is allocated entirely to Low.
- Above TP, Low continues at its TP-level contribution while High and Peak are
  added from excess power.
- As power rises from TP toward PP, the excess allocation shifts progressively
  from High toward Peak.
- `P > PP` makes the algebraic High allocation negative. Treat such a workout
  target as invalid even if a server calculation accepts it.

## Below-TP allocation and interpretive limits

Scott Steele states that Xert currently classifies all XSS below TP as Low
Strain. Therefore recovery riding, VT1, tempo, sweet spot, and subthreshold VT2
can all produce only Low XSS.

Their distinction comes from context outside the Low label:

| Pattern | XSS mechanics | What still determines the training domain |
| --- | --- | --- |
| Recovery | Low only, low XSS rate | Very low power, short/easy intent, physiological response |
| VT1/endurance | Low only | Sustainable aerobic target, duration, drift and plan role |
| Tempo | Low only | Higher sustained power and carbohydrate cost, but still below TP |
| VT2/subthreshold | Often Low only | Near-TP target, interval structure, lactate/ventilatory response and progression |
| Threshold | Low only at exactly TP; High appears only above TP | Target and duration near maximal steady-state work |
| VO2max-style | Low plus meaningful absolute High and often Peak | Repeated supra-TP work, interval duration, recovery and MPA drawdown |
| Sprint | Large instantaneous Peak share but often small total XSS | Near-maximal power and very short duration |

Never write "the workout was easy because it was only Low XSS." State instead
that Xert allocated it entirely to Low because modeled power stayed at or below
TP, then classify the workout from its target, structure, physiology, and plan.

Armando also notes that XSS does not directly account for central fatigue and
that prolonged work between LTP and TP can feel harder than its MPA movement
suggests. Preserve that limitation when interpreting long tempo or VT2 work.

## HIE, MPA, and strain

`Calculate-validated` state mapping:

```text
MPA = max(TP, PP-(PP-TP)*(Wexp/HIE)^2)
```

At the start, `Wexp=0` and `MPA=PP`. Above TP, expenditure advances by:

```text
Wexp_next = min(HIE, Wexp+(P-TP)*dt)
```

At TP there is no net MPA change, matching Scott Steele's definition of TP.
Below TP, Calculate recovery followed this empirical recurrence:

```text
Wexp_next = max(
  0,
  Wexp*exp(-(TP-P)*dt/HIE)-c*(TP-P)*dt
)
c = 0.0038245044912813284 seconds
```

The offset `c` has no known published origin and must remain labelled empirical.
Completed activity series tested so far followed the pure exponential without
the offset, so do not transfer the Calculate offset to production activity
reconstruction.

`Calculate-validated` strain coefficient:

```text
when P < MPA:
  k_strain = (PP-MPA+TP)/(PP-P+TP)

when P >= MPA:
  k_strain = MPA/P
```

Apply the same coefficient to low/high/peak work allocation. Before failure,
the same power produces more XSS as MPA falls. This is why work under fatigue
can accrue strain faster even when target power is unchanged. At and beyond MPA,
Calculate continues a hypothetical capped numerical path; that does not make
the workout feasible or constitute a detected breakthrough.

For constant `TP < P <= PP`:

```text
Wexp_failure = HIE*sqrt((PP-P)/(PP-TP))
t_failure = Wexp_failure/(P-TP)
```

At `Wexp=HIE`, Calculate floors MPA at TP. Below-TP recovery can raise it again;
no persistent post-failure state was observed in unsaved calculations.

## XSS normalization

`Calculate-validated` per sample:

```text
F = PP/TP^2*100/3600

XLSS += k_strain*P_low *F*dt
XHSS += k_strain*P_high*F*dt
XPSS += k_strain*P_peak*F*dt
XSS   = XLSS+XHSS+XPSS
XSSR  = k_strain*P*PP/TP^2*100
```

At unfatigued TP, XSSR is 100 XSS/hour and all XSS is Low. More than 100 XSS in
an hour is possible when work is performed under short-term fatigue. This
normalization does not claim that arbitrary durations at TP are physiologically
sustainable.

Judge High and Peak as absolute doses against comparable workouts. A VO2max
session can remain overwhelmingly Low by total share because every hard minute
continues accumulating Low while only the excess over TP contributes High/Peak.

## Difficulty

Scott Steele defines Difficulty Score as a 30-minute exponentially weighted
moving average of XSS/hour. `Calculate-validated` recurrence:

```text
alpha = 1-exp(-dt/1800)
DS_next = DS+alpha*(XSSR-DS)
Difficulty = maximum DS reached
```

Consequences:

- Difficulty describes concentration of recent strain, not total strain.
- A short maximal sprint can cause a breakthrough without high Difficulty.
- A long effort can repeatedly draw down MPA and create high Difficulty without
  a breakthrough.
- Easy riding before or after a sprint affects Difficulty differently from
  total XSS.

## Focus and Specificity

Official Xert material says the accumulated low/high/peak ratios determine
Focus and Specificity. `Calculate-validated` Focus reconstruction uses the
Peak-to-Low XSS ratio:

```text
r = XPSS/XLSS
P_focus = TP+sqrt(r*TP*(PP-TP))

t_focus = HIE*sqrt((PP-P_focus)/(PP-TP))/(P_focus-TP)
```

The duration expression applies for `TP < P_focus < PP`; endurance and peak
limits use Xert display conventions. Specificity describes whether the same
system ratio came from concentrated, mixed, or polarized powers. It is not a
synonym for workout quality or plan compliance.

## Offline calculation

Use the pure local model when the Fitness Signature and workout structure are
already known:

```bash
python3 -B plugins/xert/scripts/xert_strain_cli.py calculate \
  --signature-tp 296 --signature-hie 14000 --signature-pp 775 \
  --segment 10:00@180 \
  --segment 3:00@340 \
  --segment 3:00@120
```

Linear ramps use `duration@start-end`, for example `05:00@150-250`. Add
`--series-output /tmp/result.json` only when the second-by-second path is needed.

The default summary must retain:

```text
source = local_xert_strain_model
network_used = false
model_basis = xert_staff_semantics_plus_calculate_validated_equations
server_summary_authoritative = false
```

Use local results for explanation, comparison, and feasibility screening. When
a live Xert Calculate or completed activity summary exists, its summary XSS and
Difficulty remain authoritative because server integration can differ slightly
when MPA changes or power ramps.

Add `--detailed` when every segment, limitation, or diagnostic field is needed.
For normal interpretation, prefer the structured summary fields over
reconstructing prose:

- `segments[].xss` and `largest_system_contributors` identify which segments
  supplied the largest Low, High, and Peak doses.
- `segments[].xss_rate_per_hour` separates accumulated dose from instantaneous
  strain rate.
- `strain_summary.mpa.maximum_same_power_strain_amplification` quantifies how
  much short-term fatigue changed strain relative to fresh MPA at the same
  power.
- `strain_summary.load_concentration` keeps total XSS, maximum XSS rate, and
  maximum Difficulty separate.
- `interpretation` explains model mechanics only; it deliberately leaves the
  training-domain decision to the calling training-analysis workflow.

## Primary sources

- [Armando Mastracci: XSS forum explanation](https://forum.xertonline.com/t/xss/6793)
  — second-by-second MPA/strain pipeline, system separation, normalization, and
  limits around central fatigue.
- [Scott Steele: 100% TP discussion](https://forum.xertonline.com/t/100-tp-for-more-than-an-hour-in-workout-creator/33963)
  — TP as no net MPA change, all below-TP XSS as Low, 100 XSS/hour at TP, and
  Difficulty as a 30-minute EWMA.
- [Armando Mastracci: official XSS glossary](https://www.baronbiosys.com/glossary/xss/)
  — XSS definition, normalization, three systems, Focus and Specificity.
- [Scott Steele: physiology behind Focus and Strain](https://www.baronbiosys.com/the-science-the-physiology-behind-focus-and-strain-and-how-to-train-the-metabolic-pathways/)
  — work under fatigue, system stimulation, Focus ratios, and examples spanning
  endurance, VO2max-style intervals, micro-intervals, and sprints.
- [Armando Mastracci: colour-coded MPA charts](https://www.baronbiosys.com/introducing-new-insight-rich-colour-coded-mpa-charts/)
  — XSSR rises as power approaches MPA and can change during constant power.
- [Scott Steele: high Difficulty without breakthrough](https://forum.xertonline.com/t/high-difficulty-rating-without-breakthrough/48856)
  — Difficulty and breakthrough are related but distinct.

Experimental details and residuals are preserved separately in
`docs/research/xert-model-research.md` and are not copied into this operational
reference.
