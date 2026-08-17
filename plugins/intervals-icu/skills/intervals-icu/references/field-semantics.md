# Intervals.icu Field Semantics

## Activity Metadata

- `icu_intensity` is expressed as a percentage, not a fraction; for example,
  `75` means 75% intensity.
- `icu_training_load` is the load calculated by Intervals.icu. Treat it as a
  source-specific load value rather than as interchangeable with other load
  metrics.
- `icu_ctl` and `icu_atl` are Intervals.icu fitness and fatigue values attached
  to the activity. Preserve their source and timestamp, and do not substitute
  them for similarly named values from another platform. For day-level fitness
  and fatigue context, prefer the selected day's wellness `ctl` and `atl`
  values rather than inferring the current state from an arbitrary activity.
- `external_id` identifies the activity in its upstream source. Use it for
  cross-source resolution; it is not the Intervals.icu activity ID.
- `gear` identifies registered equipment. A bike identity may help constrain
  route suitability and distinguish road, gravel, and indoor setups. It does
  not by itself prove the ridden surface; corroborate it with route geometry,
  activity context, or other surface evidence when that distinction matters.
- `decoupling`, `icu_variability_index`, and `icu_efficiency_factor` are
  Intervals.icu-calculated whole-activity summaries. Use them for orientation
  and comparison, but do not let them replace stream inspection when pauses,
  terrain, intervals, warmup/cooldown, or changing power make the whole-ride
  value unrepresentative.

## Activity And Streams

- Intervals.icu respiratory stream fields use these meanings:
  - `respiration`: BR, breathing rate in breaths per minute.
  - `tidal_volume`: VT, the Tyme Wear-reported per-breath volume or breathing-
    depth value. Existing exports appear scaled as centiliters per breath, but
    preserve the source value and do not assume laboratory-calibrated liters
    without verifying the device generation and export contract.
  - `tidal_volume_min`: VE, the Tyme Wear-reported minute-ventilation value.
    Existing exports appear scaled as liters per minute, but treat the absolute
    unit as source-reported unless independently verified for the exact device
    and processing path.
  - For current normalized Tyme Wear streams, `tidal_volume_min` should be
    arithmetically consistent with `tidal_volume / 100 * respiration`. This
    consistency check validates the mapping, not the absolute volume accuracy.
- Intervals.icu CORE sensor stream fields use these meanings:
  - `heat_strain_index`: HSI from the CORE 2 sensor, ranging from 0 to around
    10. It is CORE's proprietary composite derived from its estimated core
    temperature and local skin temperature. Preserve it as a product-derived
    index; do not reinterpret it as a direct physiological measurement or a
    medical heat-risk classification.
  - `core_temperature`: CORE-estimated body-core temperature in degrees C. The
    wearable estimates this value from thermal inputs and, in applicable
    operating modes, heart rate; it does not directly measure temperature at an
    invasive core site.
  - `skin_temperature`: local skin temperature in degrees C at the CORE sensor.
    Airflow, clothing, sweat, placement, ambient conditions, and peripheral
    blood flow can affect it.
  - Older or incomplete FIT exports can omit `heat_strain_index` even when
    `core_temperature` and `skin_temperature` are present. Treat absent or
    incomplete HSI as a coverage/export limitation, not as zero heat strain.
- Custom environmental fields use these meanings:
  - `Humidity` and `RuuviHumidity`: relative humidity percentage.
  - `RuuviTemperature`: ambient temperature in degrees C from Ruuvi.
- Intervals.icu muscle oxygen sensor stream fields use these meanings:
  - `smo2`: muscle oxygen saturation percentage from a Moxy or similar muscle oxygen sensor.
  - `thb`: the total-heme/total-hemoglobin value delivered by a Moxy or similar
    muscle oxygen sensor. Preserve the source value and unit when available,
    but do not interpret Moxy's absolute THb as a clinical blood-hemoglobin
    concentration. Use it primarily as a relative trend or delta within the
    same session and stable measurement setup.
- Respect Intervals.icu ignore flags in activity metadata:
  - If `icu_ignore_hr` is true, do not use heart rate, W/HR, or HR drift for that activity.
  - If `icu_ignore_power` is true, do not use power or torque-derived metrics unless the user explicitly asks to inspect the raw stream.
  - If `icu_ignore_time` is true, exclude the activity from time and distance
    totals or comparisons that are intended to match Intervals.icu totals. It
    does not mean that the activity's elapsed-time stream is unusable for a
    deliberate inspection of that activity.
  - Treat `ignore_velocity` and `ignore_pace` as source instructions not to use
    the corresponding velocity or pace data in aggregate analysis.
  - `ignore_parts` is structured, partial-ignore metadata. Do not interpret a
    non-empty value as permission to discard the whole activity. Preserve it
    in normalized handoffs, and avoid the affected portions or metrics only
    when their scope can be resolved from the payload.

## Wellness

- Sickness is a calendar event with `category=SICK`; it is not a wellness field. Multi-day events use an exclusive `end_date_local`.

- Wellness fields can be copied from connected systems. Use only fields present
  in the payload and do not assume Intervals.icu is their original or freshest
  source.
- Use daily wellness fields for pre-training subjective values rather than storing them on the activity.
- Do not add a generic wellness comment such as `Pre training`.

## Wellness UI Scales

- `sleepQuality`: `1 = great`, `2 = good`, `3 = avg`, `4 = poor`
- `soreness`, `fatigue`, and `stress`: `0 = none`, `1 = low`, `2 = avg`,
  `3 = high`, `4 = extreme`; `null` means no value has been recorded and is
  not equivalent to `0`
- `mood`: `1 = great`, `2 = good`, `3 = ok`, `4 = grumpy`
- `motivation`: `1 = extreme`, `2 = high`, `3 = avg`, `4 = low`
- `injury`: `1 = none`, `2 = niggle`, `3 = poor`, `4 = injured`
- `hydration`: `1 = good`, `2 = ok`, `3 = poor`, `4 = bad`

## Subjective Wellness Meanings

- Treat `soreness` primarily as local leg or muscle soreness/heaviness before training. Leg ache that disrupts sleep after hard training is an important recovery signal and should reduce next-day training ambition even if model-based readiness looks acceptable.
- Treat `fatigue` as general/systemic tiredness that may not be fully captured by objective source data.
- Treat `motivation` as mental readiness/drive to do the session.
- Treat `injury` as a safety and modality constraint, not merely as another
  readiness-score input. A niggle or worse should trigger location- and
  movement-specific follow-up before recommending intensity.
- Treat `stress` as perceived non-training or systemic strain. It can reduce
  training tolerance even when HRV, resting heart rate, and sleep look normal.
- Treat `mood` as contextual subjective evidence. Use it alongside fatigue,
  stress, and motivation; do not downgrade training from mood alone.
- Treat `hydration` as the user's daily subjective hydration status, not a
  measured fluid balance and not proof of adequate on-bike drinking.
- Treat `sleepQuality` as subjective sleep quality. Keep it distinct from
  objective duration and source-specific `sleepScore`, and investigate a
  disagreement instead of silently averaging the values.

## Subjective Activity Fields

- Intervals.icu activities may include subjective fields such as `feel`, `perceived_exertion`, `session_rpe`, and `icu_rpe`.
- When saving RPE, write `icu_rpe`. Intervals.icu derives `session_rpe` from RPE and duration and rejects direct writes to `session_rpe`.
- Prefer Intervals.icu activity fields for feel/RPE when available rather than burying the information only in chat.
