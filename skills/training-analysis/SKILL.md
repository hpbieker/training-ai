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

### Readiness or daily recommendation

Read [references/daily-recommendations.md](references/daily-recommendations.md).
Use the narrow readiness helper for a focused question and the recommendation
helper for a complete session decision:

```bash
python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD>
python3 -B scripts/recommend_today.py --date <YYYY-MM-DD> <resolved-context-args> --summary
```

Treat helper output as structured evidence, not the final recommendation.

### Outdoor route recommendation

Also read [references/outdoor-routes.md](references/outdoor-routes.md). Select
from actual saved activity geometry before inventing a generic route.

## Output

- Answer in chat unless the user explicitly requests a report file.
- Keep `outputs/` artifacts as working evidence; do not link JSON packets in a
  normal recommendation.
- Lead with one clear recommendation. Include timing, duration, warm-up,
  watts/intensity, route or setup, practical fueling, and the decisive reasons.
- Include only modalities available at the resolved location. When indoor and
  outdoor cycling are both available, give concrete versions of both and state
  which wins.
- Separate mechanical execution/pacing from physiological cost when analysing
  a completed session.
- Label each training-load value with its source and metric; never treat values
  from different sources as interchangeable.
- State missing or stale inputs and how they reduce confidence before upgrading
  intensity.
- Ask how the session felt when useful, but not when feel/RPE is already known.

## Boundaries

This skill owns local persistence, helper workflows, readiness composition,
route/workout selection, and chat output. It does not own source-specific field
meaning or remote mutation rules.
