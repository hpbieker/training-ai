---
name: eatmyride
description: Use when reading or changing EatMyRide activities, food plans, products, fueling, glycogen, energy fields, or carbohydrate intake.
---

# EatMyRide

Use this skill for EatMyRide access, field interpretation, and safe writes. The
CLI emits JSON and does not persist read responses.

## Choose The Narrowest Command

```bash
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py activities <start-date> <end-date>
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py foodplan <activity-id> --summary
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py activity <activity-id> --summary
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py fueling <activity-id> --summary
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py products-search "<text>"
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py products-custom --contains "<text>"
python3 -B plugins/eatmyride/scripts/eatmyride_cli.py products-suggested <activity-id> <food|drinks>
```

- `activities` is the cheap discovery call. Its date range is inclusive and
  local; select the newest result by `date` when the user asks for latest.
- `foodplan --summary` is normally sufficient for item-level intake and totals.
- `activity --summary` adds activity-level energy and glycogen state.
- `fueling --summary` combines both when the analysis needs intake and energy
  state; do not make the two separate calls.
- For a previous usable plan, search an inclusive range before the reference
  date, sort newest first, and inspect candidates until one has food or drink
  events.

## Interpretation

Read [references/field-semantics.md](references/field-semantics.md) before
interpreting food-plan quantities, carbohydrate totals, glycogen,
`caloriesThreshold`, `carbohydratesFromFood`, or activity warnings.

Distinguish recorded food-plan events from confirmed real-world intake. For a
recent incomplete activity, ask what was actually consumed when recall is
plausible; otherwise report the intake as unknown.

When reporting glycogen state, include both the minimum and final value from
the curve when available.

## Writes

Read [references/write-safety.md](references/write-safety.md) before replacing a
food plan or creating, updating, or deleting a custom product. All remote writes
require explicit user intent and `--yes`; use dry-run where available and verify
the resulting remote state.

## Authentication And Boundaries

Credentials come from `EATMYRIDE_EMAIL` and `EATMYRIDE_PASSWORD` in the selected
secret store or `.env`. The plugin uses a short-lived bearer token in memory and
does not persist it. API requests use `accept-version: 1.03`.

This plugin owns EatMyRide access, field interpretation, payload normalization,
and write safety. The caller owns persistence, freshness policy, cross-source
composition, reports, and final fueling or training decisions.
