# EatMyRide Write Safety

Perform remote writes only when the user explicitly asks. Review the payload,
require `--yes`, and read the changed object back before reporting success.

## Replace A Food Plan

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan-replace <activity-id> <foodplan.json> --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan <activity-id> --summary
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py activity <activity-id> --summary
```

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
