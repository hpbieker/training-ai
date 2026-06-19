# Training AI

Utilities for downloading and analysing cycling training data.

## Local plugins

This repo includes local Codex plugins under `plugins/`. They keep
source-specific live access, field semantics and write-safety rules separate
from this repo's persistence, orchestration and cross-source analysis.

- Xert: `plugins/xert/skills/xert/SKILL.md`
- EatMyRide: `plugins/eatmyride/skills/eatmyride/SKILL.md`
- Yr: `plugins/yr/skills/yr/SKILL.md`

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

## Use Xert

Xert source semantics, live access, CLI examples and write-safety rules live in
the local plugin. Start with `plugins/xert/skills/xert/SKILL.md`.

Do not use `data/xert` or other local Xert caches for current analysis,
summaries, readiness or recommendations. Fetch Xert data live through the plugin
and pass only normalized source-aware output to repo-level helpers such as
`scripts/readiness_snapshot.py`.

## Use EatMyRide

EatMyRide live access, source semantics, CLI examples and write-safety rules
live in the local plugin. Start with
`plugins/eatmyride/skills/eatmyride/SKILL.md`.

Do not use `data/eatmyride` or other local EatMyRide caches for current
analysis, fueling checks or recommendations. Fetch EatMyRide data live through
the plugin. Historical files may still be plotted when the user explicitly
selects a local artifact.

## Use Yr / MET Norway

Yr/MET Norway forecast access, source semantics and CLI examples live in the
local plugin. Start with `plugins/yr/skills/yr/SKILL.md`.

```bash
python3 -B plugins/yr/scripts/yr_cli.py
python3 -B plugins/yr/scripts/yr_cli.py <known-location>
python3 -B plugins/yr/scripts/yr_cli.py --lat 60.0000 --lon 10.0000
```

Forecasts are fetched live and printed to stdout. The Yr plugin does not write
local weather files.

The API requires a non-generic User-Agent. The plugin client sets one by
default.

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

## Build readiness context

Build a compact readiness context for chat. The script reads local Garmin and
Intervals.icu inputs when present, and accepts a normalized Xert readiness JSON
with only the selected fields this repo needs:

```json
{
  "source_time_local": "2026-05-14T08:15:00+02:00",
  "recovery": {
    "recovery_hours": {"low": -3.5, "high": 12.0, "peak": 24.0},
    "training_load": {"low": 125.0, "high": 1.2, "peak": 0.4},
    "recovery_load": {"low": 90.0, "high": 0.8, "peak": 0.2},
    "workout_capacity": {"low": 250.0, "high": 8.0, "peak": 1.0},
    "training_status": {"form_cat": "Fresh"}
  },
  "activity_loads": [
    {
      "start_local": "2026-05-13T17:30:00",
      "name": "Endurance ride",
      "xss": {"total": 75.0, "low": 70.0, "high": 4.0, "peak": 1.0},
      "difficulty": 42.0,
      "difficulty_rating": "Moderate"
    }
  ]
}
```

```bash
python3 -B scripts/readiness_snapshot.py --date 2026-05-14 --xert-json /tmp/xert-readiness.json
```

The readiness script does not call source plugins itself and does not parse raw
source API payloads; source-specific field interpretation belongs to the source
plugin or the orchestration layer above this script. The only repo-level
contract is the normalized JSON passed with `--xert-json`.

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
