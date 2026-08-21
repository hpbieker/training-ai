#!/usr/bin/env python3
"""CLI for mixed Xert Planner events that have no MCP equivalent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from xert_api import (
    create_calendar_event_with_opener,
    delete_calendar_event_with_opener,
    fetch_calendar_event_with_opener,
    fetch_calendar_events_with_opener,
    update_calendar_event_with_opener,
    xert_web_login,
)
from xert_service import discover_xert_credentials


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Xert mixed Planner-event utilities without MCP parity."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    calendar_events = subparsers.add_parser("calendar-events")
    calendar_events.add_argument("date")
    calendar_event = subparsers.add_parser("calendar-event")
    calendar_event.add_argument("path")
    calendar_event.add_argument("--date", required=True)
    create = subparsers.add_parser("calendar-event-create")
    create.add_argument("--event-json", required=True)
    create.add_argument("--yes", action="store_true")
    update = subparsers.add_parser("calendar-event-update")
    update.add_argument("path")
    update.add_argument("--date", required=True)
    update.add_argument("--patch-json", required=True)
    update.add_argument("--yes", action="store_true")
    delete = subparsers.add_parser("calendar-event-delete")
    delete.add_argument("path")
    delete.add_argument("--date", required=True)
    delete.add_argument("--yes", action="store_true")

    args = parser.parse_args()
    credentials = discover_xert_credentials()
    username = _require(credentials.username, "XERT_USERNAME")
    password = _require(credentials.password, "XERT_PASSWORD")
    opener = xert_web_login(username=username, password=password)
    if args.command == "calendar-events":
        payload = fetch_calendar_events_with_opener(opener, args.date)
    elif args.command == "calendar-event":
        payload = fetch_calendar_event_with_opener(opener, args.date, args.path)
        if payload is None:
            raise SystemExit(f"Xert calendar event not found: {args.path}")
    elif args.command == "calendar-event-create":
        event = _json_object(args.event_json, "--event-json")
        payload = (
            {"dry_run": True, "event": event}
            if not args.yes
            else create_calendar_event_with_opener(opener, event)
        )
    elif args.command == "calendar-event-update":
        patch = _json_object(args.patch_json, "--patch-json")
        current = fetch_calendar_event_with_opener(opener, args.date, args.path)
        if current is None:
            raise SystemExit(f"Xert calendar event not found: {args.path}")
        payload = (
            {"dry_run": True, "current": current, "patch": patch}
            if not args.yes
            else update_calendar_event_with_opener(
                opener, args.date, args.path, patch
            )
        )
    else:
        if not args.yes:
            raise SystemExit("Refusing to delete Xert calendar event without --yes")
        payload = delete_calendar_event_with_opener(opener, args.date, args.path)
    print(json.dumps(payload, indent=2, sort_keys=True))


def _json_object(raw: str, option: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{option} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{option} must contain a JSON object")
    return value


def _require(value: str | None, name: str) -> str:
    if not value:
        raise SystemExit(f"Missing Xert credential: {name}")
    return value


if __name__ == "__main__":
    main()
