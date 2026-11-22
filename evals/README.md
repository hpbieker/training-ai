# Evaluations

The shared repository includes synthetic scenarios for Garmin Connect,
Intervals.icu, Xert and [daily recommendations](training-analysis/recommendations/README.md).
The [Route Planner evaluation](route-planner/README.md) checks a saved route
against a public-road corridor on Hurum.

Completed-session evaluations use local activity artifacts under
`outputs/intervals/activities/`. Keep their inputs, reviews and results local.
Use the ignored `evals/training-analysis/cases.json` for the default case list,
or pass an explicit local file with `--cases-file`. Each entry in `cases`
needs an `id`, the name of the saved `activity` directory, an `options` array
for the inspection helper and a `context` string for the evaluator. For example:

```json
{
  "cases": [
    {
      "id": "example",
      "activity": "example-activity",
      "options": [],
      "context": "Assess whether the effort stayed steady."
    }
  ]
}
```

Set up local coaching preferences and practical context before preparing the
cases. The preparation script includes copies of these files in each private
evaluation workspace.
