# Daily recommendation evaluations

These scenarios test recommendation composition and communication on the
same frozen inputs for Sol and Luna. They extend the completed-session suite
one directory above. They do **not** test live connectors or the complete
`recommend_training.py` CLI. The generator exercises the production intensity,
evidence-coverage, dose-composition and primary-decision helpers; the HRV cases
also execute the acute-readiness dose guardrail. The model
then interprets that precomputed packet using an isolated skill snapshot.

The calculation fixtures preserve unsaved Xert calculations from 18 October
2026. All readiness, calendar, capacity horizons and product-portion scenarios
are explicit test data, not current athlete facts or permanent preferences.
The capacity value is intentionally held constant across synthetic horizons to
test attribution rather than the load model. Endurance capacity was generated
with the plugin's pure offline solver and the fixture's signature and segments.

## Prepare and run

```sh
python3 -B scripts/prepare_training_recommendation_eval.py \
  --output-dir /private/tmp/training-recommendation-eval
python3 -B scripts/run_training_recommendation_eval.py \
  --inputs /private/tmp/training-recommendation-eval \
  --output-dir outputs/training-recommendation-eval/new-run \
  --models gpt-6.1-sol gpt-6-luna --repeats 2 --workers 2
```

Use `--cases missing_recovery normal_recovery later_complete_window` for a targeted
rerun; omitted cases are not evaluated. Prepare outside the repository (as above) to avoid inherited repository
context; archive a copy with results afterward. Use new paths for each run. The runner requires the authenticated Codex CLI and
model/network access. Each session is ephemeral and read-only, without user
config. The prompt restricts data reads to its own case directory. This is not
an OS-level isolation guarantee: audit transcripts for out-of-scope reads.
No source fetches, plan-state writes or remote mutations are permitted.
Do not give models this README, cases.json, previous answers or the rubric.

The input manifest hashes fixtures, generator, production helper, skill snapshots
and packets. The run manifest records exact model IDs, effort, commands, answer
hashes and whether inputs stayed unchanged. Exact answers and JSONL transcripts
remain under the Git-ignored output directory. Execution status is not a pass.
Keep the prepared package with the runs for audit/replay; paths are absolute.

## Review after answers are complete

Review each answer against the required/prohibited findings in `cases.json`.
Additionally assess these common dimensions as 0 (wrong/absent), 1 (partial) or
2 (adequate), quoting the answer evidence:

1. Correct plan role and treatment of completed versus remaining load.
2. Evidence and uncertainty: missing, normal and adverse observations differ;
   no automatic missing-data downgrade or assertion of confirmed readiness.
3. Dose and execution: justify quality and filler separately; follow the actual
   segment order and calendar; keep capacity distinct from recommendation.
4. Practical execution: relevant response checkpoint, feasible fueling arithmetic,
   and an alternative with explicit intensity and effect on the quality queue.

A pass requires all case-specific required findings, no prohibited conclusion,
and no dimension scored zero. A score cannot offset fabricated facts or an
unauthorized action. Do not grade semantics by keywords. Report reviewer
uncertainty and distinguish minor wording issues from changed decisions.
Use at least two fresh runs per model/case before calling a finding repeatable;
a small unblinded sample does not establish general model reliability.

Run deterministic regressions separately:

```sh
python3 -B -m unittest discover -s tests -p 'test_recommendation*.py'
```

Development results: [18 October 2026](results/2026-10-18.md),
[HRV regression, 22 October 2026](results/2026-10-22-hrv.md).

## Isolated HRV regression cases

`isolated_hrv_drop` and `isolated_hrv_missing_history` test the failure observed
on 22 October: a single low night was converted into a fixed 45-Low-XSS dose,
and TL above RL was interpreted as increasing recovery concern. The first case
contains actual three-night values; the second deliberately omits history.
Both use a frozen, offline Xert calculation for the 219-Low-XSS starting dose.
The expected behavior is justified coaching with explicit uncertainty, not
automatic acceptance of either 45 or 219 Low XSS. These are composition evals;
source ingestion and three-consecutive-night validation have deterministic
coverage in `tests/test_recommendation_hrv_dose.py`.
