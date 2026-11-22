# EatMyRide Write Safety

Perform remote writes only when the user explicitly asks. Resolve the exact
activity or custom product first, preview the proposed change with
`confirm: false`, and use `confirm: true` only after review.

## Food Plans

Use `set_foodplan_products` for exact product quantities and elapsed times. It
removes existing events only for the mentioned product IDs, preserves unrelated
events, writes one complete server-side food plan, triggers activity
recalculation, and reads back the food plan and activity state.

Piece quantities expand to one event per piece. Use `pieces` for counted
products and `gram` for weighed products. A gram amount creates one event at
`time_s` or at the midpoint of `start_s` and `end_s`. A piece count within a
period is distributed evenly. Repeat an item for separate periods.

If saving the plan or recalculating the activity fails, inspect `failed_stage`,
`readback_succeeded`, `mutation_detected` and `desired_state_present` on
either `partial_write` or `write_failed`. If readback failed, use
`get_foodplan` to resolve the current entries before retrying. If the desired
plan is already present, keep it. After a failure at `put_activity`, report
the verified entries separately from the uncertain recalculation outcome.

Build input from reviewed `search_products`, `list_products`, `get_product`, or
food-plan rows. Do not infer an exact product from label similarity alone.

## Custom Products

`create_product`, `update_product`, and `delete_product` operate only on custom
products and preview by default.

- `create_product` accepts user-facing kcal, grams, millilitres, and caffeine
  values. A confirmed create reads back the new product. If the result is
  uncertain, check `list_products(source="custom")` for the proposed item
  before repeating the create.
- `update_product` first reads the exact existing product, changes only
  explicitly supplied user-facing fields, and returns `before` plus the
  proposed or verified product.
- `delete_product` first resolves the exact custom product. A confirmed delete
  verifies that the product is absent before reporting success.
