# EatMyRide Field Semantics

## Authentication

- Default API base: `https://backend.eatmyride.com/api`.
- Login path relative to the API base: `POST /auth/login`.
- Login body: `{"email": "...", "password": "..."}`.
- Expected login response includes `token`.
- Authenticated requests send `Authorization: Bearer <token>`.
- Requests should include `Accept: application/json` and `accept-version: 1.03`.
- Tokens are treated as short-lived session credentials and should not be written to disk. In-memory reuse inside one short-lived operation/session is fine; login again when the token is missing, expired, or rejected.

## Activity And Food Plan

- `GET /api/activities/<activity-id>` returns the activity document.
- `GET /api/foodplan/<activity-id>` returns the activity's food-plan event list.
- A food plan can be prepared before an activity and updated afterward; do not assume every event represents confirmed real-world intake unless the user or app workflow confirms it.
- Activity-level fueling fields are useful for summary context, but food-plan events are the source of item-level food and drink details.
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

- Food-plan replacement posts the full list to `/api/foodplan/<activity-id>`.
- The mobile-app-compatible flow then updates the activity document with `PUT /api/activities/<activity-id>` to trigger recalculation.
- Verify by reading both the activity and the food plan back from the server.
- Product create/update/delete endpoints affect remote account state and should require explicit confirmation.

## Observed Additional Endpoints

- `GET /api/activities/evaluated/<activity-id>`
- `GET /api/products/regular/drink`
- `GET /api/products/regular/food`
- `GET /api/account/profile`
- `GET /api/days/<local-date>`
- `GET /api/days/<local-date>/timeline`

The evaluated activity endpoint can include evaluated activity, energy graph and burn series. Product endpoints are useful when adding intake events for products that are not already present in a food plan.

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
