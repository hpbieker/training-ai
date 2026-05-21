#!/usr/bin/env python3
"""Cache Xert training status and activity summaries for local analysis."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from xert_api import (
    cache_activity_summaries,
    cache_legacy_training_advice,
    cache_recommended_training,
    cache_recovery_model,
    cache_training_forecast,
    cache_training_info,
    cache_workout,
    cache_workouts,
    load_xert_credentials,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache Xert training info and activity summary data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    activities = subparsers.add_parser("activities", help="Cache Xert activity summaries")
    activities.add_argument("--since", default=f"{date.today().year}-01-01")
    activities.add_argument("--until", default=date.today().isoformat())
    activities.add_argument(
        "--session-data",
        action="store_true",
        help="Also cache per-second Xert session data such as MPA/XDS/TWS",
    )

    subparsers.add_parser("training-info", help="Cache current Xert training info")
    subparsers.add_parser("workouts", help="Cache the user's Xert workout library")
    workout = subparsers.add_parser("workout", help="Cache one resolved Xert workout")
    workout.add_argument("path", help="Xert workout path from the workouts list")
    subparsers.add_parser(
        "training-forecast",
        help="Cache Xert calendar training forecast using XERT_COOKIE",
    )
    subparsers.add_parser(
        "recovery-model",
        help="Calculate Xert recovery days from direct web model inputs",
    )
    subparsers.add_parser(
        "legacy-training-advice",
        help="Cache legacy Xert training advice from the old Appspot proxy",
    )
    recommended = subparsers.add_parser(
        "recommended-training",
        help="Cache Xert recommended workouts for a date",
    )
    recommended.add_argument("--date", default=date.today().isoformat())
    recommended.add_argument("--recent", action=argparse.BooleanOptionalAction, default=True)
    recommended.add_argument("--additional", action=argparse.BooleanOptionalAction, default=False)
    recommended.add_argument("--sport", default=None)

    args = parser.parse_args()
    credentials = load_xert_credentials()

    if args.command == "activities":
        artifacts = cache_activity_summaries(
            access_token=credentials.access_token,
            username=credentials.username,
            password=credentials.password,
            oldest=args.since,
            newest=args.until,
            include_session_data=args.session_data,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "training-info":
        artifacts = cache_training_info(
            access_token=credentials.access_token,
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "workouts":
        artifacts = cache_workouts(
            access_token=credentials.access_token,
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "workout":
        artifacts = cache_workout(
            args.path,
            access_token=credentials.access_token,
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "training-forecast":
        artifacts = cache_training_forecast(
            cookie=credentials.cookie,
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "recovery-model":
        artifacts = cache_recovery_model(
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "legacy-training-advice":
        artifacts = cache_legacy_training_advice(
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "recommended-training":
        artifacts = cache_recommended_training(
            date_value=args.date,
            recent=args.recent,
            additional=args.additional,
            sport=args.sport,
            cookie=credentials.cookie,
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return


def _print_artifacts(artifacts: dict[str, Any]) -> None:
    for name, path in artifacts.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
