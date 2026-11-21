# Training AI

Tools for analysing cycling workouts, managing training plans, and recommending
daily sessions and routes. Local Codex plugins connect the workflows to
training, health, and weather data.

## Getting started

1. Open this repository in Codex and make sure `uv` is available.
2. Use the [plugin catalog](.agents/plugins/marketplace.json) to find the plugins
   for your data sources.
3. Follow [Plugin installation](#plugin-installation) to build and install
   the plugins.
4. Follow [Data source setup](#data-source-setup) to configure the plugins.
5. Use [`$training-analysis`](.agents/skills/training-analysis/SKILL.md) in Codex
   for workout analysis, readiness, daily recommendations or routes. Use
   [`$training-plan`](.agents/skills/training-plan/SKILL.md) to create or update a
   training plan.

Keep your preferences, plans and plan state in the local `config/` directory.
See [Personal configuration](docs/personal-configuration.md) for the file layout
and initial plan state.

## Plugin installation

With the local `training-ai` marketplace configured, build and install each
plugin by its name from the catalog:

```sh
python3 scripts/build_plugin.py xert
codex plugin add xert@training-ai
```

The build targets macOS arm64 because the locked `cryptography` release
publishes macOS wheels for arm64 only. It uses `uv` to install Python 3.13 if
needed and packages the locked dependencies in `dist/<plugin>/.venv`. Codex
starts the bundled interpreter directly. Keep the base Python 3.13
installation.

## Usage

Ask Codex in plain language. For example:

- “Analyse my latest ride. How steady was the effort?”
- “What should I ride today given my training plan, recovery and available time?”
- “Find a paved endurance route from my saved rides that fits a 90-minute session.”
- “Help me adjust next week's training plan around my travel days.”

## Data source setup

Configure only the plugins you use. Keep credential files outside the
repository and restrict files containing secrets to mode `0600`.

### EatMyRide

**Authentication.** Create `~/.eatmyride_mcp.json` in your home directory.
Replace the example values with the email address and password you use to sign
in to EatMyRide. The plugin reads this file when it needs to sign in.

```json
{
  "username": "you@example.com",
  "password": "<eatmyride-password>"
}
```

[EatMyRide plugin guide](plugins/eatmyride/skills/eatmyride/SKILL.md#authentication-and-boundaries)

### Garmin Connect

**Authentication.** Store your Garmin `username` and `password` in
`~/.garmin_mcp.json`.

```json
{
  "username": "you@example.com",
  "password": "<garmin-password>"
}
```

[Garmin Connect plugin guide](plugins/garmin-connect/skills/garmin-connect/SKILL.md)

### Intervals.icu

**Authentication.** Store your Intervals.icu API key as `apiKey` in
`~/.intervals_icu_mcp.json`.

```json
{
  "apiKey": "<intervals-api-key>"
}
```

[Intervals.icu plugin guide](plugins/intervals-icu/skills/intervals-icu/SKILL.md)

### Komoot

**Authentication.** Sign in to Komoot in Safari and make sure the local
[curl-safari](https://github.com/hpbieker/codex-plugin-curl-safari) cookie service
is running. The plugin uses the existing Safari
session through that service.

[Komoot plugin guide](plugins/komoot/skills/komoot/SKILL.md)

### Olympiatoppen

**Authentication.** Sign in to the training diary in the Codex browser.
When the plugin reports `auth_required`, follow the session setup in the
plugin guide. The plugin's `import_session` tool verifies and saves the
browser session for subsequent requests.

[Olympiatoppen plugin guide](plugins/olympiatoppen/skills/olympiatoppen/SKILL.md#session-setup)

### Strava

**Authentication.** Import a signed-in Safari session on your Mac.

1. Sign in to Strava in Safari and open a page that requires your account,
   such as your training log.
2. Open Safari Web Inspector, select **Network**, and reload the page. Find
   a request to `www.strava.com` whose request headers include `Cookie`.
   Right-click that request and choose **Copy as cURL**.
3. With the request still on your clipboard, run this from the repository root:

   ```sh
   python3 -B plugins/strava/scripts/strava_session.py import-curl
   ```

The importer reads the clipboard directly and verifies the session before
saving the cookie header locally. Repeat these steps if the plugin returns
`auth_required`.

[Strava plugin guide](plugins/strava/skills/strava/SKILL.md#authentication)

### Xert

**Authentication.** Fill in all four fields in `~/.xert_mcp.json`.

```json
{
  "username": "you@example.com",
  "password": "<xert-password>",
  "oauthClientId": "<xert-client-key>",
  "oauthClientSecret": "<xert-client-secret>"
}
```

[Xert plugin guide](plugins/xert/skills/xert/SKILL.md#writes-and-access)

### Yr / MET Norway

**Authentication.** Forecasts require no credentials. For historical station
observations, save a Frost client ID in `~/.yr_mcp.json` under
`frost.client_id`. See [MET Norway's guide to getting a Frost client ID](https://frost.met.no/howto.html).
Public observations require only the client ID.

```json
{
  "frost": {
    "client_id": "<frost-client-id>"
  }
}
```

[Yr plugin guide](plugins/yr/skills/yr/SKILL.md)

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
