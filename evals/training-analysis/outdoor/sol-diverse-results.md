# Sol: five additional outdoor cases — 2026-10-18

This round tests the current workflow unchanged: gpt-6.1-sol, medium effort,
two fresh sessions per case. Ten first attempts; no response repairs, input
changes or instruction tuning during the experiment. Case-specific requirements
were saved before model calls. No synthetic athlete experience is supplied.

| Case | Real ride | Why included |
|---|---|---|
| ultra | Vätternrundan, 2026-06-13 | Very long duration despite modest average power; event time versus recording time; model fuel-use estimates |
| hill_repeats | Olav Bulls vei x 6 + Sørkedalen x 3, 2025-08-09 | Repeated harder work mixed with endurance; title is not verified prescription |
| equipment | Utstyrssjekk, 2026-06-12 | Short, explicitly practical purpose; avoid treating it as failed endurance training |
| mountain | Mogán, 2025-07-26 | Long duration and extensive climbing; no core-temperature stream; location does not prove heat limitation |
| named_vt1 | VT1 65 min (Sørkedalen x 2), 2026-06-27 | Named target versus actual total duration and unknown historical threshold |

All are new to these outdoor evaluation rounds. Historical anchors, felt
effort, food/fluid intake and subsequent recovery remain unknown unless the
sources explicitly establish them. Saved activity descriptions with estimated
Xert calorie/substrate use are not measurements of consumed food or metabolism.

Semantic review is independent of the implementing agent and uses anonymized
run IDs, predefined criteria and raw/frozen evidence. The reviewer can inspect
case identities and knows the workflow; this is not revision-blind. Numeric
citation checks are reported separately, because they do not validate prose
meaning, completeness or physiology. No live data or training plan is changed.

## Results

| Case | Semantic pass | Numeric citations pass |
|---|---:|---:|
| Vätternrundan | 2/2 | 2/2 |
| Hill repetitions + endurance | 2/2 | 2/2 |
| Equipment check | 2/2 | 2/2 |
| Mogán mountain ride | 0/2 | 2/2 |
| Named VT1 ride | 2/2 | 2/2 |
| Total | 8/10 | 10/10 |

Eight answers scored 8/8 on the semantic rubric; two mountain answers scored 6/8.
The mountain omissions repeat across both runs: neither integrates the 3085 m
climbing/terrain into the verdict, and both discuss temperature without
identifying it as device/ambient temperature or explicitly preserving absent
core-temperature data. They do not invent a numerical core temperature or
diagnose heat limitation. This is a material completeness/source-meaning
failure, despite correct numeric citations and otherwise qualified analysis.

The other cases preserve important distinctions: large total demand despite
modest mean power, varied hill work versus verified prescriptions, practical
equipment-check purpose versus training stimulus, and a named VT1 target
versus actual whole-ride duration and unknown historical anchor. The named VT1
answers do not assert 65 minutes of verified VT1 work. No prohibited causal
physiological diagnosis was found in the semantic review.

## Consequence

Keep Sol with the existing numeric and semantic review. The next targeted
improvement should expose terrain/climbing and temperature source/availability
more clearly in the compact packet and assess whether the verdict actually
uses them where material. No implementation or rerun was done in this round:
these are the preserved first-attempt outcomes on new cases, not repaired
scores. This small offline sample does not validate live data discovery or
establish general reliability.

## Audit and artifacts

All ten sessions completed and preserved input hashes. Recorded completed
commands were reviewed for live requests, external writes and paths outside
the test package; none were found. This is not an OS-level access audit.
The analysis code and skills were unchanged throughout the round; only new
evaluation cases, results and documentation were added. Whitespace check passes.

Exact answers, numeric checks, commands, usage and semantic mapping:
`sol-diverse-results.json`. Independent review: `sol-diverse-independent-review.json`.
Frozen inputs/transcripts: `outputs/training-analysis-eval/2026-10-18-outdoor/sol-diverse-inputs`
and `sol-diverse-runs`. Embedded paths retain their original temporary locations.

## Subsequent rubric correction

The user correctly challenged mandatory elevation reporting when power is
available. The original criteria are preserved in `sol-diverse-cases.v1.json`;
`sol-diverse-cases.json` now explicitly versions the corrected criteria. The
8/10 result above is historical under the original rubric, not automatically
re-scored. See `sol-mogan-results.md` for separate re-review of old answers and
new Sol answers under the revised power-first/temperature-source criteria.
