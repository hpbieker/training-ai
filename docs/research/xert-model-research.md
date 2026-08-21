# Xert XSS and MPA research log

Date preserved: 2026-08-07

This document preserves the exploratory work behind the proposed
`xert-training-reasoning` skill. It is a research record, not an instruction
file and not a resource that the skill should load automatically.

## Scope

The work investigated whether Xert Workout Designer's unsaved `calculate`
endpoint and its second-by-second time series could be used to reconstruct and
validate relationships among power, low/high/peak work allocation, HIE, MPA,
strain, system XSS, and Difficulty.

The controlled Calculate scope now includes `P >= MPA`. This extension models
what Workout Designer Calculate returns for an unsaved hypothetical workout; it
does not establish how Xert recognizes or awards a breakthrough from a completed
activity.

## Evidence classes and sources

Claims were separated into:

1. **Published model** — present in the official paper, official Xert/Baron
   Biosystems documentation, or an explanation by Xert staff.
2. **Calculate-validated** — reproduced by controlled Workout Designer
   `calculate` probes and second-by-second output.
3. **Approximation** — fits observed behavior but is not established as the exact
   production equation.

Armando Mastracci (`xertedbrain`) and Scott Steele (`ManofSteele`) were
treated as Xert staff sources. Armando cautioned that the paper is foundational
but not an exact description of everything implemented in Xert. A published
equation and a production-equivalence claim are therefore distinct.

## Tested Fitness Signature

Most controlled probes used:

```text
TP  = 296 W
HIE = 14,000 J
PP  = 775 W
```

Agreement under one signature does not establish generality.

## Calculation hypothesis

```text
power
  -> low/high/peak work allocation
  -> HIE expenditure or recovery
  -> MPA
  -> feasibility check
  -> strain coefficient
  -> low/high/peak strain
  -> system and total XSS
  -> Difficulty
```

## Work allocation

For `P <= TP`:

```text
P_low  = P
P_high = 0
P_peak = 0
```

For `TP < P <= PP`:

```text
excess = P - TP
span   = PP - TP
P_low  = TP
P_peak = excess^2 / span
P_high = excess - P_peak
       = excess * (PP - P) / span
```

Thus:

```text
peak share of above-TP work = (P - TP) / (PP - TP)
high share of above-TP work = (PP - P) / (PP - TP)
```

The contributions sum exactly to power. These equations matched controlled
Calculate output to floating-point precision for the tested signature.

### Raw work versus accumulated strain

The formulas above allocate instantaneous power, not the final workout XSS
split. A common strain coefficient is subsequently applied to all three
contributions. Because it changes with MPA:

- system strain shares within one sample equal its work shares;
- samples performed at lower MPA can receive greater weight;
- cumulative strain and XSS shares need not equal unweighted raw-work shares.

This corrects an earlier loose use of “work-allocation ratios” for accumulated
system XSS.

## HIE expenditure and MPA

During above-TP work:

```text
Wexp_(i+1) = min(HIE, Wexp_i + (P_i - TP) * dt)
MPA_i = PP - (PP - TP) * (Wexp_i / HIE)^2
```

The MPA expression with the square matched Calculate. A simpler linear
CP/W-prime-style expression did not.

## Recovery below TP

Candidate continuous model:

```text
dWexp/dt ~= -Wexp * (TP - P) / HIE
tau_recovery ~= HIE / (TP - P)
Wexp(t) ~= Wexp(0) * exp(-t / tau_recovery)
```

Controlled probes below MPA produced:

```text
Recovery power   measured tau   HIE/(TP-P)   error
0% TP               46.6 s         47.3 s     1.5%
25% TP              62.1 s         63.1 s     1.6%
50% TP              92.9 s         94.6 s     1.8%
75% TP             186.4 s        189.2 s     1.5%
90% TP             466.7 s        473.0 s     1.3%
```

Also:

```text
tau * (1 - P/TP) ~= 46.6 s
HIE / TP          = 47.3 s
```

This supports the functional form to roughly 1–2% for this signature. It remains
an approximation because residuals may reflect discrete recovery, rounding,
starting depletion, or additional production handling.

## Feasibility boundary and Calculate behavior at/above MPA

Require:

```text
P_i < MPA_i
reserve_i = MPA_i - P_i
```

Record minimum positive reserve, its timestamp, and the first
`P_i >= MPA_i`. At failure, the workout is no longer feasible under the supplied
signature. Calculate nevertheless continues its numerical series.

Controlled unsaved probes with `TP=300 W`, `HIE=1414.213562 J`, and `PP=500 W`
used constant `P=400 W`. Equality occurred at `Wexp=1000 J`:

```text
MPA = 500 - 200*(1000/1414.213562)^2 = 400 W
```

The surrounding exported samples were:

```text
Wexp    MPA    P      XSSR/h
900     419    400    211.667
1000    400    400    222.222
1100    379    400    210.556
1200    356    400    197.778
```

At and above MPA, Calculate switches to:

```text
k_strain = MPA / P
SR_total = MPA
XSSR = MPA * PP / TP^2 * 100
```

The equation is continuous at `P=MPA`: both branches give `k_strain=1`.
Calculate still applies the same common coefficient to low/high/peak work
allocation, so system shares remain based on instantaneous power allocation.

Depletion continues until it reaches the following floor:

```text
Wexp = HIE
MPA = TP
XSSR = PP / TP * 100
```

`Wexp` and MPA then remain clamped even when power stays above TP. In the probe,
the plateau was `Wexp=1414.213562 J`, `MPA=300 W`, and `XSSR=166.667/h`.
Dropping below TP immediately restarted the already fitted Calculate recovery
recurrence; no persistent post-failure state was observed.

For constant `TP < P <= PP`, Calculate's squared MPA curve predicts first
point-of-failure at:

```text
Wexp_failure = HIE * sqrt((PP-P)/(PP-TP))
t_failure = Wexp_failure / (P-TP)
```

For `P > PP`, the input begins above initial MPA. Calculate accepts such input
algebraically, even producing a negative high-system allocation because the
quadratic peak allocation exceeds total excess power. Treat this as an invalid
workout-design input, not physiological evidence.

Operational interpretation:

1. mark point-of-failure;
2. reject the complete workout as feasible under that signature;
3. Calculate post-failure XSS and Difficulty may be reconstructed with the
   capped branch above, but describe them as hypothetical;
4. do not interpret Calculate crossing MPA as a detected breakthrough or a new
   Fitness Signature.

The actual completed-activity breakthrough/signature-update logic remains
unresolved. Calculate returned no new signature and persisted nothing in these
unsaved probes.

## Strain coefficient

```text
k_strain = (PP - MPA + TP) / (PP - P + TP)  when P < MPA
k_strain = MPA / P                           when P >= MPA

SR_total = k_strain * P
SR_low   = k_strain * P_low
SR_high  = k_strain * P_high
SR_peak  = k_strain * P_peak
```

The published coefficient matched Calculate below MPA. At fixed power, falling
MPA raises the common coefficient up to point-of-failure. Above MPA the capped
branch makes it fall with MPA. Work allocation remains unchanged, but the common
coefficient applied to it changes branch.

This explains why continuous above-TP work can create more strain than comparable
work split by enough recovery to restore MPA.

## XSS normalization

```text
F = PP / TP^2 * 100 / 3600

XLSS = sum(SR_low)  * F
XHSS = sum(SR_high) * F
XPSS = sum(SR_peak) * F
XSS  = XLSS + XHSS + XPSS
```

These are one-second formulas. For arbitrary `dt`, multiply each strain-rate
term by `dt` before normalization.

They reproduced Calculate's system and total XSS to floating-point precision in
the controlled probes.

At unfatigued TP:

```text
XSS = 100 * duration_seconds / 3600
```

All modeled XSS is low. This is normalization, not evidence that arbitrary
durations at TP are physiologically sustainable or subjectively easy.

## Difficulty Score

```text
XSSR = SR_total * PP / TP^2 * 100
alpha = 1 - exp(-dt / 1800)
DS_i = DS_(i-1) + alpha * (XSSR_i - DS_(i-1))
```

For steady `XSSR=R`, starting at zero:

```text
DS(t) = R * (1 - exp(-t / 1800))
```

For feasible samples this matched Calculate's second-by-second `xds` apart
from display rounding. Workout Difficulty is the maximum attained value.
Average XSS Rate is not a substitute for Difficulty.

## Workout implications

Within the validated domain:

- Below TP, constant-power XSS is linear with duration and entirely low.
- Above TP, HIE expenditure lowers MPA and raises strain, so XSS becomes
  superlinear with duration before failure.
- Recovery raises MPA and reduces the strain coefficient applied later.
- Moving power from TP toward PP shifts more above-TP work from high to peak.
- Peak XSS is not inherently small; its share rises toward PP.
- Predominantly low XSS does not prove a workout was easy.
- Compare system XSS, Difficulty, minimum MPA reserve, failure, Focus, and
  workout purpose—not total XSS alone.

## Fitness prediction findings

The paper presents a general three-system impulse-response structure with
Training Load and Recovery Load terms. It must not be treated as an exact
description of current production prediction.

Armando stated in March 2025 that signature prediction then used Training Load
only because adding Recovery Load had not improved prediction enough. Recovery
Load had separately been improved for Forecast AI, and Xert could revisit a
non-zero coefficient later.

In February 2026 he clarified:

- Recovery Demand does not directly affect the Fitness Signature.
- It affects Training Status boundaries and required recovery.
- Signature parameters move with system Training Loads.
- Decay, training responsiveness, breakthroughs, and near breakthroughs also
  affect signature adjustment.

Do not subtract Recovery Load when estimating current TP, HIE, or PP without new
production-specific evidence.

## Training Load and capped Recovery Load validation

Implemented 2026-08-07 in `plugins/xert/scripts/xert_load_model.py`; the current
interface is MCP `project_load_model`.

Xert's `/my-fitness/measures` history provides the TL/RL state immediately
before each activity together with that activity's system XSS. Consecutive rows
validate this event order:

```text
gain = 1-exp(-1/tau)
next_TL = (TL + XSS*gain_TL)*exp(-elapsed_days/tau_TL)
classic_next_RL = (RL + XSS*gain_RL)*exp(-elapsed_days/tau_RL)
next_RL = max(classic_next_RL, next_TL*exp(-1/tau_RL))
```

The elapsed interval is exact activity-start to activity-start time, and the
previous activity's XSS impulse is applied at its start. This rules out activity
end time and upload/processing time as the completed-load timestamp.

The last term is Xert's Forecast-AI cap and matches the exposed `ftp-cap`,
`hie-cap`, and `pp-cap` fields.

Full-history live validation used 2,767 consecutive transitions. Maximum
absolute residuals were 0.00082/0.00221/0.00218 for low/high/peak TL and
0.00891/0.00396/0.00388 for low/high/peak RL. All six passed the declared 0.01
threshold; mean absolute residuals were below 0.0025 for every load.

### 2026 forward-relevant validation slice

A fresh read on 2026-08-07 isolated rows from 2026-01-01 through 2026-08-07.
The slice contained 223 activity-bearing rows: 218 ordinary activity rows, four
breakthrough/near-breakthrough rows, and one manual/locked signature row. No
flagged activity occurred in this period. The latter five transitions were
excluded from marginal signature error as intended.

Across 371 measurable TL/RL transitions, mean absolute residuals for
Low/High/Peak TL were 0.000251/0.000198/0.000193, with maxima
0.000822/0.002178/0.002143. Corresponding RL means were
0.002285/0.000339/0.000326, with maxima 0.008845/0.003904/0.003834. Freshness
classification matched all 373 observed states.

All 367 clean signature transitions were within the practical tolerances of
1 W TP, 0.1 kJ HIE, and 2 W PP. On the 218 ordinary activity rows, mean absolute
unclassified adjustment was 0.0337 W TP, 0.00149 kJ HIE, and 0.0818 W PP. The
maximum clean adjustment across all row types was 0.671 W TP, 0.0340 kJ HIE,
and 1.786 W PP. This slice is verification of the current recurrence and
forward mental model, not a dataset for fitting athlete history.

Current `ir_params` expose per-system responsiveness. With current `k2=0`, the
local marginal signature projection is anchored to the live signature and uses
`signature_future = signature_now + k1*(TL_future-TL_now)`. This models the TL
effect and solves the system load needed to build TP/HIE/PP, but does not claim
breakthrough-equivalent future signatures because signature decay and
breakthrough/near-breakthrough feedback remain production adjustments.

Future scenario timing is explicit: `load-model --target-at T
--workout-after-hours H` decays to the workout, applies XSS, and then decays
through the remainder of the target horizon. Required build output is consequently named
`single_impulse_xss_at_workout_time`; the earlier ambiguous horizon label was
removed rather than retained as an internal compatibility alias.

A later boundary probe measured a planned `(60,8,2)` Low/High/Peak XSS event at
07:59:59, 08:00:00, 08:00:01, 08:30:00, and 08:30:01 local time. The exact
start was still the pre-event state; one second later contained the complete
load and signature impulse, and the planned end produced no second impulse.
Thus Planner applies XSS immediately after the planned start. The earlier
24-hour build probe targeted gains remaining after decay; it did not imply
that adaptation first occurred at the 24-hour observation.

### Historical Fitness Signature and decay validation

`load-model --validate-history` also compares each consecutive historical
Fitness Signature change with `current k1 * change in matching system TL`.
Fitness Measures stores HIE as `atc` in joules, so validation converts it to
kJ before comparison. Residuals are reported as *adjustments*: they are
compatible with decay, breakthroughs, near-breakthroughs, manual changes, or
recalculations, but the endpoint does not expose enough event metadata to
classify the cause safely.

The live 2,769-transition check showed that ordinary changes closely follow
the TL model. Mean absolute adjustment was about 0.23 W for TP, 0.040 kJ for
HIE, and 1.24 W for PP; the 95th percentiles were about 0.83 W, 0.082 kJ, and
1.24 W respectively. A small number of very large changes dominate the maxima
and must be treated as adjustment candidates rather than normal model error.

The response's `medal` field was `1` for every observed row. It therefore
cannot identify breakthroughs in this history and must not be used as a
classifier. The exact proprietary decay rule remains unresolved: the history
validates the Training-Load-matched component and exposes residual adjustments,
but does not distinguish decay from breakthrough/reset/recalculation events.
No Xert write is needed for this analysis.

Rows with `manual: true` are explicit Fitness Signature overrides/locks. The
transition into each such row is excluded from every signature-error and decay
statistic: it measures a user-supplied value, not predictive-model accuracy.
The next transition can still be evaluated from that manual value as its new
anchor. The observed history contains 11 such override rows.

Activity details, rather than Fitness Measures `medal`, expose the explicit
`breakthrough` field. Cross-checking showed that Fitness Measures `pmcb` marks
both breakthroughs (positive activity-detail breakthrough value) and
near-breakthroughs (`breakthrough: -1`). The validator therefore excludes all
non-manual `pmcb` transitions, including small signature changes, rather than
only detecting large residuals. It also excluded 118 early states carrying
`No BT yet. Using first signature`, since those precede a valid model anchor.

Eight recent `pmcb` rows were subsequently joined to their complete OAuth
activity details. In every case the Fitness Measures row signature exactly
equalled the signature saved on the activity. Rounded row Low/High/Peak XSS
matched the activity's full-precision XSS, and using that saved XSS reproduced
the following Training Load with residuals below 0.002. This confirms the
forward event order for a completed breakthrough: Xert saves the new Fitness
Signature on the activity, recalculates that activity's XSS under the resolved
signature, and that stored XSS becomes the impulse used by subsequent TL/RL.
The breakthrough signature transition is excluded from marginal prediction
error, but its recalculated load must never be removed from load history.

The project does not attempt to reconstruct historical `k1`, `p0`, or `stl`
merely to explain old activities. Historical rows are used only to verify the
recurrence and event semantics. A new projection snapshots current live
`tau`, `k1`, Recovery Demands, Fitness Signature, TL, and RL. It anchors future
signature movement to the current signature and does not rebuild that anchor
from `p0` or `stl`. After Xert processes a new breakthrough, the next model
snapshot adopts Xert's saved new signature and recalculated activity XSS.

### Same-day completed plus planned probe

On 2026-08-07, a real completed ride had `(69, 8.6, 1.8)` rounded
Low/High/Peak `completedXSS` and Xert supplied `(160, 0, 0)` `remainingXSS`.
A temporary later Planner event with `(40, 6, 1)` was added at 23:00 local.
Before and at the exact start, state was unchanged. One second after start, TL
increased by precisely the Planner event impulse under the current time
constants. `completedXSS` remained the completed ride only, and
`remainingXSS` remained `(160, 0, 0)`; the planned event neither became
completed nor reduced the remaining recommendation. On the next calendar day
`completedXSS` reset to zero while both activities' load remained represented
in TL. The temporary event was deleted and readback left only the original
completed ride.

All 11 transitions immediately following manual signatures resumed normal
movement from the supplied anchor; there is no evidence in this history of a
hidden multi-activity lock period. The previously unresolved 1961 W PP spike
on 2022-03-23 came from an activity with `flag: true`; excluding that transition
and its following invalid-anchor transition removes the spike and reversal
from model-error statistics.

The Activity Dashboard exposes `flag: true`; the OAuth activity summary does
not. Xert's UI defines this action as flagging an invalid breakthrough and says
it recalculates the signature. Signature validation therefore excludes both
the transition into a flagged activity and the following transition from its
invalid signature anchor. Flagging does not disable the activity (`enabled`
remains true), and the TL/RL recurrence still matches Xert with its XSS, so the
load validation continues to reproduce Xert's own load history rather than
silently deleting the XSS impulse.

The complete 1,965-activity dashboard contained nine flagged activities. All
18 adjacent signature transitions were excluded. The remaining 2,582 clean
transitions had practical-tolerance match shares of 97.21% TP, 97.79% HIE, and
98.33% PP; mean absolute adjustments were 0.110 W, 0.0136 kJ, and 0.263 W.

A fresh 2,582-transition rerun split clean residuals by row type. Across 809
synthetic daily rows, mean absolute residuals were only 0.00215 W TP, 0.000032
kJ HIE, and 0.00402 W PP. Activity-row residuals were materially larger at
0.159 W, 0.0198 kJ, and 0.382 W. This rejects a simple extra fixed daily decay
term in the observed Fitness Measures sequence; residual production changes
are concentrated when activities are processed.

Xert staff describe the post-November-2023 behavior as Training-Load matched
for all decay settings. Slow, Optimal, and Aggressive converge at different
rates toward approximately 5% below the No-Decay estimate, while No Decay
tracks the expected Training-Load signature. The exact convergence function
encoded behind the exposed decay selector remains proprietary.

Frontend inspection resolves the numeric labels: `1` is None/Training Load
Matched, `1.03` is Small, `1.1` is Optimal/Default, and `1.2` is Aggressive.
The values are submitted to `/my-fitness/decay_method`; no decay or convergence
formula appears in the frontend bundles, so the server-side function remains
unavailable. The current athlete setting `1.03` therefore means Small Decay,
not a literal 1.03% decay rule.

Nine of the largest remaining clean residual dates were joined to OAuth
activity details. Every checked activity had `manual=false` and no breakthrough
(`breakthrough=0` or legacy null), and none was flagged. Moving `pmcb` exclusion
to the following transition was explicitly tested and rejected because it
restored large known breakthrough jumps. A second test regressed residuals on
the difference between current and previous activity XSS to detect a one-row
signature/load alignment error. Correlations were weak to moderate and fitted
alignment increased rather than reduced MAE for all three systems. The residual
is therefore best classified as an ordinary server-side activity-processing
adjustment, not breakthrough leakage, manual lock, flag leakage, or XSS timing.

### Controlled future calendar sequence

On 2026-08-07, three temporary future Planner events were created and read
back, using system impulses `(60,0,0)`, `(10,8,2)`, and `(75,12,3)` Low/High/Peak
XSS on 2026-08-24, 25, and 27. Xert's pre-event states and a final observation
on 2026-08-29 were compared with `simulate_calendar_sequence`.

Across all three transitions and all three systems, TL and RL residuals were
exactly zero. TP and HIE signature residuals were exactly zero; the only PP
residual was floating-point noise of approximately `1.1e-13 W`. Xert's final
status was Tired, consistent with the local system-recovery boundary.

All three events were then deleted by their returned paths. Readback confirmed
zero events and zero `CODEX MODEL PROBE` objects on all three dates. No profile,
decay, responsiveness, Recovery Demands, or other model parameter was changed.

### Training Status, Freshness, and Recovery Demands

The Fitness Measures history exposes per-system Form, RL caps, and the actual
pre-activity `tsbColor`. All 2,770 observed states validate the following
classification with the athlete's current Recovery Demands value:

```text
more than 7 days since recorded activity -> Detraining (brown)
low recovery time > 0                 -> Very Tired (red)
high or peak recovery time > 0        -> Tired (yellow)
all three Recovery Loads at their caps -> Very Fresh (green)
otherwise                              -> Fresh (blue)
```

The `diff` field supplies the activity clock on real activity rows. Synthetic
daily rows do not consistently carry it, but brown and green otherwise share
the fully capped recovery state.

The Recovery Demands UI bundle exposes a range of `-0.8` to `1.2` in `0.1`
steps; the current setting is `0.2`. For a system, the Train/Recover RL boundary
is:

```text
boundary_RL = TL - (TL/divisor - base + recovery_demand*scale)
```

with `(divisor, base, scale)` equal to `(5,35,10)` for Low,
`(25,0.6,0.5)` for High, and `(25,0.12,0.1)` for Peak. Raising Recovery
Demands lowers the allowed RL boundary and therefore lengthens recovery. This
is exposed by `load-model` as `recovery_demand_sensitivity`, including the
critical slider value at which each current system becomes tired.

This is not an independent threshold model: the existing Workout Capacity
implementation in `xert_recovery.py` solves the same equation in reverse. With
`next_workout_days=0`, Workout Capacity is exactly zero at the Train/Recover
boundary, positive on the fresh side, and negative on the tired side. Unit
tests verify this identity for Low, High, and Peak. The blue-to-green change is
different: Very Fresh requires all three Recovery Loads to equal their caps.

## Calculate API and local tooling

Calculate exposed second-by-second series useful for model testing. The former
CLI exposed this as:

```text
workout-calculate --series-output FILE
```

Relevant files at the time included the now-removed general Xert CLI alongside:

- `plugins/xert/scripts/xert_workouts.py`
- `plugins/xert/skills/xert/SKILL.md`
- `plugins/xert/skills/xert/references/write-safety.md`

The helper's `include_series` path returns raw `signature`, `series`, and
`calculation_stats` when requested.

Verification completed:

- Python compilation passed.
- `git diff --check` passed.
- `python3 -B -m unittest tests.test_xert_cli` passed 31 tests.

Dedicated tests for `--series-output` and unsaved signature overrides were added
in the later real-activity and error-bound validation round.

## Experiments still needed

1. Obtain a production-side field definition, implementation detail, or Xert
   staff clarification for deeply depleted activity MPA; the exported fields are
   now exhausted as candidates.
2. Validate against another athlete's production Xert session export if a
   consented non-private example becomes available; the public research data do
   not contain production Xert MPA exports.
3. Obtain evidence for completed-activity breakthrough detection and Fitness
   Signature updates; unsaved Calculate does not exercise that production path.

## Automated Calculate analyzer

Implemented 2026-08-07 as:

```text
plugins/xert/scripts/xert_calculate_analyze.py
```

Usage:

```bash
python3 -B plugins/xert/scripts/xert_calculate_analyze.py /tmp/calculate-series.json
```

The analyzer returns machine-readable JSON containing:

- signature and sample counts;
- minimum positive `MPA-P` reserve before failure;
- first failure index and reserve;
- maximum absolute MPA and XSSR residuals;
- reconstructed and reported low/high/peak/total XSS;
- an explicit summary-integration warning when those totals differ;
- reconstructed and reported Difficulty diagnostics;
- reconstructed Focus Power and Focus Duration;
- separate feasibility and per-sample-model validity flags, including the
  Calculate-specific post-failure strain branch and TP floor.

The analyzer was checked against the feasible 4x4-minute series and the
point-of-failure 8x1-minute 450 W series. The feasible series reported 2580 valid samples,
minimum reserve 61.27 W, MPA residual `1.14e-13 W`, XSSR residual
`1.42e-13 XSS/h`, exact Focus Duration, and the summary-integration and
Difficulty reconstruction warnings. The original analyzer stopped fitting the
450 W series at sample 838; after the controlled boundary probes it now retains
Calculate samples using the validated capped-XSSR branch while still rejecting
the workout as feasible.

Dedicated unit tests cover feasible and point-of-failure series, the HIE/TP
floor, Focus reconstruction, recovery, sampling, and malformed inputs.

## Validation round: recovery recurrence, summary integration, Specificity, and edges

Completed 2026-08-07.

### Recovery recurrence

Across 2,905 below-TP transitions from multiple recovery powers, starting
depletions, and three contrasting signatures, the best compact recurrence was:

```text
c = 0.0038245044912813284 seconds
Wexp_next ~= max(0, Wexp * exp(-(TP-P)/HIE) - c*(TP-P))
```

Aggregate fit quality:

```text
RMS next-Wexp residual:       0.142 J
maximum absolute residual:   <0.58 J
```

The pure exponential systematically recovered too slowly near full recovery.
The affine term explains the finite-time transition to exactly `Wexp=0` seen
in Calculate. For example, a zero-watt recovery descended through approximately
`8.27, 6.60, 4.92, 3.25, 1.58, 0 J` rather than asymptotically approaching zero.

The recurrence is near-exact empirically but the constant has not been located
in published documentation or production source. Preserve it as a fitted
Calculate model, not a claim about exact private code.

An authenticated inspection of the current Workout Designer client bundle
(`workouts.js`, asset id `4432620eae3c5b4e5aa7856bbf975613`) found UI/chart
handling for `wexp`, `xssr`, `xds`, and summary fields, but no recovery equation
or matching coefficient. The browser client consumes server-calculated series
and statistics. Together with the absence of a formula in the reviewed official
documentation and staff forum material, this means the coefficient's production
origin is not identifiable from the available public/client surface. This closes
the source-identification attempt as **empirically useful, theoretically
unattributed**, not as an exact recovered private constant.

### Summary integration is not a row-boundary effect

Controlled 100-second probes at 200 W used one 100-second row, two 50-second
rows, and ten 10-second rows. XSS and Difficulty were identical to floating-point
precision. Two 50-second below-TP rows at 200/250 W also summed exactly in both
orders.

A single 60-second row at 340 W, where MPA changed, already showed a small
summary difference:

```text
reported XSS:                  2.0711433
sum of exposed sample model:   2.0676905
difference:                    0.0034527
```

Repeated hard/recovery work increased the difference. Therefore the earlier
“row-boundary” label was incorrect. Calculate summary strain follows an internal
integration/state path that differs slightly from summing its exposed display
XSSR whenever MPA changes. Summary `calculation_stats` remain authoritative for
system totals; the exposed series remain authoritative for the validated
per-sample relationships and feasibility analysis.

A follow-up fitted the time offset required to force a rectangular sum of the
validated XSSR equation to equal summary XSS for constant-power, 60-second
probes. The implied offsets were not constant:

```text
Power       implied offset
105% TP        4.276 s
110% TP        2.378 s
120% TP        1.434 s
140% TP        0.967 s
160% TP        0.811 s
```

A separate 340 W probe implied `1.755 s`. This rejects a fixed half-sample,
trapezoidal, or other single time-shift explanation. The inspected client bundle
contains only rendering of returned XSS/Difficulty fields, not the summary
integrator. The exact internal summary-XSS and summary-Difficulty path is
therefore not identifiable from the exposed series. Do not invent a correction
factor: use `calculation_stats` for summaries and reconstructed series metrics
for diagnostics.

### Exact Specificity reconstruction

With Focus Power already reconstructed from Peak:Low XSS:

```text
P_high_focus = (P_focus-TP)*(PP-P_focus)/(PP-TP)
pure_high_share = P_high_focus/P_focus
actual_high_share = XHSS/XSS
Specificity = actual_high_share/pure_high_share
```

This matched Calculate to floating-point precision for all available
non-endurance probes, including contrasting signatures and narrow/wide TP-to-PP
spans. Rating boundaries were confirmed as Polar at or below one third, Pure at
or above two thirds, and Mixed between. Calculate uses `0.5/Mixed` for zero load
and `1.0/Pure` for positive pure endurance.

### Edge probes

The model was validated with unsaved Calculate probes at:

- `P=TP-1`, `P=TP`, and `P=TP+1`;
- zero watts;
- `TP=300, HIE=2,000, PP=330`;
- `TP=200, HIE=40,000, PP=1,500`;
- one second at 329 W with PP 330 W and exactly 1 W initial MPA reserve.

All probes stayed feasible and matched MPA/XSSR equations to floating-point
precision. The `TP+1` probe also showed that extremely long calculated Focus
can be presented as Endurance with `sfd=0`; pure below-TP examples returned
Endurance with `sfd=3600` in these short probes. These are display conventions,
not failures of the Peak:Low Focus equation.

### Analyzer extension

The Calculate analyzer now reports:

- exact numeric Specificity and its Polar/Mixed/Pure classification;
- endurance display-clamp status for Focus;
- the affine-exponential recovery recurrence, sample count, RMS/max residual,
  and comparison with a pure exponential;
- a summary-integration warning rather than the disproven row-boundary warning.

An additional recovery unit test brought the focused Xert test count to 36.

## Validation round: multiple signatures, workouts, update order, and Focus

Completed 2026-08-07 after the initial model reconstruction.

### Unsaved signature overrides

The local Calculate CLI was extended with:

```text
--signature-tp
--signature-hie
--signature-pp
```

These override the Workout Designer form's `ftp`, `atc`, and `pp` fields for
an unsaved calculation only. They do not modify the Xert profile or save a
workout. Existing 31 CLI tests and Python compilation still passed.

### Cross-signature protocol

Three contrasting signatures were tested:

```text
A: TP 250 W, HIE 10,000 J, PP 1000 W
B: TP 296 W, HIE 14,000 J, PP  775 W
C: TP 350 W, HIE 25,000 J, PP  900 W
```

Each corrected protocol used 120% TP until approximately 40% of HIE was
expended, followed by 50% TP for about three predicted recovery time constants.

The first B and C probes used incorrectly calculated work durations and were
discarded as comparable recovery tests. Corrected work durations were 95 and
143 seconds; A used 80 seconds.

Across all valid samples in the corrected probes:

- the squared MPA equation matched the reported MPA to floating-point precision;
- the strain coefficient and XSSR equation matched reported XSS Rate to
  floating-point precision;
- analytic low/high/peak work totals matched Calculate's work-allocation totals;
- no sample reached MPA.

This materially strengthens generality beyond the original single signature,
but more signatures and edge conditions are still desirable.

### Recovery result

Starting depletion was approximately 40.0% for each signature. Over the full
recovery block:

```text
Signature   predicted tau   observed effective tau   difference   remaining
A              80.00 s             74.96 s             -6.29%       4.12%
B              94.59 s             88.62 s             -6.32%       4.10%
C             142.86 s            133.79 s             -6.35%       4.08%
```

A pure exponential run for three time constants would leave 4.98%. Calculate
left about 4.1% for all three signatures. Earlier short/local probes were only
1–2% faster than `HIE/(TP-P)`; the longer probes show that the effective rate
increases weakly as depletion falls.

Conclusion: `tau ~= HIE/(TP-P)` is a useful local approximation and correctly
captures the dominant scaling across signatures and recovery power, but it is
not the exact global discrete recovery law. The remaining task is to identify
the nonlinear state dependence and transition behavior.

### Sample update order

The series reports state at the start of each one-second sample:

- the first work sample has `Wexp=0` and `MPA=PP`;
- after 80 seconds at 300 W with TP 250 W, sample 79 reports `Wexp=3950 J`;
- the first recovery sample reports `Wexp=4000 J` and the corresponding lowered
  MPA;
- recovery then updates the state used by the next sample.

Thus the per-sample order is:

```text
read Wexp_i -> calculate MPA_i and sample metrics -> apply sample power
             -> obtain Wexp_(i+1)
```

At this stage the summary discrepancy was initially suspected to involve row
boundaries. Later controlled probes disproved that interpretation: identical
rows and below-TP transitions are exact, while a single row with changing MPA
already differs. See the later summary-integration validation section. This
aggregation detail remains separate from the resolved MPA state order.

### Complete workout validation

Four feasible current-signature workouts were calculated:

```text
Workout                    XSS       XLSS    XHSS   XPSS   Difficulty  Focus       min MPA-P
3x10 min at 280 W         71.05     71.05    0.00   0.00     64.55     Endurance     494.0 W
4x4 min at 340 W          70.44     64.37    5.51   0.56     85.23     Rouleur        61.3 W
8x1 min at 400 W          52.27     45.48    5.31   1.48     63.05     Pursuiter     194.4 W
10x10 s at 700 W          40.07     31.67    1.30   7.10     41.57     Power Sprinter 35.1 W
```

The original short-hard proposal, 8x1 minute at 450 W with two-minute recovery,
crossed MPA at series sample 838 and was rejected. It was replaced by the
feasible 400 W variant. This validated the feasibility gate in a realistic
failure case.

The four feasible workouts confirm the expected progression from all-low
subthreshold strain through increasing high and peak contributions. The sprint
workout also confirms that peak XSS need not be numerically small.

### Exact Focus Duration reconstruction

Official explanations state that Focus is determined primarily by the Peak:Low
XSS ratio and mapped to a duration on the athlete's power curve. Calculate's
numeric `sfd` was reconstructed as:

```text
r = XPSS / XLSS
P_focus = TP + sqrt(r * TP * (PP - TP))
FocusDuration = HIE * sqrt((PP - P_focus) / (PP - TP)) / (P_focus - TP)
```

The first equation solves the work-allocation formula for the constant power
with the same peak-to-low ratio. The second solves time-to-failure using the
squared MPA curve.

This matched Calculate's `sfd` exactly, with zero floating-point residual, for:

- the three signature probes;
- long over-TP intervals;
- the rejected 450 W short-hard probe before using its feasibility result;
- the sprint-like probe;
- the feasible 400 W short-hard replacement.

Observed labels included Breakaway Specialist, GC Specialist, Rouleur, Road
Sprinter, Pursuiter, and Power Sprinter. For `XPSS=0`, Calculate reports
Endurance and `sfd=0`; the duration equation is singular and must not be used.

High XSS is not part of this Focus equation. Official staff explanations assign
High:Low primarily to Specificity, which was not reconstructed in this round.

## Validation round: real activities, sampling robustness, and error bounds

Completed 2026-08-07.

### Analyzer and CLI coverage

The CLI tests now verify that `--series-output` writes the full signature,
series, and calculation statistics to the requested file without printing the
large series to stdout. Separate tests verify that unsaved TP, HIE, and PP
overrides reach Calculate. The row-JSON parser also accepts `ramp_ftp`,
`ramp_ltp`, and `ramp_absolute` power specifications with an explicit endpoint.

The analyzer now accepts either a native Calculate payload or session data saved
by MCP `get_activity(save_session=true)`. It derives `dt` from `time`
or `seconds`, reports irregular intervals and the largest gap, integrates using
a sample-and-hold assumption, and rejects missing required model fields with a
field-specific error. Synthetic regression tests cover a three-second gap and
a missing `Wexp` value.

### Completed activity validation

Three feasible completed activities were fetched read-only from Xert:

```text
Type                         samples   max |XSS error|   max |Difficulty error|
VO2Max 4x4 plus VT1            7,330       5.3e-12             1.3e-13
VT2 2x18                       4,029       1.5e-14             5.7e-14
Variable outdoor endurance    10,872       6.0e-13             2.2e-14
```

All had regular one-second exported timestamps and stayed below MPA. Contrary
to Workout Designer Calculate summaries, completed-activity system XSS and
Difficulty were exactly reproducible from the exposed series to floating-point
precision. This establishes a source-specific distinction rather than one
global summary-integration rule.

Completed-activity recovery transitions also matched

```text
Wexp_next = Wexp * exp(-(TP-P)*dt/HIE)
```

to floating-point precision. The affine offset fitted to Calculate made these
activity transitions worse (`0.31-0.40 J` RMS), so that offset must remain
Calculate-specific.

The squared MPA reconstruction had maximum residuals of `0.0013 W` for VT2 and
`0.70 W` outdoors, but `39.91 W` in the VO2 activity at deep depletion. XSSR
still reconstructed exactly when using the activity's reported MPA. This means
the exported activity `wexp` and summary signature are not always sufficient to
recreate activity MPA during substantial depletion. Possible dynamic/internal
state remains unresolved; do not alter the exact per-sample XSSR conclusion.

### Expanded feasible Calculate matrix

Seventeen unsaved probes covered four signatures, 10-300 second steady efforts,
20-minute endurance, below-TP ramps, a ramp crossing TP, and repeated
work/recovery intervals. All remained in the explicitly allowed `P < MPA`
domain. That matrix established the pre-failure branch; the later controlled
failure probes extend Calculate validation beyond it. Signatures included:

```text
A: TP 250 W, HIE 10,000 J, PP 1,000 W
B: TP 296 W, HIE 14,000 J, PP   775 W
C: TP 350 W, HIE 25,000 J, PP   900 W
D: TP 300 W, HIE  5,000 J, PP   500 W
```

Observed worst-case reconstruction errors by workout family:

```text
Family                  n   max XSS abs   max XSS %   max Difficulty abs
constant endurance      1      3.7e-13      1.7e-12%       1.2e-13
steady over TP          8      0.02160      0.5333%         0.02782
ramps below TP          3      0.00664      0.0534%         0.00232
ramp crossing TP        1      0.00634      0.0374%         0.00237
repeated intervals      4      0.08393      0.5114%         0.88598
```

Across the full matrix, the largest absolute XSS error was `0.08393`, the
largest relative XSS error was `0.5333%`, and the largest Difficulty error was
`0.88598`. These are tested empirical bounds, not guaranteed global limits.
They support using reconstructed series for feasibility and mechanism analysis,
while retaining Calculate summary values for workout comparison and dosing.
Ramps introduce a small discrepancy even while MPA remains constant, likely
because the summary integrates a continuous ramp while the exposed series is
discrete; this extends the earlier MPA-change-only warning.

## Validation round: deep activity depletion, export gaps, and fixtures

Completed 2026-08-07.

Four additional completed activities were selected for substantial high/peak
load or variable outdoor power: 10x30-second anaerobic work, 2x8x60-second VO2,
a pursuiter-type outdoor ride, and a 374-minute outdoor ride. Together with the
three earlier activities, the audit covered more than 59,000 exported samples.

### MPA versus depletion

The new maximum `Wexp/HIE` values ranged from `0.289` to `0.785`. Maximum
absolute MPA residuals from the squared Calculate equation were:

```text
Activity family                 max Wexp/HIE   max MPA residual
VT2                                  0.002          0.001 W
moderate outdoor                     0.054          0.702 W
long variable outdoor                0.289         14.350 W
anaerobic 10x30 s                    0.575         39.292 W
VO2 2x8x60 s                         0.641         32.603 W
VO2 4x4 plus VT1                     0.767         39.912 W
outdoor pursuiter                    0.785         55.752 W
```

Pooled errors rose materially with depletion. Below `0.10 HIE`, median MPA
error was effectively zero and the 95th percentile was `0.235 W`. Between
`0.30-0.50 HIE`, median error was `8.97 W`; between `0.50-0.70 HIE`, it was
`13.56 W`. No single replacement exponent was stable across activity or
depletion bins.

In every activity, reconstructed XSSR remained within floating-point error when
reported MPA was used, and total XSS/Difficulty remained exact. The strongest
supported conclusion is therefore that exported activity `Wexp` plus the
summary/end signature omits state needed to reconstruct deeply depleted MPA.
It is not evidence against the reported activity MPA or downstream strain
formula.

### Export sampling policy

Every inspected native session export used consecutive one-second `time`
values. Each contained exactly two more samples than the reported activity
duration, consistently suggesting endpoint/padding samples on a server-normalized
model timeline. No genuine source timestamp gap was found, even in long outdoor
recordings.

The analyzer policy is now:

- continuous one-second export: authoritative summary comparison is allowed;
- irregular timestamps: sample-and-hold integration is diagnostic only and its
  summary residual is not model-validation evidence;
- missing `power`, `wexp`, or `mpa`: fail with a field-specific error.

### Anonymized regression fixtures

Two five-sample fixtures were derived from a real deeply depleted activity using
uniform dimensionless scaling. They contain no activity id, name, date,
location, route, sensor data, or original signature:

- `deep_depletion_segment.json` preserves an `18.27 W` normalized MPA residual
  while XSSR remains exact;
- `exponential_recovery_segment.json` preserves pure exponential activity
  recovery to below `1e-9 J` RMS.

These fixtures make the source distinction durable without retaining complete
personal activity files in the repository.

## Validation round: hidden-state audit and older/public data

Completed 2026-08-07.

### Exported candidate fields

All plausible additional activity-series fields were tested or classified:

- `mm` tracks distance in millimetres;
- `t_scaled` tracks the model time axis;
- `mmp0s` is equal to returned MPA and therefore contains the answer, not an
  independent causal state;
- `tws`, `hws`, and `pws` are cumulative downstream strain/work fields;
- `proximity` and the overage fields are derived diagnostics, not an HIE state.

Reconstruction with `prev_sig` was also tested. It did not fix deeply depleted
activities and was dramatically worse for several 2023 activities where Xert
had extracted a changed activity signature. The stored activity `sig` is the
correct available reference, consistent with Xert's documentation that activity
analysis starts from the preceding signature and may then extract a signature
for the activity.

No exported independent field remains that can explain the MPA residual.

### Older Xert activity processing

Three activities from 2023 and one race from 2021 were fetched read-only. All
retained the completed-activity pattern:

```text
Year/type                  max Wexp/HIE   max quadratic MPA error
2023, 30/30 VO2                0.149              1.79 W
2023, 45 s VO2                 0.210              2.71 W
2023, long VO2                 0.294              4.58 W
2021, race                     0.491             26.36 W
```

For all four, activity XSS and Difficulty reconstructed to floating-point
precision and below-TP recovery followed the pure exponential. The 2021 result
shows that the deep-depletion MPA discrepancy is not unique to current 2026
processing. Error magnitude again followed depletion more strongly than year.

### Open research implementation and dataset

The peer-reviewed PLOS One paper provides public supplementary files and links
to `HKont/3DIR-model-code`. That repository contains public FIT/power examples,
derived time series, and the analysis implementation. Its MPA mapping is the
published linear W-prime-balance form:

```text
MPA = TP + (PP-TP) * Wbal/HIE
```

This is not the production activity mapping. Across every inspected production
activity it was substantially worse than the squared Calculate diagnostic; for
the deeply depleted activities its maximum error was often above `100 W`.
The public repository is valuable for validating the paper's strain method but
does not contain Xert production session exports with `wexp`, reported MPA, and
the private server calculation. It therefore cannot independently validate the
Calculate-versus-production distinction.

### Identifiability conclusion

The remaining missing quantity is genuinely server-internal or algorithmic,
not merely an overlooked JSON field. A unique production MPA reconstruction
cannot be inferred from current exports. The analyzer now reports both squared
and published-linear MPA residuals and explicitly treats completed-activity MPA
as authoritative. Further identification requires a production-side field
definition, code detail, staff clarification, or a newly exposed state.

## Official sources

- XSS calculation and normalization:
  https://forum.xertonline.com/t/xss/6793
- Work allocation and system XSS:
  https://forum.xertonline.com/t/how-do-you-find-work-allocation-ratios-on-a-workout/6555
- TP, MPA, low strain, and Difficulty:
  https://forum.xertonline.com/t/100-tp-for-more-than-an-hour-in-workout-creator/33963
- Above-TP work and system buckets:
  https://forum.xertonline.com/t/xert-magic-buckets-impossible-interval-targets/47283
- Fitness Signature effects:
  https://forum.xertonline.com/t/workout-xss-hie-and-fatigue/35993
- Paper discussion and production caveats:
  https://forum.xertonline.com/t/research-paper/47398
- Recovery Demand and signature prediction:
  https://forum.xertonline.com/t/wellness-readings-from-intervals-icu-to-xert-instead-of-freshness-feedback/48945
- Difficulty:
  https://www.baronbiosys.com/glossary/xert-difficulty-scoring/
- Work allocation:
  https://www.baronbiosys.com/xerts-work-allocation-ratios-specificity-all-the-way/
- Fitness prediction:
  https://www.baronbiosys.com/fitness-prediction-and-potential/
- Research paper:
  https://arxiv.org/pdf/2503.14841
- Peer-reviewed paper and public supplementary dataset:
  https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0341721
- Public paper implementation and example FIT/power data:
  https://github.com/HKont/3DIR-model-code

## Preservation rule

Keep this document separate from resources loaded by the skill. When new
experiments alter a result, record the exact signature, probe structure,
Calculate output, residuals, and any change in evidence level here.
