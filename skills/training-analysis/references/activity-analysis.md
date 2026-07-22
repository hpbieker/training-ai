# Activity Analysis

## Selection And Inspection

- Treat “latest” as a discovery request. Fetch and save the newest source
  activity before passing its directory to `activity_inspect.py`.
- If an activity identifier has no local package, create it through the source
  workflow first. Repo analysis helpers must not call source APIs directly.
- Prefer `scripts/analysis.py` and `scripts/activity_inspect.py` over one-off
  analysis snippets.
- Use `--compact` or full output only when detailed per-block/per-sensor JSON is
  needed, `--no-intervals` when interval rows are irrelevant, and `--stdout`
  only when full terminal JSON is genuinely useful.

## Block Detection

- Use a known target with `--target`, `--tolerance`, and `--min-block` when the
  intended structure is known.
- Use `--auto-blocks` for mixed or unclear structured indoor sessions. Do not
  infer outdoor VT1/VT2 intent from variable `WORK` segments without supporting
  activity name, workout structure, or user context.
- Exclude warm-up and cooldown from work-block metrics.

## Quality Sections

- For outdoor endurance, inspect `outdoor_vt1_pacing`. Pass the caller-resolved
  anchor with `--vt1-watts`; use `--outdoor-vt1` or
  `--no-auto-outdoor-vt1` only to override detection deliberately.
- For pure indoor trainer VT1, inspect `indoor_vt1_quality` and pass
  `--vt1-watts`. Treat warm-up/cooldown as part of a selected workout unless
  explicitly modifying it.
- For threshold-like work, inspect `vt2_quality`. Pass `--vt2-watts` for a
  known indoor target; omit it for variable outdoor work so the result remains
  a control/cost diagnostic rather than exact target compliance.
- Keep `beta_stability`, `beta_vo2`, and experimental VT1 metrics as
  development evidence. Do not present them as threshold diagnoses or let them
  override the main score without a clear pattern. Prefer `beta_summary` for
  tabular summaries and preserve separate parts in mixed sessions.

## Interpretation

- Report mechanical execution separately from physiological cost. A variable
  ride can be mechanically uneven yet physiologically tolerable, and a tightly
  controlled interval can still have excessive physiological cost.
- When power varies, prefer HR/BR/VE-per-watt drift over raw drift. Raw
  physiology can fall while cost per watt rises.
- Use relevant available sensors, not power and HR alone. Check data quality and
  continuous gaps before calculating averages, extremes, or drift.
- For respiration, distinguish BR, VE, and VT; use five-second rolling VE peaks
  for short hard efforts.
- For muscle oxygenation, inspect SmO2 desaturation and recovery reoxygenation,
  THb trend, and alignment with power, HR, and ventilation.
- Use normalized source activity summaries for their own load and model
  perspectives. They supplement rather than replace stream/block analysis.
- Numeric difficulty should accompany a text difficulty rating when present.
- Save subjective feel/RPE remotely only when the user asks, using the owning
  source skill's write workflow.
