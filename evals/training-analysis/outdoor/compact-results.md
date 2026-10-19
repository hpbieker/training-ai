# Compact packet and numeric checking — 2026-10-18

## Implemented

`analysis_packet.py` builds a compact outdoor packet from a current inspection.
Every numeric fact retains its source JSON path, unit and scope. The full
inspection and raw inputs remain available on demand. The packet for the
October ride is 13,472 bytes versus 157,522 bytes for the full inspection
(91.4% smaller). This is file size, not a token or cost saving estimate.

A structured answer separates ordinary prose paragraphs, declared numeric
citations and a focused follow-up question. The checker rejects incorrect
values, unsupported conversions, unknown facts, mismatched scope labels,
missing citations and malformed references. Unknown anchors remain unknown.
Numeric checking does not validate prose meaning, spelled-out numbers,
completeness, causal explanations or coaching decisions. No automatic model
routing or external writes were introduced.

## Model experiment

16 fresh sessions: four existing cases, two repeats for each model, medium
reasoning effort. The cases reuse the previous experiment for comparison;
none is a new unseen holdout. Compact evidence, structured answer format and
explicit question instructions changed together, preventing attribution to a
single component.

| Model | Numeric contract passed on first answer | Mean seconds, all four cases |
|---|---:|---:|
| gpt-6.1-sol | 8/8 | 75.5 |
| gpt-6-luna | 0/8 | 30.5 |

Luna's failures are chiefly contract errors: display strings containing units,
citations absent from the paragraph, unsupported unit names and uncited
numbers. They must not be reported as eight factually wrong analyses. The
responses were not repaired or silently normalized to improve the pass rate.
Sol's numeric pass is not a semantic endorsement.

On the same two development cases, reported mean input-token usage fell from
426,104 to 374,069 for Sol (about 12%) and from 352,300 to 209,693 for Luna
(about 40%) relative to the overview round. Some sessions still opened the full
inspection. These are observed exploratory usage figures, affected by tool
choices, repeated reads and cache accounting; no pricing/cost claim is made.
Mean durations for those cases changed from 82.0 to 80.8 seconds and from
35.3 to 30.9 seconds, respectively.

All answers now contain a follow-up field. Whether each question is relevant,
and whether known experience remains central, are assessed independently in
semantic review rather than inferred from field presence.

## Validation and provenance

86 relevant automated tests pass after updating the snapshot fixture to include
the new script. Skill validation and whitespace checks pass. An independent
code review found attached-unit bypass, malformed-field robustness and a
ride-specific PC scope label; all were corrected, with regression tests.

The model inputs stayed immutable in all 16 sessions. Frozen packages predate
those review fixes and the small skill routing addition. The final checker was
rerun on all frozen model answers and original packets; results are preserved
separately from the runner's initial validation. The neutral PC label in newly
generated packets has not had a further model round. Model behavior claims
therefore apply to the archived frozen inputs, not every final source change.

Answers, commands, usage and validation results: `compact-results.json`.
Raw immutable inputs and transcripts:
`outputs/training-analysis-eval/2026-10-18-outdoor/compact-inputs` and
`compact-runs`. Recorded completed commands were checked for external paths,
live calls and writes; none were found. This is not an OS-level access audit.

## Independent semantic review and decision

A separate reviewer saw anonymized prose and follow-up fields, case context,
rubric and source evidence, without model identities or prior results. It
reviewed semantics separately from the numeric contract:

| Model | Semantic pass | Both semantic and numeric pass |
|---|---:|---:|
| Sol | 6/8 | 6/8 |
| Luna | 4/8 | 0/8 |

Sol now asks the material question in both unknown-experience cases, but both
answers omit the required total-versus-moving-time distinction. Its other six
answers pass. Luna's semantic failures include a substantial Finnish paragraph,
omitted interruption or intake context, and one incomplete answer reporting
3.6 kJ rather than approximately 3634 kJ. The latter is also rejected by the
numeric audit as an uncited number. Numeric and semantic checks complement
one another; neither should replace the other.

Continue to prefer Sol for this workflow, with review of completeness. Do not
automatically accept Luna output on the strength of its shorter runtime. The
small packet improves information access and the question behavior improved,
but this experiment does not demonstrate a reliable complete workflow or a
general improvement across new rides. The prior round had a different reviewer,
so score changes are not a controlled causal comparison.

The implemented priorities were compact evidence and numerical claim checking,
with the known/unknown athlete-report pair retained. New counterexample rides
and automated routing remain unimplemented; this run must not be represented
as validation on new held-out rides.
