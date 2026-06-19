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

## Activity Naming

- Prefer concise training-purpose names in Intervals.icu.
- For steady VT1/base rides, use the detected work-segment duration rather than total elapsed time, for example `VT1 150 min`.
- For structured intervals, use the interval structure, for example `VT2 3x22 min` or `VO2Max 2x8x60 sec`.
- For mixed sessions, combine the main blocks, for example `VT2 3x16 min + VT1 45 min`.
- Use route/place names for outdoor route-specific rides when that is the meaningful identity, for example `Sørkedalen x 2`.

## Xert Workout Selection

- When choosing a Xert workout to perform, prefer workout names that start with `XMB: ` when suitable for the training goal and load target.

## Observed Workout Responses

- In VT2 workouts, the user can come down to about 106 bpm during the recovery after the first interval. Treat this as a contextual recovery-response benchmark, not as a fixed requirement.

## Training Venue

- Structured intervals are generally preferred indoors because the indoor setup is good and controllable.
- Long, easy rides are good candidates for outdoors when the weather is genuinely pleasant.
- The user dislikes riding indoors when it is sunny/nice outside.
- If outdoor weather is merely mediocre, indoor riding is preferred over going outside just for the sake of it.

## Nutrition

- Standard sports drink: SiS GO Electrolyte Orange.
- For EatMyRide, do not interpret activity `warning` as a fueling-quality
  verdict. Treat it as a likely workflow/status flag for whether intake has
  been reviewed or edited. Judge fueling primarily from foodplan totals,
  `energyGraph.energy.glycogen`, `caloriesThreshold`, `caloriesStart`,
  `caloriesNeeded`, `energyNeeded`, and relevant intake timing.
- For new activity analyses where fueling has not been registered, ask the
  user what they ate and drank if the session is recent enough that recall is
  plausible. For older activities, state that fueling is unknown rather than
  asking for retrospective recall.

## Workout Analysis Expectations

- When the user asks to analyze a workout, inspect the actual activity data
  rather than only metadata or title. Use the available streams from the sensor
  profile, including power, heart rate, VE, VT, BR, Moxy SmO2/THb,
  core/skin temperature and environmental temperature/humidity.
- Include a fueling assessment in workout analyses when EatMyRide data or
  user-provided intake is available. If products are missing from EatMyRide,
  distinguish logged fueling from likely real fueling and state the uncertainty.

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
