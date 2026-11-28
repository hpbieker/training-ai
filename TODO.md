# TODO

- Support sign-in for Strava, Olympiatoppen, and Komoot, either directly
  through the plugin or through a standardized sign-in flow.
  The plugins currently handle sign-in differently, which can be confusing.
- Use `streams.xds` to draw the Strava workout card's difficulty curve
  once Xert exposes it in `GET /oauth/v2/activity/{path}?include_session_data=1`.
- Ask Xert to add an `at` timestamp to `GET /oauth/v2/training/suggestions`.
  The recovery endpoint already accepts `at`, and `GET /oauth/v2/workouts`
  accepts a date and time in `date`. Return the recommended XSS dose and
  ranked workouts for the requested start time, taking into account training
  completed or scheduled before then.
