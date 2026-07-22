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

## Same-day training recommendation

For "what should I train today?" use `recommend_today.py` as the primary
orchestrator. It fetches the standard live inputs, writes the full source packet
under `outputs/recommendations/<date>/`, ranks indoor XMB workouts, selects a
saved-history outdoor route, adds timing guidance, and prints a compact
chat-oriented summary with `--summary`.

Source refresh is cache-aware by default. `--refresh auto` reuses snapshots
within source-specific TTLs; `--refresh all` forces every source;
`--refresh garmin,xert` forces selected source groups; and `--refresh none`
uses existing files without network calls. The packet records the decision,
age, TTL, and reason for each source under `source_refresh`. An explicit
`--garmin-json <path>` overrides Garmin input and cannot be combined with a
forced Garmin refresh.

```bash
python3 -B scripts/recommend_today.py --date 2026-06-26 --planned-at 10:30 --target-minutes 75 --target-load 60 --summary
```

If the user does not give a training time, omit `--planned-at`; the packet will
mark the planned time as an assumed planning anchor and include
`coach_summary.timing_guidance`. Chat answers should mention that timing
guidance, including whether the time was assumed, the evaluated weather window,
and whether Garmin/watch sync is needed before considering a harder session.
When giving practical fueling, translate carbohydrate targets into countable
actions using `config/user-training-profile.md` when personal product
defaults are available. Keep concrete product choices and piece-count cues in
that profile rather than in code.

Use the full JSON output when debugging or when another script consumes the
packet:

```bash
python3 -B scripts/recommend_today.py --date 2026-06-26 --planned-at 10:30
```

The indoor workout ranking prefers `XMB: ` workouts. When multiple XMB workouts
fit the same goal, the packet includes `relevant_options` so chat answers can
show a short menu such as conservative, normal and longer duration choices
instead of only one winner. The default candidate list filters out threshold,
VO2, hard-power, high-average-power, and high-difficulty structures. Those
workouts are still retained as `higher_intensity_candidates` in the packet for
days where intensity is explicitly appropriate.

Daily dose guardrails use direct readiness domains rather than Garmin's
composite Training Readiness score: HRV/resting-HR response, sleep, Body
Battery, plus cumulative load context from ACWR and rolling-load percentile.
The previous day's individual workout is not weighted separately because its
effect should already appear in recovery and physiological response signals.
Training Readiness remains in the packet only as a
diagnostic agreement check and is marked `used_for_dose: false`.

For chat recommendations, assume indoor trainer workouts are ridden in ERG mode
unless the user says otherwise. Describe indoor options as fixed workout targets
or workout-intensity adjustments, not as free-riding above target watts. Reserve
slope mode language for explicitly requested slope sessions or workouts where it
naturally fits the purpose, typically VO2Max, opener, standing, or harder
over-threshold work.

## Recommend outdoor routes from history

For same-day outdoor training recommendations, prefer concrete route candidates
from saved Intervals.icu activity history instead of generic geography. The
route helper reads local `outputs/intervals/activities/*` packages, filters to
GPS-backed outdoor rides from the last five years, uses the caller-provided or
profile-resolved start/end anchor, and ranks candidates by fit to the planned
duration, load and distance.

```bash
python3 -B scripts/route_recommendations.py --date 2026-06-26 --years 5 --target-minutes 120 --target-load 100
```

Use `--query Sørkedalen` or another fragment only when the user asks for that
route family. Use `--allow-away` only when non-Oslo travel routes should be
eligible. In chat recommendations, cite the selected prior activity by route
name, date and activity id. The route helper's `url` field is the Intervals.icu
activity URL for the saved route reference; it is not a map image. When a route
is proposed in chat, embed the Xert route map image whenever available and the
chat surface supports Markdown images. In live recommendation packets, prefer
`xert_map_local_path` for Codex/app Markdown image embeds, for example
`![Xert-kart for <route>](<xert_map_local_path>)`, because app chat may not
render external asset URLs reliably. Fall back to `xert_map_url` when no local
copy exists. If the route packet lacks `xert_map_url`, fetch Xert activities for
the selected route date with `plugins/xert/scripts/xert_cli.py activities
<YYYY-MM-DD> <YYYY-MM-DD>`, match by route name/date/distance, and use that
row's `map_url` as the route map. If no Xert map can be found, say so explicitly
instead of silently omitting it. If Markdown image embedding is not supported,
include the direct map URL as a fallback.

Route results may include `route_flexibility` from GPS analysis. When
`scalable` is true, the route is not necessarily a fixed full-distance
prescription:

- `out_and_back_adjustable` means the ride substantially retraces the same road,
  so examples like Sørkedalen can be scaled by doing fewer/more loops or by
  turning earlier/later.
- `repeatable_segment_adjustable` means the activity contains a repeated
  corridor or climb, so interval routes such as OB/Olav Bulls vei or
  Gressbanen-Tryvann can be shortened by doing fewer repeats or shorter climbs.

For chat recommendations, prefer a direct short variant when one matches the
day. If only a longer scalable reference exists, prescribe the relevant fraction
or repeat count rather than treating the full historical route as mandatory.
