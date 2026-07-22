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
- When a source skill says to read `references/...`, resolve that path relative
  to the source skill's own `SKILL.md` directory, for example
  `plugins/xert/skills/xert/references/field-semantics.md`, not relative to
  the plugin's broader `skills/` directory.
- Prefer UTC for internal time calculations and stored/comparable timestamps. Convert to the machine's local timezone only when parsing or displaying user-facing local inputs, matching human calendar days, or calling APIs that explicitly require local dates.

## Output Defaults

- Answer analyses and comparisons in chat by default.
- Do not create standalone report files unless the user explicitly asks for a file.
- Treat `outputs/` as temporary local output for downloaded activities, streams, scratch outputs, helper artifacts, and generated reports when explicitly requested.
- Present planned workouts, forecasts, and recommendations in readable training language. Avoid raw JSON terms and code blocks for short workout-plan summaries unless the user asks for raw values.
- Do not link to local JSON packets, output files, or helper artifacts in the chat recommendation unless the user explicitly asks for the underlying file. Use those artifacts only as background inputs. For outdoor route/session recommendations, it is useful to include a direct Intervals.icu activity link when the route candidate came from a saved activity; present it as a route/intensity reference, not as something the user needs to inspect.
- For training recommendations, include concrete options only for modalities
  that are actually available at the resolved location/destination. When both
  indoor and outdoor cycling are available, include both and state which option
  is preferred and why. When a modality is unavailable, do not fetch or present
  a workout/route for it; mention the unavailable reason briefly only when it is
  useful context.
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
- The `--brief` output includes key efforts, peaks, the hardest block, work blocks, recoveries, post-work continuation blocks, first-pass HR recovery context, for qualifying outdoor endurance rides an `outdoor_vt1_pacing` section, and for qualifying pure indoor VT1 trainer rides an `indoor_vt1_quality` section.
- For outdoor endurance/VT1-like rides, inspect `outdoor_vt1_pacing` before judging whether the session was controlled. It summarizes 30s/60s power-cap compliance, pedaling-normalized power distribution, climb detection, climb vs non-climb cost, post-pause reset, matched-power drift, split `execution_score`/`response_score`/`session_value_score`, experimental power-bin physiology, late-session control, traffic/restart spikes, and a compact verdict. The caller should apply user preferences and pass the working anchor with `--vt1-watts <watts>`; the helper does not read `PREFERENCES.md` directly. Caps are calculated from that anchor plus `10/20/30/50/90 W`.
- Treat `outdoor_vt1_pacing.experimental_metrics` as candidate signals while we learn whether they add value. Use best continuous VT1 blocks to find the cleanest 60/90/120/150-minute endurance window inside an otherwise messy outdoor ride, power-bin physiology to see sensor cost across power ranges, late-session control to check whether caps/drift worsen toward the end, traffic/restart spikes to separate stop-light surges from sustained pacing errors, `smo2_response` to test whether muscle oxygenation adds useful VT1 discrimination, and `spike_aftereffects` to test whether power spikes have measurable HR/VE/BR/SmO2 cost. Do not let these override the main score unless the pattern is clear.
- Use `--outdoor-vt1` to force this section for a brief activity inspection, and `--no-auto-outdoor-vt1` to suppress the automatic outdoor pacing section when it would distract from another analysis goal.
- For pure indoor VT1 trainer rides, inspect `indoor_vt1_quality` before rating the workout. It is a compact subset of the outdoor VT1 logic without terrain: 30s/60s cap compliance, time around the caller-provided VT1 anchor, first/middle/final-third stability, HR/W, VE/W, BR/W, core-temperature cost, a duration-aware A/B/C-style rating, limiter hints such as `stable`, `ventilation_drift`, `heat_cost`, or `power_above_vt1`, and separate `watch_notes` for small drift/heat signals that should be mentioned without making an otherwise controlled A ride sound limited. The helper auto-adds it only for indoor/trainer activities whose name looks like pure `VT1`, not mixed `VT2 + VT1` or VO2 sessions. Use `--indoor-vt1` to force it and `--no-auto-indoor-vt1` to suppress it. The caller should apply user preferences and pass the working anchor with `--vt1-watts <watts>`; the helper does not read `PREFERENCES.md` directly.
- For VT2/threshold-like blocks, inspect `vt2_quality` in `--brief` output when present. It is separate from VT1 scoring and reports `execution_score`, `response_score`, `heat_adjusted_response_score`, `recovery_score`, limiter hints, and verdicts such as `controlled_vt2`, `controlled_high_cost_vt2`, `heat_limited_controlled_vt2`, `near_upper_control_limit`, or `variable_or_off_target_vt2`. For indoor ERG-style VT2 work, pass the caller-level anchor with `--vt2-watts <watts>` so power control is judged against the intended target. For outdoor or route-based threshold efforts without a fixed target, omit `--vt2-watts`; the helper will score power control around the block average and treat the result as a VT2-like control/cost diagnostic rather than an exact target-compliance verdict.
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

### Daily Recommendation Workflow

For same-day or next-morning training recommendations, keep the recommendation
logic split between personal context, live source data, helper output, and final
LLM coaching judgment:

1. Read relevant personal context from the user's request, durable memory, and
   `config/user-training-profile.md`. This is LLM/agent context only; do not
   make helper scripts read it.
2. Resolve conflicts in this order: explicit user message, temporary profile
   rule, stable profile value, durable memory, generic fallback. Never let an
   older profile or memory value override something the user just said.
3. Resolve planning context before running helpers: workout window, planned
   start, current location/start anchor, modality availability, unavailable
   reasons, surface/bike intent, practical fueling defaults, and whether calendar
   uncertainty matters.
4. Fetch volatile source data through the relevant source plugin when current
   readiness, forecasts, or activity state matter. Pass normalized source JSON
   into repo helpers instead of making helpers call plugins directly.
5. Run `recommend_today.py` with explicit CLI arguments for the resolved
   planning choices. Treat its packet as structured evidence, not as the final
   answer.
6. In chat, make one clear recommendation and explain the tradeoff against the
   main alternative. Include timing, route/setup, watts/intensity, weather, and
   practical fueling. Only include modalities that are actually available in the
   resolved context. If a recurring automation prompt or generic user request
   asks for both indoor and outdoor alternatives, the resolved destination
   availability still wins; do not create hypothetical fallback options for
   unavailable modalities unless the user explicitly says that equipment or
   access is available.

When a trace of the resolved personal/logistics context is useful, create or
inspect a small `planning-context.json` next to the recommendation packet under
`outputs/recommendations/<date>/`. It should be LLM-authored trace context, not
a new script input contract. Typical fields are `planned_at`, `available_window`,
`available_modalities`, `unavailable_reasons`, `start_anchor`,
`start_radius_km`, `surface_preference`, `fueling_defaults_used`, and
`context_sources`.

#### Helper And Timing

- For same-day or next-morning "foreslå dagens økt" style recommendations, use
  `python3 -B scripts/recommend_today.py --date <YYYY-MM-DD> --available-window "<HH:MM-HH:MM[; note]>" --available-modalities indoor,outdoor|indoor|outdoor --unavailable-reason indoor=<reason> --start-anchor-displayname "<label>" --start-anchor-lat <lat> --start-anchor-lng <lng> --start-radius-km <km> --summary`
  as the primary command. It fetches Garmin/Xert/Yr inputs, builds the
  readiness snapshot, ranks XMB indoor workouts, finds an outdoor route from
  saved ride history, and writes the full packet under `outputs/recommendations/`.
  Treat its output as a context packet, not as the training recommendation
  itself: the script should collect and normalize source data, route
  candidates, workout candidates, timing, and weather, while the LLM makes the
  actual recommendation in chat.
  The default `--refresh auto` policy reuses source snapshots within their
  source-specific TTL and fetches only missing or stale inputs. Use
  `--refresh all` to force every source, `--refresh garmin,xert` (or another
  comma-separated source selection) to force selected groups, and
  `--refresh none` to work strictly from existing local source files. When
  Garmin has just been refreshed separately, pass the normalized day payload
  with `--garmin-json <path>`; this explicit override cannot be combined with a
  forced Garmin refresh.
  The helper checks recent Intervals.icu activities and saves only missing local
  activity packages before reading latest activity context or route history; this
  keeps the route-index cache useful while still letting today's new ride appear
  in tomorrow's recommendation. Use `--refresh none` when deliberately working
  from existing local artifacts.
- For narrower "can/should I train?" questions, prefer `python3 -B scripts/readiness_snapshot.py --date <YYYY-MM-DD>` after refreshing relevant inputs when appropriate.
- Before same-day or next-morning training recommendations, refresh volatile inputs when possible, including live Garmin Connect day/recent data for Body Battery, stress, readiness, and current Xert recovery data.
- Treat Garmin Training Readiness and Garmin recovery time as composite
  diagnostics, not independent dose inputs. `recommend_today.py` derives dose
  caution from direct physiological domains (HRV/resting-HR autonomic response,
  sleep, and Body Battery) plus cumulative load context from ACWR and
  rolling-load percentile. Do not weight the previous day's individual workout
  separately; its effect should already be reflected in the recovery and direct
  physiological response data. Keep the Garmin
  composite values visible for agreement/disagreement checks, but do not cite
  them as the reason for the dose or count them again alongside their inputs.
- Before same-day or next-morning training recommendations, also fetch recent
  Intervals.icu wellness entries including the requested date. Inspect explicit
  wellness annotations/events such as sickness in addition to activity history.
  A current-day sickness annotation overrides Garmin/Xert readiness and planned
  training dose: recommend no training rather than offering a workout or route.
  Keep recent sickness events visible as return-to-training context even when
  the requested day itself is not marked sick.
- If the previous day is marked sick and the requested day is unmarked, do not
  assume recovery. Ask whether the user is still sick or this is the first
  healthy day. Until that is clarified, avoid intensity and present only a
  provisional rest or very easy return-to-training option. If the user confirms
  continued illness, recommend rest; if the user confirms the first healthy
  day, use conservative return-to-training volume and intensity rather than the
  normal model-derived dose.
- Use a two-day default return ramp after the last sick day, adjusted further
  downward when symptoms, Garmin, Xert, sleep, HRV, Body Battery, or body feel
  argue for it: day 1 is rest or 20-45 minutes very easy, day 2 is 30-60 minutes
  easy endurance. Do not schedule intensity during these two days. From day 3,
  resume normal readiness-based logic if the user feels healthy. Cap model-derived duration/load
  to the return-ramp ceiling rather than merely describing the ramp while still
  ranking full-dose workouts or routes.
- Obtain Xert readiness context live through the Xert plugin, translate it to the normalized readiness JSON shape, and pass that file with `--xert-json <file>`. Do not pass raw Xert API/plugin payloads to `readiness_snapshot.py`.
- Pass Garmin Connect day data as an explicit JSON file with `--garmin-json <file>`.
- Add `--now <local time>` and one or more `--available-window "<HH:MM-HH:MM[; note]>"` values for same-day or next-morning planning when calendar context is available. The optional note is for traceability only; the window start/end remain the structured logistics input. If `--planned-at` is omitted, `recommend_today.py` uses the first available window's start as the planned workout time. Use `--planned-at <local time>` only when choosing a specific start inside a supplied window or when there is no calendar-window context.
- Inspect `target_resolution.split` and each primary candidate's `window_fit`
  when calendar windows are supplied. If a route or workout does not fit the
  first window, treat it as a dose reference or later-window option rather than
  the practical first-session prescription, and prefer `shorter_window_options`
  when they exist.
- When the user gives no planned workout time, use the earliest default start
  from personal context, currently `config/user-training-profile.md`. If
  calendar context is available, inspect it and pass `--planned-at` for the
  first practical free window at or after that configured time; if no calendar
  context is available, let `recommend_today.py` use the configured default and
  say that this was an assumption.

#### Final Chat Decision

- Treat script output as decision inputs, not the conclusion. The chat answer should still weigh normal training load, goals, planned future sessions, and user-provided body feel.
- When Xert projected low, high, and peak recovery hours are all negative at
  the planned workout time, describe Xert as green for intensity/all systems,
  not merely "fresh enough for low intensity". If the final recommendation is
  still VT1, make clear that the limiter is Garmin, freshness, weather,
  logistics, recent completed work, or user feel rather than Xert.
- Interpret Xert recovery and capacity as separate decisions. If
  `recovery_hours.high` or `recovery_hours.peak` is `0` or negative, Xert says
  the athlete is ready for over-TP work in that system. If Xert then assigns
  high/peak XSS in `target_xss`, treat that as Xert's view of the stimulus
  needed that day, not as a hard minimum or maximum. When preserving ability to
  train the next day, use `workout_capacity` for the relevant systems instead:
  keep high/peak work within high/peak capacity if tomorrow needs over-TP
  readiness, and keep low-system load within low capacity if tomorrow needs
  aerobic readiness.
- When interpreting Xert `target_xss` or workout XSS split, compare high and
  peak XSS as absolute system doses against known workout-library profiles and
  recent completed workouts. Do not judge high/peak stimulus by its percentage
  of total XSS, because even clear VO2Max workouts can contain mostly low XSS
  with relatively small high/peak values. A few high XSS can still be a real
  over-TP signal; peak XSS should be read separately as peak-power-specific
  load, not as a generic intensity score.
- Treat Xert low/high/peak XSS as additive system loads, not replacement
  buckets. Work above TP can still earn full low-XSS credit for that duration
  while also adding high and/or peak XSS. Therefore, never argue that a session
  or target is "mostly low" as proof that it lacks over-TP work; inspect the
  absolute high/peak amounts and compare them with known workout profiles.
- Use this practical Xert model when explaining XSS split: low XSS accumulates
  faster as intensity rises toward TP and is effectively capped at TP; above TP,
  low XSS continues at that capped rate while high/peak XSS are additive loads
  on top. Present this as a reasoning model, not as Xert's exact formula.
- When the exact Xert low/high/peak accumulation behavior matters, verify it
  empirically with Xert Workout Designer `calculate` on controlled workout
  variants. Prefer non-persistent dry-run/calculate flows and compare the
  returned absolute low/high/peak XSS across intensities and durations.
- Do not use low `high`/`peak` XSS in Xert's training advice as an argument
  against controlled VT2/subthreshold work. Xert `high`/`peak` primarily
  indicates work over threshold power/TP, while the user's VT2 prescription is
  usually below TP. A low high/peak split can rule against VO2Max, peak-power,
  or over-TP work; it does not by itself rule against subthreshold VT2. When
  recommending VT1 over VT2, base that choice on Garmin/readiness, recent
  workout response, route/logistics, weather, progression timing, or user feel.
- Interpret training load primarily relative to this user's history, not as an absolute number. Recent hours, load, or activity count should not by themselves imply rest if they are normal or low for the user. Compare the current recent load against historical distribution and, when possible, against prior periods where recovery signals and workout response stayed acceptable. Absolute load still matters as a sanity check for genuinely extreme totals, but avoid generic conclusions such as "six hours this week means rest" for a rider who commonly tolerates more.
- For routine same-day recommendations, do a quick historical-load sanity check before shortening a normally reasonable endurance ride because of acute readiness signals. At minimum compare the current rolling 7-day load and current calendar-week load against the user's recent historical distribution, then decide whether caution comes from actual high load or from acute physiology/readiness. If the load is normal or low for this user, prefer extending easy VT1/endurance duration over adding intensity, unless weather, calendar, fueling, or body feel argue against it.
- When the user asks for a deeper readiness check, challenges a load/readiness interpretation, or the readiness signals conflict, compare the current recent load against the user's historical distribution before calling it high or low. Prefer rolling 7-day and calendar-week load percentiles from live Intervals.icu activity history or an equivalent local history; state whether a load is high relative to this user, not only whether the last few days look busy. Use this deeper check selectively when requested or when it could change the recommendation, not for every routine workout suggestion.
- In deeper readiness checks, separate absolute/historical load from acute physiological response. If historical load is normal but HRV, sleep, resting HR, stress, Xert recovery, Garmin recovery/readiness, or the latest workout response are mixed, explain that the caution comes from the acute signals rather than from the load being objectively high for the user.
- For training recommendations, account for what the user is training for and
  how much time remains until that target. Choose the session type by combining
  target specificity and time horizon with readiness, recent load, weather and
  user constraints. If the target or time horizon is missing and materially
  affects the recommendation, ask for it or state the assumption.
- For same-day and next-morning cycling recommendations, provide two concrete prescriptions: one indoor trainer option and one outdoor route/session option. Include duration, watts/intensity, warmup, practical fueling, and when it fits to train for both when relevant, then make a clear recommendation between them.
- Before recommending VT2, threshold, VO2Max, peak-power, or harder work, inspect today's Intervals.icu `soreness` wellness value. If it is missing, assume soreness is non-limiting, provide the high-intensity recommendation normally, and ask the user to set today's soreness value in Intervals.icu. Treat an explicit zero/no-soreness value as present. Missing soreness must not block or downgrade any recommendation by itself.
- When presenting the final chat recommendation, suggest target watts for
  recovery, VT1, VT2, and VO2Max for the current context. Treat these as
  coach/LLM-selected day targets based on the recommendation packet, user
  history, recent workout response, and readiness; do not expose raw model field
  names. Keep the selected session's target watts clearly separate from the
  other watt anchors, which are reference targets for alternative intensities.
- When suggesting practical fueling, translate carbohydrate targets into
  countable on-bike actions, not only grams per hour. Use configured personal
  fueling defaults from `config/user-training-profile.md` when available;
  otherwise use generic countable food portions plus the planned sports drink.
- Always mention the timing guidance from `recommend_today.py` in chat, including whether the planned time was user-provided or assumed, the evaluated weather window, and any sync/readiness caveat before upgrading intensity.

#### Indoor Option

- Apply the resolved readiness bias to workout candidates before ranking them.
  For `rest` or active-recovery-only days, retain only explicit recovery
  workouts that fit the capped dose. For `easy_vt1`, retain recovery or
  endurance/VT1 workouts that fit the capped duration and load. Keep suppressed
  workouts as compact audit context, but do not expose them as normal or
  higher-intensity candidates. This filtering is workout-specific; do not apply
  it to outdoor route ranking because routes describe geometry rather than a
  fixed intensity structure.
- Assume indoor trainer recommendations are ridden in ERG mode by default. Describe the indoor option as using the selected workout as-is, or adjusting workout intensity/power, duration, or repetitions for a concrete reason. When recommending an existing Xert/XMB workout as-is, treat warmup and cooldown as part of that workout's total duration; do not prescribe extra warmup time unless you explicitly say you are modifying or extending the workout. Do not use free-riding language such as drifting or gliding above target watts for normal indoor ERG work.
- For indoor trainer recommendations, prefer suitable enabled/usable `XMB: ` workouts from Xert when they match readiness, available time, load target, and session goal. Present a short menu of relevant indoor options when multiple XMB workouts fit, typically conservative/normal/longer duration choices, and still state which one is preferred for the day. Mention workout name/path or URL when available and say whether to use it as-is or adjust power, duration, or repetitions. Suggest XMB structure changes only for a concrete reason such as readiness, load target, available time, or session specificity; do not vary structure just for variety. Reserve slope mode language for explicitly requested slope sessions or workouts where it naturally fits the purpose, typically VO2Max, opener, standing, or harder over-threshold work. `recommend_today.py` keeps threshold/VO2/hard-power workouts out of the primary default candidate list; only pull from its `higher_intensity_candidates` when intensity is explicitly appropriate. If a non-XMB indoor session is better, say why.

#### Outdoor Option

- For outdoor route/session options, do not invent generic route text from
  geography alone. Prefer concrete route candidates from the user's saved
  outdoor ride history. Resolve the desired start/end anchor from the user's
  explicit request, memory, and `config/user-training-profile.md` before
  running helpers; do not hard-code a universal home anchor in scripts. Resolve
  desired surface from the user's bike/intent and pass `--surface-preference
  road|gravel|any|unknown-ok`; default to `road` only when the user asks for
  landevei or no surface/bike context is given. Run `python3 -B
  scripts/route_recommendations.py --date <YYYY-MM-DD> --years 5
  --surface-preference <surface> --start-anchor-displayname "<label>"
  --start-anchor-lat <lat> --start-anchor-lng <lng> --start-radius-km <km>`
  when the route should start/end near the requested anchor. Use
  `--start-radius-km` only when the user wants a looser or tighter match, and
  `--no-start-filter`/`--allow-away` when the user wants to list or compare
  saved routes without filtering on start/end location. `--query <fragment>` is
  only a hard filter for deliberately narrowing a list, not a ranking signal. If
  no suitable historical route is available, say that explicitly before giving a
  fallback route idea.
- Rank outdoor route candidates by route properties, not by historical execution, naming quality, query/name matching, or how often the route was ridden. Do not use moving time, XSS/training load, IF/intensity, average watts, recency, activity name specificity, repeat count/familiarity, query match, or how the user rode the activity as route-quality signals. Those fields may be kept as reference metadata, and activity names may be used for display. `route_reference_count` may be shown as metadata for how many saved references have the same route shape, but it must not affect score/ranking. The recommendation should be based on actual route shape, start/end anchor match, distance when explicitly requested, steady-endurance suitability/bratt nedover-andel, and match against the requested surface preference.
- For route display names, do not leave generic activity names such as `Morning Ride`, `Ride`, or `<place> Landeveissykling`, and do not use workout titles such as `Xert Cycling Workout` or named Xert workouts as the route name when a better route label can be inferred. Prefer a concrete non-generic name from another reference with the same actual `route_group_key`; if all references are generic/workout-derived, infer a compact display name from specific places the route goes through, not just the broad municipality/start area and not distance. Prefer several meaningful intermediate places when they describe the route, and avoid using the start/end anchor as the only name. This display-name repair must not affect route scoring, dedupe identity, or route-reference counts.
- For standalone route recommendations outside `recommend_today.py`, refresh local Intervals.icu artifacts first when live access is appropriate, for example by checking recent activities and saving missing ones with the Intervals.icu plugin. Do not blindly rewrite already cached activity packages just to refresh; the route-index cache invalidates from local activity file mtimes, so unnecessary rewrites make recommendations slow without adding information.
- For route-catalog work, use `python3 -B scripts/build_route_catalog.py --date <YYYY-MM-DD> --years 5 --start-anchor-displayname "<label>" --start-anchor-lat <lat> --start-anchor-lng <lng> --start-radius-km <km> --surface-preference <surface>`. It builds incremental route artifacts under `outputs/routes/`: raw route files, first-pass cleaned GPS routes, scored routes, and grouped/deduplicated route summaries. The current cleaned-route model removes obvious GPS duplicates, impossible jumps, and short spike/detour points before recalculating distance. For selected routes, add `--map-match-osm --activity-id <id>` to build an ordered OSM `way_id` sequence; this uses approximately 1 km lat/lng corridor tiles cached under `outputs/osm-cache/tiles` (`0.01` latitude degrees by `0.02` longitude degrees, with 200 m padding by default). OSM tile fills may be slow the first time, but subsequent map-match rebuilds should hit the tile cache. Keep the first-pass GPS-only limitation visible when `map_matched=false`.
- When recommending an outdoor route, explicitly say whether the route reference is landevei, grus, or unknown and whether it matches the requested `surface_preference`. Use the route helper's `surface` field, which is based on the source activity's registered gear/bike when available. Do not silently recommend a gravel reference as a road route, or a road reference as a gravel route; either pass the correct `--surface-preference`, use `any`, or explain the mismatch. If `surface.surface=unknown`, say that landevei vs grus is not confirmed and include the registered `gear_id`/`gear_name` when present so the source activity can be corrected.

#### Clothing And Weather

- When the final recommendation includes an outdoor ride, include a practical
  clothing recommendation based on the forecasted route weather and the clothing
  items the user has explicitly provided in the current request, repo
  preferences, or durable memory. Treat clothing selection as LLM-authored chat
  guidance, not `recommend_today.py` logic. Do not invent specific owned
  clothing items when no clothing inventory is available; in that case give only
  generic layer guidance or say the inventory is not available.
- For outdoor clothing recommendations, read the repo wardrobe config
  `config/cycling-clothing.md` first when it is available. It contains the
  user's known Castelli items, model-confidence notes, manufacturer temperature
  ranges, and practical selection rules. Do not move this clothing inventory
  into `recommend_today.py`; keep clothing choice as LLM chat guidance based on
  the recommendation packet's weather and route context.
- For endurance outdoor recommendations from the selected start anchor, use the helper's `steady_endurance` fields as a primary route-quality signal, not just distance or load. This is currently a terrain-based steady-endurance signal: `terrain_steady_endurance_metrics` checks GPS/altitude using 200 m rolling downhill windows. `steady_endurance.downhill_disruption_pct` is a weighted share of route distance with downhill grades steeper than 4% and 5%; lower is better. When presenting this signal, include both kilometers and percent of route distance for `descent_gt4` and `descent_gt5`, not only the weighted percentage. Treat long/steep descents as a real penalty because they break steady pedaling for this user. Exclude or clearly downgrade routes with `steady_endurance.available=false` due to suspect altitude data unless there is another clean reference for the same route.
- When showing junction/crossing counts for saved routes, use map-backed `--junction-source osm`, which queries OSM/Overpass highway topology near the actual GPS track and returns `map_junctions`. The helper should first map-match the GPS route to OSM ways/arcs, then count junction nodes on those matched ways; do not count arbitrary OSM nodes merely because they are inside a route buffer. Do not present GPS bearing-change counts as real junction counts. OSM route analysis is expensive and should use `--route-analysis-cache outputs/route-analysis-cache.json` by default; the cache is keyed by a GPS route fingerprint plus conflict-model version, so identical route shapes reuse conflict points while changed conflict semantics invalidate old entries. Use `--rebuild-route-analysis-cache` when the OSM data or model needs a deliberate refresh. Treat `map_junctions.count` as an OSM topology estimate, not as right-of-way or traffic-light truth.
- For vikeplikt counts, use `map_yield_situations` from `--junction-source osm`. Clean/map-match the GPS route to relevant non-service OSM highway ways first, then score conflicts on that cleaned route; do not score a raw GPS trace that briefly snaps to a nearby driveway or service road. It counts explicit OSM `highway=give_way` plus `highway=stop` nodes only when those nodes lie on OSM ways matched to the cleaned route, and reports traffic lights/crossings separately. It also reports `inferred_priority_yield_count`, a map-matched OSM highway-class/geometry heuristic for likely priority situations: count when the route enters a higher-priority road class at a junction, when a geometrically distinct side branch has a higher road class than the incoming route, or when a geometrically distinct same-class side branch is on the rider's right by the route direction. Ignore OSM `highway=service` ways in this heuristic; they are usually driveways, parking/access roads, or private-scale service roads and should not create landevei route-conflicts. Evaluate each route pass through a junction separately; if an out-and-back route passes the same OSM node in both directions, the right-hand-rule result can differ and both passes must be considered. Example: `residential` into `secondary` counts; `secondary` to `secondary` with a same-class branch from the right counts; `secondary` to `secondary` with only a lower-class side road or a same-class branch from the left does not. Road-name changes must not affect the count. Treat this as a route-planning interruption signal, not legal proof of vikeplikt.
- Treat saved route variants as concrete historical routes, not as abstract templates. For example, distinguish `Sørkedalen x2`, `Sørkedalen x3`, and `Sørkedalen x4` by their actual GPS shape, distance, duration, and steady-endurance metrics instead of deriving one variant from another.
- When proposing an outdoor route, embed the Xert route map image in chat whenever available and the chat surface supports Markdown images. In `recommend_today.py` packets, prefer `xert_map_local_path` from the selected route for Markdown image embeds in Codex/app chat, for example `![Xert-kart for <route>](<xert_map_local_path>)`; fall back to `xert_map_url` when no local copy exists. `xert_map_url` is the ready-made Xert PNG map from the Xert activity row, but external image embeds may fail in app chat. The route helper's `url` field is the Intervals.icu activity URL for the saved route reference, not a map image. If the route packet lacks `xert_map_url`, fetch Xert activities for the selected route date, match by route name/date/distance, and use the matching Xert activity row's `map_url`. If no Xert map can be found, say so explicitly instead of silently omitting the map. If Markdown image embedding is not supported, include the direct map URL as a fallback.
- Prefer a transparent combination of recent training load plus wellness fields actually present in source inputs: HRV, resting HR, sleep duration, and sleep score.
- Treat Garmin aggregated readiness as a second opinion, not as a replacement for Xert/Intervals load or actual workout sensor response.
- Treat Garmin recovery time/readiness as live, sync-sensitive physiological estimates. Interpret Garmin recovery time as guidance for readiness for the next hard workout, not a blanket restriction on easy or moderate training.
- For same-day recommendations, do not let low Garmin Training Readiness or
  long Garmin recovery time dominate the whole recommendation when Xert is
  green and direct wellness signals such as sleep, HRV, resting HR, Body
  Battery, stress, and the latest workout response are good. Keep Garmin as a
  stronger guardrail for threshold/VO2/hard work than for controlled VT1 or
  endurance dose.
- When Garmin recovery time is available for a planned future session, project remaining recovery time forward to the planned session time, assuming no intervening training unless known.
- Use positive remaining Garmin recovery to scale confidence and ambition based on planned intensity, Xert recovery, wellness signals, and actual workout response.
- When fetching Garmin same-day time series such as heart rate, stress, or Body Battery, check whether expected data is present and how recent the newest datapoint is. If data is missing, incomplete, or stale enough to affect the decision, explicitly encourage syncing Garmin/the watch before relying on those signals.

## Garmin Analysis Notes

- For activity summaries, use Garmin/Firstbeat activity training load, TSS/IF, aerobic and anaerobic training effect, training effect label/message, stamina begin/end/min, performance condition trend, calories, and Garmin normalized power when available.
- For readiness summaries, use Garmin Training Readiness, HRV status/baseline, Body Battery charge/drain, daily stress, sleep details, resting HR, and training status when available.
- In recommendation context output, put numeric readiness values and their
  thresholds/baselines before enum labels. For Garmin HRV, show last-night or
  weekly HRV plus the balanced range; for Training Readiness, show the numeric
  score and recovery hours. Treat labels such as `BALANCED`, `POOR`, or
  `UNPRODUCTIVE_*` as metadata only, not primary LLM decision inputs.
- For same-day workout suggestions, inspect `recommendation_inputs.garmin_load_focus` from `readiness_snapshot.py` when Garmin training status is available. Treat Garmin load-focus feedback such as `ANAEROBIC_SHORTAGE` as a recent-load mix signal that can shape the next useful stimulus, but do not let it override acute readiness, recovery time, HRV, post-activity HR/stress, Xert recovery, or the session goal.
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
- When a historical route candidate is selected, use its actual route family/name and practical metrics such as duration, distance, elevation, and training load to choose relevant weather points. Do not mention route areas that are not supported by the selected prior activity or the user's explicit instruction.
- Use fresh live data for same-day and next-day training-weather decisions.
