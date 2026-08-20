# Project Instructions

- Apply user-specific preferences from `PREFERENCES.md` when they are relevant.
- For repo-internal helper scripts and automation-only interfaces, prefer
  clear current names over backwards-compatible aliases. It is acceptable to
  remove or rename internal flags when updating the calling automation/scripts,
  because these scripts are not public APIs.
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
