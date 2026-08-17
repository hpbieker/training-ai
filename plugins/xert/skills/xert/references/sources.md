# Xert Source Registry

Use this registry to distinguish published Xert semantics, locally validated
behavior, and claims that remain outside the available evidence.

## Evidence Order

1. Current official Xert/Baron Biosystems glossary and support pages establish
   product meaning and user-facing behavior.
2. Xert staff articles and forum answers add implementation context, but may
   describe an older product version.
3. Controlled read-only or unsaved probes document current observed behavior;
   keep the test conditions and do not generalize beyond them.
4. Peer-reviewed work can validate the published physiological model, but not
   the complete proprietary production service.

When sources conflict, prefer the current product terminology plus current
observed behavior. In particular, do not transfer the direction of the older
`Freshness Feedback` slider to today's `Recovery Demands` setting.

## Primary Sources

| Topic | Source | Supports | Does not establish |
|---|---|---|---|
| XSS | [XSS glossary](https://www.baronbiosys.com/glossary/xss/), [Xert staff forum explanation](https://forum.xertonline.com/t/xss/6793) | XSS as signature-relative strain and Low/High/Peak system load | Every private production equation |
| Status and Form | [Training Status and Form](https://baronbiosys.com/glossary/training-status-and-form/), [updated Training Status](https://www.baronbiosys.com/updated-training-status/) | Star thresholds, freshness colors, and that status represents recorded data rather than subjective feeling | A complete whole-body readiness score |
| Recovery Demands | [Recovery Demands glossary](https://baronbiosys.com/glossary/recovery-demands/) | Moving right is more conservative and lengthens modeled recovery | Subjective recovery or recovery from non-cycling stress |
| Older freshness control | [Assessing Readiness to Train](https://baronbiosys.com/assessing-readiness-to-train/) | Historical description of Freshness Feedback | Direction of the current Recovery Demands setting |
| Adaptive advice | [Training with XATA](https://baronbiosys.com/training-with-the-xert-adaptive-training-advisor/), [full glossary](https://baronbiosys.com/full-glossary/) | XATA considers load, deficit/surplus, Improvement Rate, program phase/focus, status, and available time | Exact proprietary scoring weights or an optimal physiological prescription |
| Progression target | [Improvement Rate](https://baronbiosys.com/glossary/improvement-rate/), [Training Availability](https://baronbiosys.com/glossary/training-availability/) | Weekly progression intent and availability as constraints on advice | That `targetXSS` equals total deficit or maximum absorbable load |
| Workout matching | [Training Suitability](https://baronbiosys.com/glossary/training-suitability/), [XSSR Preference](https://baronbiosys.com/glossary/xssr-pref/), [XSS Buckets](https://baronbiosys.com/xss-buckets/) | Suitability uses XSS, Difficulty, and Focus; XSSR Preference changes dose density in available time | That `Productive` proves superior adaptation, or that XSSR is readiness/Difficulty |
| Data completeness | [Xert FAQ](https://baronbiosys.com/support_home/frequently-asked-questions/) | Cycling power history must be sufficiently contiguous; missing load can distort TL/status | Valid automatic cycling-XSS equivalence for other sports |
| Fitness response | [Fitness Breakthroughs](https://baronbiosys.com/glossary/fitness-breakthroughs/), [PLOS ONE paper](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0341721), [public model code](https://github.com/HKont/3DIR-model-code) | Breakthrough semantics and independent publication/code for the underlying 3-parameter model | Validation of Xert's complete private advice, decay, or breakthrough service |

## Local Empirical Evidence

See [Xert model research](../../../../../docs/research/xert-model-research.md)
for controlled probes, equations, and validation samples. It currently supports
the TL/RL recurrence, RL floor, status boundaries, Recovery Demands direction,
Planner impulse timing, and marginal `k1 * delta_TL` response under the stated
conditions.

A live read on 2026-08-08 also returned `xss_deficit = 507.2084` while the
availability-restricted `targetXSS` summed to `264.2`. This is direct evidence
that `targetXSS` can be a constrained planning dose rather than the total XSS
deficit.

## Claim Boundaries

- Call `targetXSS` an adaptive planning/progression target, not physiological
  need, maximum tolerable dose, or a recovery prescription.
- Call status/Form cycling-load context. Combine it with current physiological
  and subjective signals when deciding readiness.
- Explain `Productive` as a match to Xert's requested progression, not proof of
  a workout's causal training benefit.
- Call local TP/HIE/PP results marginal Training-Load-matched projections, not
  guaranteed future signatures.
- Do not claim independent validation of the full XATA recommendation system,
  Recovery Demands calibration, proprietary decay, or production breakthrough
  detection. Those remain open evidence gaps.
