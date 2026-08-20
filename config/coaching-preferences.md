# Coaching Preferences

This file describes how training recommendations should be selected, executed,
and presented. Facts about locations, equipment, sensors, and products belong
in `practical-context.md`.

## Planning

- Earliest preferred workout start: `09:00`.
- Latest reasonable workout start: `20:30`.
- Latest normal workout end: `21:15`.
- Reserve `15 minutes` before a workout for setup and `15 minutes` afterward
  for cleanup.

### Outlook Calendar Interpretation

- Treat `Focus time` and `X` as open training time.
- Treat tentative events as non-blocking, but disclose any overlap by name and
  time.
- Treat `Lunsj` and `Middag` as movable meal requirements. Preserve the
  scheduled meal duration when moving it is sufficient; shorten `Lunsj` to 30
  minutes only when a concrete constraint requires it.
- Treat accepted meetings and fixed appointments as blocking unless the user
  says otherwise.
- Check the complete occupied window, including setup and cleanup, while
  displaying the actual workout start separately.
- Report the slack after cleanup to the next fixed appointment and name that
  appointment as the hard stop. If none exists, say so.
- If the complete dose does not fit, show the intended dose, executable dose,
  shortfall, constraint, remainder disposition, and smallest optional calendar
  change that would make it fit.
- Estimate meeting movability from available attendee evidence and label the
  estimate uncertain when that evidence is incomplete.
- A large all-hands Teams meeting may be treated as non-blocking for indoor
  cycling when passive attendance and no active role are reasonable. Disclose
  that assumption; never apply it to outdoor cycling.

## Workout Segmentation

- For workout analysis, prefer detecting the actual work segment from the power trace rather than using fixed durations.

## Indoor Workouts

- Assume indoor trainer recommendations are ridden in ERG mode by default.
- When I ask to update or prepare “today’s workout”, update `XMB VT2 TODAY` or
  `XMB VO2Max TODAY` according to the selected workout domain and current final
  recommendation. Normally preserve the existing warm-up and cool-down.
- For structured indoor ERG workouts, keep interval prescriptions simple and flat by default.
- When recommending an existing Xert/XMB workout as-is, treat its warmup and
  cooldown as included in the listed total duration. Do not add a separate
  warmup instruction unless the recommendation explicitly modifies or extends
  the workout.
- Describe ERG prescriptions as fixed workout targets or workout-intensity
  adjustments, not as drifting or gliding above the target.
- Use the same watt target for every work interval unless the user explicitly asks for progressive stepping or lifting the final interval.
- Use slope mode only when it is explicitly requested or when the workout purpose
  naturally calls for it, typically VO2Max, opener, standing, or harder
  over-threshold work.
- Prefer existing suitable workout-library options over inventing a parallel
  structure in chat.
- When several workout-library options fit the same goal, present a short menu
  of relevant indoor options rather than only one winner. Include at least
  conservative/normal duration choices when both are reasonable for readiness
  and available time.
- Suggest changes to XMB workout power, duration, or repetitions only when readiness, load target, available time, or session goal gives a concrete reason. Do not vary structure just for variety.

## Xert Workout Selection

- When ranking Xert recommended workouts, filter to actual workouts first, then
  rank by the user's goal, XSS split, duration, focus, suitability, difficulty
  and workout-library fit.

## Nutrition

- For EatMyRide-specific field semantics and write-safety, use the repo-local
  `eatmyride` plugin skill.
- When recommending practical fueling, convert carbohydrate targets into
  countable on-bike actions instead of only grams per hour.
- Use `1 x 1000 ml` indoors by default, adding a refill or second bottle for
  sessions well beyond 90 minutes or in a hot room.
- Use `2 x 750 ml` outdoors for shorter or moderate rides and `2 x 1000 ml`
  when duration, heat, or intensity increases.
- Use `60-80 g carbohydrate/hour` as the normal long outdoor target unless the
  session calls for something else.
- Translate the target into SiS plus countable seigmenn. A simple default cue is
  `2 seigmenn every 15-20 minutes from the start`, adjusted for drink strength.

## Outdoor Routes

- Prefer road cycling routes over gravel routes when both are reasonable options
  for the day's training goal.
- When deciding whether a saved route reference is gravel or road, check the
  bike/gear registered on the source activity instead of relying only on route
  name, map shape, or description text.
- Sandungen is not one route family: Sandungen in Nordmarka is gravel, while
  Sandungen in Vestmarka is a road route.
- Treat Tryvannstarnet/Tryvannstarnet-style climbs and Olav Bulls vei as
  interval/climbing routes. Do not recommend them for normal VT1 route options
  unless the session is VT2/harder or the user explicitly asks for hill
  intervals.
- For VT1 route recommendations, account for terrain quality and whether the
  road allows good steady flow. Prefer routes where power can be held smoothly
  with limited stop/start, technical sections, or interval-like climbs.
- Always include the Intervals.icu link to the reference activity for route
  recommendations.
- Exclude route references whose activity comment/description says they were
  with HCK when recommending solo VT1 routes, because intensity, watts,
  duration, and speed from group rides are not representative for solo
  prescriptions.

## Workout Analysis Expectations

- When the user asks to analyze a workout, inspect the actual activity data
  rather than only metadata or title. Use the available streams from the
  practical context and source data.
- Include a fueling assessment in workout analyses when EatMyRide data or
  user-provided intake is available. If products are missing from EatMyRide,
  distinguish logged fueling from likely real fueling and state the uncertainty.

## Data Source Priority

- Default activity-load source priority is Xert, then Garmin, then Intervals.icu.
- The user may override this priority for a specific analysis.
- Xert is preferred by default because of the MPA model and its activity-level XSS, low/high/peak XSS, XEP, focus, specificity, difficulty, freshness/status and fitness-signature context.
- Before recommending VT2 or higher intensity, check today's Intervals.icu
  `soreness` wellness value. If it is missing, assume soreness is not limiting,
  provide the high-intensity recommendation normally, and ask Hans Petter to
  set today's soreness value in Intervals.icu. An explicit zero/no-soreness
  value counts as present; missing soreness must not block or downgrade the
  recommendation by itself.
