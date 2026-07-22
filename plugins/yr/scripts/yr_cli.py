#!/usr/bin/env python3
"""Fetch MET Norway / Yr Locationforecast data."""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from yr_weather import compact_hourly_forecast, fetch_locationforecast


KNOWN_LOCATIONS = {
    "oslo": {"latitude": 59.9139, "longitude": 10.7522, "altitude": 23},
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Yr/MET Locationforecast weather data.",
    )
    parser.add_argument(
        "location",
        nargs="?",
        default="oslo",
        help="Known location name, default: oslo.",
    )
    parser.add_argument("--lat", type=float, help="Latitude for a custom location")
    parser.add_argument("--lon", type=float, help="Longitude for a custom location")
    parser.add_argument("--altitude", type=int, help="Altitude in meters")
    parser.add_argument(
        "--hourly",
        action="store_true",
        help="Print compact hourly forecast rows instead of raw Locationforecast JSON.",
    )
    parser.add_argument("--from-local", help="Start local datetime for --hourly")
    parser.add_argument("--to-local", help="End local datetime for --hourly")
    args = parser.parse_args()

    if args.lat is not None or args.lon is not None:
        if args.lat is None or args.lon is None:
            raise SystemExit("Use both --lat and --lon for custom coordinates")
        location = {
            "latitude": args.lat,
            "longitude": args.lon,
            "altitude": args.altitude,
        }
    else:
        key = args.location.lower()
        if key not in KNOWN_LOCATIONS:
            known = ", ".join(sorted(KNOWN_LOCATIONS))
            raise SystemExit(f"Unknown location {args.location!r}. Known: {known}")
        location = KNOWN_LOCATIONS[key]

    forecast = fetch_locationforecast(**location)
    if args.hourly:
        payload = {
            "source": "yr_locationforecast",
            "location": location,
            "from_local": args.from_local,
            "to_local": args.to_local,
            "hourly": compact_hourly_forecast(
                forecast,
                from_local=parse_local_datetime(args.from_local),
                to_local=parse_local_datetime(args.to_local),
            ),
        }
    else:
        payload = forecast
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def parse_local_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


if __name__ == "__main__":
    main()
