# Intervals.icu Field Semantics

## Role In This Repo

- Intervals.icu is a live source for activity metadata, interval summaries, wellness, and available stream/file exports.
- Treat Intervals.icu as a copy and aggregation layer. If the original system is available locally or through a live plugin/helper, prefer the original source for source-specific meaning because it may be fresher or more complete.
- Use Intervals.icu metadata and intervals to orient activity summaries, but prefer Xert for activity-load language when Xert data is available.
- Treat Intervals.icu load, intensity, and interval metadata as useful secondary context. Do not let Intervals.icu load override Xert XSS when both are available.

## Activity And Streams

- Use Intervals.icu stream fields actively for workout analysis: power, heart rate, respiratory, Moxy, thermal, and environmental streams should be checked according to the repo sensor profile.
- Respect Intervals.icu ignore flags in activity metadata:
  - If `icu_ignore_hr` is true, do not use heart rate, W/HR, or HR drift for that activity.
  - If `icu_ignore_power` is true, do not use power or torque-derived metrics unless the user explicitly asks to inspect the raw stream.
- For workout analyses, exclude warm-up and cooldown from interval metrics. Prefer detecting the actual work segment from the power trace rather than using the full stream.

## Wellness

- Intervals.icu wellness fields may come from Garmin or other connected systems.
- Use only wellness fields that are actually present in the fetched wellness data.
- For Garmin-specific wellness and readiness fields such as Training Readiness,
  Body Battery, HRV, stress and sleep, prefer Garmin Connect when it is
  available. These values can change through the day after device syncs, Garmin
  Connect is normally the freshest source, and it can expose useful time series
  for fields such as stress, heart rate and Body Battery.
- Use daily wellness fields for pre-training subjective values rather than storing them on the activity.
- Do not add a generic wellness comment such as `Pre training`.

## Wellness UI Scales

- `sleepQuality`: `1 = great`, `2 = good`, `3 = avg`, `4 = poor`
- `soreness`, `fatigue`, and `stress`: `1 = low`, `2 = avg`, `3 = high`, `4 = extreme`
- `mood`: `1 = great`, `2 = good`, `3 = ok`, `4 = grumpy`
- `motivation`: `1 = extreme`, `2 = high`, `3 = avg`, `4 = low`
- `injury`: `1 = none`, `2 = niggle`, `3 = poor`, `4 = injured`
- `hydration`: `1 = good`, `2 = ok`, `3 = poor`, `4 = bad`

## Routine Pre-Training Wellness

- Ask for `soreness`, `fatigue`, and `motivation` and save them to Intervals.icu wellness when the user confirms.
- If any of those fields are already populated for the day, do not overwrite them without first asking the user to confirm the overwrite.
- Treat `soreness` primarily as local leg or muscle soreness/heaviness before training. Leg ache that disrupts sleep after hard training is an important recovery signal and should reduce next-day training ambition even if model-based readiness looks acceptable.
- Treat `fatigue` as general/systemic tiredness that may not be fully captured by Xert or Garmin.
- Treat `motivation` as mental readiness/drive to do the session.
- Do not suggest or log `stress`, `sleepQuality`, `hydration`, or `injury` as routine fields. Garmin normally populates sleep, and the other fields are only useful when the user explicitly says they are relevant.

## Subjective Activity Fields

- Intervals.icu activities may include subjective fields such as `feel`, `perceived_exertion`, `session_rpe`, and `icu_rpe`.
- When saving RPE, write `icu_rpe`. Intervals.icu derives `session_rpe` from RPE and duration and rejects direct writes to `session_rpe`.
- Prefer Intervals.icu activity fields for feel/RPE when available rather than burying the information only in chat.
