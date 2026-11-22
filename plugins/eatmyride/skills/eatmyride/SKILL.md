---
name: eatmyride
description: Read EatMyRide activities, recorded fueling and modeled glycogen, compare food plans across rides, and edit food-plan entries or custom products.
---

# EatMyRide

Use the EatMyRide MCP tools for activity and product lookup, fueling analysis,
and authorized changes to food plans and custom products.

## MCP Tools

- `list_activities` lists candidates in an inclusive local-date range. Select
  the newest row by `date` when the user asks for the latest activity. It
  returns compact identity rows; use `includeFields` for selected source fields.
- `get_fueling` returns compact activity energy and glycogen state together
  with aggregated food-plan products, calculated intake totals, hourly rates,
  and an explicit reminder that recorded planning data is not confirmed intake.
- Use `get_foodplan_summaries` for recorded volume, carbohydrates and event
  counts across activities. Supply EatMyRide `activity_ids` or both inclusive
  local dates. Use `filter="has_fluids"` for positive recorded volume,
  `"has_events"` for non-empty plans, or `"all"` to include empty plans.
  Date-range rows include `start_local`. Check `failed_count` and `errors`
  before aggregating. For a cross-source analysis, select activities and use
  their durations in the caller.
- `get_foodplan` returns exact item-level events. Use it only when event timing
  matters, when preparing a change, or when verifying a write; normal activity
  analysis should stop at `get_fueling`.
- `search_products` searches the broader EatMyRide product catalogue. Product
  lists are compact by default; use `includeFields` for selected nutrition and
  serving fields.
- `list_products` uses `source: custom` for the user's products or
  `source: suggested` with `activity_id` and `kind` for activity-specific food
  or drink candidates, with the same compact rows and `includeFields` choices.
- `get_product` resolves one exact product before a food-plan or product write.
- `set_foodplan_products` sets exact quantities and elapsed times for selected
  products while preserving unrelated food-plan events.
- `create_product`, `update_product`, and `delete_product` operate only on
  custom products. `update_product` changes only explicitly supplied fields.

List and search responses use `count` for the number of returned rows and
`total_count` for all matching rows before `limit` is applied.

Live MCP reads and writes require external network access.

## Interpretation

Read [references/field-semantics.md](references/field-semantics.md) before
interpreting food-plan quantities, carbohydrate totals, glycogen,
`caloriesThreshold`, `carbohydratesFromFood`, or activity warnings.

- Activity-list rows identify candidates but do not include evaluated fueling
  or complete glycogen state; use `get_fueling` after selecting an activity.
- Distinguish recorded food-plan events from confirmed real-world intake. A
  food plan can be prepared before an activity or edited afterward.
- When reporting glycogen state, include both its minimum and final value when
  available.
- For the most recent recorded plan before a reference date, use
  `get_foodplan_summaries` with a date range and `filter="has_events"`.
  Choose the latest `start_local` and fetch that plan if item details matter.
  If a read failed, its activity might have a more recent plan.

## Writes

Read [references/write-safety.md](references/write-safety.md) before changing a
food plan or custom product. All remote writes require explicit user intent.
Preview first with `confirm: false`; use `confirm: true` only after reviewing
the exact target and proposed change. Confirmed tools verify remote state before
reporting success.

For `partial_write` or `write_failed`, use the food-plan readback guidance in
the write reference before repeating a save.

For `set_foodplan_products`:

- Use `pieces` for counted products and `gram` for weighed products.
- Pass `ml` together with `gram` for a prepared drink when both volume and
  powder amount are known.
- Use `time_s` for one exact elapsed time or `start_s` plus `end_s` to spread
  occurrences evenly through a period.
- Repeat the same product in `items` when separate servings occurred in
  different periods.
- Resolve pause timing and other activity interpretation before the MCP call;
  pass only elapsed seconds to EatMyRide.

## Authentication And Boundaries

Credentials come from `username` and `password` in the user-owned
`~/.eatmyride_mcp.json`. The MCP uses only this file.

This plugin owns EatMyRide access, field interpretation, payload normalization,
and write safety. The caller owns persistence, freshness policy, cross-source
composition, reports, and final fueling or training decisions.
