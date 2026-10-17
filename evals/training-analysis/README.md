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
Each case gets a prompt and helper evidence. The manifest records source and
skill hashes, commands and output hashes. Source snapshots are local dependencies;
copy them with the manifest when moving the evaluation to another machine.

## Run the actual model evaluation

Use a fresh session for each case and model. Give it only the generated prompt,
the referenced skill and source artifacts, and the generated inspection.json.
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
