#!/usr/bin/env python3
"""Cache MET Norway / Yr Locationforecast data for local training planning."""

from __future__ import annotations

import argparse

from yr_weather import cache_locationforecast


KNOWN_LOCATIONS = {
    "oslo": {"latitude": 59.9139, "longitude": 10.7522, "altitude": 23},
    "lier": {"latitude": 59.7866, "longitude": 10.2459, "altitude": 70},
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache Yr/MET Locationforecast weather data.",
    )
    parser.add_argument(
        "location",
        nargs="?",
        default="oslo",
        help="Known location name, default: oslo. Known: oslo, lier.",
    )
    parser.add_argument("--lat", type=float, help="Latitude for a custom location")
    parser.add_argument("--lon", type=float, help="Longitude for a custom location")
    parser.add_argument("--altitude", type=int, help="Altitude in meters")
    parser.add_argument("--label", help="Cache folder label for custom coordinates")
    args = parser.parse_args()

    if args.lat is not None or args.lon is not None:
        if args.lat is None or args.lon is None:
            raise SystemExit("Use both --lat and --lon for custom coordinates")
        location = {
            "latitude": args.lat,
            "longitude": args.lon,
            "altitude": args.altitude,
        }
        label = args.label or "custom"
    else:
        key = args.location.lower()
        if key not in KNOWN_LOCATIONS:
            known = ", ".join(sorted(KNOWN_LOCATIONS))
            raise SystemExit(f"Unknown location {args.location!r}. Known: {known}")
        location = KNOWN_LOCATIONS[key]
        label = args.label or key

    artifacts = cache_locationforecast(label=label, **location)
    for name, path in artifacts.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
