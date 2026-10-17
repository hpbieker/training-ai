# Completed-session analysis evaluation

This suite evaluates the coaching answer produced with the skill, not merely
helper arithmetic. It uses saved real streams plus explicit test context.
Test assumptions (anchors, ERG and prescriptions) are scenario inputs, not new
athlete preferences or verified historical facts.

## Prepare a reproducible run

From the repository root:

```sh
python3 -B scripts/prepare_training_analysis_eval.py --output-dir /private/tmp/training-analysis-eval
```

The command reads local artifacts and runs activity_inspect into a **new** output
directory. It never contacts source services or updates plan state. Missing
artifacts fail preparation; do not silently substitute another activity.
Each case gets a prompt, freshly generated helper evidence, and a local snapshot
of only activity.json and streams.csv, plus the skill, calculation scripts and
two relevant context files. Legacy analysis.json files and reports are excluded.
The manifest records the original source hashes and every case snapshot file.
Keep the complete package with the manifest; embedded paths require regeneration
if moved. This is input isolation and an explicit read-scope instruction, not an
OS-level filesystem access boundary.

## Run the actual model evaluation

Use a fresh session for each case and model. Give it only the generated prompt and its case directory, including the copied
skill, raw artifacts and generated inspection.json. Do not grant additional
source-directory context or point it back to the original repository.
Do not provide cases.json, this rubric, earlier answers, or this conversation.
Allow read-only local inspection and temporary outputs; do not allow live-source
fetches, plan-state changes or remote writes. The prompt makes this restriction
explicit. Model runs are a separate step: preparation does not run Sol or Luna.

Save the exact answer and tool transcript, model identifier, reasoning effort,
run date and manifest hash. Keep the same inputs and settings when comparing
skill revisions. Use at least two fresh runs per case before treating a result
as repeatable. Do not infer that a model is better from one answer.

## Judge the answer

After the answer is complete, review it against the case's criteria in
cases.json. Those are review expectations, not a verbatim reference answer.
For each dimension assign 0 (wrong/absent), 1 (partly adequate), or 2 (adequate),
and quote the answer evidence supporting the assessment:

1. Actual task and completed work: distinguishes name, prescription, anchor,
   observed structure and completeness; does not hide omitted work.
2. Physiological synthesis: explains the decisive pattern in the context of
   the session; does not merely enumerate sensor values.
3. Evidence limits: respects quality scope, sensor dependence, missing context,
   and the distinction between acute response and residual cost/adaptation.
4. Practical conclusion: gives a direct, useful verdict and proportionate
   consequence, with only material uncertainties or follow-up questions.

A pass requires every case-specific required finding, no prohibited conclusion,
and no dimension scored 0. A score cannot offset an unsupported causal claim,
fabricated prescription/history/RPE, or unauthorized write. Record disagreement
between reviewers rather than forcing consensus. Do not automatically grade
semantic correctness with keyword matching.

Compare *which failures occur*, not just the total score. To measure the value
of research references, run a separate controlled comparison with the same
model, inputs and effort; record exactly which references were withheld.
Do not mix that experiment with testing a different script version.

## Current validation status

The first 20-run evaluation was completed on 17 October 2026: five cases,
two fresh runs each on Sol and Luna at medium reasoning effort. See the
[findings and limitations](results/2026-10-17.md) and the
[per-answer review record](results/2026-10-17.json). These are exploratory
behavioral results, not a controlled measurement of the articles' contribution.

A post-fix twenty-run evaluation is recorded in the
[follow-up findings](results/2026-10-17-postfix.md) and
[per-answer review](results/2026-10-17-postfix.json). The targeted errors did not
recur in that sample; recovery-metric scope and some response summaries still
need care.

The next [recovery-scope rerun](results/2026-10-17-recovery.md) completed twenty
more sessions. No 60-second error recurred, but no relevant answer quantified
HR recovery, so numeric interpretation remains unproven. See its
[per-answer review](results/2026-10-17-recovery.json).

A subsequent [targeted recovery test](results/2026-10-17-targeted.md) explicitly
requested all three HR differences. All eight answers got the requested values
and scopes right; one added incorrect minimum timestamps.

The [work-block overview rerun](results/2026-10-17-overview.md) tested the two
threshold cases in eight fresh sessions. Cross-bout swaps did not recur, but
one answer still misstated matched-window values and read a legacy analysis.

The final [isolated-package control](results/2026-10-17-isolated.md) completed
eight sessions with correct reported block/window attribution and no observed
application-data reads outside the case packages. One respiratory-unit wording
error remained. The recommendation is to stop repeated broad tuning and use
the skill on ordinary sessions.
