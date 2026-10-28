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

Treat a new message thread as the normal case. Before deciding today's role,
print the compact, validated progression context and check for unprocessed
activities:

```bash
python3 -B scripts/plan_state.py context
python3 -B scripts/plan_state.py pending
```

Use `context` as the only `plan-state.json` content brought into the LLM
context. Do not `cat` the raw file or use `plan_state.py show` during a daily
recommendation; `show` is for an explicit full-state audit. `context` includes
the active plan, processing cursor, current queue/spacing, and per-role
progression, while omitting the historical `activity_events` log.

If `pending` returns activities, inspect and classify every activity in
chronological order and apply each reviewed classification with
`scripts/plan_state.py apply --classification-json '<normalized-json>'`. The
command writes the complete updated state but prints only its compact context.
The JSON object contains the activity identity, timestamps, planned/completed
roles, booleans `quality_stimulus` and `quality_role_fulfilled`,
`planned_workout_completed` (boolean, or null when unknown), progression effect,
reason, evidence array, and optional `progression_update`. Do not skip an older pending activity to
apply a newer one. The state owns the current queue; chat history and
automation memory are explanatory context only. Re-run `context` after
applying pending activities before choosing today's plan role.

Queue advancement follows fulfilled quality roles, not perfect completion of
the prescription or progression. A shortened but substantial quality session
can fulfill its role while holding progression. A brief insufficient attempt
can warrant recovery spacing without fulfilling the role. Require an explicit
evidence-based classification rather than a fixed completion percentage.
Use the correction/replay workflow in training-analysis's activity-analysis
reference when an already-applied classification needs to change.

Plan state v3 requires explicit role fulfillment and workout completion. To
upgrade a v2 state, use `scripts/migrate_plan_state_v3.py` with a reviewed
`--quality-reviews-file` covering every incomplete quality event. Preview first;
`--write` persists the schema migration. Whole-prescription completion remains
unknown where the historical record only establishes quality completion. The
migration preserves the curated queue; replay affected classifications from a
verified checkpoint to correct queue placement.

When updating progression, distinguish the established achieved dose from the
latest execution and any temporary consolidation prescription. A reduced or
incomplete session does not erase a previously completed dose. Record the reason
for a temporary reduction and the recovery review needed in `last_result` and
`next_step`; lower the established anchor only
when the evidence supports a lasting change. A hold on progression can mean
repeating the achieved dose, rather than repeating the latest reduced session.

Decide today's plan role from the updated state. If the explicit
`intensity_goal` differs from the state's `next_role`, give
`recommend_training.py` a concrete `role_mismatch_reason` inside `--plan-selection-json`. This is for a
deliberate plan-level placement decision such as an additional aerobic day, not
for readiness: readiness may downgrade the selected session without changing
the quality queue.

Then use `training-analysis` to adjust dose, modality, timing, weather,
route/workout, and fueling from current evidence. Explain the answer as plan
role first and readiness/logistics second.
