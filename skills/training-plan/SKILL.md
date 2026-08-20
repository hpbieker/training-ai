---
name: training-plan
description: Use when creating, updating, reviewing, or applying medium-term training plans in training-ai, including goals, phases, weekly structure, progression, downgrade rules, tapering, and plan files.
---

# Training Plan

Use this skill for medium-term plan structure and plan-file maintenance. Use
`training-analysis` afterward for live readiness, logistics, and a concrete
same-day prescription.

Read `config/coaching-preferences.md` and `config/practical-context.md` when
their personal defaults or constraints affect the plan.

## Plan Files

Store plans under `config/plans/` unless the user requests another location.
Use a creation-date prefix such as `YYYY-MM-DD-goal-plan.md`. Keep athlete- and
goal-specific details in plan files, not this skill.

Each plan should state concisely:

- creation date, status, goal, and current phase;
- performance objective and time horizon;
- phase structure and weekly session roles;
- progression, downgrade, interruption, and taper rules;
- open questions or assumptions.

Plan files are LLM-readable context. Helper scripts must not parse them, and
volatile daily measurements must not become permanent plan rules.

## Create Or Update

1. Read the relevant existing plan and inspect actual training history when it
   affects the change.
2. Define the goal in performance terms and set phases, weekly rhythm,
   progression, downgrade, interruption, and taper rules.
3. Preserve useful history while editing with `apply_patch`.
4. Read the changed section back and verify internal consistency.

Do not rewrite a medium-term plan because of one daily recommendation unless
the user explicitly asks.

## Apply A Plan Today

Discover candidate plans under `config/plans/`, choose the active or most
relevant one from metadata and content, and state any assumption when multiple
plans compete.

Treat a new message thread as the normal case. Read `config/plan-state.json`
before deciding today's role, then run:

```bash
python3 -B scripts/plan_state.py pending
```

If it returns activities, inspect and classify every activity in chronological
order and apply each reviewed classification with `scripts/plan_state.py
apply --classification-json '<normalized-json>'`. The JSON object contains the
activity identity, timestamps, planned/completed roles, boolean
`quality_completed`, progression effect, reason, evidence array, and optional
`progression_update`. Do not skip an older pending activity to apply a newer one. The state
owns the current queue; chat history and automation memory are explanatory
context only.

Decide today's plan role from the updated state. If the explicit
`intensity_goal` differs from the state's `next_role`, give
`recommend_training.py` a concrete `role_mismatch_reason` inside `--plan-selection-json`. This is for a
deliberate plan-level placement decision such as an additional aerobic day, not
for readiness: readiness may downgrade the selected session without changing
the quality queue.

Then use `training-analysis` to adjust dose, modality, timing, weather,
route/workout, and fueling from current evidence. Explain the answer as plan
role first and readiness/logistics second.
