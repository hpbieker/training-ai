---
name: yr
description: Use when working with Yr/MET Norway Locationforecast data, weather forecasts, forecast source semantics, or live Yr forecast access.
---

# Yr

Use this skill for Yr/MET Norway-specific source access and source semantics. The plugin fetches live forecasts, but it does not store forecasts, perform domain-specific analysis, make downstream decisions, or plan routes.

## Start Here

Use the local CLI when Yr/MET Norway forecast data is needed:

```bash
python3 -B plugins/yr/scripts/yr_cli.py
python3 -B plugins/yr/scripts/yr_cli.py oslo
python3 -B plugins/yr/scripts/yr_cli.py --lat 60.0000 --lon 10.0000
```

The CLI fetches live Locationforecast data and prints JSON to stdout.

Known locations include:

- `oslo`: Oslo point forecast.

For a custom point, pass both `--lat` and `--lon`. For a planned route or other multi-point scenario, fetch one forecast per relevant time/place point, then let the caller combine those point forecasts for the final use case.

## Source Semantics

Read `references/locationforecast.md` before interpreting Yr/MET Norway Locationforecast fields, update cadence, uncertainty, or route-weather limitations.

## Boundaries

This plugin owns:

- Yr/MET Norway Locationforecast API access.
- Yr/MET Norway field interpretation and source quirks.
- Live forecast fetching through the CLI.

The caller owns:

- choosing which place, coordinate, or route time/place points to fetch.
- combining weather with domain-specific context or user preferences.
- plotting and report generation.
