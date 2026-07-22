# Intervals.icu Field Semantics

## Role In This Repo

- Intervals.icu is a live source for activity metadata, interval summaries, wellness, and available stream/file exports.
- Treat Intervals.icu as a copy and aggregation layer. If the original system is available locally or through a live plugin/helper, prefer the original source for source-specific meaning because it may be fresher or more complete.
- Use Intervals.icu metadata and intervals to orient activity summaries, but prefer Xert for activity-load language when Xert data is available.
- Treat Intervals.icu load, intensity, and interval metadata as useful secondary context. Do not let Intervals.icu load override Xert XSS when both are available.

## Activity And Streams

- Use Intervals.icu stream fields actively for workout analysis: power, heart rate, respiratory, Moxy, thermal, and environmental streams should be checked according to the repo sensor profile.
- Intervals.icu respiratory stream fields use these meanings:
  - `respiration`: BR, breathing rate in breaths per minute.
  - `tidal_volume`: VT, Tyme Wear-reported breathing volume in centiliters per breath, inferred from exported stream values.
  - `tidal_volume_min`: VE, Tyme Wear-reported breathing volume in liters per minute, inferred from exported stream values.
  - For Tyme Wear streams, `tidal_volume_min` should be consistent with `tidal_volume / 100 * respiration`.
- Intervals.icu CORE sensor stream fields use these meanings:
  - `heat_strain_index`: HSI from the CORE 2 sensor, on a 0 to 5.0 scale.
  - `core_temperature`: CORE sensor core temperature in degrees C.
  - `skin_temperature`: CORE sensor skin temperature in degrees C.
- Other Intervals.icu stream fields use these meanings:
  - `time`: elapsed activity time in seconds.
  - `watts`: power in watts.
  - `heartrate`: heart rate in beats per minute.
  - `distance`: distance in meters.
  - `lat`: latitude in degrees.
  - `lng`: longitude in degrees.
  - `velocity_smooth`: smoothed speed in meters per second.
  - `temp`: measured ambient air temperature in degrees C.
  - `cadence`: crank cadence in revolutions per minute.
  - `altitude`: elevation above sea level in meters.
  - `torque`: torque in Nm from the power sensor.
  - `left_right_balance`: left-side power percentage.
  - `Humidity`: relative humidity percentage.
  - `RuuviHumidity`: relative humidity percentage from Ruuvi.
  - `RuuviTemperature`: ambient air temperature in degrees C from Ruuvi.
- Intervals.icu muscle oxygen sensor stream fields use these meanings:
  - `smo2`: muscle oxygen saturation percentage from a Moxy or similar muscle oxygen sensor.
  - `thb`: total hemoglobin in g/dL from a Moxy or similar muscle oxygen sensor; use primarily for trend analysis.
- Respect Intervals.icu ignore flags in activity metadata:
  - If `icu_ignore_hr` is true, do not use heart rate, W/HR, or HR drift for that activity.
  - If `icu_ignore_power` is true, do not use power or torque-derived metrics unless the user explicitly asks to inspect the raw stream.
- For workout analyses, exclude warm-up and cooldown from interval metrics. Prefer detecting the actual work segment from the power trace rather than using the full stream.

## Wellness

- Sickness is a calendar event with `category=SICK`; it is not a wellness field. Multi-day events use an exclusive `end_date_local`.
- Legacy wellness comments such as `Syk` may be read as fallback context, but structured `SICK` events take precedence and new writes must use calendar events.

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
