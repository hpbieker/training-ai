# TODO

- Normalize internal time handling:
  - Use timezone-aware UTC datetimes for calculations, comparisons and source matching.
  - Keep local `Europe/Oslo` dates for human-facing day buckets and cache filenames such as Garmin day files and activity folders.
  - In normalized/script output, prefer paired fields such as `start_utc` + `start_local`, `end_utc` + `end_local`, `latest_utc` + `latest_local`, and `source_mtime_utc` + `source_mtime_local`.
  - Avoid deriving comparable timestamps from naive local strings; parse provider timestamps into UTC first, then format local time only for display.
- Remove the old Xert Appspot proxy dependency. `recovery-model` now uses direct Xert web login/model inputs by default for recovery days and workout capacity; keep `legacy-training-advice` only for temporary validation/comparison until this cleanup is done.
- Remove `legacy-training-advice` and the Appspot proxy code completely once replacement fields are available through direct Xert endpoints. This includes deleting `XERT_LEGACY_ADVICE_URL`, `cache_legacy_training_advice`, `fetch_legacy_training_advice`, legacy cache fallback reads, and README/AGENTS references to the legacy path.
