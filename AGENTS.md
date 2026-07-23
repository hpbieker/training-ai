# Project Instructions

- Apply user-specific preferences from `PREFERENCES.md` when they are relevant.
- For repo-internal helper scripts and automation-only interfaces, prefer
  clear current names over backwards-compatible aliases. It is acceptable to
  remove or rename internal flags when updating the calling automation/scripts,
  because these scripts are not public APIs.
- For home-based outdoor ride recommendations, route filtering/scoring, local
  weather context, default workout timing, modality availability, local gear
  mapping, and practical fueling defaults, resolve personal context from the
  user's explicit request, durable memory, or the repo-local user profile at
  `config/user-training-profile.md`. Keep those personal values out of code
  and project instructions.
- `config/user-training-profile.md` is LLM/agent-readable personal context,
  not a runtime config file for helper scripts. Do not make scripts import,
  parse, or otherwise read this profile directly. The LLM/agent should read it
  when relevant and pass the resulting choices to existing helpers through
  explicit CLI arguments or normalized source inputs.
- When discussing Garmin readiness inputs for future dates, do not say HRV,
  Training Readiness, Body Battery, sleep, or similar same-day signals are
  "missing". Say they are not available yet because the date has not happened.
  Use "missing" only when the relevant date/time has already happened and the
  expected synced data is absent or stale.
- When the user asks for a same-day or next-day training recommendation without
  giving a workout time, use the configured earliest preferred workout start
  from personal context. If calendar access/context is available, check
  availability and move the planned workout time later to the first practical
  free window; do not move it earlier than the configured default unless the
  user explicitly asks for an earlier session.
- Do not infer indoor training availability from the repository. Use explicit
  user input or personal context, and pass the resulting modalities to the
  recommendation helper.
- In daily training recommendations, show the training alternatives that are
  available at the resolved destination/location. Do not force both indoor and
  outdoor alternatives when personal context says one modality is unavailable.
- For training recommendations, justify the intensity domain using readiness,
  recent stimulus, progression goals, and source load targets.
- For workout analyses, activity comparisons, readiness or "can/should I train?"
  questions, outdoor ride recommendations, weather-informed training decisions,
  planned workout summaries, cross-source endurance analysis, or saved activity
  inspection, use the repo-local training-analysis skill at
  `skills/training-analysis/SKILL.md`.
- The training-analysis skill owns repo-level training analysis, local
  persistence, readiness composition, helper-script workflows, and chat output.
- Source plugin skills own source-specific API access, field interpretation,
  API quirks, and write-safety rules:
  - EatMyRide: `plugins/eatmyride/skills/eatmyride/SKILL.md`
  - Xert: `plugins/xert/skills/xert/SKILL.md`
  - Yr/MET Norway: `plugins/yr/skills/yr/SKILL.md`
  - Garmin Connect: `plugins/garmin-connect/skills/garmin-connect/SKILL.md`
  - Intervals.icu: `plugins/intervals-icu/skills/intervals-icu/SKILL.md`
- Fetch live source data through the relevant source plugin whenever current
  analysis, readiness, summaries, forecasts, or recommendations need that
  source's context.
- When source-aware data is needed by repo helpers, pass normalized output into
  the helper rather than making the helper call plugins directly or interpret raw
  source payloads.
