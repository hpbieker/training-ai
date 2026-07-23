#!/usr/bin/env python3
"""Command-line tool for Intervals.icu API access."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from intervals_icu_api import (
    create_event,
    delete_activity,
    download_activity_file,
    download_activity_streams_csv,
    get_activity,
    get_wellness,
    list_activities,
    list_events,
    list_wellness,
    load_intervals_icu_api_key,
    save_activity_streams,
    save_latest_activity_streams,
    search_activities,
    update_activity,
    update_event,
    update_wellness,
    upload_activity_file,
)


METADATA_UNAVAILABLE_SAMPLE_LIMIT = 20


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and update Intervals.icu data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    latest = subparsers.add_parser("latest", help="Fetch the latest activity summary")
    latest.add_argument("--lookback-days", type=int, default=365)
    _add_output_arg(latest)

    recent = subparsers.add_parser("recent", help="Fetch recent activity summaries")
    recent.add_argument("--count", type=int, default=2)
    recent.add_argument("--lookback-days", type=int, default=365)
    _add_output_arg(recent)

    activities = subparsers.add_parser(
        "activities",
        help="Fetch activity summaries for a date range",
    )
    activities.add_argument("--since", required=True, help="Start date formatted YYYY-MM-DD")
    activities.add_argument("--until", required=True, help="End date formatted YYYY-MM-DD")
    _add_output_arg(activities)

    activity = subparsers.add_parser("activity", help="Fetch one activity")
    activity.add_argument("activity_id")
    activity.add_argument(
        "--summary-only",
        "--no-intervals",
        dest="omit_intervals",
        action="store_true",
        default=False,
        help="Omit Intervals.icu interval summaries from the activity payload",
    )
    _add_output_arg(activity)

    save_activity = subparsers.add_parser(
        "save-activity",
        help="Save activity metadata and streams for local analysis",
    )
    save_activity.add_argument("activity_id")
    save_activity.add_argument(
        "--type",
        dest="stream_types",
        action="append",
        help="Stream type to include. Can be repeated.",
    )
    save_activity.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/intervals"),
        help="Directory for saved Intervals.icu artifacts",
    )
    _add_output_arg(save_activity)

    save_latest = subparsers.add_parser(
        "save-latest",
        help="Save the latest activity metadata and streams for local analysis",
    )
    save_latest.add_argument("--lookback-days", type=int, default=365)
    save_latest.add_argument(
        "--type",
        dest="stream_types",
        action="append",
        help="Stream type to include. Can be repeated.",
    )
    save_latest.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/intervals"),
        help="Directory for saved Intervals.icu artifacts",
    )
    _add_output_arg(save_latest)

    file_parser = subparsers.add_parser(
        "file",
        help="Download the original or generated FIT file for one activity id",
    )
    file_parser.add_argument("activity_id")
    file_parser.add_argument(
        "--kind",
        choices=["original", "fit", "web-original"],
        default="original",
        help="Download the API original, web-session original, or Intervals.icu generated FIT",
    )
    file_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Explicit file path or directory for the downloaded artifact",
    )

    streams = subparsers.add_parser(
        "streams",
        help="Download activity streams CSV for one activity id",
    )
    streams.add_argument("activity_id")
    streams.add_argument(
        "--type",
        dest="stream_types",
        action="append",
        help="Stream type to include. Can be repeated.",
    )
    streams.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Explicit CSV file path or directory for the downloaded streams",
    )

    search = subparsers.add_parser(
        "search",
        help="Search activities by query text",
    )
    search.add_argument("query")
    search.add_argument("--limit", type=_positive_int, default=10)
    search.add_argument(
        "--since",
        type=_iso_date,
        help="Optional inclusive start date formatted YYYY-MM-DD",
    )
    search.add_argument(
        "--until",
        type=_iso_date,
        help="Optional inclusive end date formatted YYYY-MM-DD",
    )
    _add_output_arg(search)

    named = subparsers.add_parser(
        "named",
        help="Fetch activities whose names contain a case-insensitive text fragment",
    )
    named.add_argument("text", help="Name fragment, for example VT1 or VT2")
    named.add_argument("--since", default=f"{date.today().year}-01-01")
    named.add_argument("--until", default=date.today().isoformat())
    _add_output_arg(named)

    outdoor = subparsers.add_parser("outdoor", help="Fetch outdoor ride summaries")
    outdoor.add_argument("--since", default=f"{date.today().year}-01-01")
    outdoor.add_argument("--until", default=date.today().isoformat())
    _add_output_arg(outdoor)

    indoor = subparsers.add_parser("indoor", help="Fetch indoor/trainer ride summaries")
    indoor.add_argument("--since", default=f"{date.today().year}-01-01")
    indoor.add_argument("--until", default=date.today().isoformat())
    _add_output_arg(indoor)

    tireless = subparsers.add_parser("tireless", help="Fetch long Tireless indoor rides")
    tireless.add_argument("--since", default="2022-01-01")
    tireless.add_argument("--until", default=date.today().isoformat())
    tireless.add_argument("--min-minutes", type=float, default=180.0)
    _add_output_arg(tireless)

    hard_indoor = subparsers.add_parser(
        "hard-indoor",
        help="Fetch hard indoor workout summaries by name pattern",
    )
    hard_indoor.add_argument("--since", default=f"{date.today().year}-01-01")
    hard_indoor.add_argument("--until", default=date.today().isoformat())
    hard_indoor.add_argument(
        "--pattern",
        action="append",
        default=None,
        help="Case-insensitive name fragment. Can be repeated.",
    )
    _add_output_arg(hard_indoor)

    wellness = subparsers.add_parser("wellness", help="Fetch wellness data")
    wellness.add_argument("--since", default=f"{date.today().year}-01-01")
    wellness.add_argument("--until", default=date.today().isoformat())
    _add_output_arg(wellness)

    events = subparsers.add_parser("events", help="Fetch calendar events")
    events.add_argument("--since", required=True)
    events.add_argument("--until", required=True)
    events.add_argument("--category", help="Comma-separated categories, e.g. SICK")
    _add_output_arg(events)

    sick_set = subparsers.add_parser(
        "sick-set", help="Create or extend one SICK calendar event"
    )
    sick_set.add_argument("--since", required=True, help="First sick day")
    sick_set.add_argument("--until", required=True, help="Last sick day, inclusive")
    sick_set.add_argument("--confirm", required=True, help="Must equal START:END")

    rename = subparsers.add_parser("rename", help="Rename one activity")
    rename.add_argument("activity_id")
    rename.add_argument("name")

    delete = subparsers.add_parser("delete-activity", help="Delete one activity")
    delete.add_argument("activity_id")
    delete.add_argument(
        "--confirm",
        required=True,
        help="Required safety confirmation. Must exactly match the activity id.",
    )
    delete.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip fetching the deleted activity afterward to verify it is gone.",
    )

    upload = subparsers.add_parser("upload-activity", help="Upload one activity file")
    upload.add_argument("file_path", type=Path)
    upload.add_argument(
        "--athlete-id",
        default=0,
        help='Intervals.icu athlete id. Defaults to 0 for "current athlete".',
    )
    _add_output_arg(upload)

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

    wellness_update = subparsers.add_parser(
        "wellness-update",
        help="Update one daily wellness record",
    )
    wellness_update.add_argument("date", help="Local date formatted YYYY-MM-DD")
    wellness_update.add_argument(
        "--soreness",
        type=int,
        help="Daily soreness value to store in Intervals.icu's soreness field",
    )
    wellness_update.add_argument(
        "--fatigue",
        type=int,
        help="Daily fatigue value to store in Intervals.icu's fatigue field",
    )
    wellness_update.add_argument(
        "--motivation",
        type=int,
        help="Daily motivation value to store in Intervals.icu's motivation field",
    )
    wellness_update.add_argument(
        "--comments",
        help="Daily wellness comments. Only use for explicit user-provided notes.",
    )
    wellness_update.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting an existing wellness value with a different value.",
    )

    args = parser.parse_args()
    api_key = load_intervals_icu_api_key()

    if args.command == "latest":
        activities = list_activities(
            api_key=api_key,
            oldest=date.fromordinal(date.today().toordinal() - args.lookback_days),
            newest=date.today(),
        )
        if not activities:
            raise SystemExit(f"No Intervals.icu activities found in last {args.lookback_days} days")
        latest_activity = max(
            activities,
            key=lambda activity: str(activity.get("start_date_local") or ""),
        )
        _emit_json({"activity": latest_activity}, output=args.output)
        return

    if args.command == "recent":
        activities = list_activities(
            api_key=api_key,
            oldest=date.fromordinal(date.today().toordinal() - args.lookback_days),
            newest=date.today(),
        )
        recent_activities = sorted(
            activities,
            key=lambda activity: activity.get("start_date_local") or "",
            reverse=True,
        )[: args.count]
        _emit_json(
            {"activities": recent_activities, "matched_count": len(recent_activities)},
            output=args.output,
        )
        return

    if args.command == "activities":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        _print_activity_matches(activities, source_activities=activities, output=args.output)
        return

    if args.command == "activity":
        activity_payload = get_activity(
            activity_id=args.activity_id,
            api_key=api_key,
            include_intervals=not args.omit_intervals,
        )
        _emit_json({"activity": activity_payload}, output=args.output)
        return

    if args.command == "save-activity":
        artifacts = save_activity_streams(
            activity_id=args.activity_id,
            api_key=api_key,
            output_dir=args.output_dir,
            stream_types=args.stream_types,
        )
        _emit_json({key: str(value) for key, value in artifacts.items()}, output=args.output)
        return

    if args.command == "save-latest":
        artifacts = save_latest_activity_streams(
            api_key=api_key,
            output_dir=args.output_dir,
            lookback_days=args.lookback_days,
            stream_types=args.stream_types,
        )
        _emit_json({key: str(value) for key, value in artifacts.items()}, output=args.output)
        return

    if args.command == "file":
        activity_file = download_activity_file(
            activity_id=args.activity_id,
            api_key=api_key,
            kind=args.kind,
            output_path=args.output,
        )
        _emit_json({"activity_file": activity_file})
        return

    if args.command == "streams":
        streams_csv = download_activity_streams_csv(
            activity_id=args.activity_id,
            api_key=api_key,
            stream_types=args.stream_types,
            output_path=args.output,
        )
        _emit_json({"streams_csv": streams_csv})
        return

    if args.command == "search":
        activities = search_activities(
            query=args.query,
            limit=args.limit,
            api_key=api_key,
        )
        if args.since or args.until:
            if not args.since or not args.until:
                parser.error("search requires both --since and --until when date bounds are used")
            if args.until < args.since:
                parser.error("search --until must not be before --since")
            activities = _filter_activity_dates(
                activities,
                since=args.since,
                until=args.until,
            )
        _print_activity_matches(activities, output=args.output)
        return

    if args.command == "named":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        matches = [
            activity
            for activity in activities
            if args.text.lower() in str(activity.get("name") or "").lower()
        ]
        _print_activity_matches(matches, source_activities=activities, output=args.output)
        return

    if args.command == "outdoor":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        matches = [
            activity
            for activity in activities
            if str(activity.get("type") or "").lower() == "ride"
        ]
        _print_activity_matches(matches, source_activities=activities, output=args.output)
        return

    if args.command == "indoor":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        matches = [
            activity
            for activity in activities
            if _is_indoor_ride(activity)
        ]
        _print_activity_matches(matches, source_activities=activities, output=args.output)
        return

    if args.command == "tireless":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        min_seconds = args.min_minutes * 60
        matches = [
            activity
            for activity in activities
            if _is_indoor_ride(activity)
            and "tireless" in str(activity.get("name") or "").lower()
            and (
                float(activity.get("elapsed_time") or activity.get("moving_time") or 0)
                >= min_seconds
            )
        ]
        _print_activity_matches(matches, source_activities=activities, output=args.output)
        return

    if args.command == "hard-indoor":
        activities = list_activities(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        patterns = args.pattern or [
            "60/60",
            "60-60",
            "30/30",
            "30-30",
            "vo2",
            "vo2max",
            "vt2",
        ]
        matches = [
            activity
            for activity in activities
            if str(activity.get("type") or "").lower() == "virtualride"
            and any(
                pattern.lower() in str(activity.get("name") or "").lower()
                for pattern in patterns
            )
        ]
        _print_activity_matches(matches, source_activities=activities, output=args.output)
        return

    if args.command == "wellness":
        wellness_rows = list_wellness(
            api_key=api_key,
            oldest=args.since,
            newest=args.until,
        )
        _emit_json(
            {"wellness": wellness_rows, "matched_count": len(wellness_rows)},
            output=args.output,
        )
        return

    if args.command == "events":
        rows = list_events(
            api_key=api_key, oldest=args.since, newest=args.until,
            categories=args.category,
        )
        _emit_json({"events": rows, "matched_count": len(rows)}, output=args.output)
        return

    if args.command == "sick-set":
        if args.confirm != f"{args.since}:{args.until}":
            parser.error("--confirm must exactly match START:END")
        start = date.fromisoformat(args.since)
        inclusive_end = date.fromisoformat(args.until)
        if inclusive_end < start:
            parser.error("--until must not be before --since")
        exclusive_end = date.fromordinal(inclusive_end.toordinal() + 1)
        sick_events = list_events(
            api_key=api_key,
            oldest=date.fromordinal(start.toordinal() - 1),
            newest=exclusive_end,
            categories="SICK",
        )
        mergeable = [
            event for event in sick_events
            if str(event.get("end_date_local") or "")[:10] >= start.isoformat()
            and str(event.get("start_date_local") or "")[:10] <= exclusive_end.isoformat()
        ]
        if len(mergeable) > 1:
            parser.error("multiple adjacent/overlapping SICK events require manual reconciliation")
        payload = {
            "category": "SICK", "name": "Syk",
            "start_date_local": f"{start.isoformat()}T00:00:00",
            "end_date_local": f"{exclusive_end.isoformat()}T00:00:00",
        }
        if mergeable:
            existing = mergeable[0]
            payload["start_date_local"] = min(
                payload["start_date_local"], str(existing.get("start_date_local"))
            )
            payload["end_date_local"] = max(
                payload["end_date_local"], str(existing.get("end_date_local"))
            )
            saved = update_event(event_id=existing["id"], updates=payload, api_key=api_key)
            action = "updated"
        else:
            saved = create_event(event=payload, api_key=api_key)
            action = "created"
        verified = list_events(
            api_key=api_key, oldest=start, newest=inclusive_end, categories="SICK"
        )
        _emit_json({"action": action, "event": saved, "verified_events": verified})
        return

    if args.command == "rename":
        updated = update_activity(
            activity_id=args.activity_id,
            updates={"name": args.name},
            api_key=api_key,
        )
        print(f"updated {updated.get('id')}: {updated.get('name')}")
        return

    if args.command == "delete-activity":
        if args.confirm != args.activity_id:
            parser.error("--confirm must exactly match the activity id")

        existing = get_activity(
            activity_id=args.activity_id,
            api_key=api_key,
            include_intervals=False,
        )
        deleted = delete_activity(
            activity_id=args.activity_id,
            api_key=api_key,
        )
        result = {
            "deleted": True,
            "activity_id": args.activity_id,
            "deleted_response": deleted,
            "activity": {
                "id": existing.get("id"),
                "name": existing.get("name"),
                "source": existing.get("source"),
                "external_id": existing.get("external_id"),
                "strava_id": existing.get("strava_id"),
                "start_date_local": existing.get("start_date_local"),
                "created": existing.get("created"),
            },
        }
        if not args.no_verify:
            try:
                get_activity(
                    activity_id=args.activity_id,
                    api_key=api_key,
                    include_intervals=False,
                )
                result["verified_deleted"] = False
                raise SystemExit(f"delete did not verify: {args.activity_id} still exists")
            except RuntimeError as exc:
                message = str(exc)
                result["verify_error"] = message
                result["verified_deleted"] = "HTTP 404" in message or "Not Found" in message
                if not result["verified_deleted"]:
                    raise
        _emit_json(result)
        return

    if args.command == "upload-activity":
        uploaded = upload_activity_file(
            file_path=args.file_path,
            api_key=api_key,
            athlete_id=args.athlete_id,
        )
        _emit_json(uploaded, output=args.output)
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

    if args.command == "wellness-update":
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
            parser.error("wellness-update requires at least one wellness field")

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


def _print_activity_matches(
    matches: list[dict[str, object]],
    *,
    source_activities: list[dict[str, object]] | None = None,
    output: Path | None,
) -> None:
    payload: dict[str, object] = {
        "activities": sorted(matches, key=lambda item: str(item.get("start_date_local") or "")),
        "matched_count": len(matches),
    }
    if source_activities is not None:
        unavailable = [
            _metadata_unavailable_summary(activity)
            for activity in source_activities
            if _activity_metadata_unavailable(activity)
        ]
        if unavailable:
            sorted_unavailable = sorted(
                unavailable,
                key=lambda item: str(item.get("start_date_local") or ""),
            )
            payload["metadata_warning"] = (
                "Some activities in the requested range do not expose searchable metadata "
                "through the Intervals.icu API. Name/type filters may miss these activities."
            )
            payload["metadata_unavailable_count"] = len(unavailable)
            payload["metadata_unavailable_activities"] = sorted_unavailable[
                :METADATA_UNAVAILABLE_SAMPLE_LIMIT
            ]
            omitted_count = len(sorted_unavailable) - METADATA_UNAVAILABLE_SAMPLE_LIMIT
            if omitted_count > 0:
                payload["metadata_unavailable_omitted_count"] = omitted_count
    _emit_json(payload, output=output)


def _activity_metadata_unavailable(activity: dict[str, object]) -> bool:
    if activity.get("_note"):
        return True
    has_searchable_metadata = any(
        _has_value(activity.get(field))
        for field in ("name", "type", "distance", "elapsed_time", "moving_time")
    )
    return str(activity.get("source") or "").upper() == "STRAVA" and not has_searchable_metadata


def _filter_activity_dates(
    activities: list[dict[str, object]],
    *,
    since: date,
    until: date,
) -> list[dict[str, object]]:
    """Keep Intervals search results inside an inclusive local-date range."""

    matches = []
    for activity in activities:
        try:
            activity_date = date.fromisoformat(
                str(activity.get("start_date_local") or "")[:10]
            )
        except ValueError:
            continue
        if since <= activity_date <= until:
            matches.append(activity)
    return matches


def _metadata_unavailable_summary(activity: dict[str, object]) -> dict[str, object]:
    summary = {
        "id": activity.get("id"),
        "source": activity.get("source"),
        "start_date_local": activity.get("start_date_local"),
    }
    if activity.get("_note"):
        summary["note"] = activity.get("_note")
    return {key: value for key, value in summary.items() if value is not None}


def _is_indoor_ride(activity: dict[str, Any]) -> bool:
    activity_type = str(activity.get("type") or "").lower()
    if activity_type not in {"ride", "virtualride"}:
        return False
    return (
        activity_type == "virtualride"
        or activity.get("trainer") is True
        or activity.get("indoor") is True
    )


def _has_value(value: object) -> bool:
    return value is not None and value != ""


def _add_output_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON payload to this explicit file instead of stdout",
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must use YYYY-MM-DD") from exc


def _emit_json(payload: object, *, output: Path | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    if output is None:
        print(body)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{body}\n", encoding="utf-8")
    print(f"wrote: {output}")


if __name__ == "__main__":
    main()
