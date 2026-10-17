# TODO

- Add managed authentication and session renewal for plugins that currently require a browser session cookie to be captured and imported manually. Both plugins require a fresh cookie after the session expires and cannot renew the session themselves:
  - `strava`: capture a logged-in request as cURL in Safari Web Inspector; the local CLI extracts, verifies, and stores its Cookie header.
  - `olympiatoppen`: capture the Cookie header from a browser request to `/api/Auth/Session` through CDP; the MCP verifies and stores it.

- Normalize internal time handling:
  - Use timezone-aware UTC datetimes for calculations, comparisons and source matching.
  - Use the machine's local timezone for human-facing day buckets and local activity folder names.
  - In normalized/script output, prefer paired fields such as `start_utc` + `start_local`, `end_utc` + `end_local`, `latest_utc` + `latest_local`, and `source_mtime_utc` + `source_mtime_local`.
  - Avoid deriving comparable timestamps from naive local strings; parse provider timestamps into UTC first, then format local time only for display.
