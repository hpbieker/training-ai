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

### Activity comparison

Read [references/activity-analysis.md](references/activity-analysis.md) for
each selected activity. Establish which sessions or work blocks are comparable,
then assess the observed differences and their uncertainty.

### Molecular stimulus analysis

If the user asks about a workout's physiological, cellular, biochemical, or
molecular stimuli, signalling pathways, or likely adaptations, analyze the
stimuli the workout likely produced based on its actual intensity, duration,
interval structure, and available sensor data.

Rank the most important signals, such as AMPK, CaMKII, p38, PGC-1alpha, p53,
HIF-1alpha, VEGF, and eNOS, by likely strength. For each, explain why it was
activated, what it affects, and which training adaptation it may contribute to.

Cover mitochondria, capillaries, muscle fibres, lactate, fuel use, ion handling,
VO2 kinetics, and durability when relevant. Distinguish observed responses,
likely signalling, and lasting adaptation. Finish with the primary effect,
secondary effects, and what the workout stimulated little.

### Readiness or daily recommendation

Read [references/daily-recommendations.md](references/daily-recommendations.md).
Also read
[references/cycling-endurance-physiology.md](references/cycling-endurance-physiology.md)
when prescribing a long ride, late-session intensity, severe intervals, heat
exposure, or deliberate low-carbohydrate availability.
Also use the repo-local `training-plan` skill: discover active plans under
`config/plans/`, select the applicable plan, decide the current plan role, and
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
Call it with the current Intervals.icu activity directory, `--xert-session`
for the matching saved Xert session, and `--output` for the PNG. Inspect the
result, then attach it through the Strava media workflow.

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
