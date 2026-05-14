# Project Instructions

- When the user asks for analyses or comparisons, answer in chat by default.
- Do not create standalone report files for analyses or comparisons unless the user explicitly asks for a file.
- Treat `data/` as temporary local cache/output. It is ignored by git and can contain downloaded activities, streams, scratch outputs and generated reports when explicitly requested.
- For workout analyses, exclude warm-up and cooldown from interval metrics. The user typically warms up for about 12 minutes and cools down for about 3 minutes. Prefer detecting the actual work segment from the power trace rather than using the full stream: look for the point where power rises into a stable target such as 195 W, 200 W, 205 W or the relevant interval target. There is usually a small step up in watts when the work interval starts.
- Do not limit training analysis to power and heart rate. The user normally has richer sensor data available, especially for indoor cycling. Check available streams per activity and use the relevant ones when present:
  - Mechanical/load: `watts`, `cadence`, `torque`.
  - Heart/cardiovascular: `heartrate`; derive W/HR and HR drift where useful.
  - Respiratory: `respiration` as breathing rate / BR, `tidal_volume` as VT, and `tidal_volume_min` as minute ventilation / VE. Analyze both averages and drift over the workout/intervals, especially BR drift, VE drift, VT drift, and whether rising VE comes from higher BR or deeper VT.
  - Muscle oxygenation: SmO2 and THb come from the user's Moxy sensor. Analyze min, max and drift over intervals/workout, including SmO2 desaturation, re-oxygenation in recoveries, THb trend/drift, and how local muscle oxygenation changes align with power, HR and respiratory drift. For re-oxygenation in recoveries, quantify both how much SmO2 rises during each recovery and the peak SmO2 reached in that recovery. In cases where Moxy data is absent or clearly unusable, leave it out and note that briefly.
  - Thermal/body: `core_temperature`, `skin_temperature`, `heat_strain_index`.
  - Environment: `temp`, `RuuviTemperature`, `Humidity`, `RuuviHumidity`.
  - Wellness/recovery: `hrv` (rMSSD), `restingHR`, `sleepSecs`, `sleepScore`, plus `weight`, `bodyFat`, `vo2max`, `spO2`, `steps` when populated.
- Xert data, when cached, should be used as additional activity-load context rather than replacing the sensor analysis. Prefer activity-level summary fields such as XSS, low/high/peak XSS, XEP, focus, specificity, difficulty, difficulty rating, freshness/status and the Xert fitness signature. This helps distinguish high aerobic volume from genuinely costly high-intensity sessions.
- For weather forecasts, use Yr/MET Norway's official Locationforecast API (`api.met.no`) as the default source. Prefer cached data under `data/weather/` when available, and avoid ad hoc weather websites unless the MET/Yr API is unavailable or the user explicitly asks for another source.
- For readiness recommendations, prefer a transparent combination of recent training load plus wellness fields actually present: HRV, resting HR, sleep duration and sleep score. Do not assume Garmin Training Readiness or Body Battery are available through Intervals.icu unless those fields appear in the downloaded wellness data.
