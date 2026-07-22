# Xert Write Safety

Perform writes only when the user explicitly asks. Validate non-persistently
where possible, require the persistence flag, and read the object back after a
successful write.

## Calendar Notes

```bash
python3 -B plugins/xert/scripts/xert_cli.py calendar-note-set <YYYY-MM-DD> "<note>" --yes
python3 -B plugins/xert/scripts/xert_cli.py calendar-notes
```

Calendar notes are separate from forecast and training-plan fields.

## Workout Updates

Inspect editable rows first:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-rows <path>
```

Test an edit with `--dry-run`, which uses Workout Designer calculation without
saving. Persist only with `--yes`, then verify with both `workout-rows <path>`
and `workouts --summary` as relevant.

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-update <path> --match-name "<row>" --set-duration <MM:SS> --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-update <path> --match-name "<row>" --set-duration <MM:SS> --yes
```

Prefer updating repeat-row fields over expanding repeated blocks into copied
rows. Use the CLI's explicit row options for names, interval count, recovery
duration, recovery power, and power type.

`workout-copy` creates a new workout and therefore also requires explicit
`--yes`. Inspect the source rows first and verify the new workout through
`workouts --summary` and `workout-rows <new-path>`.

## Synthetic Calculation

Use `workout-calculate` for controlled, unsaved XSS probes:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-calculate --duration 10:00 --power-type relative_ftp --power 120
```

Do not save synthetic workouts unless the user explicitly requests it.

## Deletion

Workout deletion is destructive and requires explicit confirmation:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-delete <path> --yes
python3 -B plugins/xert/scripts/xert_cli.py workouts --summary
```

The implementation uses authenticated `DELETE /workout/<path>`. Do not test it
against a real workout merely to characterize the endpoint.
