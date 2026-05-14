# TODO

- Use cached Xert training advice in readiness recommendations.
  - `python3 -B scripts/cache_xert.py training-advice` caches current Xert advice, including current Recovery Load, recovery days and workout capacity.
  - Use the returned `recovery_days_*`, `recoveryload_*`, `trainingload_*` and `workout_capacity_*` fields directly. Do not reimplement the recovery-days formula locally.
  - Do not use per-activity `summary.progression.rl` as current Recovery Load. It appears to describe activity progression/state around that activity, not the current post-sync recovery state.
