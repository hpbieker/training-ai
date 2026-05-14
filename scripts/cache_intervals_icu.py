#!/usr/bin/env python3
"""Cache Intervals.icu activity streams for local analysis."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from intervals_api import (
    cache_activity_streams,
    cache_latest_activity_streams,
    cache_wellness,
    list_activities,
    load_intervals_icu_api_key,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache Intervals.icu streams.csv and activity.json files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    latest = subparsers.add_parser("latest", help="Cache streams for the latest activity")
    latest.add_argument("--lookback-days", type=int, default=365)

    recent = subparsers.add_parser("recent", help="Cache streams for recent activities")
    recent.add_argument("--count", type=int, default=2)
    recent.add_argument("--lookback-days", type=int, default=365)

    activity = subparsers.add_parser("activity", help="Cache streams for one activity id")
    activity.add_argument("activity_id")

    named = subparsers.add_parser(
        "named",
        help="Cache activities whose names contain a case-insensitive text fragment",
    )
    named.add_argument("text", help="Name fragment, for example VT1 or VT2")
    named.add_argument("--since", default=f"{date.today().year}-01-01")
    named.add_argument("--until", default=date.today().isoformat())

    wellness = subparsers.add_parser("wellness", help="Cache wellness data")
    wellness.add_argument("--since", default=f"{date.today().year}-01-01")
    wellness.add_argument("--until", default=date.today().isoformat())

    args = parser.parse_args()
    api_key = load_intervals_icu_api_key()

    if args.command == "latest":
        artifacts = cache_latest_activity_streams(
            api_key=api_key,
            lookback_days=args.lookback_days,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "recent":
        activities = list_activities(
            api_key=api_key,
            oldest=date.fromordinal(date.today().toordinal() - args.lookback_days),
            newest=date.today(),
        )
        recent_activities = sorted(
            activities,
            key=lambda activity: activity.get("start_date_local") or "",
            reverse=True,
        )[: args.count]
        for activity in recent_activities:
            artifacts = cache_activity_streams(
                activity_id=activity["id"],
                activity_summary=activity,
                api_key=api_key,
            )
            print(
                f"cached {activity.get('start_date_local')} "
                f"{activity.get('id')} {activity.get('name')}"
            )
            _print_artifacts(artifacts, indent="  ")
        print(f"cached_count: {len(recent_activities)}")
        return

    if args.command == "activity":
        artifacts = cache_activity_streams(
            activity_id=args.activity_id,
            api_key=api_key,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "named":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        matches = [
            activity
            for activity in activities
            if args.text.lower() in str(activity.get("name") or "").lower()
        ]
        for activity in sorted(matches, key=lambda item: item.get("start_date_local") or ""):
            artifacts = cache_activity_streams(
                activity_id=activity["id"],
                activity_summary=activity,
                api_key=api_key,
            )
            print(
                f"cached {activity.get('start_date_local')} "
                f"{activity.get('id')} {activity.get('name')}"
            )
            _print_artifacts(artifacts, indent="  ")
        print(f"cached_count: {len(matches)}")
        return

    if args.command == "wellness":
        artifacts = cache_wellness(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        _print_artifacts(artifacts)
        return


def _print_artifacts(artifacts: dict[str, Any], *, indent: str = "") -> None:
    for name, path in artifacts.items():
        print(f"{indent}{name}: {path}")


if __name__ == "__main__":
    main()
