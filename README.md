# Training AI

Utilities for downloading and analysing cycling training data.

## Local plugins

This repo includes local Codex plugins under `plugins/`. They keep
source-specific live access, field semantics and write-safety rules separate
from this repo's persistence, orchestration and cross-source analysis.

- Xert: `plugins/xert/skills/xert/SKILL.md`
- EatMyRide: `plugins/eatmyride/skills/eatmyride/SKILL.md`
- Yr: `plugins/yr/skills/yr/SKILL.md`
- Garmin Connect: `plugins/garmin-connect/skills/garmin-connect/SKILL.md`
- Intervals.icu: `plugins/intervals-icu/skills/intervals-icu/SKILL.md`

## Use Intervals.icu

Intervals.icu source semantics, API access and write-safety rules live in the
local plugin. Start with `plugins/intervals-icu/skills/intervals-icu/SKILL.md`.

## Use Xert

Xert source semantics, live access, CLI examples and write-safety rules live in
the local plugin. Start with `plugins/xert/skills/xert/SKILL.md`.

Fetch Xert data live through the plugin for current analysis, summaries,
readiness or recommendations, and pass only normalized source-aware output to
repo-level helpers such as
`scripts/readiness_snapshot.py`.

## Use EatMyRide

EatMyRide live access, source semantics, CLI examples and write-safety rules
live in the local plugin. Start with
`plugins/eatmyride/skills/eatmyride/SKILL.md`.

Fetch EatMyRide data live through the plugin for current analysis, fueling
checks or recommendations.

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

## Fetch health data from Garmin Connect

Garmin Connect does not provide a simple public personal API. For local personal
use, this project uses `gccli`, with credentials managed by `gccli auth login`
outside the repository. Source-specific access and interpretation live in the
repo-local Garmin Connect plugin at
`plugins/garmin-connect/skills/garmin-connect/SKILL.md`. Garmin Connect data is
fetched live through the plugin.

Install and authenticate:

```bash
/opt/homebrew/bin/brew install bpauli/tap/gccli
/opt/homebrew/bin/gccli auth login
```

Fetch Garmin readiness/health data:

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day 2026-05-14
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py recent --days 7 --until 2026-05-14
```

`day` fetches all daily Garmin health sources used for readiness checks,
including heart rate, stress, HRV, sleep, summary, training readiness and
training status. `--only` is available for targeted debugging, but normal
readiness work should fetch the whole day so the sources stay in sync.

Use `python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py status`
only for troubleshooting `gccli` authentication. It does not fetch readiness
data.

Fetch Garmin metadata for a specific activity when Garmin's activity-level
assessment is useful:

```bash
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py activity i148448596
```

`activity` fetches Garmin activity metadata such as Training Effect, stamina,
performance condition and secondary Garmin load context. It accepts either a
Garmin activity id or a saved Intervals.icu artifact id; for Intervals
artifacts from Garmin Connect it uses `external_id` as the Garmin activity id.
Use `--summary-only` when the chart details are not needed.

## Build readiness context

Build a compact readiness context for chat. The script reads local Intervals.icu
inputs when present, accepts a Garmin Connect day JSON with `--garmin-json`,
and accepts a normalized Xert readiness JSON with only the selected fields this
repo needs:

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
python3 -B plugins/garmin-connect/scripts/garmin_connect_cli.py day 2026-05-14 > /tmp/garmin-connect-day.json
python3 -B scripts/readiness_snapshot.py --date 2026-05-14 --garmin-json /tmp/garmin-connect-day.json --xert-json /tmp/xert-readiness.json
```

The readiness script does not call source plugins itself and does not parse raw
Xert API payloads; source-specific field interpretation belongs to the source
plugin or the orchestration layer above this script. The repo-level contracts
are the Garmin Connect day JSON passed with `--garmin-json` and the normalized
Xert JSON passed with `--xert-json`.
