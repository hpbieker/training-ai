# Training AI

Utilities for downloading and analysing cycling training data.

## Download data from Intervals.icu

Create an Intervals.icu API key in your account settings, then run:

```python
import os

from intervals_icu import cache_latest_activity_streams, download_intervals_icu_data

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
