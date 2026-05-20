# User Preferences

## Workout Segmentation

- Typical warm-up: about 12 minutes.
- Typical cooldown: about 3 minutes.
- For workout analysis, prefer detecting the actual work segment from the power trace rather than using fixed durations.
- Typical stable VT1/work-segment targets include 195 W, 200 W and 205 W, plus the relevant interval target for the workout.
- Work intervals often start with a small step up in watts.

## Indoor Workouts

- For structured indoor ERG workouts, keep interval prescriptions simple and flat by default.
- Use the same watt target for every work interval unless the user explicitly asks for progressive stepping or lifting the final interval.

## Observed Workout Responses

- In VT2 workouts, the user can come down to about 106 bpm during the recovery after the first interval. Treat this as a contextual recovery-response benchmark, not as a fixed requirement.

## Training Venue

- Structured intervals are generally preferred indoors because the indoor setup is good and controllable.
- Long, easy rides are good candidates for outdoors when the weather is genuinely pleasant.
- The user dislikes riding indoors when it is sunny/nice outside.
- If outdoor weather is merely mediocre, indoor riding is preferred over going outside just for the sake of it.

## Sensor Profile

- Mechanical/load: `watts`, `cadence`, `torque`.
- Heart/cardiovascular: `heartrate`.
- Respiratory: `respiration` as breathing rate / BR, `tidal_volume` as VT, and `tidal_volume_min` as minute ventilation / VE.
- Muscle oxygenation: SmO2 and THb from the user's Moxy sensor.
- Thermal/body: `core_temperature`, `skin_temperature`, `heat_strain_index`.
- Environment: `temp`, `RuuviTemperature`, `Humidity`, `RuuviHumidity`.
- Wellness/recovery: `hrv` (rMSSD), `restingHR`, `sleepSecs`, `sleepScore`, plus `weight`, `bodyFat`, `vo2max`, `spO2`, `steps` when populated.

## Data Source Priority

- Default activity-load source priority is Xert, then Garmin, then Intervals.icu.
- The user may override this priority for a specific analysis.
- Xert is preferred by default because of the MPA model and its activity-level XSS, low/high/peak XSS, XEP, focus, specificity, difficulty, freshness/status and fitness-signature context.

## Weather

- Use Yr/MET Norway's official Locationforecast API (`api.met.no`) as the default weather source.
- Use the user's home/start area around Slemdal as the default weather anchor when relevant.
- Add likely destination or exposed-route points, such as Ytre Enebakk, when the planned ride suggests them.
