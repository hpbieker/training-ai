# Xert Write Safety

Perform writes only when the user explicitly asks. Validate non-persistently
where possible, require the persistence flag, and read the object back after a
successful write.

## Calendar Notes

Use MCP `set_note` only after explicit confirmation. Read the date back with
MCP `get_note`; use `list_notes` when range context is relevant.

Calendar notes are separate from forecast and training-plan fields.

## Planner Events

Planner events are separate from calendar notes. Read them with MCP
`list_planner_events`. Create and update accept source-native event objects;
`duration` is seconds. Persisted creates and updates are read back. MCP
`delete_planner_event` reads the target first and verifies that it is absent
afterward. Use create, update, or delete only when the user explicitly requests
that write.

## Workout Updates

Inspect editable workout rows first with MCP `get_workout(view=editable)`.
Submit an ordered `rows` array of `update`, `insert`, and `remove` operations to
MCP `update_workout`; never submit a complete replacement array. Omitted
metadata and row fields remain unchanged, and the tool verifies the saved
structure. Use MCP `calculate_workout` only when an empirical Calculate result
is actually required before the write.

Prefer updating repeat-row fields over expanding repeated blocks into copied
rows. Keep row fields directly in each operation; do not nest them under
`set` or `row`.

When the new structure makes the existing workout name or description stale,
pass the corrected `name` and `description` together with the row operations in
the same MCP `update_workout` call. Verify all three surfaces on readback: rows,
name, and description. Do not leave metadata describing the changed structure.

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

Use MCP `calculate_workout` with complete workout rows for controlled, unsaved
XSS probes.

When the second-by-second response is needed, set `include_series=true` and
keep the verbose series out of chat output.

The series file includes Xert's calculation signature and per-second fields
such as power, MPA, proximity, XSS rate, cumulative XSS, and difficulty. It is
still an unsaved calculation. It also includes raw calculation statistics for
system work and strain analysis.

Pass complete rows in execution order. A row can represent one segment or a
repeated work/recovery block.

Do not save synthetic workouts unless the user explicitly requests it.

## Deletion

Workout deletion is destructive and requires explicit confirmation. Use MCP
`delete_workout`; it reads the target metadata before deletion and verifies
afterward that the path is absent. Do not test it against a real workout merely
to characterize the endpoint.
