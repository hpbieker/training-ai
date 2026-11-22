# Xert Write Safety

Call a write tool only for the change the user authorized. Inspect its
readback. For an uncertain outcome, resolve the current state before retrying.

## Calendar Notes

Use `get_note` before appending to an existing note. `set_note` replaces the
whole text for the date and returns the verified text. An empty string clears it.

Calendar notes are separate from forecast and training-plan fields.

## Planner Events

Planner events are separate from calendar notes. Read them with MCP
`list_planner_events`. Use `create_planner_event(event=...)` for a new event
and omit `options.edit_id`. To change an existing event, pass its current
local `date`, `event_path` and `patch` to `update_planner_event`.
`duration` is in seconds. Persisted creates and updates are read back. MCP
`delete_planner_event` reads the target first and verifies that it is absent
afterward. Use create, update, or delete only when the user explicitly requests
that write.

## Workout Updates

Inspect editable rows with `get_workout(workout_path=..., view="editable")`.
Submit an ordered `rows` array of `update`, `insert`, and `remove` operations to
MCP `update_workout`; never submit a complete replacement array. Omitted
metadata and row fields remain unchanged, and the tool verifies the saved
structure. Use MCP `calculate_workout` only when an empirical Calculate result
is actually required before the write.

Row positions refer to the structure just read. If a response is lost after an
insert or removal, read the editable rows again and derive any remaining edits
from their current positions.

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

The MCP response includes Xert's calculation signature and per-second fields
such as power, MPA, proximity, XSS rate, cumulative XSS, and difficulty. It is
still an unsaved calculation. It also includes raw calculation statistics for
system work and strain analysis.

Pass complete rows in execution order. A row can represent one segment or a
repeated work/recovery block.

Do not save synthetic workouts unless the user explicitly requests it.

## Deletion

Workout deletion is destructive and requires explicit confirmation. Use MCP
`delete_workout`; it reads the target metadata and requires the path to exist
in the personal API library before deletion, then verifies afterward that the
path is absent. API errors must not count as an empty library. Do not test it against a real workout merely
to characterize the endpoint.
