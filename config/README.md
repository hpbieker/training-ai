# Config

This directory contains both helper/runtime config and LLM/agent-readable
personal context. Keep those roles separate.

## LLM/Agent Context

These files are read by the LLM/agent and translated into explicit CLI
arguments, normalized source inputs, or chat reasoning. Helper scripts must not
import, parse, or read these files directly.

- `user-training-profile.md`: personal training context for planning defaults,
  locations, modality availability, equipment, route context, and fueling.
- `cycling-clothing.md`: wardrobe context for outdoor clothing
  recommendations.
- `plans/YYYY-MM-DD-*-plan.md`: medium-term training plans, goals, phases,
  weekly structure, progression rules, taper logic, and plan-specific open
  questions. These files should be date-stamped by creation date and selected by
  the LLM/agent before live readiness checks when a recommendation should be
  grounded in a plan.

## Helper/Runtime Config

These files may be read by repo helper scripts.

- `route-data-quality.json`: route/activity data-quality registry.
- `sensor-data-quality.json`: sensor data-quality registry.

## Rule

If a personal-context value is needed for a helper, the LLM/agent passes it
through an existing explicit CLI argument or normalized input. Do not make
helper scripts read `user-training-profile.md` or `cycling-clothing.md`.

Temporary personal context must include a start date, end date, affected
context, and a short reason. Remove or revise temporary rules when the end date
has passed, instead of treating them as stable profile facts.
