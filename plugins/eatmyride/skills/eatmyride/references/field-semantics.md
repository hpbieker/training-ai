# EatMyRide Field Semantics

## Activity And Food Plan

- Activity-list rows identify candidate activities but do not contain the full
  evaluated fueling state or `energyGraph`.
- Food-plan events are the source of item-level food and drink details. A plan
  can be prepared before an activity and edited afterward, so it is not proof
  that every item was consumed.
- Activity-level `warning` appears to be a review/workflow flag. Do not treat it
  as a fueling-quality verdict.
- `carbohydratesFromFood` is misleadingly named: observed values match rounded
  food energy in kcal, not carbohydrate grams.

## Energy State

- `energyGraph.energy.glycogen` is the observed glycogen/depletion curve.
- `caloriesThreshold` is the exposed upper boundary of the app's glycogen risk
  zone. The lower high-risk boundary is not exposed; any derived boundary must
  be labelled as a caller assumption.
- `caloriesStart`, `caloriesNeeded`, `energyNeeded`, and
  `estimatedFatConsumption` are modelled activity-energy context, not recorded
  intake.
- The app-style glycogen gram display has been observed to match kcal-equivalent
  values divided by 4.0.

## Food-Plan Quantities

- Product carbohydrate values are stored as milligrams per serving in
  `product.carbohydrates`.
- For gram-based products, serving count is
  `event.gram / product.ingredientsQty` when `ingredientsQtyUnit == "gram"`.
- Fluid quantity comes from `event.ml`.
- Event timing is normally `event.time` in seconds from activity start; some
  payloads may also contain distance-based timing.
- Calculate carbohydrate grams from event quantities and product serving data,
  not from activity-level `carbohydratesFromFood`.

## Product Units

- User-facing inputs use kcal, grams, and millilitres.
- EatMyRide stores product weight, macronutrients, salt, and several nutrients
  as integer milligrams.
- `calories` is kcal and `volume` is ml.
