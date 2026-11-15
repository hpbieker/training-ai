# Training AI

Tools for analysing cycling workouts, managing training plans, and recommending
daily sessions and routes. Local Codex plugins connect the workflows to
training, health, and weather data.

## Getting started

1. Open this repository in Codex and make sure `uv` is available. The local MCP
   plugins use it to create their Python environments when they start.
2. Use the [plugin catalog](.agents/plugins/marketplace.json) to find the plugins
   for your data sources. Follow [Data source setup](#data-source-setup) for
   credentials and service-specific settings.
3. Use [`$training-analysis`](.agents/skills/training-analysis/SKILL.md) in Codex
   for workout analysis, readiness, daily recommendations or routes. Use
   [`$training-plan`](.agents/skills/training-plan/SKILL.md) to create or update a
   training plan.

## Usage

Ask Codex in plain language. For example:

- “Analyse my latest ride. How steady was the effort?”
- “What should I ride today given my training plan, recovery and available time?”
- “Find a paved endurance route from my saved rides that fits a 90-minute session.”
- “Help me adjust next week's training plan around my travel days.”

## Data source setup

### Intervals.icu

Intervals.icu source semantics, MCP access and write-safety rules live in the
local plugin. Start with `plugins/intervals-icu/skills/intervals-icu/SKILL.md`.

For first-time MCP setup, store the Intervals.icu API key in the user-owned
`~/.intervals_icu_mcp.json` file:

```json
{"apiKey":"..."}
```

`INTERVALS_ICU_API_KEY` can override the file. The MCP server loads the key at
startup; it is not passed as a tool argument.

### Olympiatoppen

Olympiatoppen diary reads are available through the local plugin in
`plugins/olympiatoppen/skills/olympiatoppen/SKILL.md`. Install the plugin to
use `list_workouts` and `get_activity`; renew the private browser session with
`import_session` from the authenticated Nettleser session when authentication
is required.

### Xert

Xert source semantics, live access, CLI examples and write-safety rules live in
the local plugin. Start with `plugins/xert/skills/xert/SKILL.md`.

Fetch Xert data live through the plugin for current analysis, summaries,
readiness or recommendations, and pass only normalized source-aware output to
repo-level helpers such as
`scripts/readiness_snapshot.py`.

### EatMyRide

EatMyRide live access, source semantics, CLI examples and write-safety rules
live in the local plugin. Start with
`plugins/eatmyride/skills/eatmyride/SKILL.md`.

Fetch EatMyRide data live through the plugin for current analysis, fueling
checks or recommendations.

### Yr / MET Norway

Yr/MET Norway forecast access and source semantics live in the local plugin.
Start with `plugins/yr/skills/yr/SKILL.md` and use its `get_forecast` or bounded
batch `get_forecasts` MCP tool for live forecast reads. Pass normalized MCP
output to repo helpers through their source-input arguments.

Historical station data uses Frost through `find_observation_stations`,
`get_observation_series`, and bounded point/time batch `get_observations`.
Store the public-archive client ID in `~/.yr_mcp.json` as
`{"frost": {"client_id": "<your-client-id>"}}`, with file permissions 0600.
Historical tools retain station identity, measurement times, sensor levels,
periods and quality codes; route interpretation stays outside the plugin.

The API requires a non-generic User-Agent. The MCP's source client sets one by
default.

Source documentation:

- https://api.met.no/weatherapi/locationforecast/2.0/documentation
- https://api.met.no/doc/GettingStarted

### Garmin Connect

To enable automatic login on first use, add your Garmin credentials to
`~/.garmin_mcp.json`:

```json
{
  "username": "example@example.com",
  "password": "<garmin-password>"
}
```

Use `chmod 600 ~/.garmin_mcp.json`. Set `GARMIN_MCP_CONFIG` to select a
different file. If Garmin requires MFA, enter the code in a terminal. After
the local plugin has started and created its Python environment, run this
command from the repository root:

```sh
plugins/garmin-connect/.venv/bin/python -B plugins/garmin-connect/scripts/garmin_connect_auth.py login
```

Python stores the session in `~/.config/training-ai/garmin` and refreshes it
when needed.
Set `TRAINING_AI_GARMIN_TOKEN_STORE` to use a separate directory.

Use the Garmin Connect MCP tools for live reads. See the
[Garmin Connect skill](plugins/garmin-connect/skills/garmin-connect/SKILL.md)
for tool examples and interpretation of Garmin fields.

## Development and tests

Run all core and plugin tests from the repository root:

```sh
uv run --no-project \
  --with-requirements plugins/strava/requirements.txt \
  --with-requirements plugins/training-visuals/requirements.txt \
  --with matplotlib \
  python -B tests/run_all.py
```

Core and cross-plugin tests live in `tests/`. Plugin-specific tests live in
`plugins/<name>/tests/`. The runner starts a separate Python process for each
suite. `tests/test_plugin_startup.py` checks every plugin's launch command and
tool catalog without a service login. The first run may download dependencies.
