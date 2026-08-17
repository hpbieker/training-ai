---
name: training-analysis
description: Use in the training-ai repo for workout analysis, activity comparison, readiness questions, daily training recommendations, outdoor route selection, weather-informed decisions, and composing normalized source data with repo helpers.
---

# Training Analysis

Use this skill for repo-level orchestration, local artifacts, cross-source
composition, and the final coaching answer. Source plugins own authentication,
live access, field semantics, and remote write safety.

## Context And Sources

- Apply `PREFERENCES.md` and relevant LLM-readable context under `config/`.
- Resolve personal-context conflicts in this order: explicit current message,
  temporary rule, stable profile, durable memory, generic fallback.
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

Read [references/activity-analysis.md](references/activity-analysis.md), then
start with:

```bash
python3 -B scripts/fetch_latest_activity.py
python3 -B scripts/activity_inspect.py <saved-activity-ref> --brief
```

Verify that a named activity matches the user's request before interpreting it.
For every completed-activity analysis, also read
[references/physiological-response-synthesis.md](references/physiological-response-synthesis.md)
before combining heart rate or multiple physiological streams into a verdict.
When an activity contains SmO2, THb, Moxy, or another wearable-NIRS muscle
oxygen signal, also read
[references/muscle-oxygen.md](references/muscle-oxygen.md) before interpreting
the signal or allowing it to affect a verdict.
When an activity contains Tyme Wear, breathing rate, tidal volume, minute
ventilation, or another wearable respiratory signal, also read
[references/respiration.md](references/respiration.md) before interpreting the
signal or allowing it to affect a verdict.
When an activity contains CORE, `core_temperature`, `skin_temperature`,
`heat_strain_index`, or another wearable thermal signal, also read
[references/thermal-sensing.md](references/thermal-sensing.md) before
interpreting the signal or allowing it to affect a verdict.
For long rides, late-session quality, physiological decoupling, heat-strain
questions, CP/W-prime reasoning, or comparisons affected by fueling, also read
[references/cycling-endurance-physiology.md](references/cycling-endurance-physiology.md).
When the question depends on Xert MPA, point-of-failure, Difficulty dynamics,
or low/high/peak strain, use the Xert source skill. Prefer the offline
`xert_strain_cli.py` whenever the workout segments can be resolved. If the
Fitness Signature is the only missing input, first reuse a fresh, time-appropriate
signature already in the source context; otherwise fetch it through the Xert
skill's narrow `training-info` workflow, then calculate locally. Do not use live
Workout Designer Calculate merely to discover the current signature. Use
`xert_calculate_analyze.py` for an existing Calculate or activity series. Keep
Xert formulas in the source skill and consume normalized model output here
instead of reimplementing them.

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

Also read [references/outdoor-routes.md](references/outdoor-routes.md). Select
from actual saved activity geometry before inventing a generic route.

## Output

- Answer in chat unless the user explicitly requests a report file.
- Keep `outputs/` artifacts as working evidence; do not link JSON packets in a
  normal recommendation.
- If the final recommendation differs from the helper script's recommendation,
  briefly explain the deviation and its reason.
- Lead with one clear recommendation. Include timing, duration, warm-up,
  watts/intensity, route or setup, practical fueling, and the decisive reasons.
- Every training recommendation must also include a separate
  `Kapasitet før neste økt` section. Resolve the next day's planned workout role
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
  1. `Fysiologisk mulighetsrom`: the readiness ceiling—what intensity current
     physiology and recovery allow, independent of what the plan calls for.
  2. `Treningsmessig behov`: the intensity direction indicated by the resolved
     goal, progression history, and recent same-family stimulus/load.
  3. `Endelig anbefaling`: the selected intensity domain and concrete dose after
     combining the first two dimensions with logistics, weather, and body feel.
  Use these exact Norwegian labels, in this order, in every recommendation. Do
  not rename them, substitute synonyms, or introduce alternative labels for the
  same three concepts.
  Do not collapse the first two into justification for the third or report only
  the final recommendation. State clearly when physiology allows harder
  training than the plan selects. Explain why the resulting domain (for example
  rest, recovery, VT1, VT2, or VO2max) is preferable to the next harder and
  easier alternatives. Do not infer VT1 rather than VT2 from a predominantly
  low-XSS target split; both can generate predominantly low XSS.
- Include only modalities available at the resolved location. When indoor and
  outdoor cycling are both available, give concrete versions of both and state
  which wins.
- Separate mechanical execution/pacing from physiological cost when analysing
  a completed session.
- For a completed-session analysis, briefly name the primary and strong
  secondary adaptation systems stimulated by the actual dose, and explain why.
  Distinguish likely training signals from adaptations proven to have occurred.
- Label each training-load value with its source and metric; never treat values
  from different sources as interchangeable.
- State missing or stale inputs and how they reduce confidence before upgrading
  intensity.
- Ask how the session felt when useful, but not when feel/RPE is already known.

## Boundaries

This skill owns local persistence, helper workflows, readiness composition,
route/workout selection, and chat output. It does not own source-specific field
meaning or remote mutation rules.
