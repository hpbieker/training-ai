#!/usr/bin/env python3
"""Fetch Garmin Connect health and activity data via gccli."""

from __future__ import annotations

import argparse
import json
from datetime import date

from garmin_connect_api import (
    DAILY_SPEC_CHOICES,
    fetch_activity,
    fetch_day,
    fetch_recent_days,
    garmin_activity_search,
    resolve_gccli,
    show_auth_status,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Garmin Connect health/readiness data using gccli.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    day = subparsers.add_parser("day", help="Fetch Garmin Connect health data for one day")
    day.add_argument("date", nargs="?", default=date.today().isoformat())
    day.add_argument(
        "--only",
        action="append",
        choices=DAILY_SPEC_CHOICES,
        help="Fetch only one daily source. Can be repeated.",
    )

    recent = subparsers.add_parser("recent", help="Fetch Garmin Connect health data for recent days")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--until", default=date.today().isoformat())

    activity = subparsers.add_parser(
        "activity",
        help="Fetch one Garmin Connect activity summary and details",
    )
    activity.add_argument(
        "activity",
        help="Garmin activity id, Intervals activity id, or cached Intervals activity dir",
    )
    activity.add_argument(
        "--summary-only",
        action="store_true",
        help="Fetch summary and compact metrics without chart details",
    )

    activities = subparsers.add_parser(
        "activities",
        help="Search Garmin Connect activities in a date range",
    )
    activities.add_argument("--since", default=f"{date.today().year}-01-01")
    activities.add_argument("--until", default=date.today().isoformat())
    activities.add_argument("--limit", type=int, default=100)
    subparsers.add_parser("status", help="Show gccli auth status")

    args = parser.parse_args()
    gccli = resolve_gccli()

    if args.command == "status":
        show_auth_status(gccli=gccli)
        return

    if args.command == "day":
        _print_json(fetch_day(args.date, gccli=gccli, only=args.only))
        return

    if args.command == "recent":
        _print_json(fetch_recent_days(days=args.days, until=args.until, gccli=gccli))
        return

    if args.command == "activity":
        _print_json(
            fetch_activity(
                args.activity,
                gccli=gccli,
                include_details=not args.summary_only,
            )
        )
        return

    if args.command == "activities":
        _print_json(
            {
                "source": "garmin_connect_gccli",
                "start_date": args.since,
                "end_date": args.until,
                "activities": garmin_activity_search(
                    gccli,
                    args.since,
                    args.until,
                    limit=args.limit,
                ),
            }
        )
        return


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
