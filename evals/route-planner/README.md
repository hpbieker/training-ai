# Hurum Route Planner evaluation

From the repository root, use a Python environment with the Route Planner
dependencies installed:

```sh
.venv/bin/python -B scripts/run_route_planner_eval.py --output-dir outputs/route-planner-eval/hurum
```

Use a fresh output directory. The run copies the skill into a temporary
workspace and saves routes, tool logs and results under the output directory.

The scenario starts and ends at a public road point in Storsand. It checks
that the saved route follows the fv. 281 checkpoints via Filtvet to Tofte
before passing Klokkarstua. It also checks the length of the eastern leg
and looks for retraced sections near Tofte. If a saved route was shown,
the evaluator scores that route. Otherwise it scores the latest saved route.
