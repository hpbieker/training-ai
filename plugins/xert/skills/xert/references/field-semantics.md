# Xert Field Semantics

## Authentication

The user-facing credential setup is:

```text
XERT_USERNAME=your-email@example.com
XERT_PASSWORD=your-password
```

The plugin uses those credentials for two internal access patterns:

- OAuth-style API calls, using the public `xert_public` client.
- Authenticated web-session calls, using Laravel CSRF/session behavior.

Some useful Xert data is only available through authenticated web endpoints, not the OAuth API.

## Activity Dates

`activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>` treats both arguments as an inclusive local-date range on the machine running the command. The plugin converts local start-of-day and local end-of-day to Unix timestamps before calling Xert's `/oauth/activity` endpoint.

Do not ask the language model to manually widen or shift these date arguments for time zone handling. If a user asks for "today", "this week", or another calendar period, pass the intended local calendar dates to the CLI.

## Recovery Model

`recovery-model` logs in to Xert web, reads `/my-fitness` `trainingAdvice` and `trainingPlan`, reads `/profile/settings` `ir_params`, then calculates low/high/peak recovery locally from those model inputs.

Do not use per-activity `summary.progression.rl` as current Recovery Load.

Express Xert recovery days as hours when answering users. `0` recovery hours is Xert's fresh threshold; negative recovery hours mean the athlete is on the fresh side of that threshold.

Interpret components by system:

- `lo`: low XSS / any cycling activity
- `hi`: high XSS / work over threshold power
- `pk`: peak XSS / peak-power-relevant work over threshold power

Treat low recovery as the first readiness gate. If low recovery hours are still positive, Xert does not indicate freshness for more cycling load.

Workout capacity is calculated against the next planned Xert workout. It is not a generic independent estimate of all absorbable training.

Interpret workout capacity as how much training can be done now while still being just fresh before the next planned Xert workout.

## Forecast And Calendar

Calendar notes are separate from forecast/training-plan fields. Read notes with:

```bash
python3 -B plugins/xert/scripts/xert_cli.py calendar-notes
```

Write notes with:

```bash
python3 -B plugins/xert/scripts/xert_cli.py calendar-note-set <YYYY-MM-DD> "<note>" --yes
```

Read back and verify after writing.

In Xert forecast/activity state, `high_intensity` means planned work over threshold power that generates high and/or peak XSS. Still check the actual low/high/peak XSS split.

In Xert calendar forecast payloads, do not present `xss_target` as the planned workout XSS unless its meaning has been verified. It can appear on rest days and looks more like a model/day target than the specific placeholder workout load. Use `xss`, `xlss`, `xhss`, and `xpss` as the planned placeholder load.

Describe whether a planned XSS load is small, moderate or large relative to the user's current Xert training load, not as an absolute label. Compare planned total/low/high/peak XSS with current `trainingload_*` or forecast `tls` values when those fields are available.

Treat Xert recovery-hour projection as deterministic from the Xert advice timestamp when assuming no intervening training. Subtract elapsed time from the low/high/peak recovery hours and state that assumption.

## Workouts

Use `workouts --summary` for compact workout-library rows with duration, parsed work watts, XSS split, difficulty and path:

```bash
python3 -B plugins/xert/scripts/xert_cli.py workouts --summary
```

Use `workout <path>` to fetch the resolved OAuth workout payload for the user's current fitness signature.

Use `workout-rows <path>` to inspect editable Workout Designer rows. For mixed-mode/slope workouts, verify against Workout Designer rows rather than relying only on `workout <path>`.

Known Workout Designer slope row types observed here:

- `t_slope_pp`
- `t_slope_mmp`
- `t_slope_w`
- `t_slope_absolute`

For relevant slope rows, `power.second_value` stores slope percent. The verified 4 percent opener pattern used:

```json
{"value": 350, "second_value": 4, "type": "t_slope_absolute"}
```

The resolved OAuth workout endpoint can return HTTP 500 for some slope variants even when the saved workout is valid. In that case, verify through `workout-rows <path>` and `workouts --summary`.

Workout deletion uses `DELETE /workout/<path>` with `X-Requested-With: XMLHttpRequest` on an authenticated web session. Treat it as destructive: require explicit user confirmation and verify afterwards.

## Recommended Training

`recommended-training` is useful for recommendation and ranking context. The payload can include both workouts and activities. When choosing a workout, filter `exercises` by `exerciseType == "Workout"` first, then rank candidates using the caller's goal, XSS split, duration, focus, suitability, difficulty and any caller-provided preferences.

## Activity Load

For Xert activity summaries, prefer Xert XSS and related fields for Xert-specific load language:

- total XSS
- low/high/peak XSS
- XEP
- focus
- specificity
- freshness/status
- fitness signature

Always include numeric difficulty when summarizing Xert workouts or activities. The text difficulty rating is useful but too coarse by itself.
