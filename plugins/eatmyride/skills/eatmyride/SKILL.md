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
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py activity <activity-id> --summary
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan <activity-id> --summary
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py fueling <activity-id> --summary
```

- For one local date, pass the same date as start and end: `activities <local-YYYY-MM-DD> <local-YYYY-MM-DD>`.
- For "today's EatMyRide activities", use the user's local date for both arguments.
- For a week or date range, use inclusive local dates: `activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>`.
- For "latest" or "most recent" EatMyRide activity requests, choose a reasonable local date range, call `activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>`, then select the newest activity by its `date` field.
- Use the activity list as the cheap first pass for selecting an activity. It usually includes id, date and duration, but not the evaluated fueling fields or `energyGraph`.
- When analyzing what the user ate or drank, fetch `foodplan <activity-id> --summary`; this returns compact item rows plus calculated food-plan totals and is usually enough for intake analysis.
- Fetch `activity <activity-id> --summary` only when the analysis needs activity-level fueling or energy state fields such as `energyGraph.energy.glycogen`, `caloriesThreshold`, `caloriesStart`, `caloriesNeeded`, `energyNeeded`, `estimatedFatConsumption`, or `carbohydratesFromFood`.
- When analysis needs both intake and activity-level energy/glycogen state, fetch `fueling <activity-id> --summary` instead of separate `foodplan` and `activity` calls.
- `activity --summary` reduces the local JSON passed to callers, but the current CLI implementation still reads the full activity document before summarizing it.
- Do not interpret activity `warning` as a fueling-quality verdict. Treat it as a likely workflow/status flag for whether intake has been reviewed or edited.
- If available, use `energyGraph.energy.glycogen` for depletion/final-state shape and `caloriesThreshold` for risk-zone context. When reporting glycogen state, include the lowest value as well as the final value.

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
- After any food-plan write, trigger/read the recalculated activity state and read back the food plan before reporting success.
- Calculate carbohydrate grams from food-plan event quantities and product serving fields.
- The CLI normalizes `foodplan-replace` input to EatMyRide's narrower
  mobile-app food-plan shape before POSTing. It is safe for callers to build a
  replacement list from product-search or suggested-product rows, but each event
  must include a `product` object plus `productId` or `product.id`.
- For piece products such as `Laban Seigmenn (1 stk, 5 g)`, model multiple
  pieces as separate `gram: 1` events rather than one lumped piece event.
- For `SiS GO Elektrolyte Orange` (`productId 3111`), use the verified drink
  scaling from prior writes: `300 ml` -> `20 g`, `700 ml` -> `47 g`, `900 ml`
  -> `60 g`. If a write fails, suspect payload shape before blaming decimal
  gram values.

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

- Use suggested/regular product commands only to identify candidate products; food-plan totals still come from activity food-plan events.
- For product create/update/delete, require explicit confirmation unless doing a dry run. Review the payload before remote product writes.
- Use `product-create --dry-run` to inspect product payloads before creating them; use product write commands with `--yes` only after confirmation.
- Product payload arguments should be presented to users in normal kcal, grams and ml. EatMyRide stores weight/macros/salt and many nutrients as integer milligrams.

## Fueling Interpretation

- Judge fueling primarily from `foodplan <activity-id> --summary` events plus activity energy fields such as `energyGraph.energy.glycogen`, `caloriesThreshold`, `caloriesStart`, `caloriesNeeded` and `energyNeeded`.
- Do not rely on activity-level `carbohydratesFromFood` as carbohydrate grams; observed values match rounded food energy in kcal.
- Distinguish EatMyRide food-plan fueling from likely real-world fueling. If products are missing from EatMyRide or the plan may not have been updated after the activity, state that uncertainty instead of treating the food plan as complete.
- For recent activities with missing fueling, ask what the user ate and drank when recall is plausible. For older activities, state that fueling is unknown.

## Implementation Files

This local plugin currently exposes:

- `plugins/eatmyride/scripts/eatmyride_cli.py` for live command-line access.
- `plugins/eatmyride/scripts/eatmyride_api.py` for API access and source-specific helpers.

Read [field-semantics.md](references/field-semantics.md) relative to this skill
file, i.e. `plugins/eatmyride/skills/eatmyride/references/field-semantics.md`,
when you need endpoint details, observed field behavior, or product/write
payload notes.
