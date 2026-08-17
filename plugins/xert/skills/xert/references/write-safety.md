# Xert Write Safety

Perform writes only when the user explicitly asks. Validate non-persistently
where possible, require the persistence flag, and read the object back after a
successful write.

## Calendar Notes

Use MCP `set_note` only after explicit confirmation. Read the date back with
MCP `get_note`; use `list_notes` when range context is relevant.

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

Inspect editable rows first with MCP `get_workout(view=editable)`. For a saved
change, construct the complete final row array and submit it to MCP
`update_workout`; omitted metadata remains unchanged and the tool verifies the
saved rows. Use the unsaved `workout-calculate` CLI only when an empirical
Calculate result is actually required before the write.

Prefer updating repeat-row fields over expanding repeated blocks into copied
rows. MCP has no separate row-edit operation: preserve every unmodified row,
change only the intended row locally, and submit all rows in execution order.

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

To copy a workout, inspect the source with MCP `get_workout(view=editable)`,
then call MCP `create_workout` with the new name and complete copied rows. The
created workout is read back and verified.

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

Workout deletion is destructive and requires explicit confirmation. Use MCP
`delete_workout`; it reads the target metadata before deletion and verifies
afterward that the path is absent. Do not test it against a real workout merely
to characterize the endpoint.
