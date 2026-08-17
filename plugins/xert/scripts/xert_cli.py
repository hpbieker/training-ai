#!/usr/bin/env python3
"""Stateless command line access to Xert.

This CLI prints live Xert payloads or compact JSON summaries to stdout. It does
not write local files; callers that want persistence should redirect or store
the output at their own layer.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from xert_api import (
    LOCAL_TIMEZONE,
    _request_json,
    create_calendar_event_with_opener,
    delete_calendar_event_with_opener,
    delete_workout,
    fetch_activity_detail,
    fetch_activity_event_metadata_for_starts,
    fetch_flagged_activity_starts_with_login,
    fetch_calendar_notes_with_opener,
    fetch_calendar_event_with_opener,
    fetch_calendar_events_with_opener,
    fetch_recommended_training_with_login,
    fetch_recovery_model_with_login,
    calculate_workout_capacity,
    fetch_fitness_measures_with_login,
    fetch_training_forecast_with_login,
    fetch_workout,
    fetch_workout_designer_rows,
    calculate_new_workout,
    list_activities,
    list_activity_details,
    list_workouts,
    load_xert_credentials,
    mutate_workout_row,
    replace_workout,
    set_calendar_note,
    summarize_workout_library,
    update_workout,
    update_calendar_event_with_opener,
    xert_web_login,
    calculate_load_projection,
    linear_daily_xss_distribution,
    recovery_demand_sensitivity,
    summarize_signature_decay_analysis,
    validate_fitness_measures_history,
    validate_freshness_history,
    validate_signature_history,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Xert access.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    activities = subparsers.add_parser(
        "activities",
        help="List Xert activities for an inclusive local-date range",
    )
    activities.add_argument("start", help="Local start date, YYYY-MM-DD")
    activities.add_argument("end", help="Local end date, YYYY-MM-DD")

    activity_loads = subparsers.add_parser(
        "activity-loads",
        help="Fetch compact XSS load rows for activities in an inclusive local-date range",
    )
    activity_loads.add_argument("start", help="Local start date, YYYY-MM-DD")
    activity_loads.add_argument("end", help="Local end date, YYYY-MM-DD")

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
    workout_capacity = subparsers.add_parser(
        "workout-capacity",
        help="Calculate XSS capacity at one time while arriving fresh at another",
    )
    workout_capacity.add_argument(
        "--as-of",
        required=True,
        help=(
            "Time at which capacity applies as an ISO date-time; naive values use "
            "the machine timezone, and Z or explicit UTC offsets are accepted"
        ),
    )
    workout_capacity.add_argument(
        "--fresh-at",
        required=True,
        help=(
            "Time by which the modeled state must be fresh as an ISO date-time; "
            "naive values use the machine timezone, "
            "and Z or explicit UTC offsets are accepted"
        ),
    )
    load_model = subparsers.add_parser(
        "load-model",
        help="Project and validate Xert TL, RL, Form, status, and Fitness Signature response",
    )
    load_model.add_argument(
        "--target-at",
        required=True,
        help=(
            "Projection target as ISO date-time; naive values use the machine timezone, "
            "and Z or explicit UTC offsets are accepted"
        ),
    )
    load_model.add_argument(
        "--workout-after-hours",
        type=float,
        default=0.0,
        help="Hours from the current Xert state until the modeled workout impulse",
    )
    load_model.add_argument("--low-xss", type=float, default=0.0)
    load_model.add_argument("--high-xss", type=float, default=0.0)
    load_model.add_argument("--peak-xss", type=float, default=0.0)
    load_model_tp_target = load_model.add_mutually_exclusive_group()
    load_model_tp_target.add_argument(
        "--build-tp", type=float, default=0.0, help="Desired TP gain in W"
    )
    load_model_tp_target.add_argument("--target-tp", type=float, help="Absolute target TP in W")
    load_model.add_argument("--build-hie", type=float, default=0.0, help="Desired HIE gain in kJ")
    load_model.add_argument("--build-pp", type=float, default=0.0, help="Desired PP gain in W")
    load_model.add_argument("--distribution", choices=("linear",))
    load_model.add_argument("--frequency", choices=("daily",))
    load_model.add_argument(
        "--start-low-xss",
        type=float,
        help="First Low XSS dose; defaults to current-load maintenance",
    )
    load_model.add_argument(
        "--summary",
        action="store_true",
        help="Return compact timing, signature, and required-XSS projection fields",
    )
    load_model.add_argument(
        "--validate-history",
        action="store_true",
        help="Validate EWMA transitions against Xert Fitness Measures pre-activity states",
    )
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
    readiness_input.add_argument(
        "--advice-source",
        choices=("current", "recommended-training", "auto"),
        default="current",
        help=(
            "Source for normalized training_advice. Use current for fast /my-fitness "
            "advice now; use recommended-training when advice is needed for a planned "
            "time; use auto to switch when the planned time differs from now and "
            "current Xert state is not fresh."
        ),
    )
    readiness_input.add_argument(
        "--advice-date",
        help=(
            "Date or ISO datetime passed to /recommended-training when "
            "--advice-source recommended-training is used. Defaults to today."
        ),
    )
    readiness_input.add_argument(
        "--advice-at",
        help=(
            "Planned local/ISO datetime for /recommended-training. The Xert UI "
            "sends selected time minus one second; this option mirrors that and "
            "adds recovery.recovery_hours_at_advice_time."
        ),
    )
    readiness_input.add_argument(
        "--advice-now",
        help="Current local/ISO datetime for --advice-source auto. Defaults to system now.",
    )
    subparsers.add_parser("training-forecast", help="Fetch Xert calendar training forecast")
    subparsers.add_parser("calendar-notes", help="Fetch Xert calendar notes")

    calendar_events = subparsers.add_parser(
        "calendar-events", help="List Xert Planner events for one date"
    )
    calendar_events.add_argument("date", help="Calendar date, YYYY-MM-DD")

    calendar_event = subparsers.add_parser(
        "calendar-event", help="Read one Xert Planner event"
    )
    calendar_event.add_argument("path", help="Planner event path")
    calendar_event.add_argument("--date", required=True, help="Event date, YYYY-MM-DD")

    calendar_event_create = subparsers.add_parser(
        "calendar-event-create", help="Create an Xert Planner event from JSON"
    )
    calendar_event_create.add_argument("--event-json", required=True)
    calendar_event_create.add_argument("--yes", action="store_true", help="Confirm the write")

    calendar_event_update = subparsers.add_parser(
        "calendar-event-update", help="Patch an Xert Planner event from JSON"
    )
    calendar_event_update.add_argument("path", help="Planner event path")
    calendar_event_update.add_argument("--date", required=True, help="Current event date")
    calendar_event_update.add_argument("--patch-json", required=True)
    calendar_event_update.add_argument("--yes", action="store_true", help="Confirm the write")

    calendar_event_delete = subparsers.add_parser(
        "calendar-event-delete", help="Delete an Xert Planner event"
    )
    calendar_event_delete.add_argument("path", help="Planner event path")
    calendar_event_delete.add_argument("--date", required=True, help="Event date, YYYY-MM-DD")
    calendar_event_delete.add_argument(
        "--yes", action="store_true", help="Confirm destructive deletion"
    )

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
    recommended.add_argument(
        "--recent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Keep the Xert query value recent=true for normal recommendations. "
            "Use --no-recent only when older repeatable activities should be included."
        ),
    )
    recommended.add_argument(
        "--additional",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Allow additional/extra training suggestions. Keep the Xert query "
            "value additional=false for the primary training advice dose."
        ),
    )
    recommended.add_argument("--sport")

    workouts = subparsers.add_parser("workouts", help="List Xert workout library")
    workouts.add_argument(
        "--name",
        help="Filter workouts by case-insensitive name keywords; all words must occur",
    )
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
    workout_update.add_argument("--expect-matches", type=int, default=1)
    workout_update.add_argument("--set-duration")
    workout_update.add_argument("--set-power", type=float)
    workout_update.add_argument("--set-power-type")
    workout_update.add_argument("--set-power-second-value", type=float)
    workout_update.add_argument("--set-row-name")
    workout_update.add_argument("--set-interval-count")
    workout_update.add_argument("--set-rib-duration")
    workout_update.add_argument("--set-rib-power", type=float)
    workout_update.add_argument("--set-rib-power-type")
    workout_update.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate with Xert calculate instead of saving",
    )
    workout_update.add_argument("--yes", action="store_true", help="Confirm the write")

    workout_replace = subparsers.add_parser(
        "workout-replace",
        help="Atomically replace every Workout Designer row",
    )
    workout_replace.add_argument("path", help="Xert workout path")
    workout_replace_input = workout_replace.add_mutually_exclusive_group(required=True)
    workout_replace_input.add_argument(
        "--rows-json",
        type=Path,
        help="JSON file containing a non-empty array of complete Workout Designer rows",
    )
    workout_replace_input.add_argument(
        "--row-json",
        action="append",
        help=(
            "Inline compact JSON row; repeat in execution order. Uses the same "
            "row fields as workout-calculate --row-json."
        ),
    )
    workout_replace.add_argument("--name")
    workout_replace.add_argument("--description")
    workout_replace.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the complete replacement with Xert calculate without saving",
    )
    workout_replace.add_argument("--yes", action="store_true", help="Confirm the atomic replacement")

    workout_row_add = subparsers.add_parser(
        "workout-row-add",
        help="Insert one Workout Designer row at a one-based row number",
    )
    workout_row_add.add_argument("path", help="Xert workout path")
    workout_row_add.add_argument("row_number", type=int, help="One-based insertion position")
    workout_row_add.add_argument("--name")
    workout_row_add.add_argument("--duration", required=True)
    workout_row_add.add_argument("--power", required=True, type=float)
    workout_row_add.add_argument("--power-type", default="absolute")
    workout_row_add.add_argument("--power-second-value", type=float)
    workout_row_add.add_argument("--interval-count", default="1")
    workout_row_add.add_argument("--rib-duration", default="00:00")
    workout_row_add.add_argument("--rib-power", type=float, default=0)
    workout_row_add.add_argument("--rib-power-type", default="absolute")
    workout_row_add.add_argument("--dry-run", action="store_true")
    workout_row_add.add_argument("--yes", action="store_true", help="Confirm the write")

    workout_row_update = subparsers.add_parser(
        "workout-row-update",
        help="Patch specified fields on one one-based Workout Designer row",
    )
    workout_row_update.add_argument("path", help="Xert workout path")
    workout_row_update.add_argument("row_number", type=int, help="One-based row number")
    workout_row_update.add_argument("--name")
    workout_row_update.add_argument("--duration")
    workout_row_update.add_argument("--power", type=float)
    workout_row_update.add_argument("--power-type")
    workout_row_update.add_argument("--power-second-value", type=float)
    workout_row_update.add_argument("--interval-count")
    workout_row_update.add_argument("--rib-duration")
    workout_row_update.add_argument("--rib-power", type=float)
    workout_row_update.add_argument("--rib-power-type")
    workout_row_update.add_argument("--dry-run", action="store_true")
    workout_row_update.add_argument("--yes", action="store_true", help="Confirm the write")

    workout_row_remove = subparsers.add_parser(
        "workout-row-remove",
        help="Remove one one-based Workout Designer row",
    )
    workout_row_remove.add_argument("path", help="Xert workout path")
    workout_row_remove.add_argument("row_number", type=int, help="One-based row number")
    workout_row_remove.add_argument("--dry-run", action="store_true")
    workout_row_remove.add_argument("--yes", action="store_true", help="Confirm the write")

    workout_copy = subparsers.add_parser(
        "workout-copy",
        help="Copy a Xert workout through Workout Designer rows",
    )
    workout_copy.add_argument("path", help="Source Xert workout path")
    workout_copy.add_argument("--name", required=True, help="Name for the copied workout")
    workout_copy.add_argument("--description")
    workout_copy.add_argument("--match-name")
    workout_copy.add_argument("--match-power", type=float)
    workout_copy.add_argument("--expect-matches", type=int, default=1)
    workout_copy.add_argument("--set-duration")
    workout_copy.add_argument("--set-power", type=float)
    workout_copy.add_argument("--set-power-type")
    workout_copy.add_argument("--set-power-second-value", type=float)
    workout_copy.add_argument("--set-row-name")
    workout_copy.add_argument("--set-interval-count")
    workout_copy.add_argument("--set-rib-duration")
    workout_copy.add_argument("--set-rib-power", type=float)
    workout_copy.add_argument("--set-rib-power-type")
    workout_copy.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the copied structure with Xert calculate without creating it",
    )
    workout_copy.add_argument("--yes", action="store_true", help="Confirm the write")

    workout_calculate = subparsers.add_parser(
        "workout-calculate",
        help="Calculate a new unsaved Xert workout",
    )
    workout_calculate.add_argument("--name", default="Xert calculate probe")
    workout_calculate.add_argument(
        "--description",
        default="Calculated by training-ai; not saved.",
    )
    workout_calculate.add_argument(
        "--row-json",
        action="append",
        default=[],
        help=(
            "Workout row as JSON. Repeat for warm-up, work/recovery blocks, and "
            "cool-down. Keys: name, duration, power, power_type, interval_count, "
            "rib_duration, rib_power, rib_power_type."
        ),
    )
    workout_calculate.add_argument(
        "--warmup-step",
        action="append",
        default=[],
        metavar="MM:SS@WATTS",
        help="Compact absolute-power warm-up step. Repeat for multiple steps.",
    )
    workout_calculate.add_argument(
        "--interval-block",
        action="append",
        default=[],
        metavar="COUNTxMM:SS@WATTS/MM:SS@WATTS",
        help=(
            "Compact repeated work/recovery block, for example "
            "4x04:00@340/03:00@120. Repeat for multiple blocks."
        ),
    )
    workout_calculate.add_argument(
        "--cooldown-step",
        action="append",
        default=[],
        metavar="MM:SS@WATTS",
        help="Compact absolute-power cool-down step. Repeat for multiple steps.",
    )
    workout_calculate.add_argument("--row-name", default="Probe")
    workout_calculate.add_argument("--duration", help="Work duration, e.g. 10:00")
    workout_calculate.add_argument(
        "--power-type",
        default="relative_ftp",
        choices=["relative_ftp", "absolute"],
        help="Use relative_ftp for percent of TP/FTP or absolute for watts.",
    )
    workout_calculate.add_argument("--power", type=float)
    workout_calculate.add_argument("--interval-count", default="1")
    workout_calculate.add_argument("--rib-duration", default="00:00")
    workout_calculate.add_argument("--rib-power", default=0.0, type=float)
    workout_calculate.add_argument(
        "--rib-power-type",
        default="absolute",
        choices=["relative_ftp", "absolute"],
    )
    workout_calculate.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print only compact calculated workout metrics such as duration, "
            "XSS split, difficulty, focus, and power."
        ),
    )
    workout_calculate.add_argument(
        "--series-output",
        help=(
            "Write Xert calculate second-by-second power, MPA, proximity, "
            "XSS rate, cumulative XSS, and difficulty data to this JSON file."
        ),
    )
    workout_calculate.add_argument(
        "--signature-tp",
        type=float,
        help="Override TP/FTP for this unsaved calculation only.",
    )
    workout_calculate.add_argument(
        "--signature-hie",
        type=float,
        help="Override HIE/ATC in joules for this unsaved calculation only.",
    )
    workout_calculate.add_argument(
        "--signature-pp",
        type=float,
        help="Override Peak Power for this unsaved calculation only.",
    )

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
    elif args.command == "activity-loads":
        details = list_activity_details(
            username=credentials.username,
            password=credentials.password,
            oldest=args.start,
            newest=args.end,
            include_session_data=False,
        )
        payload = {
            "source": "xert_plugin_activity_loads",
            "start_date": args.start,
            "end_date": args.end,
            "activity_count": len(details),
            "activities": [compact_activity_load(detail) for detail in details],
        }
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
    elif args.command == "workout-capacity":
        recovery_model = fetch_recovery_model_with_login(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
        )
        payload = explicit_workout_capacity(
            recovery_model,
            as_of=args.as_of,
            fresh_at=args.fresh_at,
        )
    elif args.command == "load-model":
        username = _require(credentials.username, "XERT_USERNAME")
        password = _require(credentials.password, "XERT_PASSWORD")
        recovery_model = fetch_recovery_model_with_login(username=username, password=password)
        training_info = fetch_training_info(username=username, password=password)
        at_state = dict(recovery_model["at_state"])
        at_state["recovery_offset"] = recovery_model["recovery_offset"]
        horizon_days = projection_horizon_days(
            state_as_of=at_state.get("start_date"),
            target_at=args.target_at,
        )
        if bool(args.distribution) != bool(args.frequency):
            raise ValueError("--distribution and --frequency must be supplied together")
        if (args.distribution or args.frequency or args.start_low_xss is not None) and args.target_tp is None:
            raise ValueError("distributed load requires --target-tp")
        current_tp = float(training_info["signature"]["ftp"])
        build_tp = (
            max(0.0, float(args.target_tp) - current_tp)
            if args.target_tp is not None
            else args.build_tp
        )
        payload = calculate_load_projection(
            at_state=at_state,
            ir_params=recovery_model["ir_params"],
            current_signature=training_info["signature"],
            planned_xss={
                "low": args.low_xss,
                "high": args.high_xss,
                "peak": args.peak_xss,
            },
            horizon_days=horizon_days,
            workout_after_days=args.workout_after_hours / 24.0,
            desired_signature_gain={
                "ftp": build_tp,
                "hie": args.build_hie,
                "pp": args.build_pp,
            },
        )
        if args.target_at:
            payload["target_at"] = normalized_target_at(args.target_at)
        if args.target_tp is not None:
            payload["target_tp"] = float(args.target_tp)
        if args.distribution == "linear" and args.frequency == "daily":
            ftp_params = recovery_model["ir_params"]["ftp"]
            payload["distributed_to_build"] = linear_daily_xss_distribution(
                current_load=float(at_state["tl"]["ftp"]),
                current_signature=current_tp,
                target_signature=float(args.target_tp),
                tau_days=float(ftp_params["tau1"]),
                responsiveness=float(ftp_params["k1"]),
                horizon_days=horizon_days,
                start_xss=args.start_low_xss,
            )
        payload["state_sync"]["input_source"] = "fresh_live_xert_load_model_call"
        payload["current_xert_training_status"] = recovery_model.get("training_status")
        if not args.summary:
            payload["recovery_demand_sensitivity"] = recovery_demand_sensitivity(
                at_state=at_state,
                ir_params=recovery_model["ir_params"],
            )
        if args.validate_history:
            measures = fetch_fitness_measures_with_login(
                username=username,
                password=password,
            )
            payload["validation"] = validate_fitness_measures_history(
                measures["history"],
                ir_params=recovery_model["ir_params"],
            )
            preliminary_signature_validation = validate_signature_history(
                measures["history"],
                ir_params=recovery_model["ir_params"],
            )
            candidate_starts = sorted(
                {
                    candidate["start_date"]
                    for stats in preliminary_signature_validation["systems"].values()
                    for candidate in stats["large_adjustment_candidates"]
                }
            )
            activity_events = fetch_activity_event_metadata_for_starts(
                candidate_starts,
                username=username,
                password=password,
            )
            flagged_activities = fetch_flagged_activity_starts_with_login(
                username=username,
                password=password,
            )
            payload["signature_validation"] = validate_signature_history(
                measures["history"],
                ir_params=recovery_model["ir_params"],
                activity_events=activity_events,
                flagged_activity_starts=set(flagged_activities),
            )
            payload["decay_analysis"] = summarize_signature_decay_analysis(
                payload["signature_validation"],
                decay_method=recovery_model["ir_params"].get("decay_method"),
            )
            payload["freshness_validation"] = validate_freshness_history(
                measures["history"],
                ir_params=recovery_model["ir_params"],
                recovery_offset=recovery_model["recovery_offset"],
            )
        if args.summary:
            payload = compact_load_model_summary(payload)
    elif args.command == "readiness-input":
        payload = build_readiness_input(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            activity_paths=args.activity,
            advice_source=args.advice_source,
            advice_date=args.advice_date,
            advice_at=args.advice_at,
            advice_now=args.advice_now,
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
    elif args.command in {
        "calendar-events",
        "calendar-event",
        "calendar-event-create",
        "calendar-event-update",
        "calendar-event-delete",
    }:
        opener = xert_web_login(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
        )
        if args.command == "calendar-events":
            payload = fetch_calendar_events_with_opener(opener, args.date)
        elif args.command == "calendar-event":
            payload = fetch_calendar_event_with_opener(opener, args.date, args.path)
            if payload is None:
                raise SystemExit(f"Xert calendar event not found: {args.path}")
        elif args.command == "calendar-event-create":
            event = _json_object(args.event_json, "--event-json")
            if not args.yes:
                payload = {"dry_run": True, "event": event}
            else:
                payload = create_calendar_event_with_opener(opener, event)
        elif args.command == "calendar-event-update":
            patch = _json_object(args.patch_json, "--patch-json")
            if not args.yes:
                current = fetch_calendar_event_with_opener(opener, args.date, args.path)
                if current is None:
                    raise SystemExit(f"Xert calendar event not found: {args.path}")
                payload = {"dry_run": True, "current": current, "patch": patch}
            else:
                payload = update_calendar_event_with_opener(
                    opener, args.date, args.path, patch
                )
        else:
            if not args.yes:
                raise SystemExit("Refusing to delete Xert calendar event without --yes")
            payload = delete_calendar_event_with_opener(opener, args.date, args.path)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise SystemExit(json.dumps(payload, indent=2, sort_keys=True))
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
            summarize_workout_library(workouts_payload, name_filter=args.name)
            if args.summary
            else _filter_workouts(workouts_payload, args.name)
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
            expected_matches=args.expect_matches,
            set_duration=args.set_duration,
            set_power=args.set_power,
            set_power_type=args.set_power_type,
            set_power_second_value=args.set_power_second_value,
            set_row_name=args.set_row_name,
            set_interval_count=args.set_interval_count,
            set_rib_duration=args.set_rib_duration,
            set_rib_power=args.set_rib_power,
            set_rib_power_type=args.set_rib_power_type,
            submit="calculate" if args.dry_run else "save",
        )
    elif args.command == "workout-replace":
        if not args.dry_run and not args.yes:
            raise SystemExit("Refusing to replace Xert workout rows without --yes")
        rows = workout_replacement_rows(args)
        payload = replace_workout(
            args.path,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            rows=rows,
            name=args.name,
            description=args.description,
            submit="calculate" if args.dry_run else "save",
        )
    elif args.command == "workout-row-add":
        if not args.dry_run and not args.yes:
            raise SystemExit("Refusing to add Xert workout row without --yes")
        payload = mutate_workout_row(
            args.path,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            operation="add",
            row_number=args.row_number,
            row=workout_probe_row(
                name=args.name or f"Row {args.row_number}",
                duration=args.duration,
                power=args.power,
                power_type=args.power_type,
                interval_count=args.interval_count,
                rib_duration=args.rib_duration,
                rib_power=args.rib_power,
                rib_power_type=args.rib_power_type,
            ),
            set_power_second_value=args.power_second_value,
            submit="calculate" if args.dry_run else "save",
        )
    elif args.command == "workout-row-update":
        if not args.dry_run and not args.yes:
            raise SystemExit("Refusing to update Xert workout row without --yes")
        payload = mutate_workout_row(
            args.path,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            operation="update",
            row_number=args.row_number,
            set_duration=args.duration,
            set_power=args.power,
            set_power_type=args.power_type,
            set_power_second_value=args.power_second_value,
            set_row_name=args.name,
            set_interval_count=args.interval_count,
            set_rib_duration=args.rib_duration,
            set_rib_power=args.rib_power,
            set_rib_power_type=args.rib_power_type,
            submit="calculate" if args.dry_run else "save",
        )
    elif args.command == "workout-row-remove":
        if not args.dry_run and not args.yes:
            raise SystemExit("Refusing to remove Xert workout row without --yes")
        payload = mutate_workout_row(
            args.path,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            operation="remove",
            row_number=args.row_number,
            submit="calculate" if args.dry_run else "save",
        )
    elif args.command == "workout-copy":
        if not args.dry_run and not args.yes:
            raise SystemExit("Refusing to copy Xert workout without --yes")
        payload = update_workout(
            args.path,
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            name=args.name,
            description=args.description,
            match_name=args.match_name,
            match_power=args.match_power,
            expected_matches=args.expect_matches,
            set_duration=args.set_duration,
            set_power=args.set_power,
            set_power_type=args.set_power_type,
            set_power_second_value=args.set_power_second_value,
            set_row_name=args.set_row_name,
            set_interval_count=args.set_interval_count,
            set_rib_duration=args.set_rib_duration,
            set_rib_power=args.set_rib_power,
            set_rib_power_type=args.set_rib_power_type,
            submit="calculate" if args.dry_run else "copy",
        )
    elif args.command == "workout-calculate":
        rows = workout_calculate_rows(args)
        payload = calculate_new_workout(
            username=_require(credentials.username, "XERT_USERNAME"),
            password=_require(credentials.password, "XERT_PASSWORD"),
            name=args.name,
            description=args.description,
            rows=rows,
            include_series=bool(args.series_output),
            signature_tp=args.signature_tp,
            signature_hie=args.signature_hie,
            signature_pp=args.signature_pp,
        )
        if args.series_output:
            series_payload = {
                "saved": False,
                "source": "xert_workout_calculate",
                "signature": payload.pop("signature", None),
                "series": payload.pop("series", None),
                "calculation_stats": payload.pop("calculation_stats", None),
                "timeline_summary": payload.get("timeline_summary"),
                "result": payload.get("result"),
            }
            Path(args.series_output).write_text(
                json.dumps(series_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            payload["series_output"] = args.series_output
        if args.summary:
            payload = compact_workout_calculation_summary(payload)
            if args.series_output:
                payload["series_output"] = args.series_output
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


def projection_horizon_days(
    *,
    state_as_of: Any,
    target_at: str,
) -> float:
    """Resolve an ISO target against the live Xert state."""

    if not state_as_of:
        raise ValueError("Xert state is missing start_date required by --target-at")

    try:
        source = datetime.fromisoformat(str(state_as_of).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Xert state start_date must be an ISO date-time") from exc
    if source.tzinfo is None:
        source = source.astimezone()
    target = datetime.fromisoformat(normalized_target_at(target_at))
    elapsed_days = (
        target.astimezone(timezone.utc) - source.astimezone(timezone.utc)
    ).total_seconds() / 86400
    if elapsed_days < 0:
        raise ValueError("--target-at must not precede the current Xert state")
    return elapsed_days


def explicit_workout_capacity(
    recovery_model: dict[str, Any],
    *,
    as_of: str,
    fresh_at: str,
) -> dict[str, Any]:
    """Calculate capacity from a locally projected explicit state time."""

    at_state = recovery_model.get("at_state")
    if not isinstance(at_state, dict) or not at_state.get("start_date"):
        raise ValueError("Xert recovery model is missing at_state.start_date")
    state_as_of = str(at_state["start_date"])
    source = datetime.fromisoformat(state_as_of.replace("Z", "+00:00"))
    if source.tzinfo is None:
        source = source.astimezone()
    capacity_at = normalized_target_at(as_of)
    projection_days = projection_horizon_days(
        state_as_of=state_as_of,
        target_at=capacity_at,
    )
    projected_state = project_at_state_without_training(
        at_state=at_state,
        ir_params=recovery_model["ir_params"],
        days=projection_days,
        start_date=capacity_at,
    )
    fresh_target = normalized_target_at(fresh_at)
    horizon_days = projection_horizon_days(
        state_as_of=capacity_at,
        target_at=fresh_target,
    )

    capacity = calculate_workout_capacity(
        next_workout_days=horizon_days,
        ir_params=recovery_model["ir_params"],
        recovery_offset=float(recovery_model["recovery_offset"]),
        at_state=projected_state,
    )
    return {
        "source": "xert_plugin_explicit_workout_capacity",
        "source_state_as_of": source.isoformat(),
        "state_as_of": capacity_at,
        "fresh_at": fresh_target,
        "workout_capacity_xss": {
            "low": capacity["lo"],
            "high": capacity["hi"],
            "peak": capacity["pk"],
        },
        "meaning": (
            "Per-system XSS that can be added at state_as_of while arriving "
            "at the Xert fresh boundary at fresh_at"
        ),
        "assumption": "no_intervening_training_before_or_after_the_modeled_impulse",
    }


def project_at_state_without_training(
    *,
    at_state: dict[str, Any],
    ir_params: dict[str, Any],
    days: float,
    start_date: str,
) -> dict[str, Any]:
    """Project Xert TL/RL to an explicit time with no intervening XSS."""

    if days < 0:
        raise ValueError("projection days must not be negative")
    training_load = at_state.get("tl")
    recovery_load = at_state.get("rl")
    if not isinstance(training_load, dict) or not isinstance(recovery_load, dict):
        raise TypeError("Expected at_state with tl and rl objects")

    projected_tl = dict(training_load)
    projected_rl = dict(recovery_load)
    for key in ("ftp", "hie", "pp"):
        params = ir_params.get(key)
        if not isinstance(params, dict):
            raise TypeError(f"Expected ir_params.{key}")
        tau1 = float(params["tau1"])
        tau2 = float(params["tau2"])
        tl = float(training_load[key]) * math.exp(-days / tau1)
        classic_rl = float(recovery_load[key]) * math.exp(-days / tau2)
        rl_cap = tl * math.exp(-1.0 / tau2)
        projected_tl[key] = tl
        projected_rl[key] = max(classic_rl, rl_cap)
        projected_rl[f"{key}-cap"] = rl_cap

    projected = dict(at_state)
    projected["start_date"] = start_date
    projected["tl"] = projected_tl
    projected["rl"] = projected_rl
    return projected


def normalized_target_at(target_at: str) -> str:
    """Return an aware ISO target, using machine-local time for naive input."""

    try:
        target = datetime.fromisoformat(str(target_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--target-at must be an ISO date-time") from exc
    if target.tzinfo is None:
        # astimezone() on a naive datetime applies the machine's local timezone
        # rules for that date, including daylight-saving transitions.
        target = target.astimezone()
    return target.isoformat()


def compact_load_model_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the decision fields from a full load-model projection."""

    state_sync = payload.get("state_sync") or {}
    state_as_of = state_sync.get("state_as_of")
    horizon_days = float(payload.get("horizon_days") or 0.0)
    workout_after_days = float(payload.get("workout_after_days") or 0.0)

    def clean(value: Any) -> float:
        return round(float(value), 6)

    def shifted_time(days: float) -> str | None:
        if not state_as_of:
            return None
        parsed = datetime.fromisoformat(str(state_as_of).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed + timedelta(days=days)).isoformat()

    signature_names = {"low": "tp", "high": "hie", "peak": "pp"}
    system_rows: dict[str, Any] = {}
    for system, values in (payload.get("systems") or {}).items():
        training_load = values["training_load"]
        signature = values["signature"]
        current_tl = float(training_load["current"])
        tau_days = float(training_load["tau_days"])
        current_signature = float(signature["current"])
        responsiveness = float(signature["responsiveness_per_training_load"])
        no_training_tl = current_tl * math.exp(-horizon_days / tau_days)
        no_training_signature = current_signature + responsiveness * (
            no_training_tl - current_tl
        )
        system_rows[signature_names[system]] = {
            "system": system,
            "unit": signature["unit"],
            "current": clean(current_signature),
            "no_training_at_target": clean(no_training_signature),
            "projected_with_planned_xss": clean(signature["projected"]),
            "planned_xss": clean(values["xss"]),
        }

    required_rows: dict[str, Any] = {}
    for signature_key, required in (payload.get("required_to_build") or {}).items():
        display_key = {"ftp": "tp", "hie": "hie", "pp": "pp"}[signature_key]
        current = system_rows[display_key]["current"]
        required_rows[display_key] = {
            "interpretation": "gain_from_current_signature",
            "desired_gain": clean(required["desired_gain"]),
            "target": clean(current + float(required["desired_gain"])),
            "system": required["system"],
            "required_xss_at_workout_time": clean(
                required["single_impulse_xss_at_workout_time"]
            ),
        }

    summary = {
        "model": payload.get("model"),
        "state_as_of": state_as_of,
        "workout_at": shifted_time(workout_after_days),
        "target_at": payload.get("target_at") or shifted_time(horizon_days),
        "horizon_hours": clean(horizon_days * 24.0),
        "workout_after_hours": clean(workout_after_days * 24.0),
        "signature": system_rows,
        "required_to_build": required_rows,
        "training_status": payload.get("training_status"),
        "freshness": payload.get("freshness"),
    }
    if "distributed_to_build" in payload:
        summary["distributed_to_build"] = {
            key: clean(value) if isinstance(value, float) else value
            for key, value in payload["distributed_to_build"].items()
        }
        summary.pop("training_status", None)
        summary.pop("freshness", None)
    if "validation" in payload:
        summary["validation"] = {
            "valid": payload["validation"].get("valid"),
            "transition_count": payload["validation"].get("transition_count"),
        }
    return summary


def _json_object(raw: str, option: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{option} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{option} must contain a JSON object")
    return value


def load_workout_rows_file(path: Path) -> list[dict[str, Any]]:
    """Load a complete Workout Designer row array for atomic replacement."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"--rows-json file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--rows-json must contain valid JSON: {exc}") from exc
    if not isinstance(value, list) or not value:
        raise SystemExit("--rows-json must contain a non-empty JSON array")
    if not all(isinstance(row, dict) for row in value):
        raise SystemExit("--rows-json entries must all be JSON objects")
    return value


def workout_replacement_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Load complete replacement rows from a file or repeated inline rows."""

    if args.rows_json is not None:
        return load_workout_rows_file(args.rows_json)
    row_json_values = list(args.row_json or [])
    if not row_json_values:
        raise SystemExit("workout-replace requires --rows-json or --row-json")
    return [
        workout_replacement_row_from_json(value, sequence=index)
        for index, value in enumerate(row_json_values)
    ]


def workout_replacement_row_from_json(value: str, *, sequence: int) -> dict[str, Any]:
    """Parse a compact or complete Designer row for atomic replacement."""

    try:
        row = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --row-json value: {exc.msg}") from exc
    if not isinstance(row, dict):
        raise ValueError("--row-json must decode to a JSON object")
    if isinstance(row.get("duration"), dict) or isinstance(row.get("power"), dict):
        required = ("duration", "power")
        missing = [key for key in required if not isinstance(row.get(key), dict)]
        if missing:
            raise ValueError(
                "complete --row-json is missing structured keys: " + ", ".join(missing)
            )
        complete = dict(row)
        complete["sequence"] = sequence
        return complete
    return workout_row_from_json(value, sequence=sequence)


def build_readiness_input(
    *,
    username: str,
    password: str,
    activity_paths: list[str],
    advice_source: str = "current",
    advice_date: str | None = None,
    advice_at: str | None = None,
    advice_now: str | None = None,
) -> dict[str, Any]:
    model = fetch_recovery_model_with_login(username=username, password=password)
    source_time = datetime.now(LOCAL_TIMEZONE)
    current_advice = compact_current_training_advice(model)
    decision = training_advice_source_decision(
        requested_source=advice_source,
        current_advice=current_advice,
        advice_at=advice_at,
        advice_date=advice_date,
        advice_now=advice_now,
    )
    resolved_source = decision["resolved_source"]
    planned_advice = None
    if resolved_source == "recommended-training":
        advice_value = recommended_training_advice_value(
            advice_at=advice_at,
            advice_date=advice_date,
        )
        recommended_training = fetch_recommended_training_with_login(
            username=username,
            password=password,
            date_value=advice_value,
            recent=True,
            additional=False,
            sport=None,
        )
        planned_advice = compact_recommended_training_advice(
            recommended_training,
            advice_value=advice_value,
        )
        training_advice = planned_advice
    elif resolved_source == "current":
        training_advice = current_advice
    else:
        raise ValueError(f"Unknown resolved Xert advice source: {resolved_source}")
    recovery = compact_recovery_model(model)
    if advice_at:
        recovery["recovery_hours_at_advice_time"] = project_recovery_hours(
            recovery.get("recovery_hours"),
            source_time=source_time,
            advice_at=parse_optional_local_datetime(advice_at),
        )
    return {
        "source": "xert_plugin",
        "source_time_local": source_time.isoformat(timespec="seconds"),
        "training_advice": training_advice,
        "training_advice_debug": training_advice_debug(
            decision=decision,
            current_advice=current_advice,
            planned_advice=planned_advice,
        ),
        "recovery": recovery,
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


def training_advice_source_decision(
    *,
    requested_source: str,
    current_advice: dict[str, Any],
    advice_at: str | None,
    advice_date: str | None,
    advice_now: str | None,
) -> dict[str, Any]:
    now = parse_optional_local_datetime(advice_now) or datetime.now(LOCAL_TIMEZONE)
    planned_at = parse_optional_local_datetime(advice_at)
    current_fresh = xert_training_status_is_fresh(current_advice.get("training_status"))
    planned_is_other_day = False
    planned_later_than_now = False
    if planned_at is not None:
        planned_is_other_day = planned_at.astimezone(LOCAL_TIMEZONE).date() != now.date()
        planned_later_than_now = planned_at > now + timedelta(minutes=5)
    elif advice_date:
        advice_date_value = parse_optional_local_datetime(advice_date)
        if advice_date_value is not None:
            planned_is_other_day = advice_date_value.date() != now.date()
        else:
            planned_is_other_day = date.fromisoformat(advice_date).isoformat() != now.date().isoformat()

    if requested_source == "auto":
        if planned_is_other_day:
            resolved = "recommended-training"
            reason = "planned_time_is_other_day"
        elif planned_later_than_now and not current_fresh:
            resolved = "recommended-training"
            reason = "planned_time_later_and_current_xert_not_fresh"
        else:
            resolved = "current"
            reason = "current_advice_sufficient"
    else:
        resolved = requested_source
        reason = f"explicit_{requested_source}"

    return {
        "requested_source": requested_source,
        "resolved_source": resolved,
        "reason": reason,
        "advice_at": advice_at,
        "advice_date": advice_date,
        "advice_now": now.isoformat(timespec="seconds"),
        "planned_is_other_day": planned_is_other_day,
        "planned_later_than_now": planned_later_than_now,
        "current_xert_is_fresh": current_fresh,
    }


def parse_optional_local_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def project_recovery_hours(
    recovery_hours: Any,
    *,
    source_time: datetime,
    advice_at: datetime | None,
) -> dict[str, Any]:
    if advice_at is None:
        raise ValueError("advice_at is required for recovery projection")
    values = recovery_hours if isinstance(recovery_hours, dict) else {}
    hours_from_source = (advice_at - source_time).total_seconds() / 3600

    def projected(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value) - hours_from_source, 1)
        except (TypeError, ValueError):
            return None

    return {
        "meaning": (
            "Deterministic projection from source_time_local to advice_time_local; "
            "assumes no intervening training."
        ),
        "advice_time_local": advice_at.isoformat(timespec="seconds"),
        "hours_from_source_time": round(hours_from_source, 1),
        "low": projected(values.get("low")),
        "high": projected(values.get("high")),
        "peak": projected(values.get("peak")),
    }


def xert_training_status_is_fresh(training_status: Any) -> bool:
    if not isinstance(training_status, dict):
        return False
    form_cat = str(training_status.get("form_cat") or "").strip().lower()
    if form_cat:
        return form_cat in {"fresh", "very fresh"}
    cat = str(training_status.get("cat") or "").strip().lower()
    if cat:
        return cat in {"fresh", "very fresh", "elite"}
    return False


def training_advice_debug(
    *,
    decision: dict[str, Any],
    current_advice: dict[str, Any],
    planned_advice: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "meaning": (
            "Debug context for choosing Xert training advice source. If planned "
            "and current targets diverge unexpectedly, inspect the source decision "
            "before changing recommendation logic."
        ),
        "decision": decision,
        "current": {
            "source_endpoint": current_advice.get("source_endpoint"),
            "target_xss": current_advice.get("target_xss"),
            "training_status": compact_debug_training_status(
                current_advice.get("training_status")
            ),
        },
        "planned": (
            {
                "source_endpoint": planned_advice.get("source_endpoint"),
                "date": planned_advice.get("date"),
                "target_xss": planned_advice.get("target_xss"),
                "remaining_xss": planned_advice.get("remaining_xss"),
                "completed_xss": planned_advice.get("completed_xss"),
                "training_status": compact_debug_training_status(
                    planned_advice.get("training_status")
                ),
            }
            if planned_advice
            else None
        ),
    }


def compact_debug_training_status(training_status: Any) -> dict[str, Any] | None:
    if not isinstance(training_status, dict):
        return None
    return {
        "cat": training_status.get("cat"),
        "form_cat": training_status.get("form_cat"),
        "form_ratio": training_status.get("form_ratio"),
        "tl_total": training_status.get("tl_total"),
        "rl_total": training_status.get("rl_total"),
    }


def recommended_training_advice_value(
    *,
    advice_at: str | None,
    advice_date: str | None,
) -> str:
    if advice_at:
        planned_at = datetime.fromisoformat(advice_at.replace("Z", "+00:00"))
        if planned_at.tzinfo is None:
            planned_at = planned_at.replace(tzinfo=LOCAL_TIMEZONE)
        return (planned_at - timedelta(seconds=1)).astimezone(timezone.utc).isoformat(
            timespec="seconds"
        )
    return advice_date or date.today().isoformat()


def compact_current_training_advice(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": model.get("source"),
        "source_endpoint": "/my-fitness",
        "source_scope": "current",
        "training_status": model.get("training_status"),
        "target_xss": _system_triplet(model.get("targetXSS"), "xlss", "xhss", "xpss"),
        "meaning": (
            "Current Xert trainingAdvice from /my-fitness. This is the fastest "
            "source for advice now."
        ),
    }


def compact_recommended_training_advice(
    payload: dict[str, Any],
    *,
    advice_value: str,
) -> dict[str, Any]:
    advice = payload.get("training_advice") if isinstance(payload, dict) else {}
    if not isinstance(advice, dict):
        advice = {}
    return {
        "source": "xert_recommended_training",
        "source_endpoint": "/recommended-training",
        "source_scope": "planned_time",
        "date": advice_value,
        "training_status": advice.get("training_status"),
        "target_xss": _system_triplet(advice.get("targetXSS"), "xlss", "xhss", "xpss"),
        "remaining_xss": _system_triplet(advice.get("remainingXSS"), "xlss", "xhss", "xpss"),
        "completed_xss": _system_triplet(advice.get("completedXSS"), "xlss", "xhss", "xpss"),
        "original_target_xss": _system_triplet(
            advice.get("originalTargetXSS"),
            "xlss",
            "xhss",
            "xpss",
        ),
        "training_advice_as_of": advice.get("training_advice_as_of"),
        "training_advice_as_of_val": advice.get("training_advice_as_of_val"),
        "daily_goal_complete": advice.get("daily_goal_complete"),
        "recovery_needed": advice.get("recovery_needed"),
        "availability": advice.get("availability"),
        "is_availability_restricted": advice.get("is_availability_restricted"),
        "xss_deficit": advice.get("xss_deficit"),
        "xss_goal": advice.get("xss_goal"),
        "hours_deficit": advice.get("hours_deficit"),
        "activity_deficit": advice.get("activity_deficit"),
        "targets_source": advice.get("targets_source"),
        "based_on_day": advice.get("based_on_day"),
        "improvement_rate": advice.get("ir"),
        "weekly_hours": advice.get("weekly_hours"),
        "training_gradient": advice.get("training_gradient"),
        "phase": advice.get("phase"),
        "recommended_athlete": advice.get("recommended_athlete"),
        "meaning": (
            "Planned-time Xert training advice from /recommended-training. Prefer "
            "this source when advice is needed for a planned time rather than now."
        ),
    }


def compact_recovery_model(model: dict[str, Any]) -> dict[str, Any]:
    at_state = model.get("at_state") if isinstance(model.get("at_state"), dict) else {}
    training_load = at_state.get("tl") if isinstance(at_state, dict) else {}
    recovery_load = at_state.get("rl") if isinstance(at_state, dict) else {}
    return {
        "source": model.get("source"),
        "time_scope": "source_time_local",
        "meaning": (
            "recovery_hours is evaluated at the top-level source_time_local. "
            "When --advice-at is supplied, recovery_hours_at_advice_time provides "
            "the projected value for that time, assuming no intervening training; "
            "recovery_hours remains the raw source-time value for auditability."
        ),
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
    list_row = payload.get("activity_list_row") if isinstance(payload.get("activity_list_row"), dict) else {}
    return {
        "source": "xert_plugin",
        "path": payload.get("path") or summary.get("path"),
        "name": payload.get("name") or summary.get("name") or list_row.get("name"),
        "map_url": payload.get("map_url") or summary.get("map_url") or list_row.get("map_url"),
        "start_local": _activity_start_local(summary),
        "distance_km": summary.get("distance") or list_row.get("distance"),
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
    keywords = contains.casefold().split()
    return [
        row
        for row in workouts
        if all(keyword in str(row.get("name") or "").casefold() for keyword in keywords)
    ]


def workout_probe_row(
    *,
    name: str,
    duration: str,
    power: float,
    power_type: str,
    interval_count: str,
    rib_duration: str,
    rib_power: float,
    rib_power_type: str,
) -> dict[str, Any]:
    return {
        "DT_RowId": "",
        "sequence": 0,
        "name": name,
        "duration": {"type": "absolute", "value": duration},
        "power": {"type": power_type, "value": power},
        "interval_count": interval_count,
        "rib_duration": {"type": "absolute", "value": rib_duration},
        "rib_power": {"type": rib_power_type, "value": rib_power},
    }


def workout_calculate_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Build one or more Workout Designer rows from CLI arguments."""

    row_json_values = list(getattr(args, "row_json", []) or [])
    compact_values = any(
        getattr(args, name, None)
        for name in ("warmup_step", "interval_block", "cooldown_step")
    )
    if row_json_values:
        if args.duration is not None or args.power is not None or compact_values:
            raise ValueError(
                "Use only one workout input form: --row-json, compact workout "
                "steps, or --duration/--power"
            )
        return [
            workout_row_from_json(value, sequence=index)
            for index, value in enumerate(row_json_values)
        ]
    if compact_values:
        if args.duration is not None or args.power is not None:
            raise ValueError(
                "Use only one workout input form: compact workout steps or "
                "--duration/--power"
            )
        return compact_workout_rows(
            warmup_steps=list(getattr(args, "warmup_step", []) or []),
            interval_blocks=list(getattr(args, "interval_block", []) or []),
            cooldown_steps=list(getattr(args, "cooldown_step", []) or []),
        )

    if args.duration is None or args.power is None:
        raise ValueError(
            "workout-calculate requires --row-json, compact workout steps, or "
            "both --duration and --power"
        )
    return [
        workout_probe_row(
            name=args.row_name,
            duration=args.duration,
            power=args.power,
            power_type=args.power_type,
            interval_count=args.interval_count,
            rib_duration=args.rib_duration,
            rib_power=args.rib_power,
            rib_power_type=args.rib_power_type,
        )
    ]


def compact_workout_rows(
    *,
    warmup_steps: list[str],
    interval_blocks: list[str],
    cooldown_steps: list[str],
) -> list[dict[str, Any]]:
    """Build complete absolute-power workout rows from compact CLI notation."""

    rows: list[dict[str, Any]] = []
    for index, value in enumerate(warmup_steps, start=1):
        duration, power = parse_power_step(value, option="--warmup-step")
        rows.append(
            workout_probe_row(
                name=f"Warm-up {index}",
                duration=duration,
                power=power,
                power_type="absolute",
                interval_count="1",
                rib_duration="00:00",
                rib_power=0.0,
                rib_power_type="absolute",
            )
        )
    for index, value in enumerate(interval_blocks, start=1):
        block = parse_interval_block(value)
        rows.append(
            workout_probe_row(
                name=f"Interval block {index}",
                duration=block["work_duration"],
                power=block["work_power"],
                power_type="absolute",
                interval_count=str(block["count"]),
                rib_duration=block["recovery_duration"],
                rib_power=block["recovery_power"],
                rib_power_type="absolute",
            )
        )
    for index, value in enumerate(cooldown_steps, start=1):
        duration, power = parse_power_step(value, option="--cooldown-step")
        rows.append(
            workout_probe_row(
                name=f"Cool-down {index}",
                duration=duration,
                power=power,
                power_type="absolute",
                interval_count="1",
                rib_duration="00:00",
                rib_power=0.0,
                rib_power_type="absolute",
            )
        )
    if not rows:
        raise ValueError("At least one compact workout step is required")
    for sequence, row in enumerate(rows):
        row["sequence"] = sequence
    return rows


def parse_power_step(value: str, *, option: str) -> tuple[str, float]:
    match = re.fullmatch(
        r"\s*(\d{1,3}:\d{2})\s*@\s*(\d+(?:\.\d+)?)\s*",
        value,
    )
    if not match:
        raise ValueError(f"{option} must use MM:SS@WATTS, got {value!r}")
    return match.group(1), float(match.group(2))


def parse_interval_block(value: str) -> dict[str, Any]:
    match = re.fullmatch(
        (
            r"\s*(\d+)\s*x\s*(\d{1,3}:\d{2})\s*@\s*(\d+(?:\.\d+)?)"
            r"\s*/\s*(\d{1,3}:\d{2})\s*@\s*(\d+(?:\.\d+)?)\s*"
        ),
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "--interval-block must use COUNTxMM:SS@WATTS/MM:SS@WATTS, "
            f"got {value!r}"
        )
    count = int(match.group(1))
    if count < 1:
        raise ValueError("--interval-block count must be positive")
    return {
        "count": count,
        "work_duration": match.group(2),
        "work_power": float(match.group(3)),
        "recovery_duration": match.group(4),
        "recovery_power": float(match.group(5)),
    }


def compact_workout_calculation_summary(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return only the calculated metrics needed by recommendation callers."""

    result = payload.get("result") or {}
    stats = result.get("stats") if isinstance(result, dict) else None
    if not isinstance(stats, dict):
        raise ValueError("Xert workout calculation has no result.stats object")
    duration_seconds = _number(stats.get("duration"))
    summary = {
        "source": "xert_workout_calculate",
        "saved": bool(payload.get("saved")),
        "duration_seconds": duration_seconds,
        "duration_minutes": _minutes(duration_seconds),
        "xss": _number(stats.get("xss")),
        "low_xss": _number(stats.get("xlss")),
        "high_xss": _number(stats.get("xhss")),
        "peak_xss": _number(stats.get("xpss")),
        "difficulty": _number(stats.get("difficulty")),
        "rating": stats.get("rating"),
        "focus": stats.get("focus"),
        "specificity": _number(stats.get("specificity")),
        "specificity_rating": stats.get("specRating"),
        "xep": _number(stats.get("xep")),
        "average_power": _number(stats.get("avg_power")),
        "max_power": _number(stats.get("max_power")),
    }
    if isinstance(payload.get("timeline_summary"), dict):
        summary["timeline_summary"] = payload["timeline_summary"]
    return summary


def workout_row_from_json(value: str, *, sequence: int) -> dict[str, Any]:
    """Parse a compact JSON row into Xert Workout Designer row structure."""

    try:
        row = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --row-json value: {exc.msg}") from exc
    if not isinstance(row, dict):
        raise ValueError("--row-json must decode to a JSON object")

    required = ("duration", "power")
    missing = [key for key in required if row.get(key) is None]
    if missing:
        raise ValueError(f"--row-json is missing required keys: {', '.join(missing)}")

    power_value = row["power"]
    power_type = str(row.get("power_type") or "absolute")
    power_second_value = row.get("power_second_value")
    if isinstance(power_value, dict):
        power_type = str(power_value.get("type") or power_type)
        power_second_value = power_value.get("second_value", power_second_value)
        power_value = power_value.get("value")

    parsed = workout_probe_row(
        name=str(row.get("name") or f"Row {sequence + 1}"),
        duration=str(row["duration"]),
        power=_required_float(power_value, "power"),
        power_type=power_type,
        interval_count=str(row.get("interval_count") or "1"),
        rib_duration=str(row.get("rib_duration") or "00:00"),
        rib_power=_required_float(row.get("rib_power", 0.0), "rib_power"),
        rib_power_type=str(row.get("rib_power_type") or "absolute"),
    )
    parsed["sequence"] = sequence
    if power_second_value is not None:
        parsed["power"]["second_value"] = _required_float(
            power_second_value,
            "power_second_value",
        )

    valid_work_power_types = {
        "relative_ftp",
        "absolute",
        "ramp_ftp",
        "ramp_ltp",
        "ramp_absolute",
    }
    for key in ("power", "rib_power"):
        candidate_type = parsed[key]["type"]
        valid_types = (
            valid_work_power_types
            if key == "power"
            else {"relative_ftp", "absolute"}
        )
        if candidate_type not in valid_types:
            raise ValueError(
                f"--row-json {key}_type is unsupported, got {candidate_type!r}"
            )
    if (
        parsed["power"]["type"].startswith("ramp_")
        and "second_value" not in parsed["power"]
    ):
        raise ValueError("--row-json ramp power requires power_second_value")
    return parsed


def _required_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"--row-json {name} must be numeric") from exc


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"Set {name} in .env")
    return value


if __name__ == "__main__":
    main()
