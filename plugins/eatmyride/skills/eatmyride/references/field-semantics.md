# EatMyRide Field Semantics

This file documents field meaning for callers that use
`plugins/eatmyride/scripts/eatmyride_cli.py`. Endpoint names below are
implementation notes for maintaining `eatmyride_api.py`; analysis workflows
should use the CLI commands from `SKILL.md`.

## Authentication

- Default API base: `https://backend.eatmyride.com/api`.
- Login path relative to the API base: `POST /auth/login`.
- Login body: `{"email": "...", "password": "..."}`.
- Expected login response includes `token`.
- Authenticated requests send `Authorization: Bearer <token>`.
- Requests should include `Accept: application/json` and `accept-version: 1.03`.
- Tokens are treated as short-lived session credentials and should not be written to disk. In-memory reuse inside one short-lived operation/session is fine; login again when the token is missing, expired, or rejected.

## Activity And Food Plan

- `activities <start> <end>` is the cheap first pass for selecting an activity by id/date/duration, but observed list entries do not include evaluated fueling fields or `energyGraph`.
- `foodplan <activity-id> --summary` returns the activity's food-plan event list plus calculated food-plan totals.
- `activity <activity-id> --summary` returns compact activity-level fueling and energy state fields from the full activity document.
- A food plan can be prepared before an activity and updated afterward; do not assume every event represents confirmed real-world intake unless the user or app workflow confirms it.
- Activity-level fueling fields are useful for summary context, but food-plan events are the source of item-level food and drink details.
- For intake-only analysis, `foodplan <activity-id> --summary` can be enough. Fetch `activity <activity-id> --summary` only when activity-level energy state fields are needed, especially `energyGraph.energy.glycogen`, `caloriesThreshold`, `caloriesStart`, `caloriesNeeded`, `energyNeeded`, `estimatedFatConsumption`, or `carbohydratesFromFood`.
- `carbohydratesFromFood` is misleadingly named. Observed responses match rounded food energy in kcal, not carbohydrate grams.
- `warning` should not be used as a fueling-quality signal.

## Energy Graph

- `energyGraph.energy.glycogen` is the best observed source for glycogen/depletion curve analysis.
- `caloriesThreshold` is the exposed upper boundary for the app's glycogen risk-zone display.
- The lower high-risk boundary is not directly exposed; the local plotting helper defaults it to `0.6 * caloriesThreshold`.
- The app-style gram display has been observed to match kcal-equivalent values divided by `4.0`.

## Food-Plan Totals

- Product carbohydrate values are stored as milligrams per serving in `product.carbohydrates`.
- For gram-based products, use `event.gram / product.ingredientsQty` as the serving count when `ingredientsQtyUnit == "gram"`.
- Fluid totals come from `event.ml`.
- Event timing is usually `event.time` in seconds from activity start. Some payloads may also include distance-based timing.

## Product Payloads

- User-facing product inputs should be normal kcal, grams and ml.
- EatMyRide stores product `weight`, `carbohydrates`, `fat`, `protein`, `salt`, `sugars`, `ofWhichSaturated`, `fibers` and several micronutrients as integer milligrams.
- `calories` is stored as kcal.
- `volume` is stored as ml.

## Write Flow

- `foodplan-replace <activity-id> <foodplan.json> --yes` sends the full replacement list.
- The CLI's mobile-app-compatible flow then updates the activity document to trigger recalculation.
- Verify by reading both the activity and the food plan back from the server.
- Product create/update/delete endpoints affect remote account state and should require explicit confirmation.

## Implementation Endpoint Notes

These are observed backend paths used or investigated by `eatmyride_api.py`.
They are not caller-facing workflow instructions:

- `GET /api/activities/<activity-id>` backs `activity <activity-id>`.
- `GET /api/foodplan/<activity-id>` backs `foodplan <activity-id>`.
- `GET /api/activities/list/<start>/<end>` backs `activities <start> <end>`.
- Food-plan replacement posts to `/api/foodplan/<activity-id>` and then updates `/api/activities/<activity-id>` to trigger recalculation.

## Observed Additional Backend Paths

- `GET /api/activities/evaluated/<activity-id>`
- `GET /api/products/regular/drink`
- `GET /api/products/regular/food`
- `GET /api/account/profile`
- `GET /api/days/<local-date>`
- `GET /api/days/<local-date>/timeline`

The evaluated activity endpoint can include evaluated activity, energy graph and burn series, but observed responses can be larger than the normal activity document. The day endpoint is small but does not expose activity-level fueling state. Product endpoints are useful when adding intake events for products that are not already present in a food plan.

## Observed App Upload Flows

The mobile app exposes file-import flows that likely have corresponding backend
upload endpoints, but their request details have not been captured yet:

```text
Routes:         upload .fit or .gpx
Training plans: upload .fit
Activities:     upload .fit
```

To automate these safely, capture the URL, HTTP method, multipart field names
and any metadata sent by the app during a manual upload.
