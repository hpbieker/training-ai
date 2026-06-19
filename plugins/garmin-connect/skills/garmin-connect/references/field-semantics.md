# Garmin Connect Field Semantics

Garmin Connect data is useful as extra physiological and activity context, but it is a synced copy of what the watch or head unit has uploaded. Treat freshness as part of the signal.

## Readiness and Recovery

- Training Readiness is Garmin's aggregate readiness estimate. Use it as a second opinion alongside Xert, Intervals.icu, recent load, and user-provided feel.
- Recovery time estimates readiness for the next hard workout. It is not a blanket ban on easy or moderate training.
- Recovery time is sync-sensitive and can change after sleep, stress, HRV changes, watch sync, or new activities.
- When recovery time is used for a future planned session, project the remaining hours forward to the planned local time assuming no intervening training unless one is known.

## Body Battery, Stress and Heart Rate

- Body Battery, stress, heart rate and related readiness fields can change through the day after device syncs. Garmin Connect is normally the freshest source for these Garmin-specific fields, and it can expose useful time series for stress, heart rate and Body Battery.
- Missing or stale data should be called out before making same-day training decisions.
- For same-day second-session decisions, inspect post-workout stress instead of relying only on daily average stress. Sustained high/orange stress after training suggests the body is still working.
- For post-workout heart rate, use the lowest post-workout HR and especially the lowest sustained 5-minute average. Latest HR and broad post-workout averages are too sensitive to movement and timing.
- If sleep occurred after the previous workout, separate the immediate post-workout window from the overnight period. Sleep, HRV, resting HR and Body Battery are stronger morning-readiness signals.
- Compare post-workout HR lows with recent resting HR. If HR does not settle near baseline before sleep, reduce ambition for same-day or next-morning intensity.

## HRV and Sleep

- Use HRV status/baseline, resting HR, sleep duration and sleep score only when those fields are actually present.
- Garmin sleep fields are normally preferable to manually asking for routine sleep quality. Do not invent missing fields from Intervals.icu wellness.

## Activity Metadata

- Garmin/Firstbeat activity metadata can add Training Effect, activity training load, TSS/IF, stamina, calories, normalized power and performance condition.
- Compact activity output keeps Garmin's raw Training Effect category in `training_effect.label`. In chat/report wording, translate Garmin's all-caps labels to natural English names rather than repeating the raw enum. Known category labels include:
  - `AEROBIC_BASE` -> `Aerobic base`
  - `ANAEROBIC_CAPACITY` -> `Anaerobic capacity`
  - `LACTATE_THRESHOLD` -> `Threshold`
  - `RECOVERY` -> `Recovery`
  - `SPEED` -> `Speed`
  - `TEMPO` -> `Tempo`
  - `UNKNOWN` -> `Unknown`
  - `VO2MAX` -> `VO2 max`
- `aerobic_message` and `anaerobic_message` are more granular Garmin message codes, not category labels. Use them as nuance if helpful, for example `IMPROVING_LACTATE_THRESHOLD_12` can be phrased as `threshold benefit`, but do not document those message codes as `training_effect.label` values.
- Preserve the full raw message code, including the numeric suffix, when the user asks to inspect Garmin fields or compare raw API values. For analysis wording, split the message at the final underscore when it ends in a number and interpret the semantic prefix. The numeric suffix appears to be a Garmin message/resource identifier, not a measured training-effect value.
- Observed aerobic message-code semantics include:
  - `MINOR_AEROBIC_BENEFIT_0` -> minor aerobic benefit
  - `MAINTAINING_AEROBIC_FITNESS_1` -> maintaining aerobic fitness
  - `IMPROVING_AEROBIC_FITNESS_2` -> improving aerobic fitness
  - `HIGHLY_IMPROVING_AEROBIC_FITNESS_3` -> highly improving aerobic fitness
  - `OVERREACHING_4` -> overreaching
  - `RECOVERY_5` -> recovery
  - `MAINTAINING_AEROBIC_BASE_7` -> maintaining aerobic base
  - `IMPROVING_AEROBIC_BASE_8` -> improving aerobic base
  - `IMPROVING_AEROBIC_ENDURANCE_9` -> improving aerobic endurance
  - `HIGHLY_IMPROVING_AEROBIC_ENDURANCE_10` -> highly improving aerobic endurance
  - `OVERREACHING_11` -> overreaching
  - `IMPROVING_LACTATE_THRESHOLD_12` -> improving lactate threshold
  - `HIGHLY_IMPROVING_LACTATE_THRESHOLD_13` -> highly improving lactate threshold
  - `OVERREACHING_14` -> overreaching
  - `IMPROVING_VO2_MAX_15` -> improving VO2 max
  - `HIGHLY_IMPROVING_VO2_MAX_16` -> highly improving VO2 max
  - `OVERREACHING_17` -> overreaching
  - `NO_AEROBIC_BENEFIT_18` -> no aerobic benefit
  - `MAINTAINING_LACTATE_THRESHOLD_19` -> maintaining lactate threshold
  - `MAINTAINING_TEMPO_21` -> maintaining tempo
  - `IMPACTING_TEMPO_22` -> impacting tempo
  - `HIGHLY_IMPACTING_TEMPO_23` -> highly impacting tempo
  - `OVERREACHING_TEMPO_24` -> overreaching tempo
- Observed anaerobic message-code semantics include:
  - `NO_ANAEROBIC_BENEFIT_0` -> no anaerobic benefit
  - `MAINTAINING_ANAEROBIC_BASE_1` -> maintaining anaerobic base
  - `IMPROVING_ANAEROBIC_BASE_2` -> improving anaerobic base
  - `HIGHLY_IMPROVING_ANAEROBIC_CAPACITY_AND_POWER_3` -> highly improving anaerobic capacity and power
  - `MINOR_FAST_FORCE_BENEFIT_5` -> minor fast-force benefit
  - `MAINTAINING_FAST_FORCE_PRODUCTION_6` -> maintaining fast-force production
  - `MAINTAINING_ANAEROBIC_POWER_7` -> maintaining anaerobic power
  - `IMPROVING_ANAEROBIC_CAPACITY_AND_POWER_8` -> improving anaerobic capacity and power
  - `MAINTAINING_ECONOMY_AND_ANAEROBIC_BASE_10` -> maintaining economy and anaerobic base
  - `IMPROVING_ECONOMY_AND_ANAEROBIC_BASE_11` -> improving economy and anaerobic base
  - `IMPROVING_ANAEROBIC_CAPACITY_AND_SPEED_12` -> improving anaerobic capacity and speed
  - `HIGHLY_IMPROVING_ANAEROBIC_CAPACITY_AND_SPEED_13` -> highly improving anaerobic capacity and speed
  - `MINOR_ANAEROBIC_BENEFIT_15` -> minor anaerobic benefit
  - `OVERREACHING_SPEED_16` -> overreaching speed
- Treat Garmin load as secondary when Xert XSS is available.
- Performance condition is a secondary trend signal. It can be less comparable between indoor and outdoor rides because of power source, terrain, coasting, riding position, core-muscle load and environmental variation.
- Stamina values are Garmin-specific estimates and should be interpreted as context, not as direct proof of remaining race capacity.

## Sync Caveats

- Garmin Connect only exposes data that has synced from the device. If expected data is missing or stale enough to affect a decision, ask the user to sync Garmin/the watch before relying on it.
- Fetch live Garmin Connect data through the plugin when Garmin context is needed.
