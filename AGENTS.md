# Project Instructions

- Apply user-specific preferences from `PREFERENCES.md` when they are relevant.
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
