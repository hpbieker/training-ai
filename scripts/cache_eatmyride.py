#!/usr/bin/env python3
"""Cache EatMyRide activities and recorded food-plan events."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from eatmyride_api import (
    LOCAL_TIMEZONE,
    cache_activity,
    cache_day,
    cache_latest_activity,
    get_activity,
    get_foodplan,
    list_activities_for_day,
    load_eatmyride_credentials,
    replace_foodplan,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache EatMyRide activity details and recorded food-plan events.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    activity = subparsers.add_parser("activity", help="Cache one EatMyRide activity id")
    activity.add_argument("activity_id")

    day = subparsers.add_parser("day", help="Cache activities for one local Oslo date")
    day.add_argument("date", nargs="?", default=datetime.now(LOCAL_TIMEZONE).date().isoformat())

    latest = subparsers.add_parser("latest", help="Cache the latest EatMyRide activity")
    latest.add_argument("--lookback-days", type=int, default=7)

    previous_foodplan = subparsers.add_parser(
        "previous-foodplan",
        help="Find the nearest earlier activity with recorded food or drink",
    )
    previous_foodplan.add_argument(
        "--before",
        default=datetime.now(LOCAL_TIMEZONE).date().isoformat(),
        help="Search strictly before this local Oslo date",
    )
    previous_foodplan.add_argument("--lookback-days", type=int, default=60)

    replace = subparsers.add_parser(
        "replace-foodplan",
        help="Replace one activity food plan from a local JSON file",
    )
    replace.add_argument("activity_id")
    replace.add_argument("json_file", type=Path)
    replace.add_argument("--yes", action="store_true", help="Confirm replacement")

    set_event = subparsers.add_parser(
        "set-event",
        help="Adjust one existing food-plan event and verify the server result",
    )
    set_event.add_argument("activity_id")
    set_event.add_argument("--label", required=True, help="Exact product label")
    set_event.add_argument("--match-time", required=True, type=int, help="Existing time in seconds")
    set_event.add_argument("--time", type=int, help="New time in seconds from activity start")
    set_event.add_argument("--ml", type=int, help="New consumed volume in milliliters")
    set_event.add_argument("--gram", type=int, help="New consumed quantity in grams")
    set_event.add_argument("--yes", action="store_true", help="Confirm replacement")

    args = parser.parse_args()
    if args.command in {"replace-foodplan", "set-event"}:
        _require_confirmation(args.yes)
    token = load_eatmyride_credentials().login()

    if args.command == "activity":
        _print_artifacts(cache_activity(args.activity_id, token=token))
        return

    if args.command == "day":
        cached = cache_day(args.date, token=token)
        for artifacts in cached:
            _print_artifacts(artifacts)
        print(f"cached_count: {len(cached)}")
        return

    if args.command == "latest":
        _print_artifacts(cache_latest_activity(token=token, lookback_days=args.lookback_days))
        return

    if args.command == "previous-foodplan":
        result = _previous_foodplan(
            args.before,
            lookback_days=args.lookback_days,
            token=token,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if args.command == "replace-foodplan":
        foodplan = json.loads(args.json_file.read_text(encoding="utf-8"))
        if not isinstance(foodplan, list):
            raise SystemExit("Expected foodplan JSON file to contain a list")
        _replace_and_cache(args.activity_id, foodplan, token=token)
        return

    if args.command == "set-event":
        foodplan = get_foodplan(args.activity_id, token=token)
        event = _find_event(foodplan, label=args.label, match_time=args.match_time)
        if args.time is not None:
            event["time"] = args.time
            event["distance"] = None
        if args.ml is not None:
            event["ml"] = args.ml
        if args.gram is not None:
            event["gram"] = args.gram
        _replace_and_cache(args.activity_id, foodplan, token=token)
        return


def _print_artifacts(artifacts: dict[str, Path]) -> None:
    for name, path in artifacts.items():
        print(f"{name}: {path}")


def _replace_and_cache(activity_id: str, foodplan: list[dict[str, Any]], *, token: str) -> None:
    verified = replace_foodplan(activity_id, foodplan, token=token)
    _print_artifacts(cache_activity(activity_id, token=token))
    print(f"foodplan_events: {len(verified['foodplan'])}")
    print(f"carbohydrates_from_food: {verified['activity'].get('carbohydratesFromFood')}")


def _previous_foodplan(
    before: str,
    *,
    lookback_days: int,
    token: str,
) -> dict[str, Any]:
    before_date = date.fromisoformat(before)
    checked_activities = 0
    for offset in range(1, lookback_days + 1):
        day = before_date - timedelta(days=offset)
        activities = sorted(
            list_activities_for_day(day, token=token),
            key=lambda item: str(item.get("date") or ""),
            reverse=True,
        )
        for summary in activities:
            activity_id = summary["id"]
            foodplan = get_foodplan(activity_id, token=token)
            checked_activities += 1
            if not foodplan:
                continue
            activity = get_activity(activity_id, token=token)
            return {
                "activity": {
                    "id": activity.get("id"),
                    "label": activity.get("label"),
                    "date": activity.get("date"),
                    "duration": activity.get("duration"),
                    "distance": activity.get("distance"),
                    "sport": activity.get("sport"),
                    "subSport": activity.get("subSport"),
                    "tracker": activity.get("tracker"),
                    "carbohydratesFromFood": activity.get("carbohydratesFromFood"),
                    "usedBalancer": activity.get("usedBalancer"),
                },
                "foodplan_events": len(foodplan),
                "products": sorted(
                    {
                        event.get("product", {}).get("label")
                        for event in foodplan
                        if event.get("product", {}).get("label")
                    }
                ),
                "events": [
                    {
                        "time": event.get("time"),
                        "distance": event.get("distance"),
                        "label": event.get("product", {}).get("label"),
                        "ml": event.get("ml"),
                        "gram": event.get("gram"),
                    }
                    for event in foodplan
                ],
                "checked_activities": checked_activities,
            }
    raise SystemExit(
        f"No earlier EatMyRide food plan found in the last {lookback_days} days"
    )


def _find_event(
    foodplan: list[dict[str, Any]],
    *,
    label: str,
    match_time: int,
) -> dict[str, Any]:
    matches = [
        event
        for event in foodplan
        if event.get("time") == match_time
        and event.get("product", {}).get("label") == label
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one event for {label!r} at {match_time}s, got {len(matches)}"
        )
    return matches[0]


def _require_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise SystemExit("Food-plan replacement requires --yes")


if __name__ == "__main__":
    main()
