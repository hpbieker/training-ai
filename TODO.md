# TODO

- Simplify session renewal for Strava and Olympiatoppen. When a plugin returns
  `auth_required`, show the shortest supported recovery path. Reuse the
  signed-in browser session where possible, verify the imported session, and
  retry the original read. Handle write retries separately by checking the
  remote state first.
