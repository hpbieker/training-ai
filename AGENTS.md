# Project Instructions

- For repo-internal helper scripts and automation-only interfaces, prefer
  clear current names over backwards-compatible aliases. It is acceptable to
  remove or rename internal flags when updating the calling automation/scripts,
  because these scripts are not public APIs.
- Do not hardcode user-specific recommendation preferences in code, skills, or
  other shared project instructions. Store them in `PREFERENCES.md` or the
  appropriate personal context file instead.
