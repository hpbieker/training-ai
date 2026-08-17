#!/usr/bin/env python3
"""Manage Garmin Connect courses and inspect gccli authentication."""

from __future__ import annotations

import argparse
import json

from garmin_connect_api import (
    delete_course,
    fetch_course,
    fetch_courses,
    resolve_gccli,
    show_auth_status,
    upload_course,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Garmin Connect courses and inspect gccli authentication.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
