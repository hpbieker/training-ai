#!/usr/bin/env python3
"""Stateless command line access to Xert.

This CLI prints live Xert payloads or compact JSON summaries to stdout. It does
not write local cache files; callers that want persistence should redirect or
store the output at their own layer.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from xert_api import (
    LOCAL_TIMEZONE,
    _request_json,
    delete_workout,
    fetch_activity_detail,
    fetch_calendar_notes_with_opener,
    fetch_recommended_training_with_login,
    fetch_recovery_model_with_login,
    fetch_training_forecast_with_login,
    fetch_workout,
    fetch_workout_designer_rows,
    list_activities,
    list_workouts,
    load_xert_credentials,
    set_calendar_note,
    summarize_workout_library,
    update_workout,
    xert_web_login,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Xert access without local caching.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    activities = subparsers.add_parser(
        "activities",
        help="List Xert activities for an inclusive local-date range",
    )
    activities.add_argument("start", help="Local start date, YYYY-MM-DD")
    activities.add_argument("end", help="Local end date, YYYY-MM-DD")

    activity = subparsers.add_parser("activity", help="Fetch one Xert activity detail payload")
    activity.add_argument("path", help="Xert activity path from activities output")
    activity.add_argument("--session-data", action="store_true")
    activity.add_argument(
        "--summary-only",
        action="store_true",
        help="Return compact activity load fields without second-by-second session data",
    )
    activity.add_argument(
        "--output",
        help="Write activity JSON to this file instead of stdout. Required with --session-data.",
    )

    subparsers.add_parser("training-info", help="Fetch current Xert training_info payload")
    subparsers.add_parser("recovery-model", help="Fetch model inputs and calculated recovery hours")
    readiness_input = subparsers.add_parser(
        "readiness-input",
        help="Fetch and compact selected Xert fields for readiness consumers",
    )
    readiness_input.add_argument(
        "--activity",
        action="append",
        default=[],
        help="Include one Xert activity path as a compact activity_load. Repeat as needed.",
    )
    subparsers.add_parser("training-forecast", help="Fetch Xert calendar training forecast")
    subparsers.add_parser("calendar-notes", help="Fetch Xert calendar notes")

    calendar_note_set = subparsers.add_parser(
        "calendar-note-set",
        help="Set one Xert calendar note and verify it",
    )
    calendar_note_set.add_argument("date", help="Local calendar date, YYYY-MM-DD")
    calendar_note_set.add_argument("notes", help="Note text. Use an empty string to clear it.")
    calendar_note_set.add_argument("--update-weight", action="store_true")
    calendar_note_set.add_argument("--weight", type=float)
    calendar_note_set.add_argument("--weight-units", default="kg")
    calendar_note_set.add_argument("--yes", action="store_true", help="Confirm the write")

    recommended = subparsers.add_parser("recommended-training", help="Fetch recommended training")
    recommended.add_argument("--date", default=date.today().isoformat())
    recommended.add_argument("--recent", action=argparse.BooleanOptionalAction, default=True)
    recommended.add_argument("--additional", action=argparse.BooleanOptionalAction, default=False)
    recommended.add_argument("--sport")

    workouts = subparsers.add_parser("workouts", help="List Xert workout library")
    workouts.add_argument("--contains", help="Only include workouts whose name contains this text")
    workouts.add_argument("--summary", action="store_true", help="Return compact workout rows")

    workout = subparsers.add_parser("workout", help="Fetch one resolved Xert workout")
    workout.add_argument("path", help="Xert workout path")

    workout_rows = subparsers.add_parser(
        "workout-rows",
        help="Fetch editable Xert Workout Designer rows for a workout",
    )
    workout_rows.add_argument("path", help="Xert workout path")

    workout_update = subparsers.add_parser(
        "workout-update",
        help="Update a Xert workout through Workout Designer rows",
    )
    workout_update.add_argument("path", help="Xert workout path")
    workout_update.add_argument("--name")
    workout_update.add_argument("--description")
    workout_update.add_argument("--match-name")
    workout_update.add_argument("--match-power", type=float)
    workout_update.add_argument("--set-duration")
    workout_update.add_argument("--set-power", type=float)
    workout_update.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate with Xert calculate instead of saving",
    )
    workout_update.add_argument("--yes", action="store_true", help="Confirm the write")

    workout_delete = subparsers.add_parser("workout-delete", help="Delete a Xert workout")
    workout_delete.add_argument("path", help="Xert workout path")
    workout_delete.add_argument("--yes", action="store_true", help="Confirm destructive deletion")

    args = parser.parse_args()
    credentials = load_xert_credentials()

    if args.command == "activities":
        payload = list_activities(
            username=credentials.username,
            password=credentials.password,
            oldest=args.start,
            newest=args.end,
        )
    elif args.command == "activity":
        if args.session_data and args.summary_only:
            raise SystemExit("Use either --session-data or --summary-only, not both")
        if args.session_data and not args.output:
            raise SystemExit("Use --output <file> with --session-data to avoid huge terminal output")
        activity_payload = fetch_activity_detail(
            args.path,
            username=credentials.username,
            password=credentials.password,
            include_session_data=args.session_data,
        )
        if args.summary_only:
            payload = compact_activity_load(activity_payload)
            payload["path"] = args.path
        else:
            payload = activity_payload
    elif args.command == "training-info":
        payload = fetch_training_info(
            username=credentials.username,
            password=credentials.password,
        )
    elif args.command == "recovery-model":
        payload = fetch_recovery_model_with_login(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
        )
    elif args.command == "readiness-input":
        payload = build_readiness_input(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            activity_paths=args.activity,
        )
    elif args.command == "training-forecast":
        payload = fetch_training_forecast_with_login(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
        )
    elif args.command == "calendar-notes":
        opener = xert_web_login(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
        )
        payload = fetch_calendar_notes_with_opener(opener)
    elif args.command == "calendar-note-set":
        if not args.yes:
            raise SystemExit("Refusing to set Xert calendar note without --yes")
        payload = set_calendar_note(
            args.date,
            args.notes,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            update_weight=args.update_weight,
            weight=args.weight,
            weight_units=args.weight_units,
        )
        if not payload.get("success"):
            raise SystemExit(json.dumps(payload, indent=2, sort_keys=True))
    elif args.command == "recommended-training":
        payload = fetch_recommended_training_with_login(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            date_value=args.date,
            recent=args.recent,
            additional=args.additional,
            sport=args.sport,
        )
    elif args.command == "workouts":
        workouts_payload = list_workouts(
            username=credentials.username,
            password=credentials.password,
        )
        payload = (
            summarize_workout_library(workouts_payload, name_filter=args.contains)
            if args.summary
            else _filter_workouts(workouts_payload, args.contains)
        )
    elif args.command == "workout":
        payload = fetch_workout(
            args.path,
            username=credentials.username,
            password=credentials.password,
        )
    elif args.command == "workout-rows":
        opener = xert_web_login(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
        )
        payload = fetch_workout_designer_rows(opener, args.path)
    elif args.command == "workout-update":
        if not args.dry_run and not args.yes:
            raise SystemExit("Refusing to save Xert workout update without --yes")
        payload = update_workout(
            args.path,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            name=args.name,
            description=args.description,
            match_name=args.match_name,
            match_power=args.match_power,
            set_duration=args.set_duration,
            set_power=args.set_power,
            submit="calculate" if args.dry_run else "save",
        )
    elif args.command == "workout-delete":
        if not args.yes:
            raise SystemExit("Refusing to delete Xert workout without --yes")
        payload = delete_workout(
            args.path,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
        )
    else:
        raise AssertionError(f"Unhandled command: {args.command}")

    output_path = getattr(args, "output", None)
    if output_path:
        Path(output_path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"wrote": output_path}, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def fetch_training_info(
    *,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    from xert_api import XertCredentials

    token = XertCredentials(
        username=username,
        password=password,
    ).bearer_token()
    payload = _request_json("/oauth/training_info", token)
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert training_info endpoint to return an object")
    return payload


def build_readiness_input(
    *,
    username: str,
    password: str,
    activity_paths: list[str],
) -> dict[str, Any]:
    model = fetch_recovery_model_with_login(username=username, password=password)
    return {
        "source": "xert_plugin",
        "source_time_local": datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
        "recovery": compact_recovery_model(model),
        "activity_loads": [
            compact_activity_load(
                fetch_activity_detail(
                    activity_path,
                    username=username,
                    password=password,
                    include_session_data=False,
                )
            )
            for activity_path in activity_paths
        ],
    }


def compact_recovery_model(model: dict[str, Any]) -> dict[str, Any]:
    at_state = model.get("at_state") if isinstance(model.get("at_state"), dict) else {}
    training_load = at_state.get("tl") if isinstance(at_state, dict) else {}
    recovery_load = at_state.get("rl") if isinstance(at_state, dict) else {}
    return {
        "source": model.get("source"),
        "training_status": model.get("training_status"),
        "target_xss": _system_triplet(model.get("targetXSS"), "xlss", "xhss", "xpss"),
        "recovery_offset": model.get("recovery_offset"),
        "next_workout_days": model.get("next_workout_days"),
        "recovery_hours": _system_triplet(model.get("recovery_hours"), "lo", "hi", "pk"),
        "training_load": _system_triplet(training_load, "ftp", "hie", "pp"),
        "recovery_load": _system_triplet(recovery_load, "ftp", "hie", "pp"),
        "workout_capacity": _system_triplet(model.get("workout_capacity"), "lo", "hi", "pk"),
    }


def compact_activity_load(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
    if not isinstance(summary, dict):
        raise TypeError("Expected Xert activity payload to contain an object summary")
    progression = summary.get("progression") if isinstance(summary.get("progression"), dict) else {}
    xss = progression.get("xss") if isinstance(progression.get("xss"), dict) else {}
    session = summary.get("session") if isinstance(summary.get("session"), dict) else {}
    return {
        "source": "xert_plugin",
        "path": payload.get("path") or summary.get("path"),
        "name": payload.get("name") or summary.get("name"),
        "start_local": _activity_start_local(summary),
        "elapsed_minutes": _minutes(_number(summary.get("duration") or session.get("total_elapsed_time"))),
        "xss": {
            "total": summary.get("xss") or xss.get("total"),
            "low": summary.get("xlss") or xss.get("xlss"),
            "high": summary.get("xhss") or xss.get("xhss"),
            "peak": summary.get("xpss") or xss.get("xpss"),
        },
        "xep_watts": summary.get("xep"),
        "focus": summary.get("focus"),
        "specificity": summary.get("specificity"),
        "difficulty": summary.get("difficulty"),
        "difficulty_rating": summary.get("difficulty_rating"),
        "freshness": summary.get("freshness"),
        "signature": summary.get("sig") or progression.get("signature"),
    }


def _system_triplet(source: Any, low_key: str, high_key: str, peak_key: str) -> dict[str, Any]:
    if not isinstance(source, dict):
        source = {}
    return {
        "low": source.get(low_key),
        "high": source.get(high_key),
        "peak": source.get(peak_key),
    }


def _activity_start_local(summary: dict[str, Any]) -> str | None:
    start = summary.get("start_date")
    if isinstance(start, dict):
        raw = start.get("date")
        if raw:
            parsed = datetime.fromisoformat(str(raw))
            if start.get("timezone") == "UTC":
                parsed = parsed.replace(tzinfo=timezone.utc).astimezone(LOCAL_TIMEZONE)
            return parsed.replace(tzinfo=None).isoformat()
    raw_progression_start = (summary.get("progression") or {}).get("start_date")
    if raw_progression_start:
        return (
            datetime.fromisoformat(str(raw_progression_start).replace("Z", "+00:00"))
            .astimezone(LOCAL_TIMEZONE)
            .replace(tzinfo=None)
            .isoformat()
        )
    return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _minutes(seconds: float | None) -> float | None:
    return round(seconds / 60, 1) if seconds is not None else None


def _filter_workouts(workouts: list[dict[str, Any]], contains: str | None) -> list[dict[str, Any]]:
    if not contains:
        return workouts
    needle = contains.lower()
    return [row for row in workouts if needle in str(row.get("name") or "").lower()]


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"Set {name} in .env")
    return value


if __name__ == "__main__":
    main()
