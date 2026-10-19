# Mogán: power-first interpretation and temperature sources

The user corrected the prior terrain criterion: with usable measured power,
work, duration and power distribution carry the primary workload evidence.
Elevation is optional context for cadence, coasting, posture or cooling; it
must not be counted as extra energetic load already included in measured work.
Omission of elevation alone is no longer a failure.

Original criteria are retained in `sol-diverse-cases.v1.json`; the versioned
replacement and focused case are in `sol-diverse-cases.json` and
`sol-mogan-cases.json`. Historical scores are preserved. Old answers are
re-reviewed separately under the same revised rubric used for new answers.
Thus rubric correction and changed model behavior can be distinguished.

## Implementation

The compact packet and skill now prioritize power evidence and explain when
terrain contributes additional context. `temperature_context` identifies device
temperature/environmental proxy, local skin temperature and wearable core
estimate separately. Availability, ignored fields and unknown status remain
distinct. Whole-record quality flags are retained separately from eligible
segment availability: a recording gap does not erase usable segment evidence.
No device-temperature value substitutes for absent core data, and a wearable
core estimate is not described as direct invasive measurement.

Tests cover absent core with present device temperature, ignored versus unknown
signals, and retaining whole-record quality flags with usable segments. All 92
relevant tests, skill validation and whitespace checks pass.

## Evaluation design

Two fresh Sol medium sessions on the same saved Mogán activity. Raw numeric
measurements and user context are unchanged; the packet and skill guidance are
revised. No synthetic experience is added. A separate reviewer sees anonymized
old/new answers, the revised rubric and source evidence, without prior scores.
It knows the revised criteria, so this is not a revision-blind causal study.
Numeric references are checked separately from prose semantics.

## Results under the same revised criteria

| Answers | Semantic pass | Numeric citations |
|---|---:|---:|
| Old Mogán answers, re-reviewed | 0/2 | 2/2 in original run |
| New Mogán answers | 2/2 | 2/2 |

Terrain omission did not affect any grade. The old answers still fail because
they discuss temperature without identifying the device/environmental source
and absent core data. The new answers explicitly identify device temperature
and distinguish it from core temperature; both use measured work, duration
and qualified variable-power comparisons without requiring elevation reporting.
One new answer says device temperature is not a core measurement; the other
explicitly states core data are missing. The reviewer accepted both, noting
that explicit missing-core wording is clearer.

This is a two-repeat targeted check, not proof of general reliability. The
rubric change is user-directed and documented, and old answers were judged
under the same new criteria. Guidance and packet changed together, so their
individual effects cannot be separated. No numeric source observations were
changed and no external activity or plan-state writes occurred.

All new sessions completed with unchanged input hashes. Recorded commands
showed no live calls, external writes or out-of-package paths; this is not an
OS-level access audit. Raw artifacts are archived under
`outputs/training-analysis-eval/2026-10-18-outdoor/sol-mogan-v2-inputs` and
`sol-mogan-v2-runs`. Exact old/new answers and scores are in
`sol-mogan-results.json`; independent grades in `sol-mogan-independent-review.json`.
The preserved original rubric hash matches the original diverse-run manifest.
