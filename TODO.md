# TODO

- Add an Xert MCP `analyze_session` tool equivalent to
  `plugins/xert/scripts/xert_calculate_analyze.py`, then update
  [activity-analysis.md](skills/training-analysis/references/activity-analysis.md)
  to use the tool instead of the script directly.
- Normalize internal time handling:
  - Use timezone-aware UTC datetimes for calculations, comparisons and source matching.
  - Use the machine's local timezone for human-facing day buckets and local activity folder names.
  - In normalized/script output, prefer paired fields such as `start_utc` + `start_local`, `end_utc` + `end_local`, `latest_utc` + `latest_local`, and `source_mtime_utc` + `source_mtime_local`.
  - Avoid deriving comparable timestamps from naive local strings; parse provider timestamps into UTC first, then format local time only for display.
