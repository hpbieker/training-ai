# Project Instructions

- Apply user-specific preferences from `PREFERENCES.md` when they are relevant.
- For EatMyRide-specific source semantics, use the repo-local plugin skill at
  `plugins/eatmyride/skills/eatmyride/SKILL.md`. The plugin owns field
  interpretation and write-safety rules; this repo still owns local persistence and
  cross-source training analysis.
- Fetch EatMyRide data live through the plugin whenever EatMyRide context is
  needed for current analysis or recommendations.
- For Xert-specific source semantics, use the repo-local plugin skill at
  `plugins/xert/skills/xert/SKILL.md`. The plugin owns live Xert access, field
  interpretation, API quirks and write-safety rules; this repo still owns local
  persistence, readiness composition and cross-source training analysis.
- Fetch Xert data live through the plugin for current analysis, summaries,
  readiness or recommendations, and pass normalized source-aware output into
  repo-level analysis helpers.
- For Xert xfair report overlays, use
  `python3 -B scripts/overlay_xert_report.py --activity-dir <activity-dir> --xert-path <xert-activity-path>`.
  The Xert path must be supplied explicitly from live/source-aware context.
- For Yr/MET Norway-specific source semantics, use the repo-local plugin skill
  at `plugins/yr/skills/yr/SKILL.md`. The plugin owns Locationforecast field
  interpretation, API quirks and live CLI access; this repo still owns
  cross-source training analysis.
- For Garmin Connect-specific source semantics, use the repo-local plugin skill
  at `plugins/garmin-connect/skills/garmin-connect/SKILL.md`.
- For Intervals.icu-specific source semantics, use the repo-local plugin skill
  at `plugins/intervals-icu/skills/intervals-icu/SKILL.md`. The plugin owns
  Intervals.icu API access, field interpretation and write-safety rules; this
  repo still owns readiness composition and cross-source training analysis.
- For EatMyRide glycogen/fueling plots from an explicitly supplied JSON file,
  use `python3 -B scripts/plot_eatmyride_fueling.py <activity-dir>`.
- When the user asks for analyses or comparisons, answer in chat by default.
- Do not create standalone report files for analyses or comparisons unless the user explicitly asks for a file.
- Treat `outputs/` as temporary local output. It is ignored by git and can contain downloaded activities, streams, scratch outputs and generated reports when explicitly requested.
- For workout analyses, exclude warm-up and cooldown from interval metrics. Prefer detecting the actual work segment from the power trace rather than using the full stream.
- For workout analyses, ask the user how the session felt when it is natural to do so, especially after interpreting sensor/load data. Do not ask again if the user has already provided feel/RPE in the conversation or it is already present on the activity. If the user wants the subjective response saved to Intervals.icu, use the update helper and prefer Intervals.icu's activity fields for feel/RPE when available rather than burying the information only in chat.
- For explicitly saved activity inspection, prefer reusable helpers in `scripts/analysis.py` and `scripts/activity_inspect.py` over one-off Python snippets. Use `python3 -B scripts/activity_inspect.py <activity-ref> --brief` for a first-pass chat-analysis artifact; the helper writes JSON to `outputs/activity-inspect/` by default and prints the output path. Add target/threshold detection such as `--target 300 --tolerance 12 --min-block 10m` or `--threshold 190 --min-block 3m` when identifying work blocks from power. Use `--compact` or full output when detailed per-sensor/per-block JSON is needed, `--no-intervals` when Intervals.icu intervals are not needed, `--output <path>` for a specific artifact path, and `--stdout` only when full terminal JSON is genuinely wanted.
- Do not limit training analysis to power and heart rate. Use the sensor profile from `PREFERENCES.md`, check available streams per activity and use the relevant ones when present:
  - For any sensor stream, be careful with min, max, average and drift calculations when the relevant measurement window has longer continuous gaps, repeated dropouts or clearly unusable value blocks. An occasional missing point is acceptable and should not by itself invalidate the aggregate. Report meaningful data-quality limitations rather than treating incomplete data as a clean continuous signal.
  - For heart/cardiovascular data, derive W/HR and HR drift where useful.
  - For respiratory data, analyze both averages and drift over the workout/intervals, especially BR drift, VE drift, VT drift, and whether rising VE comes from higher BR or deeper VT.
  - For muscle oxygenation data, analyze min, max and drift over intervals/workout, including SmO2 desaturation, re-oxygenation in recoveries, THb trend/drift, and how local muscle oxygenation changes align with power, HR and respiratory drift. For re-oxygenation in recoveries, quantify both how much SmO2 rises during each recovery and the peak SmO2 reached in that recovery.
- Use the data source priority from `PREFERENCES.md` for activity-load context unless the user overrides it for a specific analysis. For Xert summaries, always include numeric difficulty because the text difficulty rating is useful but too coarse on its own.
- For weather forecasts, use the repo-local `yr` plugin skill when the preferred
  source is Yr/MET Norway. Fetch weather live; do not use or create local Yr
  weather files. Avoid ad hoc weather websites unless the preferred source is
  unavailable or the user explicitly asks for another source. For outdoor ride
  recommendations, fetch one or more relevant forecast points for the planned
  ride area or route corridor rather than relying on a single point forecast.
  Use fresh live data for same-day and next-day training-weather decisions.
- For “can/should I train?” questions, prefer `python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD>` after refreshing relevant inputs when appropriate. Pass Garmin Connect day data as an explicit JSON file with `--garmin-json <file>` and selected Xert readiness fields as one normalized JSON file with `--xert-json <file>`; do not pass raw Xert API/plugin payloads. Add `--now <local time>` and `--planned-at <local time>` for same-day or next-morning planning. Treat the script output as decision inputs, not a conclusion: the chat answer should still weigh the user's normal training load, goals, planned future sessions and any user-provided body feel.
- Before same-day or next-morning training recommendations, refresh volatile inputs when possible, including live Garmin Connect day/recent data for Body Battery/stress/readiness and current Xert recovery data. Obtain Xert readiness context live through the Xert plugin, translate it to the normalized readiness JSON shape, then pass that file into `scripts/readiness_snapshot.py`; the readiness script should not call plugins directly or interpret raw Xert fields.
- For readiness recommendations, prefer a transparent combination of recent
  training load plus wellness fields actually present in the provided source
  inputs: HRV, resting HR, sleep duration and sleep score.
- When presenting planned workouts or forecasts, use readable training language rather than raw JSON terms. Do not use code blocks/text boxes for short workout-plan summaries unless the user explicitly asks for raw values. Translate technical forecast fields into plain language, for example "utendørs sykling", "planlagt/forecastet", "høyintensiv treningsdag", and "arbeid over terskel".
- Prefer UTC for internal time calculations and stored/comparable timestamps. Convert to the machine's local timezone at the boundaries: when parsing user-facing local inputs, displaying times in chat, matching human calendar days, or calling APIs that explicitly require local dates. Avoid mixing naive local datetimes with UTC-aware datetimes inside calculation logic.

## Intervals.icu

- Use the Intervals.icu plugin skill for Intervals.icu API access, source
  semantics, field interpretation and write-safety rules.
- Fetch Intervals.icu activity, stream, interval and wellness context live
  through the plugin by default. Save artifacts only when the user explicitly
  asks for a file or a downstream repo helper requires one.
- Treat Intervals.icu as a copy/aggregation layer for data that often
  originates in other systems. Prefer live original-source plugins when they
  are available for source-specific signals: Xert for XSS/recovery/difficulty,
  Garmin Connect for Garmin/Firstbeat activity and readiness context, and
  EatMyRide for fueling/glycogen context.
- Use Intervals.icu for live activity metadata, interval summaries, wellness
  fields and stream exports when those are the best available inputs, but do
  not use Intervals.icu copies as a replacement for better original-source
  data. In particular, if Garmin Connect is available, prefer Garmin for Garmin
  Training Readiness, Body Battery, HRV, stress, sleep and Garmin/Firstbeat
  activity metrics.
- This repo owns saved-file inspection, workout analysis, readiness
  composition and cross-source training analysis. The plugin owns how
  Intervals.icu fields and writes should be interpreted.

## Garmin Connect

- Use Garmin Connect as extra live activity and readiness context according to
  the configured data-source priority.
- For current-day wellness/readiness, prefer Garmin Connect for Garmin-specific
  fields when Garmin data is available. Training Readiness, Body Battery, HRV,
  stress, heart rate and sleep can change through the day after device syncs,
  and Garmin can expose useful time series for fields such as stress, heart
  rate and Body Battery.
- For activity analyses, fetch Garmin activity details through the Garmin
  Connect plugin when available. Garmin-unique or Garmin-most-useful activity
  context is typically Training Effect, Stamina and Garmin/Firstbeat Training
  Load.
- Garmin can in some cases expose more sensor time series than sources such as Strava and Xert, but Intervals.icu typically has all activity time series needed for analysis.
- For activity summaries, use Garmin/Firstbeat activity training load, TSS/IF, aerobic and anaerobic training effect, training effect label/message, stamina begin/end/min, performance condition trend, calories and Garmin normalized power when available.
- For readiness summaries, use Garmin Training Readiness, HRV status/baseline, Body Battery charge/drain, daily stress, sleep details, resting HR and training status when available.
- Treat Garmin aggregated readiness as a second opinion, not as a replacement for Xert/Intervals load or actual workout sensor response.
- Treat Garmin recovery time/readiness as a live physiological estimate that can change after watch sync based on stress, HRV, sleep, activity and other signals. Garmin projections are therefore provisional and refresh/sync-sensitive.
- Interpret Garmin recovery time as guidance for readiness for the next hard workout, not as a blanket restriction on easy or moderate training.
- When Garmin recovery time is available for a planned future session, project the remaining recovery time forward to the planned session time, assuming no intervening training unless known. Use positive remaining Garmin recovery to scale confidence and ambition based on planned intensity, Xert recovery, wellness signals and actual workout response.
- When fetching Garmin time-series data for same-day readiness (`heart_rate`, `stress`, Body Battery, etc.), check whether the expected Garmin data is present and how recent the newest returned datapoint is. Garmin Connect only has data that has synced from the watch/head unit. If Garmin data is missing, incomplete, or stale enough to affect a "can I train now?" decision, explicitly encourage the user to sync Garmin/the watch before relying on those signals.
- For stress, inspect post-workout stress instead of relying only on daily average stress. Continuous orange/high stress after the workout suggests the body is still actively working and should reduce same-day training ambition.
- For post-workout heart rate, use the lowest post-workout HR value and especially the lowest sustained 5-minute post-workout HR average. Do not base the interpretation on latest HR or average post-workout HR, since those are too sensitive to movement and timing.
- If sleep occurred after the previous workout, separate the immediate post-workout window from the overnight period. Use post-workout HR/stress mainly for the evening after the workout, and use sleep, HRV, resting HR and Body Battery as the stronger morning-readiness signals.
- Compare post-workout HR lows with the user's recent restingHR baseline. If sustained post-workout HR remains elevated before sleep and never drops close to baseline, treat that as evidence that the system was still working and reduce training ambition, especially for same-day second sessions or next-morning intensity.
- Treat Garmin performance condition as a secondary trend signal. It depends on power meter/source and is often less comparable between indoor and outdoor rides because outdoor rides involve variable power, riding position, more core-muscle activation, terrain, coasting/stops and environmental conditions.
