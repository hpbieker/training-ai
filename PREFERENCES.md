# Project Preferences

Durable user-specific training preferences have been moved to global memory.
Keep this file focused on repo-local implementation defaults, helper behavior,
and source-integration reminders.

## Workout Segmentation

- For workout analysis, prefer detecting the actual work segment from the power trace rather than using fixed durations.

## Indoor Workouts

- For structured indoor ERG workouts, keep interval prescriptions simple and flat by default.
- Use the same watt target for every work interval unless the user explicitly asks for progressive stepping or lifting the final interval.

## Xert Workout Selection

- When choosing a Xert workout to perform, prefer workout names that start with `XMB: ` when suitable for the training goal and load target.
- When ranking Xert recommended workouts, filter to actual workouts first, then rank by the user's goal, XSS split, duration, focus, suitability, difficulty and the `XMB: ` name preference.

## Nutrition

- For EatMyRide-specific field semantics and write-safety, use the repo-local
  `eatmyride` plugin skill.

## Workout Analysis Expectations

- When the user asks to analyze a workout, inspect the actual activity data
  rather than only metadata or title. Use the available streams from the sensor
  profile, including power, heart rate, VE, VT, BR, Moxy SmO2/THb,
  core/skin temperature and environmental temperature/humidity.
- Include a fueling assessment in workout analyses when EatMyRide data or
  user-provided intake is available. If products are missing from EatMyRide,
  distinguish logged fueling from likely real fueling and state the uncertainty.

## Data Source Priority

- Default activity-load source priority is Xert, then Garmin, then Intervals.icu.
- The user may override this priority for a specific analysis.
- Xert is preferred by default because of the MPA model and its activity-level XSS, low/high/peak XSS, XEP, focus, specificity, difficulty, freshness/status and fitness-signature context.
