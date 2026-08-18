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

If either server write fails, the tool reads the food plan again before
returning. Treat `partial_write` as a completed or partial remote mutation, not
as proof that nothing changed. Check `failed_stage`, `mutation_detected`,
`desired_state_present`, and `readback_succeeded`; do not retry when
`desired_state_present=true`, because that would repeat an already applied
write. When readback is unavailable, report the state as uncertain rather than
claiming success or failure.

Build input from reviewed `search_products`, `list_products`, `get_product`, or
food-plan rows. Do not infer an exact product from label similarity alone.

## Custom Products

`create_product`, `update_product`, and `delete_product` operate only on custom
products and preview by default.

- `create_product` accepts user-facing kcal, grams, millilitres, and caffeine
  values. A confirmed create reads back the new product.
- `update_product` first reads the exact existing product, changes only
  explicitly supplied user-facing fields, and returns `before` plus the
  proposed or verified product.
- `delete_product` first resolves the exact custom product. A confirmed delete
  verifies that the product is absent before reporting success.
