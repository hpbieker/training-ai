# Variable outdoor ride evaluation

This evaluates offline analysis of frozen real rides, not live retrieval or
individual physiological truth. Four cases cover three rides: a group ride
with unknown athlete experience, the same ride with the athlete's actual report,
a separate steady-endurance scenario, and a second group ride with unknown
historical anchors. The latter two are held out from instruction development.
The steady solo intent/anchor is explicitly a scenario assumption, not newly
established historical fact. No confirmed intake or numerical RPE was supplied.

## Reproduce

Prepare outside the repository to avoid inherited repository instructions:

```sh
python3 -B scripts/prepare_training_analysis_eval.py \
  --cases-file evals/training-analysis/outdoor/cases.json \
  --output-dir /private/tmp/outdoor-analysis-inputs-NEW
python3 -B scripts/run_training_analysis_eval.py \
  --inputs /private/tmp/outdoor-analysis-inputs-NEW \
  --output-dir /private/tmp/outdoor-analysis-runs-NEW \
  --models gpt-6.1-sol gpt-6-luna --repeats 2 --effort medium --workers 4
```

The runner checks input hashes before and after sessions. It records exact model,
effort, commands, answers, JSONL transcripts, elapsed time and reported usage.
Prepare a new immutable package for every revision. Do not edit running packages.
Private real activity artifacts are required; they are not committed to Git.
No test may update plan state, fetch live sources or write externally.

## Review

Use the parent suite's four dimensions (0–2 each): actual task/work, physiological
synthesis, evidence limits, and practical conclusion. Required/prohibited
case findings are in cases.json and must not be supplied to evaluated models.
A pass requires all required findings, no prohibited conclusion and no zero
dimension. Keep a narrative issue record: totals do not offset factual errors.

Hide model identifiers for the initial semantic review. Retain exact answer
quotes and the mapping after grading. Audit recorded commands for package-scope
violations, live calls or writes. Command audit is not an OS-level access audit.
Do not grade solely by keywords or demand exact reference wording.

An outdoor analysis should explain what the rider actually did, how the response
developed in valid periods and what the athlete's report changes. A list of
sensor values and generic uncertainty is insufficient. Distinguish power-domain
anchors from prescription, comparable variable work from steady state, clock
pauses from field loss, and large dose from established residual cost.

## Engineering evidence boundaries

`outdoor_evidence` is descriptive. The five-minute matching tolerances and
30-minute chronological segmentation are engineering choices, not validated
physiological thresholds. Matching uses mechanics rather than response outcomes;
it reports accumulated observed work, timing, interruptions, field quality and
unresolved confounders. Do not interpret a selected pair as whole-ride durability,
threshold movement or a causal diagnosis. No match is a valid outcome.

The October 18 cycle changes helper evidence and instructions together; it can
evaluate the resulting workflow but cannot attribute any gain to one component.
Two repetitions per case/model are exploratory, not a reliability estimate.
Held-out cases test transfer of the first revised version, not a measured
before/after improvement: their baseline answers were not generated. They were
not rerun after the subsequent overview-routing change. See results.md for
revision-specific results and remaining failures.

## Compact packet and numeric audit

Add `--compact-packet` to preparation to start model sessions from
`analysis-packet.json`, retaining the full inspection and raw data on demand.
The model returns JSON paragraphs with scoped numeric citations and a separate
follow-up question. The runner records `numeric_validation` independently of
manual coaching review. A passing numeric audit does not certify semantic use,
physiology, completeness, or spelled-out numbers. Render ordinary paragraph
text for the user only after review; the JSON is an evaluation artifact.

For ordinary saved outdoor inspections:

```sh
python3 -B scripts/analysis_packet.py inspection.json --output analysis-packet.json
python3 -B scripts/analysis_packet.py inspection.json --answer answer.json
```

The module docstring documents the answer contract. Unknown anchors and missing
values are omitted rather than substituted. Seconds/minutes can be displayed
in supported time units with normal rounding. Incorrect values, unknown fact
references, mismatched scope labels, incompatible units and uncited numeric
literals fail validation. The source JSON path is retained for each fact.

## Sol completion and transfer suite

`sol-cases.json` adds four real rides not used in the earlier rounds and retains
the October 18 unknown-experience regression. Easy/hard reports on the July 5
and July 9 rides are explicit synthetic test contexts, not historical facts.
Run with `--cases-file evals/training-analysis/outdoor/sol-cases.json`,
`--compact-packet`, `--models gpt-6.1-sol --effort medium --repeats 2`.
See `sol-completeness-results.md` for independent review, source defects found,
focused reruns and version-specific limits. Earlier first-pass failures are
retained; final selected-case results must not be presented as pristine unseen
first-pass performance.

## Additional diverse rides, unchanged Sol workflow

`sol-diverse-cases.json` covers Vätternrundan, mixed hill repetitions, an equipment
check, a long mountain ride and a named VT1 ride with unknown historical anchor.
Use the compact-packet preparation mode and Sol medium with two repeats. This
round uses only saved source context, no synthetic experience and no repairs
between attempts. Findings are in `sol-diverse-results.md`; exact answers and
separate numeric/semantic grades are retained in `sol-diverse-results.json`.
