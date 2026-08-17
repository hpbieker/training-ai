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

## Planner Events

Planner events are separate from calendar notes. Read a date or one event with:

```bash
python3 -B plugins/xert/scripts/xert_cli.py calendar-events 2026-08-01
python3 -B plugins/xert/scripts/xert_cli.py calendar-event <path> --date 2026-08-01
```

Create and update accept JSON on the command line. Without `--yes`, create and
update only print their dry-run inputs. Persisted writes are read back. Delete
requires `--yes` and verifies that the event is absent afterward. Event JSON
uses Xert's source fields; in particular, `duration` is seconds.

```bash
python3 -B plugins/xert/scripts/xert_cli.py calendar-event-create --event-json '<json>' --yes
python3 -B plugins/xert/scripts/xert_cli.py calendar-event-update <path> --date 2026-08-01 --patch-json '<json>' --yes
python3 -B plugins/xert/scripts/xert_cli.py calendar-event-delete <path> --date 2026-08-01 --yes
```

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

Use `workout-update` only for a bounded metadata change or an in-place change
to matching existing rows. Saved updates read all rows back and fail if Xert's
saved structure differs from the submitted structure. Row changes require a
name or power selector and expect exactly one match by default; pass
`--expect-matches <count>` only when multiple matches are intentional.

For a single row, prefer the explicit one-based row operations:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-row-add <path> 3 \
  --name "VT1" --duration 15:00 --power 205 --interval-count 4 --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-row-update <path> 3 \
  --name "VT1" --duration 15:00 --power 205 --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-row-remove <path> 3 --dry-run
```

Repeat the identical command with `--yes` only after inspecting the dry-run.
`workout-row-update` has patch semantics: omitted fields remain unchanged.
Add and update use the same field options, without JSON: `--name`, `--duration`,
`--power`, `--power-type`, `--power-second-value`, `--interval-count`,
`--rib-duration`, `--rib-power`, and `--rib-power-type`. Add requires duration
and power and supplies defaults for omitted optional fields. Add accepts
positions 1 through row-count plus one; update and remove require an existing
row. Remove refuses to delete the workout's only row. Saved operations renumber
all rows and verify a fresh readback against the complete submitted structure.

When the workout changes shape, replace the complete row array atomically:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-rows <path> > /tmp/current-rows.json
python3 -B plugins/xert/scripts/xert_cli.py workout-replace <path> \
  --rows-json /tmp/replacement-rows.json --dry-run
python3 -B plugins/xert/scripts/xert_cli.py workout-replace <path> \
  --rows-json /tmp/replacement-rows.json --yes
```

`workout-replace` renumbers rows, clears transport row IDs, submits every row
in one request, and compares the saved rows with the requested rows.

For a small number of compact or complete Designer rows, repeated inline
`--row-json` arguments may be used instead of creating a temporary rows file.
Complete inline rows preserve advanced power types such as ramps. Use the file
form for large or already-materialized complete Designer payloads.

When the new structure makes the existing workout name or description stale,
pass the corrected `--name` and `--description` in the same dry-run and saved
`workout-replace` calls. Verify all three surfaces on readback: rows, name, and
description. Do not leave metadata describing the replaced structure.

`rib_duration` and `rib_power` represent Xert's `Rest in between`. Xert appends
that recovery after every repeated work interval, including the final
repetition. Thus `interval_count=4` with `rib_duration=05:00` already includes
four five-minute recoveries, and the next workout row starts after the fourth
recovery. Do not add a separate following recovery row unless an additional
recovery beyond that final RIB is explicitly intended. Confirm this behavior
against Xert's calculated total duration as well as the saved row readback.

`workout-copy` creates a new workout and therefore also requires explicit
confirmation. Inspect the source rows first, run `workout-copy ... --dry-run`,
then use the same command with `--yes`. The copy is read back and its rows must
match the calculated structure.

## Synthetic Calculation

Use `workout-calculate` for controlled, unsaved XSS probes:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-calculate --duration 10:00 --power-type relative_ftp --power 120
```

When the second-by-second response is needed for empirical analysis, write it
to an explicit temporary file rather than printing it:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-calculate \
  --duration 10:00 --power-type relative_ftp --power 120 \
  --series-output /tmp/xert-120pct-series.json --summary
```

The series file includes Xert's calculation signature and per-second fields
such as power, MPA, proximity, XSS rate, cumulative XSS, and difficulty. It is
still an unsaved calculation. It also includes raw calculation statistics for
system work and strain analysis.

For a complete workout, repeat `--row-json` in execution order. A row can be
one segment or a repeated work/recovery block:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-calculate \
  --name "4 x 4 calculation" \
  --row-json '{"name":"Warm-up","duration":"15:00","power":180}' \
  --row-json '{"name":"4 x 4","duration":"04:00","power":340,"interval_count":4,"rib_duration":"03:00","rib_power":120}' \
  --row-json '{"name":"Cool-down","duration":"10:00","power":140}' \
  --summary
```

For normal absolute-power workouts, prefer the compact notation so warm-up,
work/recovery, and cool-down are all explicit without JSON row construction:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-calculate \
  --name "4 x 4 calculation" \
  --warmup-step 10:00@170 \
  --warmup-step 05:00@220 \
  --interval-block 4x04:00@340/03:00@120 \
  --cooldown-step 10:00@140 \
  --summary
```

`--summary` prints only compact calculated metrics to stdout: duration,
total/low/high/peak XSS, difficulty, rating, focus, specificity, XEP, and
average/max power.

Do not save synthetic workouts unless the user explicitly requests it.

## Deletion

Workout deletion is destructive and requires explicit confirmation:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workout-delete <path> --yes
python3 -B plugins/xert/scripts/xert_cli.py workouts --summary
```

The implementation uses authenticated `DELETE /workout/<path>`. Do not test it
against a real workout merely to characterize the endpoint. The command reads
the target metadata before deletion and verifies afterward that the path is no
longer present in the workout library.
