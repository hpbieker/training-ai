# Illness And Return

Use illness duration/severity, current symptoms and observed exercise response.
There is no automatic day-three clearance. A current-day sickness event blocks
training even if a model or an older assessment suggests recovery. Missing
sickness entries do not establish health. Preserve unresolved known episodes
across source windows: retrieve earlier records or supply their dates in the
assessment; do not infer recovery when an episode leaves a 14-day query.

For mild illness with symptoms resolved or only very mild local symptoms and no
warning signs, consider an easy exercise challenge. Reassess after 10–20 minutes.
The helper limits the initial prescription to 20 minutes pending review: this
is a conservative implementation choice, not a universal daily training limit.
Do not translate a percentage of normal exercise intensity into percent FTP.

Stop and seek medical assessment for chest pain, unusual breathlessness,
palpitations, dizziness, disproportionate fatigue/effort or other abnormal
exercise responses. Systemic symptoms or unresolved warning signs block training.
Moderate/severe illness needs clinical guidance. Severe illness requires an
appropriately supervised initial challenge, not an autonomous workout proposal.
This respiratory-illness framework does not replace diagnosis-specific advice.

Before progressing, review response during, immediately after and through 24
hours after the last return session. Unknown or abnormal response does not permit
progression. Adjust load individually and reassess after each session. Full
return requires demonstrated normal training tolerance; one good short test is
insufficient. The helper conservatively withholds a new prescription while the
response review is pending; never fabricate a normal response to clear it.

## Explicit Assessment

Both `readiness_snapshot.py` and `recommend_training.py` accept
`--illness-return-json '<assessment>'`. This is reviewed coaching context,
separate from unchanged MCP source payloads. Omit it when evidence is insufficient.

Required fields:

- `date`: target local ISO date; `assessed_at`: offset-aware timestamp on that
  date, no later than the recommendation's data cutoff;
- `illness_started_on`, `last_sick_date`: ISO dates identifying the episode;
- `severity`: `mild`, `moderate`, `severe`, or `unknown`;
- `symptoms`: `none`, `mild_local`, `systemic`, or `unknown`;
- `red_flags`: boolean, false only after checking warning signs;
- `clinical_review`: boolean; true means documented clinical advice supports
  the proposed return, including any required supervision;
- `response`: `not_started`, `pending`, `normal`, or `abnormal`;
- `return_complete`: boolean supported by normal training tolerance;
- `reason`: assessment and dose rationale, including illness duration;
- `evidence`: nonempty references to athlete reports, sessions or clinical advice.

For `normal` or `pending`, include offset-aware `exercise_ended_at`. Normal
means actually reviewed through the assessment time, not predicted recovery.
At least 24 elapsed hours are required before progression or full return.

For a challenge or graded return, also supply `dose_minutes` and `dose_xss`:
the justified duration and calculated load of the complete easy workout,
including warm-up/cool-down. These are limits, not an instruction to fill XATA's
remaining dose. A solver result exceeding the duration is rejected. Unresolved
illness yields rest and a follow-up question. Full return only removes the
illness restriction; ordinary readiness and plan checks still apply.

## Evidence

[IOC consensus on acute respiratory infections, 2022](https://doi.org/10.1136/bjsports-2022-105759)
supports severity-dependent assessment, an exercise challenge and monitoring
during, immediately after and 24 hours after exercise. It does not support a
universal two-day return schedule. The helper states and dose fields are
implementation choices, not a validated medical decision algorithm.
