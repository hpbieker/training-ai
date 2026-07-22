#!/usr/bin/env python3
"""Fetch MET Norway / Yr Locationforecast data."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from yr_weather import compact_hourly_forecast, fetch_locationforecast


KNOWN_LOCATIONS = {
    "oslo": {
        "latitude": 59.9139,
        "longitude": 10.7522,
        "altitude": 23,
        "timezone": "Europe/Oslo",
    },
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
        "--timezone",
        help="IANA timezone for compact local times, for example Europe/Lisbon",
    )
    parser.add_argument(
        "--hourly",
        action="store_true",
        help="Print compact hourly forecast rows instead of raw Locationforecast JSON.",
    )
    parser.add_argument("--from-local", help="Start local datetime for --hourly")
    parser.add_argument("--to-local", help="End local datetime for --hourly")
    args = parser.parse_args()

    if (args.from_local or args.to_local) and not args.hourly:
        parser.error("--from-local and --to-local require --hourly")
    if args.timezone and not args.hourly:
        parser.error("--timezone requires --hourly")

    if args.lat is not None or args.lon is not None:
        if args.lat is None or args.lon is None:
            parser.error("use both --lat and --lon for custom coordinates")
        validate_coordinates(parser, latitude=args.lat, longitude=args.lon)
        location = {
            "latitude": args.lat,
            "longitude": args.lon,
            "altitude": args.altitude,
        }
        timezone_name = args.timezone
    else:
        key = args.location.lower()
        if key not in KNOWN_LOCATIONS:
            known = ", ".join(sorted(KNOWN_LOCATIONS))
            parser.error(f"unknown location {args.location!r}. Known: {known}")
        known_location = KNOWN_LOCATIONS[key]
        location = {
            name: value for name, value in known_location.items() if name != "timezone"
        }
        if args.altitude is not None:
            location["altitude"] = args.altitude
        timezone_name = args.timezone or str(known_location["timezone"])

    local_timezone = parse_timezone(parser, timezone_name) if args.hourly else None
    try:
        from_local = parse_local_datetime(args.from_local, local_timezone=local_timezone)
        to_local = parse_local_datetime(args.to_local, local_timezone=local_timezone)
    except ValueError as exc:
        parser.error(f"invalid local datetime: {exc}")
    if from_local and to_local and from_local > to_local:
        parser.error("--from-local must be before or equal to --to-local")

    try:
        forecast = fetch_locationforecast(**location)
    except (RuntimeError, TypeError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")
    if args.hourly:
        payload = {
            "source": "yr_locationforecast",
            "location": location,
            "timezone": timezone_name,
            "from_local": args.from_local,
            "to_local": args.to_local,
            "hourly": compact_hourly_forecast(
                forecast,
                local_timezone=local_timezone,
                from_local=from_local,
                to_local=to_local,
            ),
        }
    else:
        payload = forecast
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def validate_coordinates(
    parser: argparse.ArgumentParser,
    *,
    latitude: float,
    longitude: float,
) -> None:
    if not -90 <= latitude <= 90:
        parser.error("--lat must be between -90 and 90")
    if not -180 <= longitude <= 180:
        parser.error("--lon must be between -180 and 180")


def parse_timezone(
    parser: argparse.ArgumentParser,
    raw: str | None,
) -> ZoneInfo:
    if not raw:
        parser.error("--timezone is required with custom coordinates and --hourly")
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError:
        parser.error(f"unknown IANA timezone: {raw}")


def parse_local_datetime(
    raw: str | None,
    *,
    local_timezone: ZoneInfo | None,
) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        if local_timezone is None:
            raise ValueError("a timezone is required for a local datetime")
        return parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(local_timezone) if local_timezone else parsed


if __name__ == "__main__":
    main()
