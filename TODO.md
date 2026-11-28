# TODO

- Simplify session renewal for Strava and Olympiatoppen. When a plugin returns
  `auth_required`, show the shortest supported recovery path. Reuse the
  signed-in browser session where possible, verify the imported session, and
  retry the original read. Handle write retries separately by checking the
  remote state first.
- Use `streams.xds` to draw the Strava workout card's difficulty curve
  once Xert exposes it in `GET /oauth/v2/activity/{path}?include_session_data=1`.
  Check that the series aligns with `streams.time` at the requested resolution.
- Ask Xert to add an `at` timestamp to `GET /oauth/v2/training/suggestions`.
  The recovery endpoint already accepts `at`, and `GET /oauth/v2/workouts`
  accepts a date and time in `date`. Return the recommended XSS dose and
  ranked workouts for the requested start time, taking into account training
  completed or scheduled before then.
