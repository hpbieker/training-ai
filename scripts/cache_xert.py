#!/usr/bin/env python3
"""Cache Xert training status and activity summaries for local analysis."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from xert_api import (
    cache_activity_summaries,
    cache_training_advice,
    cache_training_info,
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
    subparsers.add_parser(
        "training-advice",
        help="Cache Xert training advice including recovery load/days",
    )

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

    if args.command == "training-advice":
        artifacts = cache_training_advice(
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
