#!/usr/bin/env python3
"""Fetch Garmin Connect health, activity, and course data via gccli."""

from __future__ import annotations

import argparse
import json
from datetime import date

from garmin_connect_api import (
    DAILY_PROFILE_SPECS,
    DAILY_SPEC_CHOICES,
    compact_day_payload,
    compact_recent_payload,
    delete_course,
    fetch_activity,
    fetch_course,
    fetch_courses,
    fetch_day,
    fetch_recent_days,
    garmin_activity_search,
    resolve_gccli,
    show_auth_status,
    upload_course,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Garmin Connect health/readiness data using gccli.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    day = subparsers.add_parser("day", help="Fetch Garmin Connect health data for one day")
    day.add_argument("date", nargs="?", default=date.today().isoformat())
    day.add_argument(
        "--only",
        action="append",
        choices=DAILY_SPEC_CHOICES,
        help="Fetch only one daily source. Can be repeated.",
    )
    day.add_argument(
        "--profile",
        choices=sorted(DAILY_PROFILE_SPECS),
        default="full",
        help="Fetch a predefined source set.",
    )
    day.add_argument(
        "--tolerate-errors",
        action="store_true",
        help="Return per-source error objects instead of aborting on the first gccli failure.",
    )
    day.add_argument(
        "--compact",
        action="store_true",
        help="Return normalized readiness/VO2max plus supporting daily source signals.",
    )

    recent = subparsers.add_parser("recent", help="Fetch Garmin Connect health data for recent days")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--until", default=date.today().isoformat())
    recent.add_argument(
        "--only",
        action="append",
        choices=DAILY_SPEC_CHOICES,
        help="Fetch only one daily source. Can be repeated.",
    )
    recent.add_argument(
        "--profile",
        choices=sorted(DAILY_PROFILE_SPECS),
        default="full",
        help="Fetch a predefined source set.",
    )
    recent.add_argument(
        "--tolerate-errors",
        action="store_true",
        help="Return per-source error objects instead of aborting on the first gccli failure.",
    )
    recent.add_argument(
        "--compact",
        action="store_true",
        help="Return normalized readiness/VO2max plus supporting signals for each day.",
    )

    activity = subparsers.add_parser(
        "activity",
        help="Fetch one Garmin Connect activity summary and details",
    )
    activity.add_argument(
        "activity",
        help="Garmin activity id, Intervals activity id, or saved Intervals activity dir",
    )
    activity.add_argument(
        "--summary-only",
        action="store_true",
        help="Return compact metrics, including Stamina analysis, without raw chart details",
    )

    activities = subparsers.add_parser(
        "activities",
        help="Search Garmin Connect activities in a date range",
    )
    activities.add_argument("--since", default=f"{date.today().year}-01-01")
    activities.add_argument("--until", default=date.today().isoformat())
    activities.add_argument("--limit", type=int, default=100)

    subparsers.add_parser(
        "courses",
        help="List saved Garmin Connect courses (routes)",
    )

    course = subparsers.add_parser(
        "course",
        help="Fetch one Garmin Connect course with route geometry",
    )
    course.add_argument("course_id", help="Garmin Connect course ID")

    course_upload = subparsers.add_parser(
        "course-upload",
        help="Upload a Garmin course directly from course JSON",
    )
    course_upload.add_argument("course_json", help="Raw course JSON or output from `course`")
    course_upload.add_argument("--name", help="Override the uploaded course name")
    course_upload.add_argument(
        "--privacy",
        type=int,
        choices=(1, 2, 4),
        default=2,
        help="Garmin privacy value (default: 2/private)",
    )

    course_delete = subparsers.add_parser(
        "course-delete",
        help="Permanently delete one Garmin course",
    )
    course_delete.add_argument("course_id", help="Garmin Connect course ID")
    course_delete.add_argument(
        "--confirm-course-id",
        required=True,
        help="Repeat the exact course ID to authorize deletion",
    )

    subparsers.add_parser("status", help="Show gccli auth status")

    args = parser.parse_args()
    gccli = resolve_gccli()

    if args.command == "status":
        show_auth_status(gccli=gccli)
        return

    if args.command == "day":
        payload = fetch_day(
            args.date,
            gccli=gccli,
            only=args.only,
            profile=args.profile,
            tolerate_errors=args.tolerate_errors,
        )
        _print_json(compact_day_payload(payload) if args.compact else payload)
        return

    if args.command == "recent":
        payload = fetch_recent_days(
            days=args.days,
            until=args.until,
            gccli=gccli,
            only=args.only,
            profile=args.profile,
            tolerate_errors=args.tolerate_errors,
        )
        _print_json(compact_recent_payload(payload) if args.compact else payload)
        return

    if args.command == "activity":
        payload = fetch_activity(
            args.activity,
            gccli=gccli,
            include_details=True,
        )
        if args.summary_only:
            payload.pop("summary", None)
            payload.pop("details", None)
        _print_json(payload)
        return

    if args.command == "activities":
        _print_json(
            {
                "source": "garmin_connect_gccli",
                "start_date": args.since,
                "end_date": args.until,
                "activities": garmin_activity_search(
                    gccli,
                    args.since,
                    args.until,
                    limit=args.limit,
                ),
            }
        )
        return

    if args.command == "courses":
        _print_json(fetch_courses(gccli=gccli))
        return

    if args.command == "course":
        _print_json(fetch_course(args.course_id, gccli=gccli))
        return

    if args.command == "course-upload":
        _print_json(
            upload_course(
                args.course_json,
                gccli=gccli,
                course_name=args.name,
                course_privacy=args.privacy,
            )
        )
        return

    if args.command == "course-delete":
        _print_json(
            delete_course(
                args.course_id,
                gccli=gccli,
                confirmed_course_id=args.confirm_course_id,
            )
        )
        return


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
