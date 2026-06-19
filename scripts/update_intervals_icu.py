#!/usr/bin/env python3
"""Update Intervals.icu activity metadata."""

from __future__ import annotations

import argparse

from intervals_api import get_wellness, load_intervals_icu_api_key, update_activity, update_wellness


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update Intervals.icu activity metadata.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rename = subparsers.add_parser("rename", help="Rename one activity")
    rename.add_argument("activity_id")
    rename.add_argument("name")

    subjective = subparsers.add_parser(
        "subjective",
        help="Update subjective Intervals.icu fields for one activity",
    )
    subjective.add_argument("activity_id")
    subjective.add_argument(
        "--feel",
        help="Subjective feel value to store in Intervals.icu's feel field",
    )
    subjective.add_argument(
        "--rpe",
        "--session-rpe",
        dest="rpe",
        type=float,
        help="RPE value to store in Intervals.icu's icu_rpe field",
    )

    wellness = subparsers.add_parser("wellness", help="Update one daily wellness record")
    wellness.add_argument("date", help="Local date formatted YYYY-MM-DD")
    wellness.add_argument(
        "--soreness",
        type=int,
        help="Daily soreness value to store in Intervals.icu's soreness field",
    )
    wellness.add_argument(
        "--fatigue",
        type=int,
        help="Daily fatigue value to store in Intervals.icu's fatigue field",
    )
    wellness.add_argument(
        "--motivation",
        type=int,
        help="Daily motivation value to store in Intervals.icu's motivation field",
    )
    wellness.add_argument(
        "--comments",
        help="Daily wellness comments. Only use for explicit user-provided notes.",
    )
    wellness.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting an existing wellness value with a different value.",
    )

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

    if args.command == "subjective":
        updates = {}
        if args.feel is not None:
            updates["feel"] = args.feel
        if args.rpe is not None:
            updates["icu_rpe"] = args.rpe
        if not updates:
            parser.error("subjective requires at least one subjective field")

        updated = update_activity(
            activity_id=args.activity_id,
            updates=updates,
            api_key=api_key,
        )
        saved = {field: updated.get(field) for field in updates}
        print(f"updated {updated.get('id')}: {saved}")
        return

    if args.command == "wellness":
        updates = {}
        if args.soreness is not None:
            updates["soreness"] = args.soreness
        if args.fatigue is not None:
            updates["fatigue"] = args.fatigue
        if args.motivation is not None:
            updates["motivation"] = args.motivation
        if args.comments is not None:
            updates["comments"] = args.comments
        if not updates:
            parser.error("wellness requires at least one wellness field")

        current = get_wellness(day=args.date, api_key=api_key)
        conflicting = {
            field: {"current": current.get(field), "requested": value}
            for field, value in updates.items()
            if _has_value(current.get(field)) and current.get(field) != value
        }
        if conflicting and not args.force:
            parser.error(
                "refusing to overwrite existing wellness values without --force: "
                f"{conflicting}"
            )

        updated = update_wellness(
            day=args.date,
            updates=updates,
            api_key=api_key,
        )
        saved = {field: updated.get(field) for field in updates}
        print(f"updated wellness {updated.get('id')}: {saved}")
        return


def _has_value(value: object) -> bool:
    return value is not None and value != ""


if __name__ == "__main__":
    main()
