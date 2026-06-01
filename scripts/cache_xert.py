#!/usr/bin/env python3
"""Cache Xert training status and activity summaries for local analysis."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from xert_api import (
    cache_activity_summaries,
    cache_calendar_notes,
    cache_recommended_training,
    cache_recovery_model,
    cache_training_forecast,
    cache_training_info,
    cache_workout,
    cache_workouts,
    copy_workout,
    copy_workout_with_rows,
    delete_workout,
    list_workouts,
    load_xert_credentials,
    replace_workout_with_rows,
    schedule_calendar_low_xss,
    set_calendar_note,
    summarize_workout_library,
    update_workout,
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
    activities.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download activity details that are already cached",
    )

    subparsers.add_parser("training-info", help="Cache current Xert training info")
    workouts = subparsers.add_parser("workouts", help="Cache the user's Xert workout library")
    workouts.add_argument("--filter", help="Only show workouts whose name contains this text")
    workouts.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact workout table after caching",
    )
    workout = subparsers.add_parser("workout", help="Cache one resolved Xert workout")
    workout.add_argument("path", help="Xert workout path from the workouts list")
    update_workout_parser = subparsers.add_parser(
        "update-workout",
        help="Update a Xert workout through Workout Designer rows",
    )
    update_workout_parser.add_argument("path", help="Xert workout path")
    update_workout_parser.add_argument("--name", help="Replacement workout name")
    update_workout_parser.add_argument(
        "--description",
        help="Replacement workout description",
    )
    update_workout_parser.add_argument(
        "--match-name",
        help="Only update rows with this exact designer row name",
    )
    update_workout_parser.add_argument(
        "--match-power",
        type=float,
        help="Only update rows with this exact power value",
    )
    update_workout_parser.add_argument(
        "--set-duration",
        help="Set matching row duration, e.g. 26:00",
    )
    update_workout_parser.add_argument(
        "--set-power",
        type=float,
        help="Set matching row power value",
    )
    update_workout_parser.add_argument(
        "--submit",
        choices=("calculate", "save"),
        default="save",
        help="Use calculate to validate without saving, or save to persist",
    )
    delete_workout_parser = subparsers.add_parser(
        "delete-workout",
        help="Delete a Xert workout from the web workout library",
    )
    delete_workout_parser.add_argument("path", help="Xert workout path")
    delete_workout_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive deletion",
    )
    copy_workout_parser = subparsers.add_parser(
        "copy-workout",
        help="Copy a Xert workout through Workout Designer rows",
    )
    copy_workout_parser.add_argument("path", help="Source Xert workout path")
    copy_workout_parser.add_argument("--name", required=True, help="New workout name")
    copy_workout_parser.add_argument("--description", help="New workout description")
    copy_workout_parser.add_argument(
        "--match-name",
        help="Only modify/trim rows with this exact designer row name",
    )
    copy_workout_parser.add_argument(
        "--match-power",
        type=float,
        help="Only modify/trim rows with this exact power value",
    )
    copy_workout_parser.add_argument(
        "--set-power",
        type=float,
        help="Set matching row power value in the copy",
    )
    copy_workout_parser.add_argument(
        "--set-interval-count",
        type=int,
        help="Set matching row interval count in the copy",
    )
    copy_workout_parser.add_argument(
        "--keep-matching-rows",
        type=int,
        help="Keep only this many matching rows in the copy",
    )
    moxy_515 = subparsers.add_parser(
        "create-moxy-515",
        help="Create a simple Moxy 5-1-5 stepped test workout in Xert",
    )
    moxy_515.add_argument(
        "--template",
        default="pliignnw1x62b5wp",
        help="Existing workout path to copy as the Workout Designer template",
    )
    moxy_515.add_argument(
        "--replace-path",
        help="Replace an existing workout in place instead of creating a copy",
    )
    moxy_515.add_argument("--name", default="Moxy 515 test")
    moxy_515.add_argument(
        "--description",
        default="Linear 5-1-5 Moxy test: 5 min steps with 1 min recovery.",
    )
    moxy_515.add_argument("--start-watts", type=int, default=285)
    moxy_515.add_argument("--end-watts", type=int, default=320)
    moxy_515.add_argument("--step-watts", type=int, default=5)
    moxy_515.add_argument("--work-duration", default="5:00")
    moxy_515.add_argument("--recovery-duration", default="1:00")
    moxy_515.add_argument("--recovery-watts", type=int, default=155)
    moxy_515.add_argument("--warmup-duration", default="12:00")
    moxy_515.add_argument("--cooldown-duration", default="3:00")
    moxy_515.add_argument(
        "--endurance-duration",
        help="Optional steady endurance block after the final step, e.g. 45:00",
    )
    moxy_515.add_argument("--endurance-watts", type=int, default=205)
    moxy_515.add_argument("--endurance-reps", type=int, default=1)
    subparsers.add_parser(
        "training-forecast",
        help="Cache Xert calendar training forecast using XERT_COOKIE",
    )
    subparsers.add_parser(
        "calendar-notes",
        help="Cache Xert calendar notes",
    )
    set_note = subparsers.add_parser(
        "set-calendar-note",
        help="Set one Xert calendar note and verify it",
    )
    set_note.add_argument("date", help="Local calendar date, e.g. 2026-05-27")
    set_note.add_argument("notes", help="Note text. Use an empty string to clear it.")
    set_note.add_argument("--update-weight", action="store_true")
    set_note.add_argument("--weight", type=float)
    set_note.add_argument("--weight-units", default="kg")
    schedule_low = subparsers.add_parser(
        "schedule-low-xss",
        help="Schedule a manual low-XSS calendar entry and verify it",
    )
    schedule_low.add_argument("date", help="Local calendar date, e.g. 2026-05-26")
    schedule_low.add_argument("low_xss", type=float, help="Low XSS to schedule")
    schedule_low.add_argument("--high-xss", type=float, default=0.0)
    schedule_low.add_argument("--peak-xss", type=float, default=0.0)
    schedule_low.add_argument("--title", default="Pure Endurance Training")
    schedule_low.add_argument("--at", help="Local start time, e.g. 12:00")
    schedule_low.add_argument("--duration-hours", type=float, default=0.0)
    subparsers.add_parser(
        "recovery-model",
        help="Calculate Xert recovery days from direct web model inputs",
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
            refresh=args.refresh,
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
        if args.summary or args.filter:
            workouts = list_workouts(
                access_token=credentials.access_token,
                username=credentials.username,
                password=credentials.password,
            )
            _print_workout_summary(
                summarize_workout_library(workouts, name_filter=args.filter),
            )
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

    if args.command == "update-workout":
        result = update_workout(
            args.path,
            username=credentials.username,
            password=credentials.password,
            name=args.name,
            description=args.description,
            match_name=args.match_name,
            match_power=args.match_power,
            set_duration=args.set_duration,
            set_power=args.set_power,
            submit=args.submit,
        )
        _print_artifacts(result)
        return

    if args.command == "delete-workout":
        if not args.yes:
            raise SystemExit("Refusing to delete workout without --yes")
        result = delete_workout(
            args.path,
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(result)
        return

    if args.command == "copy-workout":
        result = copy_workout(
            args.path,
            username=credentials.username,
            password=credentials.password,
            name=args.name,
            description=args.description,
            match_name=args.match_name,
            match_power=args.match_power,
            set_power=args.set_power,
            set_interval_count=args.set_interval_count,
            keep_matching_rows=args.keep_matching_rows,
        )
        _print_artifacts(result)
        return

    if args.command == "create-moxy-515":
        rows = _build_moxy_515_rows(
            start_watts=args.start_watts,
            end_watts=args.end_watts,
            step_watts=args.step_watts,
            work_duration=args.work_duration,
            recovery_duration=args.recovery_duration,
            recovery_watts=args.recovery_watts,
            warmup_duration=args.warmup_duration,
            cooldown_duration=args.cooldown_duration,
            endurance_duration=args.endurance_duration,
            endurance_watts=args.endurance_watts,
            endurance_reps=args.endurance_reps,
        )
        kwargs = {
            "username": credentials.username,
            "password": credentials.password,
            "name": args.name,
            "description": args.description,
            "rows": rows,
        }
        result = (
            replace_workout_with_rows(args.replace_path, **kwargs)
            if args.replace_path
            else copy_workout_with_rows(args.template, **kwargs)
        )
        _print_artifacts(result)
        return

    if args.command == "training-forecast":
        artifacts = cache_training_forecast(
            cookie=credentials.cookie,
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "calendar-notes":
        artifacts = cache_calendar_notes(
            username=credentials.username,
            password=credentials.password,
        )
        _print_artifacts(artifacts)
        return

    if args.command == "set-calendar-note":
        result = set_calendar_note(
            args.date,
            args.notes,
            username=credentials.username,
            password=credentials.password,
            update_weight=args.update_weight,
            weight=args.weight,
            weight_units=args.weight_units,
        )
        _print_artifacts(result)
        if not result.get("success"):
            raise SystemExit("Xert calendar note verification failed")
        return

    if args.command == "schedule-low-xss":
        result = schedule_calendar_low_xss(
            args.date,
            args.low_xss,
            username=credentials.username,
            password=credentials.password,
            title=args.title,
            at=args.at,
            high_xss=args.high_xss,
            peak_xss=args.peak_xss,
            duration_hours=args.duration_hours,
        )
        _print_artifacts(result)
        if not result.get("success"):
            raise SystemExit("Xert low-XSS calendar verification failed")
        return

    if args.command == "recovery-model":
        artifacts = cache_recovery_model(
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


def _print_workout_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No workouts matched.")
        return
    columns = [
        ("name", "Name"),
        ("duration_min", "Min"),
        ("work_watts", "W"),
        ("xss", "XSS"),
        ("xlss", "Low"),
        ("xhss", "High"),
        ("xpss", "Peak"),
        ("difficulty", "Diff"),
        ("path", "Path"),
    ]
    widths = {
        key: max(len(label), *(len(_format_cell(row.get(key))) for row in rows))
        for key, label in columns
    }
    print("  ".join(label.ljust(widths[key]) for key, label in columns))
    print("  ".join("-" * widths[key] for key, _label in columns))
    for row in rows:
        print("  ".join(_format_cell(row.get(key)).ljust(widths[key]) for key, _label in columns))


def _build_moxy_515_rows(
    *,
    start_watts: int,
    end_watts: int,
    step_watts: int,
    work_duration: str,
    recovery_duration: str,
    recovery_watts: int,
    warmup_duration: str,
    cooldown_duration: str,
    endurance_duration: str | None = None,
    endurance_watts: int = 205,
    endurance_reps: int = 1,
) -> list[dict[str, Any]]:
    if step_watts <= 0:
        raise ValueError("step_watts must be positive")
    if end_watts < start_watts:
        raise ValueError("end_watts must be greater than or equal to start_watts")
    if endurance_reps <= 0:
        raise ValueError("endurance_reps must be positive")
    watts = list(range(start_watts, end_watts + 1, step_watts))
    if not watts or watts[-1] != end_watts:
        raise ValueError("end_watts must align with start_watts and step_watts")

    rows: list[dict[str, Any]] = []

    def add_row(name: str, duration: str, power: dict[str, Any]) -> None:
        sequence = len(rows)
        rows.append(
            {
                "DT_RowId": str(sequence),
                "duration": {"value": duration, "type": "absolute"},
                "interval_count": "1",
                "name": name,
                "power": power,
                "rib_duration": {"value": "00:00", "type": "absolute"},
                "rib_power": {"value": 0, "type": "absolute"},
                "sequence": sequence,
            }
        )

    add_row(
        "Warmup",
        warmup_duration,
        {"value": 55, "second_value": 70, "type": "ramp_ftp"},
    )
    for index, watt in enumerate(watts):
        add_row(f"Step {watt}W", work_duration, {"value": watt, "type": "absolute"})
        if index != len(watts) - 1:
            add_row(
                "Recovery",
                recovery_duration,
                {"value": recovery_watts, "type": "absolute"},
            )
    if endurance_duration:
        add_row("Endurance", endurance_duration, {"value": endurance_watts, "type": "absolute"})
        rows[-1]["interval_count"] = str(endurance_reps)
    add_row("Cooldown", cooldown_duration, {"value": 45, "type": "relative_ftp"})
    return rows


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


if __name__ == "__main__":
    main()
