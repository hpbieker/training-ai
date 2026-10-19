# Raw-cache analysis and conversational update

Run:

```sh
python3 -B scripts/run_training_dialog_eval.py \
  --cases-file evals/training-analysis/dialog/cases.json \
  --output-dir <new-path> --repeats 2 --workers 4
```

Model is deliberately fixed to gpt-6.1-sol medium.

Each run has a separate workspace containing the analysis skill, helpers,
coaching/practical context and an allowlisted raw activity pool. User turn one
contains only an activity ID. No derived inspection, compact packet, expected
answer or JSON output schema is supplied. The model may generate its own local
analysis. AGENTS.md only supplies skill discovery, cache location and test
isolation/write boundaries. Exact data discovery and source use are audited.

The initial CLI session is persisted, and turn two resumes its exact returned
thread ID; `--last` and transcript replay into a new session are not used.
The manifest records both thread IDs to verify continuity. Four runs yield
four conversations/eight turns. The long-ride follow-up replays actual athlete
feedback; the short-ride report is synthetic test context only.

All initial files are hashed before and after both turns. Generated artifacts
are allowed; source/context modifications are failures. Workspace-write is
required for normal helper-generated artifacts, while external writes and live
retrieval are prohibited. This tests raw-cache lookup, calculation, freeform
coaching and conversational adaptation, not live connector authentication,
sync freshness, scheduling or the complete production environment.

Rubric in cases.json is not copied into model workspaces. Independent review
scores initial answer and update separately, considering command provenance.
Unchanged provisional advice is acceptable if the new information meaningfully
sharpens the verdict and uncertainty; do not reward unnecessary reversal or
invented precision. There is no automated numeric-citation contract for these
ordinary prose answers. Numerical and physiological claims need source review.

Latest recorded run: [results-v3.md](results-v3.md), with exact answers and command
provenance in [results-v3.json](results-v3.json). Original baseline: [results.md](results.md). Full raw snapshots and CLI events are
archived under `outputs/training-analysis-eval/2026-10-18-dialog/` and
`outputs/training-analysis-eval/2026-10-18-dialog-v2/` and
`outputs/training-analysis-eval/2026-10-18-dialog-v3/`.
CLI token usage is preserved verbatim; resume counters may be cumulative, so
turn totals must not be added together as independent usage.
