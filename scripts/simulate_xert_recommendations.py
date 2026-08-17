#!/usr/bin/env python3
"""Simulate future Xert advice by temporarily completing each prior dose."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
XERT_SCRIPTS = ROOT / "plugins" / "xert" / "scripts"
sys.path.insert(0, str(XERT_SCRIPTS))

from xert_calendar import (  # noqa: E402
    create_calendar_event_with_opener,
    delete_calendar_event_with_opener,
    fetch_calendar_events_with_opener,
    fetch_recommended_training_with_opener,
)
from xert_common import load_xert_credentials, xert_web_login  # noqa: E402


OSLO = ZoneInfo("Europe/Oslo")


def system_values(payload: dict) -> dict[str, float]:
    advice = payload.get("training_advice", payload)
    target = advice.get("targetXSS") or {}
    return {
        "low": float(target.get("xlss") or 0),
        "high": float(target.get("xhss") or 0),
        "peak": float(target.get("xpss") or 0),
    }


def daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("start_date")
    parser.add_argument("end_date")
    parser.add_argument("--start-time", default="11:00")
    parser.add_argument("--xss-per-hour", type=float, default=60.0)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--cleanup-stale", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        parser.error("simulation writes temporary Xert Planner events; use --yes")

    first = date.fromisoformat(args.start_date)
    last = date.fromisoformat(args.end_date)
    hour, minute = (int(part) for part in args.start_time.split(":"))
    credentials = load_xert_credentials()
    if not credentials.username or not credentials.password:
        parser.error("XERT_USERNAME and XERT_PASSWORD are required")

    opener = xert_web_login(
        username=credentials.username,
        password=credentials.password,
    )
    if args.cleanup_stale:
        deleted = []
        for day in daterange(first, last):
            for event in fetch_calendar_events_with_opener(opener, day)["events"]:
                name = str(event.get("name") or "")
                if name.startswith(("Codex Xert simulation ", "Codex sequential simulation ")):
                    path = event.get("path") or event.get("id")
                    delete_calendar_event_with_opener(opener, day, str(path))
                    deleted.append({"date": day.isoformat(), "path": path})
        print(json.dumps({"deleted": deleted, "success": True}, indent=2))
        return
    created: list[tuple[date, str]] = []
    results = []
    cleanup_errors = []
    prefix = f"Codex Xert simulation {datetime.now().isoformat(timespec='seconds')}"
    try:
        for day in daterange(first, last):
            recommendation = fetch_recommended_training_with_opener(
                opener,
                date_value=day,
                recent=True,
                additional=False,
                sport=None,
            )
            systems = system_values(recommendation)
            total = sum(systems.values())
            results.append({"date": day.isoformat(), "xss": total, **systems})
            if day == last:
                continue

            duration_seconds = round(total / args.xss_per_hour * 3600)
            start_at = datetime.combine(day, time(hour, minute), tzinfo=OSLO)
            end_at = start_at + timedelta(seconds=duration_seconds)
            title = f"{prefix} {day.isoformat()}"
            event = {
                "start_date": start_at.isoformat(),
                "end_date": end_at.isoformat(),
                "duration": duration_seconds,
                "manualExercise": True,
                "sport": "Cycling",
                "title": title,
                "description": "Temporary sequential completed-dose simulation; remove after run.",
                "focus": "Triathlete",
                "sfd": 10800,
                "specificity_rating": "Mixed",
                "sp": 0.5,
                "xss": total,
                "xlss": systems["low"],
                "xhss": systems["high"],
                "xpss": systems["peak"],
                "options": {
                    "state": ["completed", "recommended", "manualEntry"],
                },
            }
            created_result = create_calendar_event_with_opener(opener, event)
            created.append((day, created_result["event"]["path"]))
    finally:
        for event_day, path in reversed(created):
            try:
                delete_calendar_event_with_opener(opener, event_day, path)
            except Exception as exc:  # Cleanup errors must be visible in output.
                cleanup_errors.append({"date": event_day.isoformat(), "path": path, "error": str(exc)})

    output = {
        "assumption": "Each prior day's recommended XSS dose is marked completed before the next query.",
        "xss_per_hour_for_duration": args.xss_per_hour,
        "results": results,
        "temporary_events_created": len(created),
        "cleanup_errors": cleanup_errors,
        "cleanup_success": not cleanup_errors,
    }
    print(json.dumps(output, indent=2))
    if cleanup_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
