# EatMyRide Write Safety

Perform remote writes only when the user explicitly asks. Review the payload,
require `--yes`, and read the changed object back before reporting success.

## Replace A Food Plan

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan-set <activity-id> \
  --item '<product-id>:pieces=<n>' \
  --item '<product-id>:ml=<n>,gram=<n>' \
  --dry-run
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan-set <activity-id> \
  --item '<product-id>:pieces=<n>' \
  --item '<product-id>:ml=<n>,gram=<n>' \
  --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan-set <activity-id> \
  --item '<product-id>:pieces=<n>,start=<seconds>,end=<seconds>' \
  --item '<same-product-id>:pieces=<n>,start=<seconds>,end=<seconds>' \
  --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan-replace <activity-id> <foodplan.json> --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan <activity-id> --summary
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py activity <activity-id> --summary
```

Prefer `foodplan-set` for product quantity changes. It resolves product objects,
preserves unrelated events, replaces all existing events for the mentioned
product IDs, expands piece counts, and verifies the server result. Repeating the
same command is idempotent.

`time` and period boundaries are elapsed activity seconds. A period distributes
the requested occurrences evenly inside its boundaries; one occurrence lands
at the midpoint. The same product may be repeated for separate periods. Keep
pause detection and other activity interpretation outside this source CLI, and
pass only the resolved elapsed times.

Use `pieces` for counted products and `gram` for weighed products. A gram amount
is one event at its exact time or at the midpoint of its period. Represent
separate weighed servings as repeated `--item` entries for the same product.

Replacement overwrites the complete server-side event list. Preserve intended
events rather than sending only the changed item.

Build input from reviewed product-search, suggested-product, or food-plan rows.
Every event must include a `product` object and either `productId` or
`product.id`. Let the CLI normalize events to the narrower mobile-app payload;
do not hand-post raw product-search objects.

For piece-based products, represent quantity according to the product's serving
model rather than assuming that event grams always mean physical grams.

The CLI triggers activity recalculation after replacement. Verify both the
food-plan events/totals and the recalculated activity energy state.

## Custom Products

Preview creation before writing:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-create --label "<name>" --dry-run
```

Persist only after review:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-create --label "<name>" ... --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-update <product-id> <product.json> --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-delete <product-id> --yes
```

Product deletion is destructive. Resolve the exact custom product first and
verify its absence afterward. Present input values to the user in kcal, grams,
and ml; the CLI handles storage-unit normalization for creation.
