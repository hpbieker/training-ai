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

## Endpoint Inventory

Track which endpoints were found in Xert's frontend JavaScript or in the local
plugin, whether we have actually tried to call them, and whether we know the
response shape. `Not called` means we should not assume anything about the
response beyond the request path and parameters seen in the frontend bundle.

| Endpoint | Found in | Call status | Response known | Notes |
| --- | --- | --- | --- | --- |
| `GET recommended-training?recent&date&additional` | Xert JS + plugin | Called | Yes | Planned-time advice and recommendation candidates. Xert JS sends ISO `date`, `recent=true`, `additional=false`; plugin mirrors selected time minus one second. |
| `GET my-fitness/xss_targets?date` | Xert JS | Called ad hoc | Yes, limited | Returned target/remaining/completed/progression/tired fields, but did not reproduce `/recommended-training` planned-time differences. |
| `POST my-fitness/xss_targets` | Xert JS | Not called | No | JS posts a body to this endpoint. Do not assume it matches the GET response. |
| `GET /calendar/adaptive-training-advisor?date&sport` | Xert JS | Called | Yes | Returns planned-time advice/status fields including `targetXSS`, `remainingXSS`, `completedXSS`, `xss_goal`, `training_status`, `signature`, `recommended_focus*`, `availability`, and `targets_source`. Same-day probes kept dose fields stable across times while `training_status.tl_total`/`rl_total` moved with time. Historical-date probes returned completed XSS plus post-completed remaining/recommended dose, not the original full-day target. Does not include the workout/activity candidate list from `/recommended-training`. |
| `GET /calendar/training-forecast?...` | Xert JS + plugin | Partly called | Partial | Plugin calls forecast with `duration=-1&includePlaceholders=true`; JS also uses forecast/simulation params such as `start`, `xss`, `focus_power`, and `title`, which we have not characterized. |
| `GET /calendar/events?forUser&start&end&unpinned` | Xert JS | Not called | No | Calendar event lookup before forecast confirmation. |
| `GET /calendar/forecast-activities-close/<YYYY-MM-DD>` | Xert JS | Not called | No | Looks relevant for nearby forecast/completed activity context. |
| `POST /calendar/training-availability` | Xert JS | Not called | No | Writes availability; do not call without explicit user intent. |
| `POST /calendar/remove-training-availability` | Xert JS | Not called | No | Write/delete availability; do not call without explicit user intent. |
| `POST /calendar/swap-activities` | Xert JS | Not called | No | Mutates planned activities; do not call without explicit user intent. |
| `GET /calendar/weather/forecast?lat&lon&cnt` | Xert JS | Not called | No | Xert weather source; repo normally uses Yr instead. |
| `GET /calendarSummaryWeekly?theDate&tz&numRows` | Xert JS | Not called | No | Weekly calendar summary. |
| `GET /calendar/training_status/<start>/<end>` | Xert JS | Not called | No | Used by JS near weekly summary; response shape unknown. |
| `GET /workouts/all-workouts?date` | Xert JS | Not called | No | Web workout list; plugin currently uses OAuth `/oauth/workouts` instead. |
| `GET /workouts/playable-workouts?date` | Xert JS | Not called | No | Workout-player candidate list. |
| `POST /autogen-workout` | Xert JS | Not called | No | Generates/schedules recommended workout; mutating or near-mutating behavior, so do not call casually. |
| `GET /workout/<path>/data` | Xert JS | Not called | No | Different from OAuth workout and Designer intervals endpoints. |
| `GET /workout/<path>/intervals` | Xert JS + plugin | Called | Yes | Editable Workout Designer rows; preferred for repeat-row-safe edits. |
| `GET /workout/<path>` | Xert JS + plugin | Called | Partial | Used for Designer form/CSRF and readback. |
| `POST /workout/<path>` | Xert JS + plugin | Called for known edits | Partial | Calculate/save Designer changes; only known row-edit shapes are characterized. |
| `DELETE /workout/<path>` | Plugin | Not called intentionally | No | Destructive. Implemented but should only be tested on a disposable workout with explicit confirmation. |
| `GET /workout/convert/<path>?<format>=true` | Xert JS | Not called | No | Downloads converted workout blob. |
| `GET /workout-players` | Xert JS | Not called | No | Workout-player state/list. |
| `POST /workout/set-workout-player-override` | Xert JS | Not called | No | Mutating player setting. |
| `GET /my-fitness/fitness_signature` | Xert JS | Not called | No | Profile/signature edit endpoint; plugin reads other embedded sources instead. |
| `GET/POST /my-fitness/training_load` | Xert JS | Not called | No | Training load edit/read endpoint; do not assume response shape. |
| `GET/POST /my-fitness/time_constants` | Xert JS | Not called | No | Time-constant edit/read endpoint; plugin uses `/profile/settings` embedded `ir_params`. |
| `GET/POST /my-fitness/training_responsiveness` | Xert JS | Not called | No | Training responsiveness settings. |
| `GET/POST /my-fitness/xpmc_settings` | Xert JS | Not called | No | Combined XPMC/settings save endpoint. |
| `GET /my-fitness/getProgram` and related weekly-hours/program endpoints | Xert JS | Not called | No | Includes continuous/challenge program variants; response shape unknown. |
| `GET /my-fitness/activity_statistics` and related statistics endpoints | Xert HTML/JS | Not called | No | Statistics panels; not used in recommendation workflow. |
| `GET /activities/<path>/map` | Xert JS | Not called | No | Different from the `map_url` image field on activity list rows. |
| `POST /activities/unlink-duplicate` | Xert JS | Not called intentionally | No | Mutating activity endpoint. |
| `GET /activities/download/<path>` | Xert JS | Not called | No | Activity download blob endpoint. |
| Session endpoints under `/sessions`, `/session-instance`, `/session-template` | Xert JS | Not called | No | Group/session feature surface; not used by current training advice flow. |
| `GET /oauth/activity`, `GET /oauth/activity/<path>` | Plugin/OAuth API | Called | Yes | Activity list/detail with XSS split and optional session data. |
| `GET /oauth/workouts`, `GET /oauth/workout/<path>` | Plugin/OAuth API | Called | Partial | OAuth workout resolver is useful, but some slope variants fail with HTTP 500. |
| `GET /oauth/training_info` | Plugin/OAuth API | Not recently characterized | Unknown/partial | CLI exposes it, but we have not used it as a trusted readiness source. |
| `GET /profile/settings` | Plugin web extraction | Called | Yes | Source for embedded `ir_params`. |
| `GET /calendar/get-notes`, `POST /calendar/save-notes` | Plugin | Called | Yes for known note use | Notes are separate from forecast/training plan fields. |

## Activity Dates

`activities <start-YYYY-MM-DD> <end-YYYY-MM-DD>` treats both arguments as an inclusive local-date range on the machine running the command. The plugin converts local start-of-day and local end-of-day to Unix timestamps before calling Xert's `/oauth/activity` endpoint.

Do not ask the language model to manually widen or shift these date arguments for time zone handling. If a user asks for "today", "this week", or another calendar period, pass the intended local calendar dates to the CLI.

## Recovery Model

`recovery-model` logs in to Xert web, reads `/my-fitness` `trainingAdvice` and `trainingPlan`, reads `/profile/settings` `ir_params`, then calculates low/high/peak recovery locally from those model inputs.

In a normalized `readiness-input` payload, `recovery.recovery_hours` is the
recovery state at the top-level `source_time_local`. This remains true when the
command receives `--advice-at`. The raw value is retained for auditability, and
the payload additionally includes `recovery.recovery_hours_at_advice_time` with
the low/high/peak values projected to the requested advice time. The projection
subtracts elapsed time from the raw recovery hours and assumes no intervening
training.

Do not use per-activity `summary.progression.rl` as current Recovery Load.

`trainingAdvice.targetXSS` is Xert's current or planned-time target /
recommended XSS dose for the training advice context. The normalized
`readiness-input` payload exposes it as `training_advice.target_xss`, mapping
`xlss` to `low`, `xhss` to `high`, and `xpss` to `peak`. It reflects activities
Xert has already accounted for. It is not a recovery target, historical activity
load, workout-library XSS, `workout_capacity`, or a repo-calculated
remaining-dose field.

Use `/my-fitness` as the fast source for advice "now". Use
`/recommended-training` when advice is needed for a planned time. Xert's UI
sends the selected time minus one second as the `date` query parameter, and the
plugin should mirror that behavior through `readiness-input --advice-at`. Use
planned-time advice at minimum when the planned time is on another date, or when
the planned time is later than now and current `/my-fitness` state is not fresh.
The `training_advice` object can include `targetXSS`, `remainingXSS`,
`completedXSS`, `originalTargetXSS`, `training_advice_as_of`, availability and
daily-goal fields.

For planned-time advice, use `/recommended-training` with `recent=true` unless
the caller explicitly wants activity suggestions that can repeat activities more
than roughly three months old. Use `additional=false` for the primary training
advice dose; `additional=true` is for allowing extra/additional training and
should not be the default for normal workout recommendations.

Express Xert recovery days as hours when answering users. `0` recovery hours is
Xert's fresh threshold; negative recovery hours mean the athlete is on the fresh
side of that threshold for the relevant system. If high or peak recovery time is
`0` or negative, interpret Xert as saying the athlete is ready for work over TP
in that system. Xert may then choose high and/or peak XSS as part of the target
when it thinks that is the day's needed stimulus; this target is guidance, not a
hard maximum or minimum.

Interpret components by system:

- `lo`: low XSS / any cycling activity
- `hi`: high XSS / work over threshold power
- `pk`: peak XSS / peak-power-relevant work over threshold power

High and peak XSS usually accumulate as small absolute numbers compared with
low XSS, even in workouts whose purpose is clearly VO2Max or other over-TP
work. Do not interpret a workout or training-advice target by the percentage of
total XSS that is high/peak. Instead compare the absolute high and peak XSS
against known workout-library profiles, recent completed workouts, and the
intended stimulus. A target with only a few high XSS can still represent a real
over-TP component; a very low peak value can indicate that the target is not
calling for much peak-power-specific work even if high XSS is present.

Low, high, and peak XSS are additive system loads, not mutually exclusive
replacement buckets. During work above TP, the athlete can still receive full
low-XSS credit for the period while also accumulating high and/or peak XSS on
top. Therefore, a workout that is mostly low XSS by total share can still contain
meaningful over-TP work. Do not say high/peak is "instead of" low, and do not
use the dominance of low XSS as evidence that the session lacks intensity.

A useful interpretation model is: from easy riding up toward 100% of TP, low XSS
accumulates at an increasing rate and is effectively maxed at TP. Above TP, low
XSS continues at that capped/maximal rate for the duration, while high and peak
XSS are additional system loads layered on top. Treat this as an interpretation
model for reasoning and communication, not as a claim about Xert's exact private
formula.

This interpretation can be checked empirically through Xert Workout Designer
`calculate`: create or modify controlled workout rows at different percentages
of TP, run calculate, and compare the returned low/high/peak XSS. Use
non-persistent calculate/dry-run flows for this kind of probing; do not save
synthetic workouts unless the user explicitly asks. Use
`python3 -B plugins/xert/scripts/xert_cli.py workout-calculate --duration 10:00 --power-type relative_ftp --power 120`
for a new unsaved synthetic calculation. The CLI can also validate edits to an
existing workout with `workout-update --dry-run`, which submits `calculate`
instead of `save`.

Treat low recovery as the first readiness gate. If low recovery hours are still positive, Xert does not indicate freshness for more cycling load.

Workout capacity is calculated against the next planned Xert workout. It is not a generic independent estimate of all absorbable training.

Interpret workout capacity as how much training can be done now while still
being just fresh before the next planned Xert workout. Choose the relevant
capacity system by what must be trainable next: if the athlete wants to train
over TP tomorrow, keep today's over-TP work within `workout_capacity.high` and
`workout_capacity.peak`; if the relevant next-day work is low/aerobic, keep
today's total low-system load within `workout_capacity.low`.

Do not infer poor high/peak recovery from low `workout_capacity.high` or
`workout_capacity.peak` alone. Use `recovery_hours.high` and
`recovery_hours.peak` for high/peak recovery state: negative values mean the
athlete is already on the fresh side of Xert's threshold for that system. Low
high/peak workout capacity can simply mean there is little room for extra work
while still arriving just fresh for the next planned Xert workout.

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

Workout Designer can represent repeated blocks inside one row rather than as
one row per visible interval. Preserve that model when editing:

- `interval_count` is the number of repeats for that row.
- `rib_duration` is the recovery-in-between duration inserted between repeats.
- `rib_power` is the recovery-in-between power target.
- For a row with `interval_count=2`, one `rib_duration` separates the two
  repeated work intervals. A separate following row may represent an additional
  interval in the same named set.
- Endurance repeats can be represented the same way, for example one
  `Endurance` row with `interval_count=4`, `duration=15:00`, and `power=205`
  instead of four copied rows.

When modifying repeated workouts, update repeat-row fields when possible. If a
new row is needed, append a minimal editable row with a new `sequence` and blank
`DT_RowId`. Validate with `calculate` before saving.

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

`training-forecast` can return `{}` even when a workout path is still editable
through Workout Designer. Do not rely on forecast alone to identify or modify
the active workout.

Workout deletion uses `DELETE /workout/<path>` with `X-Requested-With: XMLHttpRequest` on an authenticated web session. Treat it as destructive: require explicit user confirmation and verify afterwards.

## Recommended Training

`recommended-training` is useful for planned-time training advice and
recommendation / ranking context. The payload can include both workouts and
activities. When
choosing a workout, filter `exercises` by `exerciseType == "Workout"` first,
then rank candidates using the caller's goal, XSS split, duration, focus,
suitability, difficulty and any caller-provided preferences.

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

For Xert activity list rows, `map_url` is a direct ready-made PNG map image for
the activity, for example under `https://www.xertonline.com/assets/images/...`.
When a route recommendation is based on a prior outdoor Xert activity, use this
as the map attachment. The Xert `path` is the activity identifier for
`https://www.xertonline.com/activity/<path>`. Do not confuse these with
Intervals.icu route-helper `url` fields, which are Intervals activity links.
