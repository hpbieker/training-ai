# Sol: new-activity generalization check

Four outdoor activities were selected before model execution and checked against all existing files in `evals/training-analysis/` for prior activity-ID references. They were absent. This establishes unused activities in the local evaluation corpus, not that the model or broader project has never encountered them.

The current analysis skill was frozen, and cases/rubric were written before execution. Each case starts with only an activity ID and raw-cache access; a second turn resumes the exact session with explicitly synthetic subjective context. Two followups report harder experience and two report controlled/easy experience. Synthetic reports are not written into historical training records.

The cases span a short post-illness form test, a six-hour ride with no SmO2, a low-average-power group ride, and an Algarve ride with thermal measurements. This checks generalization and naturally absent sensor data. It does not test artificially corrupted sensors or live connector authentication/sync.

```sh
python3 -B scripts/run_training_dialog_eval.py \
  --cases-file evals/training-analysis/holdout/cases.json \
  --output-dir <new-path> --repeats 1 --workers 4
```

Model: gpt-6.1-sol, medium. One run per activity, four two-turn conversations. This broadens activity diversity rather than estimating repeatability. Each workspace contains all four raw activities as possible lookup targets, current helpers and skill/context files, but no derived analyses, rubric or expected answers.

Review initial answers and followups separately against `cases.json`, using exact answers, executed commands and raw sources. Keep critical failures distinct from minor writing improvements. Any repeated use of these cases after tuning is regression testing, not a fresh holdout evaluation. CLI usage is preserved as reported; resume counters may be cumulative and should not be summed across turns.

Recorded outcome: [results.md](results.md), exact transcripts/commands in [results.json](results.json), and [independent review](independent-review.json).

Follow-up regression after precision fixes: [results-v2.md](results-v2.md). These activities are no longer untouched holdouts.
