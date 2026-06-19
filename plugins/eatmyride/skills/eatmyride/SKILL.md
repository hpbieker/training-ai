---
name: eatmyride
description: Use when working with EatMyRide activity, food-plan, product, fueling, glycogen, caloriesThreshold, caloriesStart, caloriesNeeded, energyNeeded, energyGraph, carbohydratesFromFood, or EatMyRide write operations. This skill covers source semantics and write-safety, not local persistence policy.
---

# EatMyRide

Use this skill for EatMyRide-specific field interpretation and write safety. Treat local persistence and data currentness policy as the caller's responsibility.

## CLI

Use `plugins/eatmyride/scripts/eatmyride_cli.py` for live access. It prints JSON to stdout and does not persist responses.

## Authentication

- Live access uses `EATMYRIDE_EMAIL` and `EATMYRIDE_PASSWORD` from the caller's secret store or local `.env`.
- Login with `POST /auth/login`, read the returned `token`, and send it as `Authorization: Bearer <token>`.
- Do not persist the token to disk. Reuse it only in memory for the current short-lived operation/session, and login again when it is missing, expired, or rejected.
- Use EatMyRide API version header `accept-version: 1.03` unless the caller explicitly overrides it.

## Activities

- Activity lists:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>
```

- Single activity:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py activity <activity-id>
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan <activity-id> --summary
```

- For one local date, pass the same date as start and end: `activities <local-YYYY-MM-DD> <local-YYYY-MM-DD>`.
- For "today's EatMyRide activities", use the user's local date for both arguments.
- For a week or date range, use inclusive local dates: `activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>`.
- For "latest" or "most recent" EatMyRide activity requests, choose a reasonable local date range, call `activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>`, then select the newest activity by its `date` field.
- When analyzing fueling, fetch both `activity <activity-id>` and `foodplan <activity-id> --summary`; activity-only payloads are not enough.
- Do not interpret activity `warning` as a fueling-quality verdict. Treat it as a likely workflow/status flag for whether intake has been reviewed or edited.
- If available, use `energyGraph.energy.glycogen` for depletion/final-state shape and `caloriesThreshold` for risk-zone context.

## Food Plans

- Read a food plan:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan <activity-id> --summary
```

- For "previous food plan" or nearest earlier fueling requests, choose a reasonable inclusive local date range before the reference date, call `activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>`, sort activities newest first by `date`, then call `foodplan <activity-id> --summary` for candidates until one has food or drink events.

- Replace a food plan:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan-replace <activity-id> <foodplan.json> --yes
```

- Food-plan writes replace the complete server-side list. Require explicit user confirmation before replacing a food plan or editing an event.
- After any food-plan write, trigger/read the recalculated activity state and read back `/foodplan/<activity-id>` before reporting success.
- Calculate carbohydrate grams from food-plan event quantities and product serving fields.

## Products

- Find products:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py products-search "<search-text>"
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py products-custom --contains "<search-text>"
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py products-suggested <activity-id> drinks --contains "<search-text>"
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py products-suggested <activity-id> food --contains "<search-text>"
```

- Preview product payloads:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-create --label "<name>" --dry-run
```

- Manage custom products:

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-create --label "<name>" ... --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-update <product-id> <product.json> --yes
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py product-delete <product-id> --yes
```

- Use suggested/regular product endpoints only to identify candidate products; food-plan totals still come from activity food-plan events.
- For product create/update/delete, require explicit confirmation unless doing a dry run. Review the payload before remote product writes.
- Use `product-create --dry-run` to inspect product payloads before creating them; use product write commands with `--yes` only after confirmation.
- Product payload arguments should be presented to users in normal kcal, grams and ml. EatMyRide stores weight/macros/salt and many nutrients as integer milligrams.

## Fueling Interpretation

- Judge fueling primarily from `/foodplan/<activity-id>` events plus activity energy fields such as `energyGraph.energy.glycogen`, `caloriesThreshold`, `caloriesStart`, `caloriesNeeded` and `energyNeeded`.
- Do not rely on activity-level `carbohydratesFromFood` as carbohydrate grams; observed values match rounded food energy in kcal.
- Distinguish EatMyRide food-plan fueling from likely real-world fueling. If products are missing from EatMyRide or the plan may not have been updated after the activity, state that uncertainty instead of treating the food plan as complete.
- For recent activities with missing fueling, ask what the user ate and drank when recall is plausible. For older activities, state that fueling is unknown.

## Local training-ai Helpers

When working inside the `training-ai` repo, the current implementation lives in:

- `plugins/eatmyride/scripts/eatmyride_cli.py` for live command-line access.
- `plugins/eatmyride/scripts/eatmyride_api.py` for API access and source-specific helpers.

Read [field-semantics.md](references/field-semantics.md) when you need endpoint details, observed field behavior, or product/write payload notes.
