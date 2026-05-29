#!/usr/bin/env python3
"""Cache Garmin Connect health data via gccli."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from garmin_api import (
    DAILY_SPEC_CHOICES,
    cache_activities,
    cache_activity,
    cache_activity_summary,
    cache_day,
    cache_indoor_activities,
    cache_pure_indoor_vt1_summaries,
    cache_recent_days,
    resolve_gccli,
    show_auth_status,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache Garmin Connect health/readiness data using gccli.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    day = subparsers.add_parser("day", help="Cache Garmin health data for one day")
    day.add_argument("date", nargs="?", default=date.today().isoformat())
    day.add_argument(
        "--only",
        action="append",
        choices=DAILY_SPEC_CHOICES,
        help="Cache only one daily source. Can be repeated.",
    )

    recent = subparsers.add_parser("recent", help="Cache Garmin health data for recent days")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--until", default=date.today().isoformat())

    activity = subparsers.add_parser(
        "activity",
        help="Cache one Garmin activity file and summary metadata",
    )
    activity.add_argument(
        "activity",
        help="Garmin activity id, Intervals activity id, or cached Intervals activity dir",
    )
    activity_summary = subparsers.add_parser(
        "activity-summary",
        help="Cache one Garmin activity summary without full chart details",
    )
    activity_summary.add_argument(
        "activity",
        help="Garmin activity id, Intervals activity id, or cached Intervals activity dir",
    )
    vt1_summaries = subparsers.add_parser(
        "vt1-summaries",
        help="Cache Garmin summaries for cached pure indoor VT1 activities",
    )
    vt1_summaries.add_argument("--since", default=f"{date.today().year}-01-01")
    indoor = subparsers.add_parser(
        "backfill-indoor",
        help="Cache Garmin details for indoor cycling activities in a date range",
    )
    indoor.add_argument("--since", default=f"{date.today().year}-01-01")
    indoor.add_argument("--until", default=date.today().isoformat())
    indoor.add_argument("--limit", type=int, default=1000)
    indoor.add_argument("--refresh", action="store_true")
    activities = subparsers.add_parser(
        "backfill-activities",
        help="Cache Garmin details for all activities in a date range",
    )
    activities.add_argument("--since", default=f"{date.today().year}-01-01")
    activities.add_argument("--until", default=date.today().isoformat())
    activities.add_argument("--limit", type=int, default=1000)
    activities.add_argument("--refresh", action="store_true")
    subparsers.add_parser("status", help="Show gccli auth status")

    args = parser.parse_args()
    gccli = resolve_gccli()

    if args.command == "status":
        show_auth_status(gccli=gccli)
        return

    if args.command == "day":
        artifacts = cache_day(args.date, gccli=gccli, only=args.only)
        _print_artifacts(artifacts)
        return

    if args.command == "recent":
        for path in cache_recent_days(days=args.days, until=args.until, gccli=gccli):
            print(path)
        return

    if args.command == "activity":
        artifacts = cache_activity(args.activity, gccli=gccli)
        _print_artifacts(artifacts)
        return

    if args.command == "activity-summary":
        artifacts = cache_activity_summary(args.activity, gccli=gccli)
        _print_artifacts(artifacts)
        return

    if args.command == "vt1-summaries":
        for path in cache_pure_indoor_vt1_summaries(args.since, gccli=gccli):
            print(path)
        return

    if args.command == "backfill-indoor":
        result = cache_indoor_activities(
            args.since,
            args.until,
            gccli=gccli,
            limit=args.limit,
            refresh=args.refresh,
        )
        print(f"searched: {result['searched']}")
        print(f"indoor: {result['considered_indoor']}")
        print(f"cached: {len(result['cached'])}")
        print(f"skipped_existing: {len(result['skipped_existing'])}")
        print(f"failed: {len(result['failed'])}")
        for path in result["cached"]:
            print(path)
        for failure in result["failed"]:
            print(f"failed {failure['activity_id']}: {failure['name']} - {failure['error']}")
        return

    if args.command == "backfill-activities":
        result = cache_activities(
            args.since,
            args.until,
            gccli=gccli,
            limit=args.limit,
            refresh=args.refresh,
        )
        print(f"searched: {result['searched']}")
        print(f"cached: {len(result['cached'])}")
        print(f"skipped_existing: {len(result['skipped_existing'])}")
        print(f"failed: {len(result['failed'])}")
        for path in result["cached"]:
            print(path)
        for failure in result["failed"]:
            print(f"failed {failure['activity_id']}: {failure['name']} - {failure['error']}")
        return


def _print_artifacts(artifacts: dict[str, Path]) -> None:
    for name, path in artifacts.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
