# Intervals.icu skill evaluations

Four synthetic cases cover missing versus zero wellness, whole/partial ignore
flags, irregular stream sample indices with WORK-only interval edits, and
source-limited search versus complete date-range activity listing.

`cases.json` contains inputs, questions and review criteria. Each isolated
model package contains only the current skill, synthetic input, prompt and
actual relevant MCP definitions; review criteria are withheld. Models propose
calls without a live Intervals.icu connection. No personal activity data or
credentials are included.

Run each case in a fresh read-only Sol and Luna session at medium effort.
Review full answers and proposed calls manually against the initial criteria
and actual schemas. Check package hashes and command transcripts afterward.
This evaluates interpretation and tool selection, not live remote behavior.

Raw packages, preparation/runner scripts, manifests, answers and command
transcripts are archived under `outputs/intervals-skill-eval/2026-10-17/`
(Git-ignored). The 93 local Intervals-related tests passed after the preceding
implementation changes; this model evaluation does not replace those tests.

Results: [17 October report](results/2026-10-17.md) and
[full answer review](results/2026-10-17.json).

The [partial-ignore follow-up](results/2026-10-17-postfix.md) passed all four
interpretation checks; one Luna answer still proposed an unsupported inline
field in a follow-up read.
