# Sol completeness and transfer — 2026-10-18

## Scope and method

Keep gpt-6.1-sol at medium effort. Add a grouped time overview and a concise
internal completion check to the packet and skill. Do not require a longer
user-facing checklist. The ordinary answer still explains this ride, its
qualified response, the athlete's experience and a supported training consequence.

Five cases, two independent fresh sessions each: one regression case from the
previous experiment and four real rides not previously used in this suite.
Case criteria were saved before generating answers. Two new cases deliberately
supply synthetic experience/intent, explicitly marked as test assumptions:

| Case | Source ride | Purpose of test |
|---|---|---|
| group_unknown | 2026-10-18 | Moving/elapsed/pause omission regression |
| large_easy | 2026-07-05 | Large workload with explicitly easy felt experience (synthetic report) |
| lower_hard | 2026-07-09 | Lower power and short duration with hard felt experience (synthetic report) |
| interrupted | 2026-07-06 | Large elapsed/moving difference and recording gaps |
| sparse_sensors | 2021-07-06 | No power, HR or specialist physiological streams |

Historical anchors, intake and subsequent recovery remain unknown in new cases.
Synthetic reports are not stored as historical athlete facts. No live retrieval,
plan-state change, remote activity mutation or automatic model routing occurs.

## Defect discovered in transfer

Preparing the sparse-sensor case exposed `observed_work_kj=0` when power was
entirely absent. The helper now returns null for absent power, including
segment work; measured zero power still gives zero work. Regression tests
cover both cases. This is a source-calculation defect, not a model mistake.

The first frozen five-case run was retained unchanged. The two sparse answers
from that run are superseded for final grading by two fresh sessions from a
separate corrected package. This first repair added two sessions. A second focused repair below adds two
more: 14 sessions total, with ten final answers selected for evaluation. This is a transfer-and-repair cycle, not ten pristine
first-pass trials on the final source version. The other four cases have
observed power and remain evaluated from their original frozen inputs.

## Verification

90 relevant automated tests pass. Skill validation and whitespace checks pass.
Independent code review confirmed timing separation, synthetic-context labels,
raw source availability and the absent-power correction. Numeric citation
checking remains separate from semantic review: passing references do not
certify their prose use or physiological conclusions.

## Duration citation repair

Initial independent semantic grading passed all ten selected answers, but the
numeric citation check passed eight. Both interrupted answers correctly stated
a five-minute best effort without a numeric citation for its duration. The
packet had offered only the effort's watts, with its duration embedded in the
scope label. A dedicated duration fact now points to `window_seconds`, allowing
seconds-to-minutes conversion using the existing checker. No checking criterion
was relaxed. Only this case was rerun twice in a new frozen package; initial
answers, validation failures and semantic scores are retained.

The reviewer also flagged overly categorical language about recording gaps
versus stationary time. Packet and skill now say these quantities need not
reconcile and prohibit deriving leftover stationary time by subtraction. The
new interrupted rerun includes that wording; the earlier sparse answers retain
their original limitation in the review record.

## Final results and decision

| Check | Final selected answers |
|---|---:|
| Independent semantic requirements | 10/10 |
| Numeric citation contract | 10/10 |
| Both | 10/10 |

The independent reviewer gave eight answers 8/8 and the two sparse-sensor
answers 6/8. Both regression answers now explicitly distinguish moving,
elapsed and recording-gap time. The easy/hard counterexamples preserve the
supplied experience and unknown recovery rather than letting workload override
felt effort. The interrupted-case reruns also avoid inferring leftover stopped
time. Sparse-sensor responses still offer less concrete route/terrain detail
and retain the earlier timing-language qualification in their review notes.

This supports using the revised Sol workflow, including the numeric and
semantic checks. It does not establish general reliability: four transfer
rides, two synthetic experience reports, two repeats and focused reruns are a
small exploratory sample. The reviewer was separate from the implementing
agent and did not read prior result reports, but also reviewed the code and
knew the revision; this is not a revision-blind study. Scores must not be
presented as ten flawless first-attempt answers.

Exact answers, commands, numeric failures, superseded reasons, source hashes
and review mapping are in `sol-completeness-results.json`. Independent grades
are in `sol-completeness-independent-review.json`. Frozen packages/transcripts
are archived under `outputs/training-analysis-eval/2026-10-18-outdoor/` as
`sol-completeness-*`, `sol-sparse-fixed-*`, and `sol-duration-fixed-*`. All 14
sessions preserved input hashes. Recorded commands showed no live retrieval,
external writes or out-of-package paths; this is a command audit, not an
OS-level access audit. Embedded temporary paths retain their original values.
