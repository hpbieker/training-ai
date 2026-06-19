#!/usr/bin/env python3
"""Fetch MET Norway / Yr Locationforecast data."""

from __future__ import annotations

import argparse
import json

from yr_weather import fetch_locationforecast


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
    print(json.dumps(forecast, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
