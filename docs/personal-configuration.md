# Personal configuration

Create `config/` at the repository root and add the files for the workflows you
use. Git ignores the entire directory. Keep a private backup if you want to
reuse your setup across machines.

| Local path | What to put there |
| --- | --- |
| `config/practical-context.md` | Locations, available training modalities, equipment, sensors and route context |
| `config/coaching-preferences.md` | Training, calendar, fueling and presentation preferences |
| `config/cycling-clothing.md` | Cycling wardrobe and notes from rides |
| `config/plans/` | Date-stamped medium-term plans created with the [training-plan skill](../.agents/skills/training-plan/SKILL.md) |
| `config/plan-state.json` | Current plan progression and next role |
| `config/route-data-quality.json`, `config/sensor-data-quality.json` | Local data-quality registries |

Codex reads the Markdown and passes the relevant context to helpers as explicit
arguments or structured data. Date temporary preferences so they can be retired
when they expire.

## Initialise plan state

Create your plan first. Ask Codex to initialise `config/plan-state.json` from
that plan and your chosen starting point. Use the example below as a starting
structure. Replace the plan ID and path, both timestamps, and the example roles
and spacing with your own values. Set the activity cursor to the cutoff before
which saved activities should be skipped.

```json
{
  "schema": "training-ai-plan-state-v3",
  "updated_at": "2026-01-15T08:00:00Z",
  "active_plan": {
    "id": "example-plan",
    "path": "config/plans/2026-01-15-example-plan.md"
  },
  "activity_cursor": {
    "started_at": "2026-01-15T08:00:00Z"
  },
  "next_role": "easy_aerobic",
  "quality_queue": {
    "steps": [
      {"id": "threshold", "intensity_goal": "vt2"},
      {"id": "vo2", "intensity_goal": "vo2max"}
    ],
    "next_quality_step": "threshold",
    "minimum_aerobic_days_after_quality": 1,
    "aerobic_dates_since_quality": [],
    "aerobic_days_since_quality": 0
  },
  "progression": {},
  "activity_events": []
}
```

With zero aerobic days recorded, the example starts with `easy_aerobic`. If
your plan can start with a quality session immediately, set the initial minimum
to zero and make `next_role` match the goal of `next_quality_step`. Ask Codex
to validate the result with `scripts/plan_state.py context` and check the first
pending activities before using it for recommendations.
