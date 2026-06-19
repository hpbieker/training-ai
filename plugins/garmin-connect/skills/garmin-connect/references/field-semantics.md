# Garmin Connect Field Semantics

Garmin Connect data is useful as extra physiological and activity context, but it is a synced copy of what the watch or head unit has uploaded. Treat freshness as part of the signal.

## Readiness and Recovery

- Training Readiness is Garmin's aggregate readiness estimate. Use it as a second opinion alongside Xert, Intervals.icu, recent load, and user-provided feel.
- Recovery time estimates readiness for the next hard workout. It is not a blanket ban on easy or moderate training.
- Recovery time is sync-sensitive and can change after sleep, stress, HRV changes, watch sync, or new activities.
- When recovery time is used for a future planned session, project the remaining hours forward to the planned local time assuming no intervening training unless one is known.

## Body Battery, Stress and Heart Rate

- Body Battery and stress require recent watch syncs. Missing or stale data should be called out before making same-day training decisions.
- For same-day second-session decisions, inspect post-workout stress instead of relying only on daily average stress. Sustained high/orange stress after training suggests the body is still working.
- For post-workout heart rate, use the lowest post-workout HR and especially the lowest sustained 5-minute average. Latest HR and broad post-workout averages are too sensitive to movement and timing.
- If sleep occurred after the previous workout, separate the immediate post-workout window from the overnight period. Sleep, HRV, resting HR and Body Battery are stronger morning-readiness signals.
- Compare post-workout HR lows with recent resting HR. If HR does not settle near baseline before sleep, reduce ambition for same-day or next-morning intensity.

## HRV and Sleep

- Use HRV status/baseline, resting HR, sleep duration and sleep score only when those fields are actually present.
- Garmin sleep fields are normally preferable to manually asking for routine sleep quality. Do not invent missing fields from Intervals.icu wellness.

## Activity Metadata

- Garmin/Firstbeat activity metadata can add Training Effect, activity training load, TSS/IF, stamina, calories, normalized power and performance condition.
- Treat Garmin load as secondary when Xert XSS is available.
- Performance condition is a secondary trend signal. It can be less comparable between indoor and outdoor rides because of power source, terrain, coasting, riding position, core-muscle load and environmental variation.
- Stamina values are Garmin-specific estimates and should be interpreted as context, not as direct proof of remaining race capacity.

## Sync Caveats

- Garmin Connect only exposes data that has synced from the device. If expected data is missing or stale enough to affect a decision, ask the user to sync Garmin/the watch before relying on it.
- Do not use local Garmin cache artifacts as a source. Fetch live Garmin Connect data through the plugin when Garmin context is needed.
