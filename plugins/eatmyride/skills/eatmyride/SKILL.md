---
name: eatmyride
description: Use when reading or changing EatMyRide activities, food plans, products, fueling, glycogen, energy fields, or carbohydrate intake.
---

# EatMyRide

Use the EatMyRide MCP tools for source access, field interpretation, and safe
writes. The plugin is stateless and returns normalized data to callers.

## MCP Tools

- `list_activities` lists candidates in an inclusive local-date range. Select
  the newest row by `date` when the user asks for the latest activity.
- `get_fueling` returns compact activity energy and glycogen state together
  with food-plan events and calculated intake totals.
- `search_products` searches the broader EatMyRide product catalogue.
- `list_products` uses `source: custom` for the user's products or
  `source: suggested` with `activity_id` and `kind` for activity-specific food
  or drink candidates.
- `get_product` resolves one exact product before a food-plan or product write.
- `set_foodplan_products` sets exact quantities and elapsed times for selected
  products while preserving unrelated food-plan events.
- `create_product`, `update_product`, and `delete_product` operate only on
  custom products. `update_product` changes only explicitly supplied fields.

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
- For a previous usable plan, search an inclusive range before the reference
  date, sort newest first, and inspect candidates until one has food or drink
  events.

## Writes

Read [references/write-safety.md](references/write-safety.md) before changing a
food plan or custom product. All remote writes require explicit user intent.
Preview first with `confirm: false`; use `confirm: true` only after reviewing
the exact target and proposed change. Confirmed tools verify remote state before
reporting success.

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
