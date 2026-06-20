---
name: training-analysis
description: Use when working in the training-ai repo on workout analyses, activity comparisons, readiness or "can/should I train?" questions, outdoor ride recommendations, weather-informed training decisions, planned workout summaries, cross-source endurance analysis, or interpreting saved activity data with repo helpers. This skill owns repo-level training analysis, local persistence, readiness composition, and chat output; source-specific field semantics remain with the Xert, Garmin Connect, EatMyRide, Intervals.icu, and Yr plugin skills.
---

# Training Analysis

Use this skill as the repo-level operating manual for training analysis. Keep source-specific API access, field meaning, and write-safety in the relevant source skill; use this skill to compose those source-aware inputs into analysis, recommendations, and chat answers.

## Boundaries

- Apply user-specific preferences from `PREFERENCES.md` when they are relevant.
- Use `plugins/xert/skills/xert/SKILL.md` for live Xert access, Xert field interpretation, API quirks, recovery/difficulty semantics, workout writes, and write safety.
- Use `plugins/garmin-connect/skills/garmin-connect/SKILL.md` for Garmin Connect access, Garmin readiness semantics, Body Battery, Training Readiness, HRV, stress, sleep, Firstbeat metrics, activity details, and write/read safety.
- Use `plugins/eatmyride/skills/eatmyride/SKILL.md` for EatMyRide activity, fueling, glycogen, food plan, product, energy, and write-safety semantics.
- Use `plugins/intervals-icu/skills/intervals-icu/SKILL.md` for Intervals.icu API access, field interpretation, streams, intervals, wellness fields, subjective feel/RPE fields, and write safety.
- Use `plugins/yr/skills/yr/SKILL.md` for Yr/MET Norway Locationforecast access, forecast source semantics, field interpretation, and live weather.
- Treat local persistence, cached artifacts, helper scripts, readiness composition, cross-source analysis, and final recommendations as this repo's responsibility.
- Prefer UTC for internal time calculations and stored/comparable timestamps. Convert to the machine's local timezone only when parsing or displaying user-facing local inputs, matching human calendar days, or calling APIs that explicitly require local dates.

## Output Defaults

- Answer analyses and comparisons in chat by default.
- Do not create standalone report files unless the user explicitly asks for a file.
- Treat `outputs/` as temporary local output for downloaded activities, streams, scratch outputs, helper artifacts, and generated reports when explicitly requested.
- Present planned workouts, forecasts, and recommendations in readable training language. Avoid raw JSON terms and code blocks for short workout-plan summaries unless the user asks for raw values.
- Translate technical forecast fields into plain language, for example "utendørs sykling", "planlagt/forecastet", "høyintensiv treningsdag", and "arbeid over terskel".
- For Xert summaries, always include numeric difficulty because the text difficulty rating is too coarse on its own.

## Activity Analysis

- Before analyzing a named activity, route, race, or event, verify that the
  selected activity actually matches the requested name.
- For explicitly saved activity inspection, prefer reusable helpers in `scripts/analysis.py` and `scripts/activity_inspect.py` over one-off Python snippets.
- Treat "latest" as a source-selection question, not as an inspection ref. For the latest workout or activity, start by running `python3 -B scripts/fetch_latest_activity.py`; it fetches and saves the newest Intervals.icu source activity and prints the saved activity directory to pass to `activity_inspect.py`.
- If you have an Intervals.icu activity id but no saved local activity package, first use the Intervals.icu source workflow to create one. Then pass the resulting local `activity_dir` to `activity_inspect.py`. Do not make repo analysis helpers call Intervals.icu APIs directly.
- Start inspection with `python3 -B scripts/activity_inspect.py <saved-activity-ref> --brief`; the helper writes JSON to `outputs/activity-inspect/` by default and prints the output path.
- For mixed, unclear, or unknown structured indoor workouts, add `--auto-blocks` on the first pass. It detects sustained stable power plateaus from the stream itself, which is useful for sessions such as `VT2 3x28 min + VT1 30 min` where not every meaningful block is a saved `WORK` interval.
- Use explicit target or threshold detection when the intended work target is known, for example `--target 300 --tolerance 12 --min-block 10m` or `--threshold 190 --min-block 3m`. Prefer explicit target detection over `--auto-blocks` when the user asks about a named interval structure and the target is known.
- The `--brief` output includes key efforts, peaks, the hardest block, work blocks, recoveries, post-work continuation blocks, and first-pass HR recovery context for chat analysis.
- Treat `beta_stability` in `--brief` as debug/decision-support only. It compares inferred intent against response stability, for example whether a VT1-intended block stays controlled or a VT2-intended set becomes high-cost. Do not present its verdict as a threshold diagnosis.
- Use `beta_stability` for structured indoor workouts only, unless the user explicitly asks to inspect outdoor behavior as a development/debug exercise. For outdoor rides, route/race efforts, and other variable-power sessions, describe any `beta_stability` output as experimental development signal only, not as a normal training interpretation.
- For VO2Max-named indoor workouts, inspect `beta_vo2` in `--brief` as a separate beta/debug section. It is for short-rep repeatability and whether the stimulus looks hard enough: rep count, power falloff, end-of-rep HR rise/peak, VE/BR peaks, SmO2 lows/desaturation, and recovery between reps. Do not force VO2Max workouts into `beta_stability`'s VT1/VT2 verdicts.
- For tabular summaries of `--brief` beta/debug output, prefer `beta_summary` over counting `beta_stability.blocks` directly. For VO2Max rows, use `beta_summary.unit_count` or `beta_vo2.rep_count` as the rep count. For mixed sessions such as `VT2 + VT1`, keep `beta_summary.parts` as separate parts instead of collapsing them into one block count.
- For normal workout analyses, include Xert activity-summary context when it is available from the Xert source layer. Let the Xert source skill own how the activity is resolved, fetched, and interpreted; this repo-level skill only composes the normalized Xert perspective into the analysis.
- Treat Xert activity context as the preferred source perspective for Xert-specific load semantics such as XSS split, XEP, focus, specificity, freshness/status, fitness signature, and numeric difficulty.
- For normal workout analyses, include Garmin/Firstbeat activity-summary context when it is available from the Garmin source layer. Let the Garmin Connect source skill own how the activity is resolved and fetched; this repo-level skill only composes the normalized Garmin perspective into the analysis.
- Treat Garmin's activity summary as an additional source perspective, not as a replacement for stream-based interval analysis or preferred Xert load semantics. Integrate Training Effect, activity training load, TSS/IF, stamina, performance condition, and Garmin normalized power when present; translate Garmin's Training Effect label/message into readable training language and call out when Garmin data is missing or lacks expected fields.
- Use `--auto-blocks` conservatively for mixed/unknown structured indoor sessions; it filters for stable raw power so variable outdoor riding is not mislabeled as ERG-like work blocks. Do not use outdoor `WORK` segments as evidence of VT1/VT2 intent unless the activity name, workout structure, or explicit user context establishes that intent.
- Use `--compact` or full output when detailed per-sensor or per-block JSON is needed. Use `--no-intervals` when Intervals.icu intervals are not needed. Use `--output <path>` for a specific artifact path and `--stdout` only when full terminal JSON is genuinely wanted.
- For workout analyses, exclude warm-up and cooldown from interval metrics. Prefer detecting the actual work segment from the power trace rather than using the full stream.
- Do not limit analysis to power and heart rate. Use the sensor profile from `PREFERENCES.md`, inspect available streams per activity, and use relevant streams when present.
- For any sensor stream, handle min, max, average, and drift carefully when the measurement window has longer continuous gaps, repeated dropouts, or clearly unusable value blocks. An occasional missing point is acceptable; report meaningful data-quality limits instead of treating incomplete data as clean.
- For heart/cardiovascular data, derive W/HR and HR drift where useful.
- For respiratory data, analyze averages and drift over workouts or intervals, especially BR drift, VE drift, VT drift, and whether rising VE comes from higher BR or deeper VT.
- When power varies materially inside a block, prefer the `*_per_watt_drift_pct` fields in `--brief` as the cost-drift signal for HR, BR, and VE. Raw VE/BR/HR drift can be misleading on outdoor climbs or variable-power blocks because ventilation may fall while power falls more.
- For short hard drags, prefer 5-second rolling VE peak inside the rep and shortly after it over mean VE alone.
- For muscle oxygenation, analyze min, max, and drift over intervals or workout, including SmO2 desaturation, recovery re-oxygenation, THb trend/drift, and how local muscle oxygenation aligns with power, HR, and respiratory drift.
- For recovery re-oxygenation, quantify both the SmO2 rise during each recovery and the peak SmO2 reached in that recovery.
- Ask how the session felt when it is natural after interpreting sensor/load data. Do not ask again if feel/RPE is already in the conversation or on the activity.
- If the user wants subjective response saved to Intervals.icu, use the update helper and prefer Intervals.icu activity fields for feel/RPE instead of burying it only in chat.

## Source Priority

- Use the data source priority from `PREFERENCES.md` for activity-load context unless the user overrides it.
- Treat Intervals.icu as a copy/aggregation layer for data that often originates elsewhere.
- Prefer original-source plugins for source-specific signals when available: Xert for XSS/recovery/difficulty, Garmin Connect for Garmin/Firstbeat activity and readiness context, EatMyRide for fueling/glycogen.
- Use Intervals.icu for live activity metadata, interval summaries, wellness fields, and stream exports when those are the best available inputs.
- Do not use Intervals.icu copies as a replacement for better original-source data. If Garmin Connect is available, prefer Garmin for Garmin Training Readiness, Body Battery, HRV, stress, sleep, and Garmin/Firstbeat activity metrics.
- For EatMyRide glycogen/fueling plots from an explicitly supplied JSON file, use `python3 -B scripts/plot_eatmyride_fueling.py <activity-dir>`.
- For Xert xfair report overlays, use `python3 -B scripts/overlay_xert_report.py --activity-dir <activity-dir> --xert-path <xert-activity-path>`. Supply the Xert path explicitly from live/source-aware context.

## Readiness

- For "can/should I train?" questions, prefer `python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD>` after refreshing relevant inputs when appropriate.
- Before same-day or next-morning training recommendations, refresh volatile inputs when possible, including live Garmin Connect day/recent data for Body Battery, stress, readiness, and current Xert recovery data.
- Obtain Xert readiness context live through the Xert plugin, translate it to the normalized readiness JSON shape, and pass that file with `--xert-json <file>`. Do not pass raw Xert API/plugin payloads to `readiness_snapshot.py`.
- Pass Garmin Connect day data as an explicit JSON file with `--garmin-json <file>`.
- Add `--now <local time>` and `--planned-at <local time>` for same-day or next-morning planning.
- Treat script output as decision inputs, not the conclusion. The chat answer should still weigh normal training load, goals, planned future sessions, and user-provided body feel.
- For training recommendations, account for what the user is training for and
  how much time remains until that target. Choose the session type by combining
  target specificity and time horizon with readiness, recent load, weather and
  user constraints. If the target or time horizon is missing and materially
  affects the recommendation, ask for it or state the assumption.
- Prefer a transparent combination of recent training load plus wellness fields actually present in source inputs: HRV, resting HR, sleep duration, and sleep score.
- Treat Garmin aggregated readiness as a second opinion, not as a replacement for Xert/Intervals load or actual workout sensor response.
- Treat Garmin recovery time/readiness as live, sync-sensitive physiological estimates. Interpret Garmin recovery time as guidance for readiness for the next hard workout, not a blanket restriction on easy or moderate training.
- When Garmin recovery time is available for a planned future session, project remaining recovery time forward to the planned session time, assuming no intervening training unless known.
- Use positive remaining Garmin recovery to scale confidence and ambition based on planned intensity, Xert recovery, wellness signals, and actual workout response.
- When fetching Garmin same-day time series such as heart rate, stress, or Body Battery, check whether expected data is present and how recent the newest datapoint is. If data is missing, incomplete, or stale enough to affect the decision, explicitly encourage syncing Garmin/the watch before relying on those signals.

## Garmin Analysis Notes

- For activity summaries, use Garmin/Firstbeat activity training load, TSS/IF, aerobic and anaerobic training effect, training effect label/message, stamina begin/end/min, performance condition trend, calories, and Garmin normalized power when available.
- For readiness summaries, use Garmin Training Readiness, HRV status/baseline, Body Battery charge/drain, daily stress, sleep details, resting HR, and training status when available.
- For stress, inspect post-workout stress instead of relying only on daily average stress. Continuous orange/high stress after the workout suggests the body is still actively working and should reduce same-day training ambition.
- For post-workout heart rate, use the lowest post-workout HR value and especially the lowest sustained 5-minute post-workout HR average. Do not base interpretation on latest HR or average post-workout HR.
- If sleep occurred after the previous workout, separate the immediate post-workout window from the overnight period. Use post-workout HR/stress mainly for the evening after the workout, and use sleep, HRV, resting HR, and Body Battery as stronger morning-readiness signals.
- Compare post-workout HR lows with the user's recent restingHR baseline. If sustained post-workout HR remains elevated before sleep and never drops close to baseline, treat that as evidence the system was still working and reduce ambition, especially for same-day second sessions or next-morning intensity.
- Treat Garmin performance condition as a secondary trend signal. It depends on power meter/source and is often less comparable between indoor and outdoor rides because outdoor rides involve variable power, riding position, more core-muscle activation, terrain, coasting/stops, and environmental conditions.

## Weather

- For weather forecasts, use the repo-local Yr skill when the preferred source is Yr/MET Norway.
- Fetch weather live; do not use or create local Yr weather files.
- Avoid ad hoc weather websites unless the preferred source is unavailable or the user explicitly asks for another source.
- For outdoor ride recommendations, fetch one or more relevant forecast points for the planned ride area or route corridor rather than relying on a single point forecast.
- Use fresh live data for same-day and next-day training-weather decisions.
