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
```

For recurring local use, whitelist the narrow command prefix:

```text
["python3", "-B", "scripts/cache_intervals_icu.py"]
```

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
```

Then cache activity summaries:

```bash
python3 -B scripts/cache_xert.py activities --since 2026-01-01
python3 -B scripts/cache_xert.py training-info
```

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
python3 -B scripts/cache_garmin.py status
python3 -B scripts/cache_garmin.py day 2026-05-14
python3 -B scripts/cache_garmin.py recent --days 7 --until 2026-05-14
```

Files are stored under:

```text
data/
  garmin/
    training_readiness/2026-05-14.json
    body_battery/2026-05-08_2026-05-14.json
    stress/2026-05-14.json
    hrv/2026-05-14.json
    sleep/2026-05-14.json
    summary/2026-05-14.json
    training_status/2026-05-14.json
```
