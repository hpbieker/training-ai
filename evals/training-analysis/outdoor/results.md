# Outdoor analysis evaluation — 2026-10-18

## Decision

Prefer Sol for these detailed outdoor analyses. The revised evidence improves its physiological synthesis, but neither model meets all requirements when athlete experience is unknown. Luna still requires factual review. This is a small targeted experiment, not a general model ranking.

## Results

32 fresh medium-effort sessions; two repeats per model/case. Pass requires every required finding, no prohibited finding, and no zero dimension. Scores are descriptive and cannot cancel failures.

| Version and cases | Sol passes | Sol mean /8 | Luna passes | Luna mean /8 |
|---|---:|---:|---:|---:|
| Baseline: two development cases | 1/4 | 6.50 | 1/4 | 4.75 |
| First revision: same cases | 2/4 | 7.50 | 1/4 | 4.50 |
| First revision: two held-out cases | 4/4 | 8.00 | 2/4 | 5.50 |
| Overview revision: development cases | 2/4 | 7.50 | 1/4 | 4.50 |

In the final development round Sol passed both actual-athlete-report answers. Both unknown-report answers were otherwise strong but omitted the required focused follow-up question. Luna used the variable-work comparison in all four final answers, improving evidence discovery, but still made a moving-time error (3h22 instead of 5h02), framed variable riding as failing to count as VT1 work, and omitted relevant ventilation context. It passed one of the two actual-report answers. The overview change did not improve aggregate pass rate or scores.

The athlete's actual report is preserved: generally hard through much of the ride, little felt easy, pronounced respiratory tiredness toward the end, legs comparatively okay. Numeric RPE, intake and subsequent recovery remain unknown. No remote subjective fields or plan state were updated during this evaluation.

## Implemented changes

- Continuous best efforts are time-weighted and cannot cross recording gaps or missing samples. Today's best continuous 20 minutes is 236 W; the previous 248 W calculation incorrectly joined samples across a pause.
- Outdoor chronology separates recording interruptions from field-specific missingness and retains observed cumulative work.
- Mechanical matching offers two comparable variable five-minute windows when strict steady windows are unavailable. Selection does not use physiological outcomes. Today's selected windows are 61–66 and 225–230 elapsed minutes; the latter is not the finish. Their comparison is descriptive, not a validated durability test.
- Garmin Performance Condition and load survive the analysis handoff. The early PC fall must not become a story of late exhaustion.
- A compact overview distinguishes strict/variable methods, eligible pairs/selected windows and exact power-threshold scopes.
- Skill guidance evaluates group riding against its actual purpose and makes subjective experience central without inventing a mechanism or exact recovery duration.

## Verification and reproducibility

73 relevant automated tests pass; skill validation and git diff whitespace checks pass. Input hashes remained unchanged in all 32 sessions. Recorded completed commands were reviewed for live calls, external writes and out-of-package paths; none were found. This command audit is not an OS-level access audit.

Raw packages and transcripts are archived under `outputs/training-analysis-eval/2026-10-18-outdoor/`: baseline-inputs/runs, final-inputs/runs (first revision), overview-inputs/runs. Paths embedded in manifests refer to original temporary locations; regenerate packages for reruns. Exact answers, scores, usage and commands are retained in baseline-results.json, final-results.json and overview-results.json here. Blind review records precede model mapping.

One reviewer initially saw anonymized answers; case and method revision were known. This is neither independent review nor revision-blind scoring. The two holdouts were evaluated only with the first revision; they do not validate the later overview revision. Helper and skill changed together, so gains cannot be attributed to a single change. Matching tolerances are engineering choices, not established physiological thresholds.

A final small code guard limits outdoor evidence to Ride/VirtualRide with GPS and respects the selected field set. The frozen overview runs predate that guard; their default Ride inputs are unaffected by its intent. The guard is covered by code-level validation, not an additional model round.

## Remaining work boundary

This bounded improvement/evaluation round is complete; full reliability is not achieved. Before broader rollout, evaluate focused-question compliance and Luna's scope/time errors on new cases with an independent reviewer. Do not loosen the existing rubric to turn these failures into passes.
