# TODO
- Consider keeping the cycling clothing wardrobe and temperature guidance in
  the repo instead of only as assistant memory. Include known Castelli product
  names, manufacturer temperature ranges, and practical personal notes so kit
  recommendations are consistent and auditable.
- Normalize internal time handling:
  - Use timezone-aware UTC datetimes for calculations, comparisons and source matching.
  - Use the machine's local timezone for human-facing day buckets and local activity folder names.
  - In normalized/script output, prefer paired fields such as `start_utc` + `start_local`, `end_utc` + `end_local`, `latest_utc` + `latest_local`, and `source_mtime_utc` + `source_mtime_local`.
  - Avoid deriving comparable timestamps from naive local strings; parse provider timestamps into UTC first, then format local time only for display.
