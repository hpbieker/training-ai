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

### Activity or workout analysis

Read [references/activity-analysis.md](references/activity-analysis.md).

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

## Output

- Answer in chat unless the user explicitly requests a report file.
- Keep `outputs/` artifacts as working evidence; do not link JSON packets in a
  normal recommendation.
- If the final recommendation differs from the helper script's recommendation,
  briefly explain the deviation and its reason.
- Lead with one clear recommendation. Include timing, duration, warm-up,
  watts/intensity, route or setup, practical fueling, and the decisive reasons.
- Every training recommendation must also include a separate
  `Capacity before the next workout` section. Resolve the next day's planned workout role
  and exact practical start time, then report how much training can be performed
  at the current recommendation's planned start while still reaching Xert's
  fresh boundary for that next workout. Show the limiting Low/High/Peak XSS
  capacity, convert the relevant limit through the actual proposed workout
  structure to minutes and watts, and distinguish this maximum from the
  recommended dose. Read the detailed workflow in
  [references/daily-recommendations.md](references/daily-recommendations.md).
- Every training recommendation must present these three items explicitly and
  separately, even when the recommendation packet already supplies the final
  selection:
  1. `Physiological scope`: the readiness ceiling—what intensity current
     physiology and recovery allow, independent of what the plan calls for.
  2. `Training need`: the intensity direction indicated by the resolved
     goal, progression history, and recent same-family stimulus/load.
  3. `Final recommendation`: the selected intensity domain and concrete dose after
     combining the first two dimensions with logistics, weather, and body feel.
  Translate these three canonical labels and `Capacity before the next workout`
  into the user's language. Use the same translated wording consistently, keep
  the three layers in this order, and present capacity as a separate section.
  Do not collapse the first two into justification for the third or report only
  the final recommendation. State clearly when physiology allows harder
  training than the plan selects. Explain why the resulting domain (for example
  rest, recovery, VT1, VT2, or VO2max) is preferable to the next harder and
  easier alternatives. Do not infer VT1 rather than VT2 from a predominantly
  low-XSS target split; both can generate predominantly low XSS.
- Include only modalities available at the resolved location. When indoor and
  outdoor cycling are both available, give concrete versions of both and state
  which wins.
- Label each training-load value with its source and metric; never treat values
  from different sources as interchangeable.
- State missing or stale inputs and how they reduce confidence before upgrading
  intensity.
