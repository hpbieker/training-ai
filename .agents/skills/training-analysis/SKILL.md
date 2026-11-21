---
name: training-analysis
description: Use in the training-ai repo for workout analysis, activity comparison, readiness questions, daily training recommendations, outdoor route selection, weather-informed decisions, and composing normalized source data with repo helpers.
---

# Training Analysis

Use this skill for repo-level orchestration, local artifacts, cross-source
composition, and the final coaching answer. Source plugins own authentication,
live access, field semantics, and remote write safety.

## Context And Sources

- Apply `config/coaching-preferences.md`, `config/practical-context.md`, and
  other relevant LLM-readable context under `config/`.
- Resolve personal-context conflicts in this order: explicit current message,
  temporary rule, durable memory, stable practical context, generic fallback.
- Never make helper scripts parse personal profile or plan Markdown. Resolve the
  context as the agent and pass explicit CLI arguments or normalized JSON.
- Read the relevant plugin skill before using a source. Resolve its linked
  references relative to that skill's directory.
- Run the `scripts/` commands in this skill from the repository root.
- Prefer original-source values for source-specific semantics and use
  aggregation copies only when they are the best available input.
- Keep comparable timestamps in UTC internally and convert at local-calendar or
  user-display boundaries.

## Choose The Workflow

Choose the workflow that answers the user's request. Combine analysis and a
new training recommendation only when both are requested; a brief consequence
for subsequent training within an activity analysis does not require a complete
daily recommendation.

### Activity or workout analysis

Read [references/activity-analysis.md](references/activity-analysis.md) to
assess a completed session's execution, physiological response, and meaning.
Follow its [reference reading order](references/activity-analysis.md#reference-roles-and-reading-order):
this entrypoint selects the workflow, the activity reference directs the
analysis, specialist references qualify the measurements, and the synthesis
reference integrates the findings.

For late efforts on long rides, compare elapsed time, work already completed and
carbohydrate actually consumed before the effort. Use the
[cycling physiology reference](references/cycling-endurance-physiology.md) when interpreting durability.

### Capture athlete feedback

At post-ride review, first read saved feedback, the activity analysis and
completed intervals. When the reason for a shortened set or omitted extension
could change a future dose, ask what made the athlete stop there. For a long
reference ride, ask about the late response at comparable power only if it is
missing and materially changes how the ride can be used. Capture actual intake
only when it could explain the response. Link the next quality result from the
activity history when it becomes available.

Save each relevant answer verbatim locally with
`python3 scripts/athlete_feedback.py --activity-id ID --observed-at DATE_OR_TIMESTAMP --reported-at ANSWER_TIMESTAMP --context SCOPE --question QUESTION --answer ANSWER`.
Use the real answer time with offset, the exact saved activity and the date of
the observation if its clock time is unknown. Split distinct observation times
(e.g. why yesterday's set ended and today's soreness). For pre-ride answers
about a previous ride, use that ride's ID and distinguish current status in
the observation context. For a standalone pre-ride answer when the upcoming ride has no activity ID,
use the latest completed activity as a history anchor and label the context
as pre-ride status for the decision date; it describes the upcoming session. Read back the saved record. Preserve earlier
answers when recording corrections.

### Activity comparison

Read [references/activity-analysis.md](references/activity-analysis.md) for
each selected activity. Establish which sessions or work blocks are comparable,
then assess the observed differences and their uncertainty. Use the same
reference reading order, selecting the specialist guidance relevant to the
measurements and session structures being compared.

### Molecular stimulus analysis

When the user asks about a workout's cellular, biochemical, or molecular
stimuli, signalling pathways, or likely adaptations, first establish actual
execution and physiological response through the
[activity analysis workflow](references/activity-analysis.md). Reuse an existing
analysis when it covers the same session and relevant evidence.

Use that analysis and relevant research references to explain plausible links
between the actual intensity, duration, work-recovery structure, possible
signalling, and expected adaptations. Select mechanisms for their relevance to
the question rather than covering a fixed list of pathways or organ systems.

Keep general research findings, observed responses in this session, plausible
session-specific mechanisms, and demonstrated individual adaptation distinct.
Do not present signalling pathways as measured to be activated or rank their
individual activation strength without suitable measurement evidence. Ordinary
activity streams may support a stimulus interpretation without establishing the
molecular response or lasting adaptation.

Apply the shared
[competing-mechanism](references/physiological-response-synthesis.md#explain-competing-mechanisms)
and [adaptation](references/physiological-response-synthesis.md#compare-sessions-and-assess-adaptation)
rules. Explain the most relevant expected effects, the supporting session
features and research, and what remains uncertain for this athlete.

### Readiness or daily recommendation

Read [references/daily-recommendations.md](references/daily-recommendations.md).
Also read
[references/cycling-endurance-physiology.md](references/cycling-endurance-physiology.md)
when prescribing a long ride, late-session intensity, severe intervals, heat
exposure, or deliberate low-carbohydrate availability.
Use the repo-local [training-plan skill](../training-plan/SKILL.md) to find active
plans under `config/plans/`, select the applicable plan, decide the current plan role, and
pass that role to the recommendation helper through an explicit
`intensity_goal` inside `--plan-selection-json`. Do not use a generic goal as a substitute for plan
selection, and do not make a helper parse an LLM-readable plan file.
Use the narrow readiness helper for a focused question and the recommendation
helper for a complete session decision:

```bash
python3 -B scripts/readiness_snapshot.py --time-context-json '<normalized-time-context>' --source-inputs-json '<normalized-source-map>'
python3 -B scripts/recommend_training.py --planning-context-json '<normalized-json>' --plan-selection-json '{"intensity_goal":"<role>"}' --summary
```

Treat helper output as structured evidence, not the final recommendation.

### Outdoor route recommendation

Read [references/outdoor-routes.md](references/outdoor-routes.md).

### Strava workout card

When the user asks to add a banner, card, or workout image to a completed
Strava activity, use `scripts/generate_strava_workout_card.py` by default.
After renaming in Intervals.icu, fetch and save fresh metadata for the same
activity ID before rendering. Call the generator with that activity
directory, `--xert-session` for the matching saved Xert session, and `--output`
for the PNG. Pass `--workout-role vo2max` or `--workout-role vt2` when the
completed role is confirmed. Pass `--inspection` with the same activity's
brief inspection JSON when it contains a measured `steady_vt1_segment`.
For VO₂max and VT2 cards, request the completed activity's model series with
Xert's `analyze_activity_xert_2(save_series=true)` and pass the saved file as
`--lactate-series` when available. The card shows the estimated maximum within
each work interval when the series covers every displayed interval.
Inspect the finished PNG against the recorded work before uploading. Check
the interval count, duration and power, and the duration and power of any
measured aerobic finish. Attach it through the
[Strava media workflow](../../../plugins/strava/skills/strava/references/write-safety.md#activity-media).

## Output

### Shared rules

- Answer in chat unless the user explicitly requests a report file.
- Label each training-load value with its source and metric; never treat values
  from different sources as interchangeable.
- State missing or stale inputs when they materially limit the conclusion.
- Use the output rules for the selected workflow below. Route recommendations,
  molecular explanations, and workout cards follow their own workflow above.

### Completed-activity analysis

Lead with a concise verdict on the actual session and whether it fulfilled its
purpose. Explain mechanical execution, integrated physiological response, and
what the findings mean for recovery and progression. Keep observed responses
separate from modeled stimulus and inferred adaptation. Use the detailed
[analysis reporting contract](references/physiological-response-synthesis.md#reporting-contract).

### Activity comparison

Lead with the main supported difference. Identify the compared sessions or work
blocks, explain their comparability and material confounders, and distinguish
execution differences from physiological response differences. State what the
comparison supports about development and what remains uncertain; a difference
between sessions does not by itself establish adaptation.

### Readiness question

Answer the specific readiness question using the relevant evidence and its
limitations. Use the readiness guidance in
[references/daily-recommendations.md](references/daily-recommendations.md).
Apply the full recommendation output contract when the user also requests a
concrete session decision.

### Training recommendation

Follow the
[Final Answer Contract](references/daily-recommendations.md#final-answer-contract),
including the separate physiological scope, training need, final recommendation,
and capacity before the next workout. Recommendation-specific timing, dose,
fueling, alternatives, and artifact handling belong to that workflow.
