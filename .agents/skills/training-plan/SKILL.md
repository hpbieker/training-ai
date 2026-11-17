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
- demand analysis and evidence for the athlete's current limitations;
- phase structure and weekly session roles;
- rationale for total weekly volume, quality frequency, distribution and spacing;
- progression, downgrade, interruption, and taper rules;
- dated block review, performance measures and criteria for changing the plan;
- open questions or assumptions.

Plan files are LLM-readable context. Helper scripts must not parse them, and
volatile daily measurements must not become permanent plan rules.

## Create Or Update

When creating a plan or changing its training content, read
[Planning method and evidence](references/planning-method.md). A wording-only
edit does not require a new physiological assessment.

1. Establish event/performance demands, time horizon, training background,
   sustainable available time and documented strengths/limitations. Distinguish
   measured findings, coaching hypotheses and missing evidence. Link each
   priority session type to the capability it is intended to develop.
2. Design phases and the week together: justify total hours, quality-session
   frequency, intensity distribution, long rides and recovery spacing against
   recent tolerated training and upcoming demands. Include other training and
   competitions. Several individually justified sessions do not establish that
   their combined week is appropriate.
3. Specify each progression variable and the execution/response evidence needed
   to increase it, repeat it or reduce it. Explain recovery weeks, interruption
   handling and event taper; do not prescribe universal percentage increases,
   fixed deload cycles or an intensity split solely because it is familiar.
4. Set a dated block review with a relevant performance baseline, comparable
   reassessment method and explicit continue/change criteria. Separate adherence
   and workload from demonstrated performance improvement.
5. Preserve useful history while editing with `apply_patch`. Verify that the
   weekly totals, session placement, progression and review criteria agree.
   For a scoped update, revise affected decisions rather than rebuilding the
   entire plan. Record material unknowns and their effect on the prescription.

Do not rewrite a medium-term plan because of one daily recommendation unless
the user explicitly asks.

Choose session dose from its purpose, achieved progression, recent response and
the surrounding training. Xert advice and next-workout capacity are comparison
data, not automatic volume targets or dose limits. Do not add endurance to fill
an XSS gap. Justify any addition separately. Use training-analysis's explicit
dose-selection and capacity-conflict workflow for the same-day prescription.

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
Copy `started_at` and, when present, `start_date_local` from `pending` into the
classification. Plan state compares `started_at` in UTC and uses
`start_date_local` for the activity's calendar day. The JSON object also contains the activity identity,
planned/completed roles, booleans `quality_stimulus` and `quality_role_fulfilled`,
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

Spacing days include reviewed aerobic rides, `recovery` rides, and explicitly
confirmed full-day `rest`. Missing activities never establish rest. For a rest
day, first review pending activities and confirm that the whole local day has
ended and contained no training. Apply a classification with a stable identity
such as `rest:YYYY-MM-DD`, an offset-aware timestamp on that day, local date,
`planned_role`/`completed_role: rest`, both quality booleans false,
`planned_workout_completed: null`, `progression_effect: none`, and a reason and
evidence reference identifying the athlete's confirmation. Apply it in
chronological order with activities; never fabricate a source activity ID or
infer rest from an empty source response. Correct conflicting records explicitly.
The v3 `aerobic_days_since_quality` counter includes these spacing days. A day
counts once, never on the same local date as quality work. Satisfying spacing
only opens the queued role for consideration; current readiness is assessed
separately and may still require easy training or rest.

Plan state v3 requires explicit role fulfillment and workout completion.
Whole-prescription completion remains unknown where the historical record only
establishes quality completion. Replay affected classifications from a verified
checkpoint to correct queue placement.

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
