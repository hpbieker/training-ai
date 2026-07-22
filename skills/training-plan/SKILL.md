---
name: training-plan
description: Use when creating, updating, reviewing, or applying medium-term training plans in training-ai, including goals, phases, weekly structure, progression, downgrade rules, tapering, and plan files.
---

# Training Plan

Use this skill for medium-term plan structure and plan-file maintenance. Use
`training-analysis` afterward for live readiness, logistics, and a concrete
same-day prescription.

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

Decide today's plan role first. Then use `training-analysis` to adjust dose,
modality, timing, weather, route/workout, and fueling from current evidence.
Explain the answer as plan role first and readiness/logistics second.
