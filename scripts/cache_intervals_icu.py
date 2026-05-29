#!/usr/bin/env python3
"""Cache Intervals.icu activity streams for local analysis."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from intervals_api import (
    cache_activity_file,
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

    file_parser = subparsers.add_parser(
        "file",
        help="Cache the original or generated FIT file for one activity id",
    )
    file_parser.add_argument("activity_id")
    file_parser.add_argument(
        "--kind",
        choices=["original", "fit", "web-original"],
        default="original",
        help="Download the API original, web-session original, or Intervals.icu generated FIT",
    )

    named = subparsers.add_parser(
        "named",
        help="Cache activities whose names contain a case-insensitive text fragment",
    )
    named.add_argument("text", help="Name fragment, for example VT1 or VT2")
    named.add_argument("--since", default=f"{date.today().year}-01-01")
    named.add_argument("--until", default=date.today().isoformat())

    outdoor = subparsers.add_parser("outdoor", help="Cache outdoor ride streams")
    outdoor.add_argument("--since", default=f"{date.today().year}-01-01")
    outdoor.add_argument("--until", default=date.today().isoformat())

    indoor = subparsers.add_parser("indoor", help="Cache indoor/trainer ride streams")
    indoor.add_argument("--since", default=f"{date.today().year}-01-01")
    indoor.add_argument("--until", default=date.today().isoformat())
    indoor.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download activities that are already cached",
    )

    tireless = subparsers.add_parser("tireless", help="Cache long Tireless indoor rides")
    tireless.add_argument("--since", default="2022-01-01")
    tireless.add_argument("--until", default=date.today().isoformat())
    tireless.add_argument("--min-minutes", type=float, default=180.0)
    tireless.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download activities that are already cached",
    )

    hard_indoor = subparsers.add_parser(
        "hard-indoor",
        help="Cache hard indoor workout streams by name pattern",
    )
    hard_indoor.add_argument("--since", default=f"{date.today().year}-01-01")
    hard_indoor.add_argument("--until", default=date.today().isoformat())
    hard_indoor.add_argument(
        "--pattern",
        action="append",
        default=None,
        help="Case-insensitive name fragment. Can be repeated.",
    )

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

    if args.command == "file":
        artifacts = cache_activity_file(
            activity_id=args.activity_id,
            api_key=api_key,
            kind=args.kind,
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

    if args.command == "outdoor":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        matches = [
            activity
            for activity in activities
            if str(activity.get("type") or "").lower() == "ride"
        ]
        _cache_activity_matches(matches, api_key=api_key)
        return

    if args.command == "indoor":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        matches = [
            activity
            for activity in activities
            if _is_indoor_ride(activity)
        ]
        _cache_activity_matches(
            matches,
            api_key=api_key,
            skip_existing=not args.refresh,
        )
        return

    if args.command == "tireless":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        min_seconds = args.min_minutes * 60
        matches = [
            activity
            for activity in activities
            if _is_indoor_ride(activity)
            and "tireless" in str(activity.get("name") or "").lower()
            and (
                float(activity.get("elapsed_time") or activity.get("moving_time") or 0)
                >= min_seconds
            )
        ]
        _cache_activity_matches(
            matches,
            api_key=api_key,
            skip_existing=not args.refresh,
        )
        return

    if args.command == "hard-indoor":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        patterns = args.pattern or [
            "60/60",
            "60-60",
            "30/30",
            "30-30",
            "vo2",
            "vo2max",
            "vt2",
        ]
        matches = [
            activity
            for activity in activities
            if str(activity.get("type") or "").lower() == "virtualride"
            and any(
                pattern.lower() in str(activity.get("name") or "").lower()
                for pattern in patterns
            )
        ]
        _cache_activity_matches(matches, api_key=api_key)
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


def _cache_activity_matches(
    matches: list[dict[str, Any]],
    *,
    api_key: str,
    skip_existing: bool = False,
) -> None:
    cached_count = 0
    skipped_count = 0
    for activity in sorted(matches, key=lambda item: item.get("start_date_local") or ""):
        if skip_existing and _activity_is_cached(activity):
            skipped_count += 1
            continue
        artifacts = cache_activity_streams(
            activity_id=activity["id"],
            activity_summary=activity,
            api_key=api_key,
        )
        cached_count += 1
        print(
            f"cached {activity.get('start_date_local')} "
            f"{activity.get('id')} {activity.get('name')}"
        )
        _print_artifacts(artifacts, indent="  ")
    print(f"matched_count: {len(matches)}")
    print(f"cached_count: {cached_count}")
    if skip_existing:
        print(f"skipped_existing_count: {skipped_count}")


def _is_indoor_ride(activity: dict[str, Any]) -> bool:
    activity_type = str(activity.get("type") or "").lower()
    if activity_type not in {"ride", "virtualride"}:
        return False
    return (
        activity_type == "virtualride"
        or activity.get("trainer") is True
        or activity.get("indoor") is True
    )


def _activity_is_cached(activity: dict[str, Any]) -> bool:
    activity_id = str(activity.get("id") or "")
    if not activity_id:
        return False
    return any(Path("data/activities").glob(f"*_{activity_id}/streams.csv"))


if __name__ == "__main__":
    main()
