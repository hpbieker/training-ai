# TODO

- Simplify session renewal for Strava and Olympiatoppen. When a plugin returns
  `auth_required`, show the shortest supported recovery path. Reuse the
  signed-in browser session where possible, verify the imported session, and
  retry the original read. Handle write retries separately by checking the
  remote state first.
- Fix timestamp handling in plan-state processing. Prefer source timestamps
  with an explicit offset. When a source supplies only local time, resolve the
  source timezone before comparing in UTC. Add tests for midnight and
  daylight-saving transitions. Use the selected timezone for display and
  preserve the activity's local date in artifact folder names.
