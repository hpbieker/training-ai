#!/usr/bin/env python3
"""Command-line interface for authenticated Strava activities and gear."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from strava_activity_service import (
    download_activity_media, get_activity, get_gear, list_activities,
    list_activity_media, list_gear, upload_activity_media, update_activities,
    update_activity,
)
from scripts.strava_route_api import StravaError


def add_activity_patch_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="New activity name")
    parser.add_argument("--tag", help="Primary tag, or 'none' to clear it")
    parser.add_argument("--trainer", action=argparse.BooleanOptionalAction, default=None,
                        help="Mark or unmark the activity as indoor/trainer")
    parser.add_argument("--visibility", choices=("everyone", "followers_only", "only_me"),
                        help="Activity visibility")
    parser.add_argument("--start-time-hidden", action=argparse.BooleanOptionalAction, default=None,
                        help="Hide or show the activity start time")
    parser.add_argument("--mute", action=argparse.BooleanOptionalAction, default=None,
                        help="Mute or unmute the activity in home feeds")
    bike = parser.add_mutually_exclusive_group()
    bike.add_argument("--bike-id", help="Bike ID, or 'none' to clear the bike")
    bike.add_argument("--bike-name", help="Exact bike name, or 'none' to clear the bike")
    parser.add_argument("--yes", action="store_true", help="Confirm this Strava write")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    sub = commands.add_parser("list_activities", help="List activities in a date range")
    sub.add_argument("--since", required=True, help="First local date (YYYY-MM-DD)")
    sub.add_argument("--until", help="Last local date (YYYY-MM-DD); defaults to today")
    sub.add_argument("--visibility", choices=("everyone", "followers_only", "only_me"),
                     help="Filter by visibility")
    sub.add_argument("--max-pages", type=int, default=20, help="Maximum pages to fetch (default: 20)")
    sub.add_argument("--per-page", type=int, default=100, help="Activities per page (default: 100)")

    sub = commands.add_parser("get_activity", help="Get one activity and its editable metadata")
    sub.add_argument("activity_id", help="Strava activity ID")

    commands.add_parser("list_gear", help="List active and retired bikes and shoes")
    sub = commands.add_parser("get_gear", help="Get one bike or shoe")
    sub.add_argument("gear_id", help="Strava gear ID")
    sub.add_argument("--gear-type", choices=("bike", "shoe"), help="Limit lookup to this gear type")

    sub = commands.add_parser("list_activity_media", help="List media attached to one activity")
    sub.add_argument("activity_id", help="Strava activity ID")

    sub = commands.add_parser("download_activity_media", help="Download one activity media item")
    sub.add_argument("activity_id", help="Strava activity ID")
    sub.add_argument("media_id", help="Media ID returned by list_activity_media")
    sub.add_argument("destination_dir", help="Destination directory")
    sub.add_argument("--overwrite", action="store_true", help="Replace an existing destination file")

    sub = commands.add_parser("upload_activity_media", help="Attach an image or video to an activity")
    sub.add_argument("activity_id", help="Strava activity ID")
    sub.add_argument("file_path", help="Local JPG, PNG, GIF, MP4, or MOV file")
    sub.add_argument("--caption", help="Optional media caption")
    sub.add_argument("--yes", action="store_true", help="Confirm this Strava write")

    sub = commands.add_parser("update_activity", help="Update one activity and read it back")
    sub.add_argument("activity_id", help="Strava activity ID")
    add_activity_patch_arguments(sub)

    sub = commands.add_parser("update_activities", help="Apply one update to several activities")
    sub.add_argument("activity_ids", nargs="+", help="One or more Strava activity IDs")
    add_activity_patch_arguments(sub)
    return parser


def nullable(value: str | None) -> str | None:
    return None if value is not None and value.lower() == "none" else value


def activity_patch(args: argparse.Namespace) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for argument in ("name", "tag", "trainer", "visibility", "start_time_hidden", "mute", "bike_id", "bike_name"):
        value = getattr(args, argument)
        if value is not None:
            patch[argument] = nullable(value) if argument in {"tag", "bike_id", "bike_name"} else value
    return patch


def command_call(args: argparse.Namespace) -> tuple[Callable[..., dict[str, Any]], dict[str, Any]]:
    if args.command == "list_activities":
        return list_activities, {"since": args.since, "until": args.until, "visibility": args.visibility,
                                 "max_pages": args.max_pages, "per_page": args.per_page}
    if args.command == "get_activity":
        return get_activity, {"activity_id": args.activity_id}
    if args.command == "list_gear":
        return list_gear, {}
    if args.command == "get_gear":
        return get_gear, {"gear_id": args.gear_id, "gear_type": args.gear_type}
    if args.command == "list_activity_media":
        return list_activity_media, {"activity_id": args.activity_id}
    if args.command == "download_activity_media":
        return download_activity_media, {"activity_id": args.activity_id, "media_id": args.media_id,
                                         "destination_dir": args.destination_dir, "overwrite": args.overwrite}
    if args.command == "upload_activity_media":
        return upload_activity_media, {"activity_id": args.activity_id, "file_path": args.file_path,
                                       "caption": args.caption, "confirm": args.yes}
    if args.command == "update_activity":
        return update_activity, {"activity_id": args.activity_id, "patch": activity_patch(args),
                                 "confirm": args.yes}
    return update_activities, {"activity_ids": args.activity_ids, "patch": activity_patch(args),
                               "confirm": args.yes}


def main() -> int:
    args = build_parser().parse_args()
    try:
        handler, arguments = command_call(args)
        print(json.dumps(handler(**arguments), indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError, StravaError) as exc:
        print(json.dumps({"error": {"code": "operation_failed", "message": str(exc)}}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
