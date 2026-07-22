---
name: training-plan
description: Use when creating, updating, reviewing, or applying medium-term training plans in the training-ai repo, including goals, phases, weekly structure, progression rules, taper planning, and repo-local LLM-readable plan files. Use this before daily workout recommendations when the user asks what the plan says or wants decisions grounded in long-term goals rather than only same-day readiness.
---

# Training Plan

Use this skill for medium-term plan work. It owns plan structure and plan-file
maintenance, not live readiness analysis.

## Boundaries

- Use this skill for goals, phases, weekly rhythm, session roles, progression
  rules, downgrade rules, and taper logic.
- Use `skills/training-analysis/SKILL.md` afterward for live source data,
  latest activity inspection, weather, calendar, route/workout selection, and
  concrete same-day prescriptions.
- Plan files are LLM/agent-readable context only. Helper scripts must not read
  them directly.

## Plan Files

Store repo-local plan context under `config/plans/` unless the user requests
another location. Name plan files with the creation date first, for example
`YYYY-MM-DD-tryvann-climb-plan.md`. Keep plan files concise and goal-specific.
Do not put plan-specific details in this skill.

When applying an existing plan, discover candidate files with
`config/plans/*plan*.md`, then choose the active or most relevant plan from the
user's request, file metadata, and plan content. If multiple plans appear
relevant, state the plan assumption before using it.

Plan files should include a short metadata section near the top with creation
date, status, goal, current phase when known, and open questions. Keep this
metadata LLM-readable only; helper scripts must not parse it.

## Workflow

For plan creation or update:

1. Read the relevant existing plan file if it exists.
2. Inspect actual workout history when the plan depends on it.
3. Define the goal in performance terms.
4. Set phase structure, weekly rhythm, progression, and downgrade rules.
5. Update the plan file with `apply_patch`.
6. Verify the changed section by reading it back.

For daily recommendation questions that reference a plan:

1. Read the relevant plan file first.
2. Decide the day's plan role before checking same-day readiness.
3. Use `training-analysis` to adjust dose and logistics.
4. Explain the result as plan role first, readiness/logistics second.

## Style

- Keep the skill generic; keep athlete-specific goals and history in plan files.
- Preserve useful plan history when updating.
- Avoid raw data dumps in plan files.
- Do not encode volatile Garmin/Xert values as permanent plan rules.
- Do not let a same-day recommendation rewrite the plan unless the user asks.
