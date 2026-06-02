# Training AI

Utilities for downloading and analysing cycling training data.

## Download data from Intervals.icu

Create an Intervals.icu API key in your account settings, then run:

```python
import os

from scripts.intervals_api import cache_latest_activity_streams, download_intervals_icu_data

artifacts = download_intervals_icu_data(
    api_key=os.environ["INTERVALS_ICU_API_KEY"],
    oldest="2026-01-01",
    newest="2026-01-31",
    output_dir="data",
    include_activity_details=True,
    include_intervals=True,
    download_activity_files=True,
    activity_file_kind="fit",
)

print(artifacts)
```

To cache streams for the newest activity:

```python
artifacts = cache_latest_activity_streams(
    api_key=os.environ["INTERVALS_ICU_API_KEY"],
)
```

Or use the CLI wrapper:

```bash
python3 -B scripts/cache_intervals_icu.py latest
python3 -B scripts/cache_intervals_icu.py activity i147489723
python3 -B scripts/cache_intervals_icu.py named VT2 --since 2026-01-01
python3 -B scripts/cache_intervals_icu.py named VT1 --since 2026-01-01
python3 -B scripts/cache_intervals_icu.py wellness --since 2026-01-01
python3 -B scripts/cache_intervals_icu.py file i150612397 --kind original
python3 -B scripts/cache_intervals_icu.py file i150612397 --kind web-original
```

For recurring local use, whitelist the narrow command prefix:

```text
["python3", "-B", "scripts/cache_intervals_icu.py"]
```

`file --kind web-original` uses the web/session endpoint
`https://intervals.icu/api/activity/<id>/file` and requires
`INTERVALS_ICU_COOKIE` in `.env`. The regular `file --kind original` command
uses the API-key endpoint under `/api/v1`.

Metadata updates, such as renaming activities in Intervals.icu, use a separate
script so the cache script stays download-only:

```bash
python3 -B scripts/update_intervals_icu.py rename i148170330 "VT1 180 min"
```

Activity-specific files are stored under:

```text
data/
  activities/
    2026-05-12_i147489723/
      activity.json
      streams.csv
  activity_summaries/
    2026-01-01_2026-01-31.csv
    2026-01-01_2026-01-31.json
  wellness/
    2026-01-01_2026-05-14.csv
    2026-01-01_2026-05-14.json
```

By default `athlete_id=0`, which means Intervals.icu uses the athlete connected
to the API key or OAuth token.

The generated FIT files are the best starting point for detailed stream
analysis of watt, heart rate, VE, BR, VT, SmO2, THb, core temperature, skin
temperature and air temperature, assuming those streams exist in the original
activity or in Intervals.icu's generated FIT export.

## OAuth

For a multi-user app, pass `bearer_token` instead of `api_key`:

```python
download_intervals_icu_data(
    bearer_token="...",
    oldest="2026-01-01",
    newest="2026-01-31",
)
```

## Download data from Xert

Xert can add activity-level strain and difficulty context such as XSS, low/high/
peak XSS, XEP, focus, specificity, difficulty rating and the fitness signature
used for the activity.

Add credentials to `.env`:

```text
XERT_USERNAME=your-email@example.com
XERT_PASSWORD=your-password
# Optional for Xert web calendar endpoints that require browser session auth:
XERT_COOKIE='cookie-name=value; another-cookie=value'
```

Then cache activity summaries:

```bash
python3 -B scripts/cache_xert.py activities --since 2026-01-01
python3 -B scripts/cache_xert.py training-info
python3 -B scripts/cache_xert.py recovery-model
python3 -B scripts/cache_xert.py workouts
python3 -B scripts/cache_xert.py workouts --filter "XMB: VT1" --summary
python3 -B scripts/cache_xert.py training-forecast
python3 -B scripts/xert_advice.py
```

`training-info` caches Xert's current status, signature, training load and
target XSS. `recovery-model` is the default readiness source: it logs in to Xert
web, reads `trainingAdvice`/`trainingPlan` from `/my-fitness`, reads `ir_params`
from `/profile/settings`, and calculates recovery days and workout capacity
locally. Negative recovery hours mean the athlete is on the fresh side of the
relevant Xert threshold.

### Xert web calendar endpoints

Some Xert calendar functionality is available only through an authenticated web
session. The local helper can log in through `/auth`, extract the Laravel CSRF
token, post credentials to `/auth/login`, and reuse the resulting cookie jar.
`XERT_COOKIE` can still be supplied manually, but username/password web login is
preferred when it works.

Known OAuth endpoints:

- `GET /oauth/workouts` lists the user's own Xert workout library.
- `GET /oauth/workout/<path>` retrieves one resolved workout using the user's
  current fitness signature, returning target power in watts and interval
  durations. Use the `path` from the workouts list. The OAuth workout endpoints
  are useful for reading/listing, but they do not provide the designer rows
  needed to edit a workout.

Known web endpoints:

- `GET /calendar/training-forecast?duration=-1&includePlaceholders=true`
  returns the current Forecast AI calendar days.
- `GET /calendar/forecast-activities-close/<YYYY-MM-DD>` returns nearby
  forecast/calendar activities, training status array and target-event context.
- `GET /calendar/get-notes` returns calendar notes keyed by local calendar date
  for the authenticated user. It does not need `forUser` for the current user.
  Prefer `python3 -B scripts/cache_xert.py calendar-notes`, which writes the
  response to `data/xert/calendar_notes_<date>.json`.
- `POST /calendar/save-notes` updates one calendar note. Prefer
  `python3 -B scripts/cache_xert.py set-calendar-note YYYY-MM-DD "VT1"`, which
  sends the minimal JSON payload and then reads back `get-notes` to verify.
  The date argument is a user-local calendar date; the helper converts local
  midnight to Xert's UTC ISO value, for example Oslo `2026-05-27` becomes
  `2026-05-26T22:00:00.000Z`. The web request needs only the authenticated
  cookie jar plus `Content-Type: application/json`, `X-CSRF-TOKEN` and
  `X-Requested-With: XMLHttpRequest`.
- `GET /recommended-training?recent=true&date=<UTC-ISO>&additional=false&sport=Cycling`
  returns Xert workout/activity recommendations for a date. The `exercises`
  array contains recommended workouts and activities, not only a small
  recommendation list. Filter by `exerciseType == "Workout"` when selecting a
  workout from recommendations, and then rank by XSS split, duration, focus,
  suitability, difficulty and naming preference. For the user's own workout
  library, prefer the OAuth `workouts`/`workout` endpoints above.
- `GET /workout/<path>` returns the web Workout Designer page when using an
  authenticated web-login cookie jar. The form action is `POST /workout/<path>`
  and contains the CSRF token, workout title, description and signature fields.
- `GET /workout/<path>/intervals` returns the editable Workout Designer rows as
  JSON. These rows preserve designer concepts such as interval groups, rest
  between intervals, relative power (`relative_ftp`, `ramp_ltp`, etc.) and
  `DT_RowId`; this is the correct source to modify a workout, not the resolved
  OAuth workout payload.
- To update an existing workout, log in via the web flow, read
  `/workout/<path>/intervals`, modify the relevant row values, then `POST` an
  `application/x-www-form-urlencoded` form to `/workout/<path>` with `_token`,
  `name`, `description`, `pp`, `atc` in joules, `ftp`, `submit=save`, and
  `rows=<JSON encoded designer rows>`. Use `submit=calculate` first when
  validating the edited rows without saving. A successful save returns JSON
  with `info: "Workout saved"`. Re-fetch both `workout <path>` and `workouts`
  after saving to verify the name, duration, XSS, difficulty and interval
  durations. Prefer the reusable CLI for this instead of ad hoc scripts:
  `python3 -B scripts/cache_xert.py update-workout <path> --match-name Intervals --match-power 300 --set-duration 26:00 --name "XMB: VT2 3x26 min (300W)"`.
- Use `workouts --filter ... --summary` for chat-friendly workout library
  listings. It prints name, duration, parsed work watts from names like
  `(205W)`, XSS split, difficulty and path.
- To create a workout variant, prefer
  `python3 -B scripts/cache_xert.py copy-workout <path> --name "..."`.
  Xert may append `(Copy)` during copy; the CLI re-fetches the new workout page
  and saves the requested name again when needed.
- `DELETE /workout/<path>` deletes a workout when using an authenticated web
  session. Send `X-Requested-With: XMLHttpRequest`. This is destructive: only
  use it after explicit confirmation, then re-fetch `workouts` to verify the
  workout disappeared from the library. Prefer
  `python3 -B scripts/cache_xert.py delete-workout <path> --yes`.
- `GET /profile/settings` returns the profile settings page. Use the web-login
  cookie jar, parse the returned HTML, and extract embedded JSON from `<script>`
  blocks. The user/IR settings are exposed in script text containing
  `window.user_params =`; parse the JSON object following keys such as
  `ir_params` when time constants or recovery-model settings are needed. The
  profile username can also be read from the first `span.username` text.
- `POST /createCalendarEvent` creates a planned calendar event/workout.
- `POST /pinCalendarEvent` toggles pinning for a calendar item.
- `POST /deleteCalendarEvent` deletes a calendar item.

Adapt Forecast is not just a simple server-side `POST`. Xert's UI loads
`/calendar/training-forecast` data, runs the adaptation in the browser via
`/js/libxert-worker.js`, then shows a confirmation step. Saving the adapted
forecast posts to `/account/settings/training-program` with a payload including
`fromDate`, `toDate`, `duration`, `program_type: "targetEvent"` and the computed
`result`. Do not automate the save step without explicit confirmation, because
Xert warns that unpinned planned activities may be removed.

Use `--session-data` only when you need per-second Xert fields such as MPA,
XDS and TWS:

```bash
python3 -B scripts/cache_xert.py activities --since 2026-05-01 --session-data
```

Xert files are stored under:

```text
data/
  xert/
    activity_summaries/
      2026-01-01_2026-05-14.csv
      2026-01-01_2026-05-14.json
    activities/
      2026-05-14_<xert-path>/
        activity.json
    training_info_2026-05-14.json
    recovery_model_2026-05-14.json
```

For recurring local use, whitelist the narrow command prefix:

```text
["python3", "-B", "scripts/cache_xert.py"]
```

## Download weather from Yr / MET Norway

Use MET Norway's public Locationforecast API, the same forecast source used by
Yr, for training-weather decisions.

```bash
python3 -B scripts/cache_yr_weather.py oslo
python3 -B scripts/cache_yr_weather.py lier
python3 -B scripts/cache_yr_weather.py --lat 59.91 --lon 10.75 --label custom-oslo
```

Forecasts are stored under:

```text
data/
  weather/
    oslo/
      yr_locationforecast_2026-05-14_163000.json
      yr_locationforecast_2026-05-14_163000.csv
```

The API requires a non-generic User-Agent. The local client sets one by default.

Source documentation:

- https://api.met.no/weatherapi/locationforecast/2.0/documentation
- https://api.met.no/doc/GettingStarted

## Download health data from Garmin Connect

Garmin Connect does not provide a simple public personal API. For local personal
use, this project uses `gccli`, with credentials managed by `gccli auth login`
outside the repository.

Install and authenticate:

```bash
/opt/homebrew/bin/brew install bpauli/tap/gccli
/opt/homebrew/bin/gccli auth login
```

Cache Garmin readiness/health data:

```bash
python3 -B scripts/cache_garmin.py day 2026-05-14
python3 -B scripts/cache_garmin.py recent --days 7 --until 2026-05-14
```

`day` refreshes all daily Garmin health sources used for readiness checks,
including heart rate, stress, HRV, sleep, summary, training readiness and
training status. `--only` is available for targeted debugging, but normal
readiness work should refresh the whole day so the sources stay in sync.

Use `python3 -B scripts/cache_garmin.py status` only for troubleshooting
`gccli` authentication. It does not refresh readiness data.

Cache Garmin metadata for a specific activity when Garmin's activity-level
assessment is useful:

```bash
python3 -B scripts/cache_garmin.py activity i148448596
```

`activity` caches Garmin activity metadata such as Training Effect, stamina,
performance condition and secondary Garmin load context. It accepts either a
Garmin activity id or a cached Intervals.icu activity id; for Intervals
activities from Garmin Connect it uses `external_id` as the Garmin activity id.

EatMyRide's backend also exposes imported activities and the recorded food plan.
Add personal credentials to `.env`:

```text
EATMYRIDE_EMAIL=your-email@example.com
EATMYRIDE_PASSWORD=your-password
```

Cache an explicit EatMyRide activity id, all activities for one local Oslo
calendar date, or the latest activity:

```bash
python3 -B scripts/cache_eatmyride.py activity 6500779
python3 -B scripts/cache_eatmyride.py day 2026-05-22
python3 -B scripts/cache_eatmyride.py latest
python3 -B scripts/cache_eatmyride.py previous-foodplan --before 2026-06-01
```

The helper logs in for a fresh JWT without storing the token. It caches activity
details and recorded intake events under:

```text
data/eatmyride/
  activity_lists/2026-05-22.json
  activities/2026-05-22_6500779/
    activity.json
    foodplan.json
```

Food-plan writes replace the complete server-side list, so write commands
require an explicit `--yes`. Adjust one existing event, or replace a food plan
from a reviewed local JSON file:

```bash
python3 -B scripts/cache_eatmyride.py set-event 6528113 \
  --label "SiS GO Elektrolyte Orange" --match-time 900 \
  --time 0 --ml 200 --gram 16 --yes
python3 -B scripts/cache_eatmyride.py replace-foodplan 6528113 \
  data/eatmyride/activities/2026-06-01_6528113/foodplan.json --yes
```

Both commands trigger EatMyRide's activity recalculation, read back the
server-side state and refresh the local activity cache.

Build a compact readiness context for chat after refreshing caches:

```bash
python3 -B scripts/readiness_snapshot.py --date 2026-05-14
```

This summarizes cached Garmin, Xert and latest Intervals.icu activity data,
including post-workout heart rate and stress when a prior activity is found.

Files are stored under:

```text
data/
  garmin/
    training_readiness/2026-05-14.json
    body_battery/2026-05-08_2026-05-14.json
    stress/2026-05-14.json
    heart_rate/2026-05-14.json
    hrv/2026-05-14.json
    sleep/2026-05-14.json
    summary/2026-05-14.json
    training_status/2026-05-14.json
    activities/2026-05-15_22888238753/
      summary.json
      details.json
      metrics_summary.json
      manifest.json
```
