---
name: yr
description: Use when working with Yr/MET Norway Locationforecast data, weather forecasts, forecast source semantics, or live Yr forecast access.
---

# Yr

## Start Here

```bash
python3 -B plugins/yr/scripts/yr_cli.py
python3 -B plugins/yr/scripts/yr_cli.py --lat 60.0000 --lon 10.0000 --timezone Europe/Oslo --hourly --from-local YYYY-MM-DDT08:00 --to-local YYYY-MM-DDT20:00
```

The CLI prints live Locationforecast JSON. Use `--hourly` with the forecast
location's IANA timezone for compact time-window rows. Use explicit coordinates
for each materially different route area rather than treating one point as a
whole-route forecast.

## Source Semantics

Read [references/locationforecast.md](references/locationforecast.md) before
interpreting fields, units, periods, uncertainty, or route limitations.

## Boundaries

- This plugin owns live point-forecast access and Yr/MET Norway semantics.
- The caller chooses forecast points, combines multi-point results, applies
  domain context, and owns persistence, plotting, reports, and decisions.
