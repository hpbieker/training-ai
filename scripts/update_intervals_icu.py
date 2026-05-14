#!/usr/bin/env python3
"""Update Intervals.icu activity metadata."""

from __future__ import annotations

import argparse

from intervals_api import load_intervals_icu_api_key, update_activity


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update Intervals.icu activity metadata.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rename = subparsers.add_parser("rename", help="Rename one activity")
    rename.add_argument("activity_id")
    rename.add_argument("name")

    args = parser.parse_args()
    api_key = load_intervals_icu_api_key()

    if args.command == "rename":
        updated = update_activity(
            activity_id=args.activity_id,
            updates={"name": args.name},
            api_key=api_key,
        )
        print(f"updated {updated.get('id')}: {updated.get('name')}")
        return


if __name__ == "__main__":
    main()
