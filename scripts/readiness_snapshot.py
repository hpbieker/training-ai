#!/usr/bin/env python3
"""Build a compact readiness context from selected training inputs."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ARTIFACTS_DIR = Path("outputs/intervals")


def parse_timezone(timezone_name: str) -> ZoneInfo:
    """Resolve one explicit IANA timezone without mutating process state."""

    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise argparse.ArgumentTypeError(
            f"Unknown IANA timezone: {timezone_name}"
        ) from exc


def parse_time_context_json(raw: str) -> dict[str, Any]:
    """Validate the complete local time context supplied by the caller."""

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--time-context-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--time-context-json must contain one JSON object"
        )
    supported = {"date", "local_timezone", "now", "planned_at"}
    unknown = sorted(set(payload) - supported)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unsupported time-context field: {unknown[0]}"
        )
    missing = sorted({"date", "local_timezone", "now"} - set(payload))
    if missing:
        raise argparse.ArgumentTypeError(
            f"missing required time-context field: {missing[0]}"
        )
    try:
        context_date = date.fromisoformat(payload["date"])
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "time-context date must be YYYY-MM-DD"
        ) from exc
    if not isinstance(payload["local_timezone"], str):
        raise argparse.ArgumentTypeError(
            "time-context local_timezone must be an IANA timezone string"
        )
    local_timezone = parse_timezone(payload["local_timezone"])
    parsed: dict[str, Any] = {
        "date": context_date.isoformat(),
        "local_timezone": payload["local_timezone"],
    }
    for field in ("now", "planned_at"):
        value = payload.get(field)
        if value is None and field == "planned_at":
            parsed[field] = None
            continue
        if not isinstance(value, str):
            raise argparse.ArgumentTypeError(
                f"time-context {field} must be a full ISO timestamp"
            )
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"time-context {field} must be a full ISO timestamp"
            ) from exc
        if "T" not in value or instant.tzinfo is None or instant.utcoffset() is None:
            raise argparse.ArgumentTypeError(
                f"time-context {field} must include an explicit UTC offset"
            )
        localized = instant.astimezone(local_timezone)
        if localized.utcoffset() != instant.utcoffset():
            raise argparse.ArgumentTypeError(
                f"time-context {field} UTC offset does not match "
                f"{payload['local_timezone']} at that instant"
            )
        if localized.date() != context_date:
            raise argparse.ArgumentTypeError(
                f"time-context {field} must fall on time-context date"
            )
        parsed[field] = instant
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize Intervals and provided Garmin/Xert JSON for chat readiness.",
    )
    parser.add_argument(
        "--time-context-json",
        required=True,
        type=parse_time_context_json,
        help=(
            "JSON object with date, local_timezone, now, and optional planned_at. "
            "Times must be full ISO timestamps with explicit UTC offsets."
        ),
    )
    parser.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR))
    parser.add_argument(
        "--source-inputs-json",
        required=True,
        type=parse_source_inputs_json,
        help=(
            "One normalized JSON object mapping optional garmin and xert files "
            "plus intervals.wellness and intervals.events files. Use an empty "
            "object when no external source files are supplied."
        ),
    )
    args = parser.parse_args()
    time_context = args.time_context_json
    source_inputs = args.source_inputs_json
    local_timezone = parse_timezone(time_context["local_timezone"])
    now = time_context["now"]
    planned_at = time_context["planned_at"]
    snapshot = build_readiness_snapshot(
        time_context["date"],
        artifacts_dir=Path(args.artifacts_dir),
        now=now,
        planned_at=planned_at,
        xert_input=load_xert_input(
            source_inputs.get("xert"),
            local_timezone=local_timezone,
        ),
        garmin_input=load_garmin_input(
            source_inputs.get("garmin"),
            local_timezone=local_timezone,
        ),
        intervals_wellness_input=load_json_input(
            (source_inputs.get("intervals") or {}).get("wellness")
        ),
        intervals_events_input=load_json_input(
            (source_inputs.get("intervals") or {}).get("events")
        ),
        local_timezone=local_timezone,
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))


def parse_source_inputs_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--source-inputs-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--source-inputs-json must contain one JSON object"
        )
    unknown = sorted(set(payload) - {"garmin", "xert", "intervals"})
    if unknown:
        raise argparse.ArgumentTypeError(
            "unsupported source-input field(s): " + ", ".join(unknown)
        )
    intervals = payload.get("intervals", {})
    if not isinstance(intervals, dict):
        raise argparse.ArgumentTypeError(
            "--source-inputs-json intervals must be an object"
        )
    unknown_intervals = sorted(set(intervals) - {"wellness", "events"})
    if unknown_intervals:
        raise argparse.ArgumentTypeError(
            "unsupported intervals source-input field(s): "
            + ", ".join(unknown_intervals)
        )

    normalized: dict[str, Any] = {}
    for key in ("garmin", "xert"):
        if key in payload:
            normalized[key] = validate_source_input_path(
                payload[key],
                field=key,
            )
    if intervals:
        normalized["intervals"] = {
            key: validate_source_input_path(value, field=f"intervals.{key}")
            for key, value in intervals.items()
        }
    return normalized


def validate_source_input_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise argparse.ArgumentTypeError(
            f"--source-inputs-json {field} must be a non-empty file path"
        )
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(
            f"--source-inputs-json {field} file does not exist: {path}"
        )
    return str(path)


def build_readiness_snapshot(
    day: str,
    *,
    artifacts_dir: Path = ARTIFACTS_DIR,
    now: datetime | None = None,
    planned_at: datetime | None = None,
    xert_input: dict[str, Any] | None = None,
    garmin_input: dict[str, Any] | None = None,
    intervals_wellness_input: dict[str, Any] | list[Any] | None = None,
    intervals_events_input: dict[str, Any] | list[Any] | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc).astimezone(local_timezone)
    now_utc = as_utc(now, local_timezone=local_timezone)
    planned_at_utc = (
        as_utc(planned_at, local_timezone=local_timezone)
        if planned_at is not None
        else None
    )
    data_cutoff = (
        min(now_utc, planned_at_utc)
        if planned_at_utc is not None
        else now_utc
    )
    activity = latest_activity_on_or_before(
        day,
        artifacts_dir=artifacts_dir,
        data_cutoff=data_cutoff,
        local_timezone=local_timezone,
    )
    xert_activity = matching_xert_activity(
        activity,
        day=day,
        xert_input=xert_input,
        data_cutoff=data_cutoff,
        local_timezone=local_timezone,
    )
    if activity and xert_activity:
        activity["xert_load"] = xert_activity
    garmin = garmin_snapshot(
        day,
        activity=activity,
        garmin_input=garmin_input,
        data_cutoff=data_cutoff,
        local_timezone=local_timezone,
    )
    xert = latest_xert_advice(
        now=data_cutoff,
        planned_at=planned_at,
        xert_input=xert_input,
        local_timezone=local_timezone,
    )
    freshness = input_freshness(
        garmin=garmin,
        xert=xert,
        now=data_cutoff,
        local_timezone=local_timezone,
    )
    intervals_wellness = intervals_wellness_context(
        day, intervals_wellness_input, events_payload=intervals_events_input
    )
    return {
        "date": day,
        "snapshot_time_local": format_local(now, local_timezone=local_timezone),
        "snapshot_time_utc": format_utc(now_utc, local_timezone=local_timezone),
        "planned_workout_time_local": (
            format_local(planned_at, local_timezone=local_timezone)
            if planned_at
            else None
        ),
        "planned_workout_time_utc": (
            format_utc(planned_at_utc, local_timezone=local_timezone)
            if planned_at_utc
            else None
        ),
        "data_cutoff_local": format_local(
            data_cutoff,
            local_timezone=local_timezone,
        ),
        "data_cutoff_utc": format_utc(
            data_cutoff,
            local_timezone=local_timezone,
        ),
        "local_timezone": timezone_name(local_timezone),
        "latest_activity": activity,
        "garmin": garmin,
        "xert": xert,
        "input_freshness": freshness,
        "recommendation_inputs": recommendation_inputs(
            activity=activity,
            garmin=garmin,
            xert=xert,
            freshness=freshness,
            now=data_cutoff,
            planned_at=planned_at,
            intervals_wellness=intervals_wellness,
            local_timezone=local_timezone,
        ),
        "notes": availability_notes(
            day,
            activity=activity,
            garmin=garmin,
            xert=xert,
            freshness=freshness,
            now=now,
        ),
    }


def latest_activity_on_or_before(
    day: str,
    *,
    artifacts_dir: Path,
    data_cutoff: datetime | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    activities_dir = artifacts_dir / "activities"
    if not activities_dir.exists():
        return None

    candidates = []
    for activity_dir in sorted(activities_dir.iterdir()):
        metadata_path = activity_dir / "activity.json"
        if not metadata_path.exists():
            continue
        metadata = load_json(metadata_path)
        raw_start_local = str(metadata.get("start_date_local") or "")
        if not raw_start_local or raw_start_local[:10] > day:
            continue
        start_datetime = parse_local_datetime(
            raw_start_local,
            local_timezone=local_timezone,
        )
        start_local = format_local(start_datetime, local_timezone=local_timezone)
        start_utc = format_utc(start_datetime, local_timezone=local_timezone)
        elapsed_seconds = number(metadata.get("elapsed_time")) or number(
            metadata.get("moving_time")
        )
        end_local = add_seconds(
            start_local,
            elapsed_seconds,
            local_timezone=local_timezone,
        )
        end_utc = (
            format_utc(
                parse_local_datetime(end_local, local_timezone=local_timezone),
                local_timezone=local_timezone,
            )
            if end_local
            else None
        )
        if data_cutoff is not None:
            activity_time = end_utc or start_utc
            if parse_garmin_utc_datetime(activity_time) > data_cutoff:
                continue
        candidates.append((start_utc, activity_dir, metadata))

    if not candidates:
        return None

    _, activity_dir, metadata = candidates[-1]
    intervals = metadata.get("icu_intervals") or []
    work_intervals = [
        interval
        for interval in intervals
        if str(interval.get("type") or "").upper() == "WORK"
    ]
    start_datetime = parse_local_datetime(
        str(metadata.get("start_date_local") or ""),
        local_timezone=local_timezone,
    )
    start_local = format_local(start_datetime, local_timezone=local_timezone)
    start_utc = format_utc(start_datetime, local_timezone=local_timezone)
    elapsed_seconds = number(metadata.get("elapsed_time")) or number(metadata.get("moving_time"))
    end_local = add_seconds(
        start_local,
        elapsed_seconds,
        local_timezone=local_timezone,
    )
    end_utc = (
        format_utc(
            parse_local_datetime(end_local, local_timezone=local_timezone),
            local_timezone=local_timezone,
        )
        if end_local
        else None
    )
    return {
        "id": metadata.get("id"),
        "name": metadata.get("name"),
        "activity_dir": str(activity_dir),
        "start_local": start_local,
        "start_utc": start_utc,
        "end_local": end_local,
        "end_utc": end_utc,
        "elapsed_minutes": minutes(elapsed_seconds),
        "type": metadata.get("type"),
        "load": {
            "source_preference": "Prefer xert_load.xss when present; Intervals load is secondary.",
            "icu_training_load": metadata.get("icu_training_load"),
            "icu_intensity": metadata.get("icu_intensity"),
            "average_watts": metadata.get("icu_average_watts") or metadata.get("average_watts"),
            "weighted_average_watts": metadata.get("icu_weighted_avg_watts")
            or metadata.get("weighted_average_watts"),
            "average_heartrate": metadata.get("average_heartrate"),
            "max_heartrate": metadata.get("max_heartrate"),
        },
        "intervals": {
            "work_count": len(work_intervals),
            "work_minutes": [minutes(number(interval.get("elapsed_time"))) for interval in work_intervals],
            "work_average_watts": [interval.get("average_watts") for interval in work_intervals],
            "work_average_heartrate": [
                interval.get("average_heartrate") for interval in work_intervals
            ],
        },
    }


def matching_xert_activity(
    activity: dict[str, Any] | None,
    *,
    day: str,
    xert_input: dict[str, Any] | None,
    data_cutoff: datetime | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    xert_activities = xert_activities_from_input(
        xert_input,
        day=day,
        data_cutoff=data_cutoff,
        local_timezone=local_timezone,
    )
    if not xert_activities:
        return None
    if not activity or not (activity.get("start_utc") or activity.get("start_local")):
        return xert_activities[-1]

    activity_start = activity_timestamp_utc(
        activity.get("start_utc"),
        activity.get("start_local"),
        local_timezone=local_timezone,
    )
    if activity_start is None:
        return xert_activities[-1]
    candidates = []
    for xert_activity in xert_activities:
        xert_start = activity_timestamp_utc(
            xert_activity.get("start_utc"),
            xert_activity.get("start_local"),
            local_timezone=local_timezone,
        )
        if xert_start is None:
            continue
        delta_seconds = abs((activity_start - xert_start).total_seconds())
        candidates.append((delta_seconds, xert_activity))

    if not candidates:
        return xert_activities[-1]

    delta_seconds, match = min(candidates, key=lambda item: item[0])
    if delta_seconds <= 30 * 60:
        match["match_delta_minutes"] = round(delta_seconds / 60, 1)
        return match
    return None


def xert_activities_from_input(
    xert_input: dict[str, Any] | None,
    *,
    day: str,
    data_cutoff: datetime | None = None,
    local_timezone: ZoneInfo,
) -> list[dict[str, Any]]:
    if not xert_input:
        return []
    result: list[dict[str, Any]] = []
    activity_loads = xert_input.get("activity_loads") or []
    if isinstance(activity_loads, dict):
        activity_loads = [activity_loads]
    if not isinstance(activity_loads, list):
        return []
    for payload in activity_loads:
        if not isinstance(payload, dict):
            continue
        normalized = compact_xert_activity_load(
            payload,
            source_file=xert_input.get("source_file"),
            local_timezone=local_timezone,
        )
        if not normalized:
            continue
        start_local = normalized.get("start_local")
        start_utc = normalized.get("start_utc")
        if not start_local or str(start_local)[:10] > day:
            continue
        if data_cutoff is not None:
            elapsed_minutes = number(normalized.get("elapsed_minutes"))
            start_timestamp = activity_timestamp_utc(
                start_utc,
                start_local,
                local_timezone=local_timezone,
            )
            end_timestamp = (
                start_timestamp + timedelta(minutes=elapsed_minutes)
                if start_timestamp is not None and elapsed_minutes is not None
                else start_timestamp
            )
            if end_timestamp is not None and end_timestamp > data_cutoff:
                continue
        result.append(normalized)
    return sorted(result, key=lambda item: str(item.get("start_local") or ""))


def compact_xert_activity_load(
    payload: dict[str, Any],
    *,
    source_file: str | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    start_local = payload.get("start_local")
    if not start_local:
        return None
    start_timestamp = activity_timestamp_utc(
        payload.get("start_utc"),
        start_local,
        local_timezone=local_timezone,
    )
    result = {
        "source": payload.get("source") or "xert_readiness_json",
        "path": payload.get("path"),
        "name": payload.get("name"),
        "start_local": start_local,
        "start_utc": (
            format_utc(start_timestamp, local_timezone=local_timezone)
            if start_timestamp
            else None
        ),
        "elapsed_minutes": payload.get("elapsed_minutes"),
        "xss": payload.get("xss"),
        "xep_watts": payload.get("xep_watts"),
        "focus": payload.get("focus"),
        "specificity": payload.get("specificity"),
        "difficulty": payload.get("difficulty"),
        "difficulty_rating": payload.get("difficulty_rating"),
        "freshness": payload.get("freshness"),
        "signature": payload.get("signature"),
    }
    if source_file:
        result["source_file"] = source_file
    return result


def garmin_snapshot(
    day: str,
    *,
    activity: dict[str, Any] | None,
    garmin_input: dict[str, Any] | None,
    data_cutoff: datetime | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    sources = garmin_sources_for_day(day, garmin_input)
    summary = sources.get("summary")
    hrv = sources.get("hrv")
    sleep = sources.get("sleep")
    stress = sources.get("stress")
    heart_rate = sources.get("heart_rate")
    compact_readiness_rows = (garmin_input or {}).get(
        "training_readiness_observations"
    )
    readiness_rows = sources.get("training_readiness")
    training_status = sources.get("training_status")
    body_battery = sources.get("body_battery") or sources.get("body_battery_range")
    cutoff_ms = (
        datetime_timestamp_ms(data_cutoff, local_timezone=local_timezone)
        if data_cutoff is not None
        else None
    )
    if isinstance(compact_readiness_rows, list):
        readiness = latest_compact_readiness_at_or_before(
            compact_readiness_rows,
            data_cutoff,
        )
    else:
        readiness = latest_row_at_or_before(
            readiness_rows,
            data_cutoff,
        )

    post_start_ms = None
    if activity and (activity.get("end_utc") or activity.get("end_local")):
        post_start_ms = local_timestamp_ms(
            str(activity.get("end_utc") or activity["end_local"]),
            local_timezone=local_timezone,
        )
    post_end_ms = post_activity_end_ms(post_start_ms=post_start_ms, sleep=sleep)

    return {
        "source_errors": {
            **garmin_source_errors(sources),
            **(
                (garmin_input or {}).get("source_errors")
                if isinstance((garmin_input or {}).get("source_errors"), dict)
                else {}
            ),
        },
        "summary": compact_summary(summary),
        "hrv": compact_hrv(hrv),
        "hrv_history": compact_hrv_history(day, garmin_input),
        "sleep": compact_sleep(sleep),
        "training_readiness": compact_training_readiness(readiness),
        "training_status": compact_training_status(
            training_status,
            data_cutoff=data_cutoff,
            local_timezone=local_timezone,
        ),
        "vo2max": compact_vo2max_context(
            day,
            compact=(garmin_input or {}).get("vo2max"),
            training_status=training_status,
        ),
        "stress": compact_stress(
            stress,
            post_start_ms=post_start_ms,
            post_end_ms=post_end_ms,
            cutoff_ms=cutoff_ms,
            local_timezone=local_timezone,
        ),
        "heart_rate": compact_heart_rate(
            heart_rate,
            post_start_ms=post_start_ms,
            post_end_ms=post_end_ms,
            cutoff_ms=cutoff_ms,
            local_timezone=local_timezone,
        ),
        "body_battery": compact_body_battery(
            summary=summary,
            stress=stress,
            body_battery=body_battery,
            cutoff_ms=cutoff_ms,
        ),
    }


def compact_vo2max_context(
    day: str,
    *,
    compact: dict[str, Any] | None,
    training_status: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Preserve Garmin VO2max categories as modeled diagnostic context."""
    if isinstance(compact, dict) and isinstance(compact.get("estimates"), dict):
        return compact
    raw = (training_status or {}).get("mostRecentVO2Max") or {}
    estimates = {}
    for category in ("cycling", "generic"):
        record = raw.get(category)
        if not isinstance(record, dict):
            continue
        calendar_date = record.get("calendarDate")
        age_days = None
        try:
            if calendar_date:
                age_days = (date.fromisoformat(day) - date.fromisoformat(calendar_date)).days
        except (TypeError, ValueError):
            pass
        estimates[category] = {
            "category": category,
            "value": number(record.get("vo2MaxValue")),
            "precise_value": number(record.get("vo2MaxPreciseValue")),
            "unit": "ml/kg/min",
            "calendar_date": calendar_date,
            "age_days_at_requested_date": age_days,
            "source_device": None,
            "source_device_available": False,
            "source_device_reason": "not_exposed_in_vo2max_record",
        }
    if not estimates:
        return None
    return {
        "estimates": estimates,
        "category_note": (
            "Preserve Garmin's raw category. Do not relabel `generic` as running "
            "without a source field that establishes the sport."
        ),
        "interpretation": {
            "modeled_not_measured": True,
            "sport_categories_must_remain_separate": True,
            "trend_preferred_over_single_point": True,
        },
    }


def garmin_source_errors(sources: dict[str, Any]) -> dict[str, Any]:
    errors = {}
    for name, payload in sources.items():
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            errors[name] = payload["error"]
    return errors


def garmin_sources_for_day(day: str, garmin_input: dict[str, Any] | None) -> dict[str, Any]:
    if not garmin_input:
        return {}
    if isinstance(garmin_input.get("sources"), dict):
        return garmin_input["sources"]
    if isinstance(garmin_input.get("days"), list):
        for entry in garmin_input["days"]:
            if isinstance(entry, dict) and entry.get("date") == day:
                sources = entry.get("sources")
                if isinstance(sources, dict):
                    result = dict(sources)
                    if "body_battery_range" in garmin_input:
                        result.setdefault("body_battery_range", garmin_input["body_battery_range"])
                    return result
    return garmin_input


def compact_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    return pick(
        summary,
        [
            "calendarDate",
            "lastSyncTimestampGMT",
            "restingHeartRate",
            "lastSevenDaysAvgRestingHeartRate",
            "minHeartRate",
            "minAvgHeartRate",
            "maxHeartRate",
            "bodyBatteryAtWakeTime",
            "bodyBatteryMostRecentValue",
            "bodyBatteryChargedValue",
            "bodyBatteryDrainedValue",
            "averageStressLevel",
            "lowStressDuration",
            "mediumStressDuration",
            "highStressDuration",
            "restStressDuration",
            "totalSteps",
        ],
    )


def compact_hrv(hrv: dict[str, Any] | None) -> dict[str, Any] | None:
    if not hrv:
        return None
    summary = hrv.get("hrvSummary") or {}
    observation_time_local = (
        hrv.get("sleepEndTimestampLocal")
        or hrv.get("endTimestampLocal")
    )
    observation_time_utc = (
        hrv.get("sleepEndTimestampGMT")
        or hrv.get("endTimestampGMT")
    )
    return {
        "observation_date": local_date_from_value(
            observation_time_local
            or summary.get("calendarDate")
        ),
        "observation_time_local": observation_time_local,
        "observation_time_utc": observation_time_utc,
        "status": summary.get("status"),
        "lastNightAvg": summary.get("lastNightAvg"),
        "weeklyAvg": summary.get("weeklyAvg"),
        "baseline": summary.get("baseline"),
    }


def compact_hrv_history(
    day: str,
    garmin_input: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = (garmin_input or {}).get("hrv_history") or {}
    rows = []
    for entry in payload.get("days") or []:
        if not isinstance(entry, dict):
            continue
        entry_day = str(entry.get("date") or "")
        if not entry_day or entry_day > day:
            continue
        sources = entry.get("sources") or {}
        summary = ((sources.get("hrv") or {}).get("hrvSummary") or {})
        value = summary.get("lastNightAvg")
        if isinstance(value, (int, float)):
            rows.append({"date": entry_day, "last_night_avg": float(value)})
    rows = sorted(rows, key=lambda row: row["date"])[-7:]
    values = [row["last_night_avg"] for row in rows]
    recent_three = values[-3:]
    mean_3d = statistics.fmean(recent_three) if len(recent_three) == 3 else None
    mean_7d = statistics.fmean(values) if len(values) == 7 else None
    median_7d = statistics.median(values) if len(values) == 7 else None
    cv_7d = (
        statistics.pstdev(values) / mean_7d * 100.0
        if mean_7d not in (None, 0) and len(values) == 7
        else None
    )
    return {
        "nights": rows,
        "nights_used_3d": len(recent_three),
        "nights_used_7d": len(values),
        "mean_3d": round(mean_3d, 3) if mean_3d is not None else None,
        "mean_7d": round(mean_7d, 3) if mean_7d is not None else None,
        "median_7d": round(median_7d, 3) if median_7d is not None else None,
        "cv_7d_percent": round(cv_7d, 3) if cv_7d is not None else None,
    }


def compact_sleep(sleep: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sleep:
        return None
    daily = sleep.get("dailySleepDTO") if isinstance(sleep, dict) else None
    source = daily if isinstance(daily, dict) else sleep
    result = pick(
        source,
        [
            "calendarDate",
            "sleepStartTimestampGMT",
            "sleepEndTimestampGMT",
            "sleepStartTimestampLocal",
            "sleepEndTimestampLocal",
            "sleepTimeSeconds",
            "sleepScore",
            "sleepScores",
            "measurableSleepSeconds",
        ],
    )
    sleep_scores = source.get("sleepScores") or {}
    overall = sleep_scores.get("overall") if isinstance(sleep_scores, dict) else None
    if isinstance(overall, dict):
        result["sleepScore"] = overall.get("value")
    return result


def compact_training_readiness(readiness: dict[str, Any] | None) -> dict[str, Any] | None:
    if not readiness:
        return None
    if isinstance(readiness.get("drivers"), dict):
        return readiness
    recovery_time_minutes = number(readiness.get("recoveryTime"))
    return {
        "score": number(readiness.get("score")),
        "level": readiness.get("level"),
        "feedback_short": readiness.get("feedbackShort"),
        "feedback_long": readiness.get("feedbackLong"),
        "observed_at": readiness.get("timestamp"),
        "observed_at_local": readiness.get("timestampLocal"),
        "calendar_date": readiness.get("calendarDate"),
        "input_context": readiness.get("inputContext"),
        "valid_sleep": readiness.get("validSleep"),
        "drivers": {
            "sleep_score": compact_readiness_driver(
                value=readiness.get("sleepScore"),
                percent=readiness.get("sleepScoreFactorPercent"),
                feedback=readiness.get("sleepScoreFactorFeedback"),
            ),
            "recovery_time": compact_readiness_driver(
                value=recovery_time_minutes,
                percent=readiness.get("recoveryTimeFactorPercent"),
                feedback=readiness.get("recoveryTimeFactorFeedback"),
                unit="minutes",
                extra={
                    "hours": (
                        round(recovery_time_minutes / 60, 1)
                        if recovery_time_minutes is not None
                        else None
                    ),
                    "change_phrase": readiness.get("recoveryTimeChangePhrase"),
                },
            ),
            "hrv_status": compact_readiness_driver(
                value=readiness.get("hrvWeeklyAverage"),
                percent=readiness.get("hrvFactorPercent"),
                feedback=readiness.get("hrvFactorFeedback"),
                unit="ms",
            ),
            "acute_load": compact_readiness_driver(
                value=readiness.get("acuteLoad"),
                percent=readiness.get("acwrFactorPercent"),
                feedback=readiness.get("acwrFactorFeedback"),
            ),
            "sleep_history": compact_readiness_driver(
                percent=readiness.get("sleepHistoryFactorPercent"),
                feedback=readiness.get("sleepHistoryFactorFeedback"),
            ),
            "stress_history": compact_readiness_driver(
                percent=readiness.get("stressHistoryFactorPercent"),
                feedback=readiness.get("stressHistoryFactorFeedback"),
            ),
        },
        "interpretation": {
            "aggregate_is_diagnostic": True,
            "drivers_are_not_independent": True,
            "not_a_race_performance_forecast": True,
        },
    }


def compact_readiness_driver(
    *,
    value: Any = None,
    percent: Any = None,
    feedback: Any = None,
    unit: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "value": number(value),
        "factor_percent": number(percent),
        "feedback": feedback,
    }
    if unit:
        result["unit"] = unit
    if extra:
        result.update(extra)
    return result


def latest_compact_readiness_at_or_before(
    rows: list[Any],
    data_cutoff: datetime | None,
) -> dict[str, Any] | None:
    """Select a normalized Garmin observation without leaking later data."""

    candidates = [row for row in rows if isinstance(row, dict)]
    if data_cutoff is not None:
        eligible = []
        for row in candidates:
            timestamp = parse_garmin_utc_datetime(row.get("observed_at"))
            if timestamp is not None and timestamp <= data_cutoff:
                eligible.append(row)
        candidates = eligible
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: str(row.get("observed_at_local") or row.get("observed_at") or ""),
    )


def compact_training_status(
    status: dict[str, Any] | None,
    *,
    data_cutoff: datetime | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    if not status or status.get("error"):
        return None
    latest_status = (
        (status.get("mostRecentTrainingStatus") or {})
        .get("latestTrainingStatusData", {})
    )
    latest_device_status = first_mapping_value(latest_status) or {}
    status_timestamp = number(latest_device_status.get("timestamp"))
    if (
        data_cutoff is not None
        and status_timestamp is not None
        and status_timestamp
        > datetime_timestamp_ms(data_cutoff, local_timezone=local_timezone)
    ):
        return None
    load_balance = (
        (status.get("mostRecentTrainingLoadBalance") or {})
        .get("metricsTrainingLoadBalanceDTOMap", {})
    )
    latest_load_balance = first_mapping_value(load_balance)
    vo2max = status.get("mostRecentVO2Max") or {}
    acute_training_load = (
        latest_device_status.get("acuteTrainingLoadDTO", {}) if latest_device_status else {}
    )
    return {
        "training_status": latest_device_status.get("trainingStatus")
        if latest_device_status
        else None,
        "feedback": latest_device_status.get("trainingStatusFeedbackPhrase")
        if latest_device_status
        else None,
        "since_date": latest_device_status.get("sinceDate") if latest_device_status else None,
        "fitness_trend": latest_device_status.get("fitnessTrend")
        if latest_device_status
        else None,
        "fitness_trend_sport": latest_device_status.get("fitnessTrendSport")
        if latest_device_status
        else None,
        "sport": latest_device_status.get("sport") if latest_device_status else None,
        "acute_load": acute_training_load.get("dailyTrainingLoadAcute"),
        "chronic_load": acute_training_load.get("dailyTrainingLoadChronic"),
        "acwr": acute_training_load.get("dailyAcuteChronicWorkloadRatio"),
        "acwr_percent": acute_training_load.get("acwrPercent"),
        "acwr_status": acute_training_load.get("acwrStatus"),
        "monthly_load_aerobic_low": latest_load_balance.get("monthlyLoadAerobicLow")
        if latest_load_balance
        else None,
        "monthly_load_aerobic_low_target_min": latest_load_balance.get(
            "monthlyLoadAerobicLowTargetMin"
        )
        if latest_load_balance
        else None,
        "monthly_load_aerobic_low_target_max": latest_load_balance.get(
            "monthlyLoadAerobicLowTargetMax"
        )
        if latest_load_balance
        else None,
        "monthly_load_aerobic_high": latest_load_balance.get("monthlyLoadAerobicHigh")
        if latest_load_balance
        else None,
        "monthly_load_aerobic_high_target_min": latest_load_balance.get(
            "monthlyLoadAerobicHighTargetMin"
        )
        if latest_load_balance
        else None,
        "monthly_load_aerobic_high_target_max": latest_load_balance.get(
            "monthlyLoadAerobicHighTargetMax"
        )
        if latest_load_balance
        else None,
        "monthly_load_anaerobic": latest_load_balance.get("monthlyLoadAnaerobic")
        if latest_load_balance
        else None,
        "monthly_load_anaerobic_target_min": latest_load_balance.get(
            "monthlyLoadAnaerobicTargetMin"
        )
        if latest_load_balance
        else None,
        "monthly_load_anaerobic_target_max": latest_load_balance.get(
            "monthlyLoadAnaerobicTargetMax"
        )
        if latest_load_balance
        else None,
        "load_balance_feedback": latest_load_balance.get("trainingBalanceFeedbackPhrase")
        if latest_load_balance
        else None,
        "vo2max_cycling": (vo2max.get("cycling") or {}).get("vo2MaxValue"),
    }


def compact_stress(
    stress: dict[str, Any] | None,
    *,
    post_start_ms: int | None,
    post_end_ms: int | None,
    cutoff_ms: int | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    if not stress:
        return None
    values = points_at_or_before(
        valid_series_values(stress.get("stressValuesArray")),
        cutoff_ms,
    )
    result = pick(stress, ["avgStressLevel", "maxStressLevel"])
    result["latest"] = latest_point(values)
    if post_start_ms is not None:
        post = points_in_window(values, start_ms=post_start_ms, end_ms=post_end_ms)
        post_30 = points_in_window(
            values,
            start_ms=post_start_ms + 30 * 60 * 1000,
            end_ms=post_end_ms,
        )
        result["post_activity_window"] = post_activity_window(
            post_start_ms,
            post_end_ms,
            local_timezone=local_timezone,
        )
        result["post_activity"] = series_stats(post)
        result["post_activity_after_30min"] = series_stats(post_30)
    return result


def compact_heart_rate(
    heart_rate: dict[str, Any] | None,
    *,
    post_start_ms: int | None,
    post_end_ms: int | None,
    cutoff_ms: int | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    if not heart_rate:
        return None
    values = points_at_or_before(
        valid_series_values(heart_rate.get("heartRateValues")),
        cutoff_ms,
    )
    result = pick(
        heart_rate,
        [
            "calendarDate",
            "restingHeartRate",
            "lastSevenDaysAvgRestingHeartRate",
            "minHeartRate",
            "maxHeartRate",
        ],
    )
    result["latest"] = latest_point(values)
    if post_start_ms is not None:
        post = points_in_window(values, start_ms=post_start_ms, end_ms=post_end_ms)
        post_30 = points_in_window(
            values,
            start_ms=post_start_ms + 30 * 60 * 1000,
            end_ms=post_end_ms,
        )
        result["post_activity_window"] = post_activity_window(
            post_start_ms,
            post_end_ms,
            local_timezone=local_timezone,
        )
        result["post_activity"] = series_stats(post)
        result["post_activity_after_30min"] = series_stats(post_30)
        result["post_activity_readiness_signal"] = post_activity_hr_signal(post_30 or post)
    return result


def compact_body_battery(
    *,
    summary: dict[str, Any] | None,
    stress: dict[str, Any] | None,
    body_battery: Any,
    cutoff_ms: int | None = None,
) -> dict[str, Any] | None:
    result = compact_body_battery_from_daily_sources(
        summary=summary,
        stress=stress,
        cutoff_ms=cutoff_ms,
    )
    if result:
        return result

    day_payload = body_battery_day_payload(body_battery)
    if not isinstance(day_payload, dict):
        return None
    values = points_at_or_before(
        valid_series_values(day_payload.get("bodyBatteryValuesArray")),
        cutoff_ms,
    )
    return {
        "source": "garmin_connect_body_battery",
        "charged": day_payload.get("charged"),
        "drained": day_payload.get("drained"),
        "latest": latest_point(values),
        "events": day_payload.get("bodyBatteryActivityEvent"),
        "dynamic_feedback": day_payload.get("bodyBatteryDynamicFeedbackEvent"),
    }


def compact_body_battery_from_daily_sources(
    *,
    summary: dict[str, Any] | None,
    stress: dict[str, Any] | None,
    cutoff_ms: int | None,
) -> dict[str, Any] | None:
    values = points_at_or_before(
        body_battery_series_values(
            (stress or {}).get("bodyBatteryValuesArray") if stress else None,
        ),
        cutoff_ms,
    )
    latest = latest_point(values)
    most_recent = latest.get("value") if latest is not None else None
    at_wake = (summary or {}).get("bodyBatteryAtWakeTime") if summary else None
    if latest is None and at_wake is None:
        return None

    return {
        "source": "garmin_connect_summary_or_stress",
        "calendar_date": (summary or {}).get("calendarDate") if summary else None,
        "at_wake": at_wake,
        "charged": (summary or {}).get("bodyBatteryChargedValue") if summary else None,
        "drained": (summary or {}).get("bodyBatteryDrainedValue") if summary else None,
        "most_recent": most_recent,
        "latest": latest,
        "events": (summary or {}).get("bodyBatteryActivityEventList") if summary else None,
        "dynamic_feedback": (
            (summary or {}).get("bodyBatteryDynamicFeedbackEvent") if summary else None
        ),
    }


def body_battery_series_values(raw_values: Any) -> list[tuple[int, float]]:
    if not isinstance(raw_values, list):
        return []
    values = []
    for row in raw_values:
        if not isinstance(row, list) or len(row) < 3:
            continue
        timestamp = int(row[0])
        value = number(row[2])
        if value is None or value < 0:
            continue
        values.append((timestamp, value))
    return values


def post_activity_end_ms(*, post_start_ms: int | None, sleep: Any) -> int | None:
    """End post-activity response at sleep start when sleep follows the activity."""

    if post_start_ms is None:
        return None
    start_ms = sleep_start_timestamp_ms(sleep)
    if start_ms is not None and start_ms > post_start_ms:
        return start_ms
    return None


def sleep_start_timestamp_ms(sleep: Any) -> int | None:
    if not isinstance(sleep, dict):
        return None
    daily = sleep.get("dailySleepDTO") if isinstance(sleep.get("dailySleepDTO"), dict) else sleep
    raw = daily.get("sleepStartTimestampGMT")
    value = number(raw)
    return int(value) if value is not None else None


def points_in_window(
    values: list[tuple[int, float]],
    *,
    start_ms: int,
    end_ms: int | None,
) -> list[tuple[int, float]]:
    if end_ms is None:
        return [point for point in values if point[0] >= start_ms]
    return [point for point in values if start_ms <= point[0] <= end_ms]


def post_activity_window(
    start_ms: int,
    end_ms: int | None,
    *,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    return {
        "start_local": timestamp_ms_to_local(
            start_ms,
            local_timezone=local_timezone,
        ),
        "end_local": (
            timestamp_ms_to_local(end_ms, local_timezone=local_timezone)
            if end_ms is not None
            else None
        ),
        "end_reason": "sleep_start" if end_ms is not None else "open_until_latest_input",
    }


def body_battery_day_payload(payload: Any) -> dict[str, Any] | None:
    day_payload = payload[-1] if isinstance(payload, list) and payload else payload
    if not isinstance(day_payload, dict):
        return None
    return day_payload


def latest_xert_advice(
    *,
    now: datetime,
    planned_at: datetime | None,
    xert_input: dict[str, Any] | None,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    if not xert_input:
        return None
    normalized_input = normalize_xert_input(xert_input)
    recovery = normalized_input.get("recovery")
    training_advice = normalized_input.get("training_advice")
    if not isinstance(recovery, dict):
        return None
    if not isinstance(training_advice, dict):
        training_advice = {}
    return compact_xert_advice(
        recovery,
        training_advice=training_advice,
        training_advice_debug=normalized_input.get("training_advice_debug"),
        now=now,
        planned_at=planned_at,
        source_time_local=normalized_input.get("source_time_local"),
        source_file=normalized_input.get("source_file"),
        local_timezone=local_timezone,
    )


def normalize_xert_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept legacy readiness input and normalized Xert MCP envelopes."""

    recovery = payload.get("recovery")
    training_advice = payload.get("training_advice")
    if isinstance(recovery, dict) and isinstance(training_advice, dict):
        return payload

    advice_envelope = payload.get("training_advice")
    if not (
        isinstance(advice_envelope, dict)
        and isinstance(advice_envelope.get("advice"), dict)
    ):
        advice_envelope = payload
    advice = advice_envelope.get("advice") if isinstance(advice_envelope, dict) else None

    state_envelope = payload.get("training_state")
    if not (
        isinstance(state_envelope, dict)
        and isinstance(state_envelope.get("state"), dict)
    ):
        state_envelope = payload
    state = state_envelope.get("state") if isinstance(state_envelope, dict) else None

    if not isinstance(advice, dict) and not isinstance(state, dict):
        return payload
    advice = advice if isinstance(advice, dict) else {}
    state = state if isinstance(state, dict) else {}
    normalized = dict(payload)
    normalized["recovery"] = {
        "source": state.get("source") or advice.get("source") or "xert_mcp",
        "recovery_hours": state.get("recovery_hours"),
        "training_load": state.get("training_load"),
        "recovery_load": state.get("recovery_load"),
    }
    normalized["training_advice"] = advice
    normalized.setdefault(
        "source_time_local",
        advice.get("training_advice_as_of") or state.get("as_of"),
    )
    return normalized


def compact_xert_advice(
    recovery: dict[str, Any],
    *,
    training_advice: dict[str, Any],
    training_advice_debug: Any,
    now: datetime,
    planned_at: datetime | None,
    source_time_local: Any,
    source_file: str | None,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    hours_until_planned = (
        round((planned_at - now).total_seconds() / 3600, 1)
        if planned_at is not None
        else None
    )
    recovery_hours = recovery.get("recovery_hours") or {}
    if not isinstance(recovery_hours, dict):
        recovery_hours = {}
    workout_capacity = recovery.get("workout_capacity") or {}
    if not isinstance(workout_capacity, dict):
        workout_capacity = {}
    result = {
        "source": recovery.get("source") or "xert_readiness_json",
        "source_time_local": format_local(
            parse_local_datetime(
                str(source_time_local),
                local_timezone=local_timezone,
            ),
            local_timezone=local_timezone,
        )
        if source_time_local
        else None,
        "training_advice": {
            "source": training_advice.get("source") or recovery.get("source") or "xert_readiness_json",
            "source_endpoint": training_advice.get("source_endpoint"),
            "source_scope": training_advice.get("source_scope"),
            "date": training_advice.get("date"),
            "training_status": training_advice.get("training_status"),
            "target_xss": training_advice.get("target_xss"),
            "remaining_xss": training_advice.get("remaining_xss"),
            "completed_xss": training_advice.get("completed_xss"),
            "original_target_xss": training_advice.get("original_target_xss"),
            "training_advice_as_of": training_advice.get("training_advice_as_of"),
            "training_advice_as_of_val": training_advice.get("training_advice_as_of_val"),
            "daily_goal_complete": training_advice.get("daily_goal_complete"),
            "recovery_needed": training_advice.get("recovery_needed"),
            "availability": training_advice.get("availability"),
            "is_availability_restricted": training_advice.get("is_availability_restricted"),
            "xss_deficit": training_advice.get("xss_deficit"),
            "xss_goal": training_advice.get("xss_goal"),
            "hours_deficit": training_advice.get("hours_deficit"),
            "activity_deficit": training_advice.get("activity_deficit"),
            "targets_source": training_advice.get("targets_source"),
            "based_on_day": training_advice.get("based_on_day"),
            "improvement_rate": training_advice.get("improvement_rate"),
            "weekly_hours": training_advice.get("weekly_hours"),
            "training_gradient": training_advice.get("training_gradient"),
            "phase": training_advice.get("phase"),
            "recommended_athlete": training_advice.get("recommended_athlete"),
            "meaning": training_advice.get("meaning")
            or (
                "Xert trainingAdvice fields. target_xss is Xert's current target "
                "or recommended XSS dose for the training advice context. "
                "High/peak XSS primarily reflects over-TP work; low high/peak "
                "does not by itself rule out controlled subthreshold VT2."
            ),
        },
        "training_advice_debug": training_advice_debug
        if isinstance(training_advice_debug, dict)
        else None,
        "recovery_offset": recovery.get("recovery_offset"),
        "next_workout_days": recovery.get("next_workout_days"),
        "recovery_hours": {
            "meaning": (
                "Positive hours are Xert's recommended wait before more load "
                "in each system: low = any activity that generates low XSS, "
                "high = work over TP that generates high XSS, peak = work over "
                "TP with special relevance to peak-power/peak-XSS work."
            ),
            **recovery_hours,
        },
        "projected_recovery_hours_at_planned_time": {
            "meaning": "Simple time projection from Xert advice; assumes no intervening training.",
            "hours_until_planned": hours_until_planned,
            **(
                recovery.get("recovery_hours_at_advice_time")
                if isinstance(recovery.get("recovery_hours_at_advice_time"), dict)
                else {
                    "low": project_hours(recovery_hours.get("low"), hours_until_planned),
                    "high": project_hours(recovery_hours.get("high"), hours_until_planned),
                    "peak": project_hours(recovery_hours.get("peak"), hours_until_planned),
                }
            ),
        },
        "workout_capacity": {
            "meaning": (
                "Training that can be done now while still being just fresh before "
                "the next planned Xert workout."
            ),
            **workout_capacity,
        },
        "training_load": recovery.get("training_load"),
        "recovery_load": recovery.get("recovery_load"),
    }
    if source_file:
        result["source_file"] = source_file
    return result


def availability_notes(
    day: str,
    *,
    activity: dict[str, Any] | None,
    garmin: dict[str, Any],
    xert: dict[str, Any] | None,
    freshness: dict[str, Any],
    now: datetime,
) -> list[str]:
    notes = []
    future_day = date.fromisoformat(day) > now.date()
    if not activity:
        notes.append("No saved Intervals activity artifact found on or before this date.")
    for key, value in garmin.items():
        if key == "source_errors":
            continue
        if value is None:
            if future_day and key in {
                "hrv",
                "training_readiness",
                "body_battery",
                "sleep",
                "heart_rate",
                "summary",
                "stress",
            }:
                notes.append(
                    f"Garmin {key} input for {day} is not available yet because "
                    "the date has not happened."
                )
            else:
                notes.append(f"Missing Garmin {key} input for {day}.")
    source_errors = garmin.get("source_errors") or {}
    if source_errors:
        notes.append(
            "Garmin source fetch errors: " + ", ".join(sorted(source_errors)) + "."
        )
    if xert is None:
        notes.append("No Xert readiness JSON input provided.")
    stale = [
        key
        for key, value in freshness.items()
        if isinstance(value, dict) and value.get("freshness") == "stale"
    ]
    if stale:
        notes.append(
            "Stale dynamic time-series input: "
            + ", ".join(stale)
            + ". This affects current-state confirmation only; completed current-day "
            "sleep, overnight HRV, resting HR, and Body Battery at wake remain "
            "usable when present. Sync before hard training when current-state "
            "confirmation matters."
        )
    return notes


def recommendation_inputs(
    *,
    activity: dict[str, Any] | None,
    garmin: dict[str, Any],
    xert: dict[str, Any] | None,
    freshness: dict[str, Any],
    now: datetime,
    planned_at: datetime | None,
    intervals_wellness: dict[str, Any] | None = None,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    """Collect decision inputs without making a training recommendation."""

    training_readiness = garmin.get("training_readiness") or {}
    heart_rate = garmin.get("heart_rate") or {}
    stress = garmin.get("stress") or {}
    body_battery = garmin.get("body_battery") or {}
    summary = garmin.get("summary") or {}
    hrv = garmin.get("hrv") or {}
    hrv_history = garmin.get("hrv_history") or {}
    hrv_baseline = hrv.get("baseline") or {}
    sleep = garmin.get("sleep") or {}
    training_status = garmin.get("training_status") or {}
    vo2max = garmin.get("vo2max") or {}
    readiness_drivers = training_readiness.get("drivers") or {}
    normalized_readiness = bool(readiness_drivers)
    recovery_driver = readiness_drivers.get("recovery_time") or {}

    readiness_age_hours = hours_since_garmin_timestamp(
        training_readiness.get("observed_at") or training_readiness.get("timestamp"),
        now=now,
    )
    garmin_recovery_hours = (
        recovery_driver.get("hours")
        if normalized_readiness
        else training_readiness.get("recovery_time_hours")
    )
    projected_recovery_now = project_garmin_recovery_hours(
        garmin_recovery_hours,
        readiness_age_hours,
    )
    hours_until_planned = (
        round((planned_at - now).total_seconds() / 3600, 1)
        if planned_at is not None
        else None
    )
    wellness = validate_garmin_wellness_signals(
        day=(planned_at.date() if planned_at is not None else now.date()).isoformat(),
        now=now,
        freshness=freshness,
        values={
            "hrv_status": hrv.get("status"),
            "hrv_last_night_avg": hrv.get("lastNightAvg"),
            "hrv_weekly_avg": hrv.get("weeklyAvg"),
            "hrv_baseline": hrv_baseline,
            "hrv_balanced_low": hrv_baseline.get("balancedLow"),
            "hrv_balanced_upper": hrv_baseline.get("balancedUpper"),
            "hrv_low_upper": hrv_baseline.get("lowUpper"),
            "hrv_nightly_averages": hrv_history.get("nights"),
            "hrv_3day_mean": hrv_history.get("mean_3d"),
            "hrv_7day_mean": hrv_history.get("mean_7d"),
            "hrv_7day_median": hrv_history.get("median_7d"),
            "hrv_7day_cv_percent": hrv_history.get("cv_7d_percent"),
            "hrv_nights_used_3d": hrv_history.get("nights_used_3d"),
            "hrv_nights_used_7d": hrv_history.get("nights_used_7d"),
            "resting_hr": heart_rate.get("restingHeartRate"),
            "resting_hr_7day": heart_rate.get("lastSevenDaysAvgRestingHeartRate"),
            "sleep_score": sleep.get("sleepScore"),
            "sleep_time_seconds": sleep.get("sleepTimeSeconds"),
            "body_battery_at_wake": body_battery.get("at_wake"),
            "body_battery_most_recent": body_battery.get("most_recent"),
            "body_battery_latest": body_battery.get("latest"),
        },
        source_context={
            "hrv_observation_date": hrv.get("observation_date"),
            "hrv_observation_time_local": hrv.get("observation_time_local"),
            "hrv_observation_time_utc": hrv.get("observation_time_utc"),
            "sleep_calendar_date": sleep.get("calendarDate"),
            "sleep_start_utc": sleep.get("sleepStartTimestampGMT"),
            "sleep_end_utc": sleep.get("sleepEndTimestampGMT"),
            "sleep_start_local": sleep.get("sleepStartTimestampLocal"),
            "sleep_end_local": sleep.get("sleepEndTimestampLocal"),
            "summary_calendar_date": summary.get("calendarDate"),
            "heart_rate_calendar_date": heart_rate.get("calendarDate"),
            "body_battery_calendar_date": body_battery.get("calendar_date"),
            "data_cutoff_local": format_local(
                now,
                local_timezone=local_timezone,
            ),
        },
        local_timezone=local_timezone,
    )
    return {
        "purpose": (
            "Input summary only. Use this to make the chat recommendation; "
            "the script intentionally does not conclude whether to train."
        ),
        "time_context": {
            "now_local": format_local(now, local_timezone=local_timezone),
            "planned_workout_time_local": (
                format_local(planned_at, local_timezone=local_timezone)
                if planned_at
                else None
            ),
            "hours_until_planned": (
                round((planned_at - now).total_seconds() / 3600, 1)
                if planned_at is not None
                else None
            ),
        },
        "input_freshness": freshness,
        "latest_activity_load": latest_activity_load_input(activity),
        "intervals_wellness_events": intervals_wellness,
        "xert_training_advice": xert_training_advice_input(xert),
        "xert_recovery": xert_recovery_input(xert),
        "garmin_recovery_readiness": {
            "training_readiness_score": training_readiness.get("score"),
            "training_readiness_level": training_readiness.get("level"),
            "training_readiness_feedback_short": training_readiness.get(
                "feedback_short" if normalized_readiness else "feedbackShort"
            ),
            "training_readiness_feedback_long": training_readiness.get(
                "feedback_long" if normalized_readiness else "feedbackLong"
            ),
            "training_readiness_diagnostic_only": True,
            "training_readiness_drivers": readiness_drivers or None,
            "training_readiness_driver_families": (
                {
                    "autonomic_lifestyle": [
                        "sleep_score",
                        "hrv_status",
                        "sleep_history",
                        "stress_history",
                    ],
                    "load_recovery": ["acute_load", "recovery_time"],
                    "meaning": (
                        "Related explanatory families, not independent decision "
                        "weights or additional dose inputs."
                    ),
                }
                if normalized_readiness
                else None
            ),
            "recovery_time_timestamp_local": training_readiness.get(
                "observed_at_local" if normalized_readiness else "timestampLocal"
            ),
            "recovery_time_timestamp_utc": training_readiness.get(
                "observed_at" if normalized_readiness else "timestamp"
            ),
            "recovery_time_hours_at_timestamp": garmin_recovery_hours,
            "recovery_time_factor_feedback": (
                recovery_driver.get("feedback")
                if normalized_readiness
                else training_readiness.get("recoveryTimeFactorFeedback")
            ),
            "projected_recovery_time_hours_now": projected_recovery_now,
            "projected_recovery_time_hours_at_planned": project_garmin_recovery_hours(
                projected_recovery_now,
                hours_until_planned,
            ),
            "recovery_projection_assumption": (
                "Simple elapsed-time projection from the timestamped Garmin "
                "Recovery Time; assumes no intervening training."
            ),
            "acute_load": (
                (readiness_drivers.get("acute_load") or {}).get("value")
                if normalized_readiness
                else training_readiness.get("acuteLoad")
            ),
            "acwr_factor_feedback": (
                (readiness_drivers.get("acute_load") or {}).get("feedback")
                if normalized_readiness
                else training_readiness.get("acwrFactorFeedback")
            ),
            "hrv_factor_feedback": (
                (readiness_drivers.get("hrv_status") or {}).get("feedback")
                if normalized_readiness
                else training_readiness.get("hrvFactorFeedback")
            ),
            "sleep_score_factor_feedback": (
                (readiness_drivers.get("sleep_score") or {}).get("feedback")
                if normalized_readiness
                else training_readiness.get("sleepScoreFactorFeedback")
            ),
            "sleep_history_factor_feedback": (
                (readiness_drivers.get("sleep_history") or {}).get("feedback")
                if normalized_readiness
                else training_readiness.get("sleepHistoryFactorFeedback")
            ),
            "stress_history_factor_feedback": (
                (readiness_drivers.get("stress_history") or {}).get("feedback")
                if normalized_readiness
                else training_readiness.get("stressHistoryFactorFeedback")
            ),
            "training_status": training_status.get("training_status"),
            "training_status_feedback": training_status.get("feedback"),
            "training_status_since_date": training_status.get("since_date"),
            "training_status_sport": training_status.get("fitness_trend_sport")
            or training_status.get("sport"),
        },
        "garmin_vo2max": {
            **vo2max,
            "diagnostic_only": True,
            "meaning": (
                "Garmin VO2max is a modeled sport-specific fitness estimate. "
                "Use trends as context; do not use a single value as acute readiness "
                "or a direct workout-dose input."
            ),
        }
        if vo2max
        else None,
        "garmin_load_focus": {
            "meaning": (
                "Garmin's load-focus balance is a recent-load mix signal, not an acute "
                "instruction. Use it to choose the next useful stimulus only after weighing "
                "readiness, recovery time, HRV, post-activity response, Xert recovery, and "
                "the session goal."
            ),
            "feedback": training_status.get("load_balance_feedback"),
            "acwr": training_status.get("acwr"),
            "acwr_percent": training_status.get("acwr_percent"),
            "acwr_status": training_status.get("acwr_status"),
            "acute_load": training_status.get("acute_load"),
            "chronic_load": training_status.get("chronic_load"),
            "monthly_load": {
                "aerobic_low": training_status.get("monthly_load_aerobic_low"),
                "aerobic_high": training_status.get("monthly_load_aerobic_high"),
                "anaerobic": training_status.get("monthly_load_anaerobic"),
            },
            "target_ranges": {
                "aerobic_low": {
                    "min": training_status.get("monthly_load_aerobic_low_target_min"),
                    "max": training_status.get("monthly_load_aerobic_low_target_max"),
                },
                "aerobic_high": {
                    "min": training_status.get("monthly_load_aerobic_high_target_min"),
                    "max": training_status.get("monthly_load_aerobic_high_target_max"),
                },
                "anaerobic": {
                    "min": training_status.get("monthly_load_anaerobic_target_min"),
                    "max": training_status.get("monthly_load_anaerobic_target_max"),
                },
            },
        },
        "wellness": wellness,
        "post_activity_response": {
            "stress": {
                "post_activity_window": stress.get("post_activity_window"),
                "post_activity": stress.get("post_activity"),
                "post_activity_after_30min": stress.get("post_activity_after_30min"),
            },
            "heart_rate": {
                "post_activity_window": heart_rate.get("post_activity_window"),
                "post_activity": heart_rate.get("post_activity"),
                "post_activity_after_30min": heart_rate.get("post_activity_after_30min"),
                "readiness_signal": heart_rate.get("post_activity_readiness_signal"),
            },
            "interpretation_note": (
                "Use post-activity stress and rolling HR lows as inputs. If sleep follows the "
                "activity, the post-activity window ends at sleep start; after that, sleep, HRV, "
                "RHR and Body Battery are usually more relevant for morning readiness. Longer HR "
                "windows require the user to have been sitting/lying calmly."
            ),
        },
    }


ILLNESS_COMMENT_PATTERN = re.compile(
    r"(?:^|\W)(?:syk|sykdom|forkjølet|influensa|feber|sick|ill|illness|flu|fever)(?:$|\W)",
    re.IGNORECASE,
)


def intervals_wellness_context(
    day: str,
    payload: dict[str, Any] | list[Any] | None,
    *,
    lookback_days: int = 14,
    events_payload: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Normalize structured calendar events and legacy wellness annotations."""

    rows: list[Any]
    if isinstance(payload, dict):
        rows = payload.get("wellness") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    end = date.fromisoformat(day)
    start = end - timedelta(days=max(0, lookback_days - 1))
    events = []
    calendar_rows = (
        events_payload.get("events") or []
        if isinstance(events_payload, dict)
        else events_payload or []
    )
    for event in calendar_rows:
        if not isinstance(event, dict) or event.get("category") != "SICK":
            continue
        try:
            event_start = date.fromisoformat(str(event.get("start_date_local"))[:10])
            event_end = date.fromisoformat(str(event.get("end_date_local"))[:10])
        except ValueError:
            continue
        cursor = max(start, event_start)
        while cursor < min(end + timedelta(days=1), event_end):
            events.append({
                "date": cursor.isoformat(),
                "comments": event.get("description") or event.get("name"),
                "illness": True,
                "source": "calendar_event",
                "event_id": event.get("id"),
            })
            cursor += timedelta(days=1)
    current_wellness = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_day = str(row.get("id") or "")[:10]
        try:
            parsed_day = date.fromisoformat(row_day)
        except ValueError:
            continue
        if parsed_day < start or parsed_day > end:
            continue
        if row_day == day:
            current_wellness = row
        comments = str(row.get("comments") or "").strip()
        illness = bool(ILLNESS_COMMENT_PATTERN.search(comments))
        subjective = {
            key: row.get(key)
            for key in (
                "injury",
                "fatigue",
                "soreness",
                "stress",
                "mood",
                "motivation",
                "hydration",
            )
            if row.get(key) is not None
        }
        if not comments and not subjective:
            continue
        events.append(
            {
                "date": row_day,
                "comments": comments or None,
                "illness": illness,
                "source": "wellness",
                **subjective,
            }
        )
    by_date = {}
    for event in events:
        previous = by_date.get(event["date"])
        if previous is None or event.get("source") == "calendar_event":
            by_date[event["date"]] = event
    events = sorted(by_date.values(), key=lambda row: row["date"])
    current = next((row for row in events if row["date"] == day), None)
    current_day_soreness = (
        current_wellness.get("soreness") if isinstance(current_wellness, dict) else None
    )
    soreness_status_missing = current_day_soreness is None
    illness_events = [row for row in events if row.get("illness")]
    latest_illness = illness_events[-1] if illness_events else None
    days_since_latest_illness = (
        (end - date.fromisoformat(latest_illness["date"])).days
        if latest_illness is not None
        else None
    )
    illness_followup_needed = bool(
        not (current and current.get("illness")) and days_since_latest_illness == 1
    )
    return_to_training_day = (
        days_since_latest_illness
        if not (current and current.get("illness"))
        and days_since_latest_illness is not None
        and 1 <= days_since_latest_illness <= 2
        else None
    )
    return_to_training_guidance = {
        1: {
            "phase": "first_unmarked_day",
            "duration_minutes": "20-45",
            "intensity": "rest_or_very_easy_recovery",
        },
        2: {
            "phase": "return_day_2",
            "duration_minutes": "30-60",
            "intensity": "easy_endurance_only",
        },
    }.get(return_to_training_day)
    return {
        "window_start": start.isoformat(),
        "window_end": day,
        "lookback_days": lookback_days,
        "current_day": current,
        "current_day_soreness": current_day_soreness,
        "soreness_status_missing": soreness_status_missing,
        "soreness_assumed_ok_when_missing": soreness_status_missing,
        "soreness_update_requested_for_vt2_plus": soreness_status_missing,
        "soreness_update_request": (
            "Jeg antar at sårhet ikke begrenser økten; sett dagens soreness-verdi i "
            "Intervals.icu når VT2 eller hardere anbefales."
            if soreness_status_missing
            else None
        ),
        "current_day_illness": bool(current and current.get("illness")),
        "recent_events": events,
        "recent_illness_events": illness_events,
        "latest_illness_event": latest_illness,
        "days_since_latest_illness": days_since_latest_illness,
        "illness_followup_needed": illness_followup_needed,
        "return_to_training_active": return_to_training_day is not None,
        "return_to_training_day": return_to_training_day,
        "return_to_training_guidance": return_to_training_guidance,
        "followup_question": (
            "Hvordan er formen i dag: er du fortsatt syk, eller er dette første friske dag?"
            if illness_followup_needed
            else None
        ),
        "source_present": payload is not None,
        "meaning": (
            "Structured Intervals.icu calendar events and legacy wellness annotations supplement Garmin and training load. "
            "A current-day SICK event should override model readiness and block training. "
            "If yesterday was marked sick but today is unmarked, ask whether illness continues or "
            "this is the first healthy day before finalizing training. Keep the first two "
            "unmarked days on a gradual return-to-training ramp. When today's Intervals soreness "
            "is missing, assume it is non-limiting and still provide the appropriate recommendation; "
            "if recommending VT2 or harder, ask the user to set today's soreness value."
        ),
    }


def latest_activity_load_input(activity: dict[str, Any] | None) -> dict[str, Any] | None:
    if not activity:
        return None
    xert_load = activity.get("xert_load") or {}
    return {
        "name": activity.get("name"),
        "start_local": activity.get("start_local"),
        "end_local": activity.get("end_local"),
        "elapsed_minutes": activity.get("elapsed_minutes"),
        "type": activity.get("type"),
        "xert_xss": (xert_load.get("xss") or {}).get("total"),
        "xert_low_xss": (xert_load.get("xss") or {}).get("low"),
        "xert_high_xss": (xert_load.get("xss") or {}).get("high"),
        "xert_peak_xss": (xert_load.get("xss") or {}).get("peak"),
        "xert_difficulty": xert_load.get("difficulty"),
        "xert_difficulty_rating": xert_load.get("difficulty_rating"),
        "icu_training_load": (activity.get("load") or {}).get("icu_training_load"),
        "icu_intensity": (activity.get("load") or {}).get("icu_intensity"),
    }


def xert_recovery_input(xert: dict[str, Any] | None) -> dict[str, Any] | None:
    if not xert:
        return None
    return {
        "recovery_hours": xert.get("recovery_hours"),
        "projected_recovery_hours_at_planned_time": xert.get(
            "projected_recovery_hours_at_planned_time"
        ),
        "workout_capacity": xert.get("workout_capacity"),
        "training_load": xert.get("training_load"),
        "recovery_load": xert.get("recovery_load"),
    }


def xert_training_advice_input(xert: dict[str, Any] | None) -> dict[str, Any] | None:
    if not xert:
        return None
    training_advice = xert.get("training_advice") or {}
    if not isinstance(training_advice, dict):
        return None
    return {
        "source": training_advice.get("source"),
        "source_endpoint": training_advice.get("source_endpoint"),
        "source_scope": training_advice.get("source_scope"),
        "date": training_advice.get("date"),
        "training_status": training_advice.get("training_status"),
        "target_xss": training_advice.get("target_xss"),
        "remaining_xss": training_advice.get("remaining_xss"),
        "completed_xss": training_advice.get("completed_xss"),
        "original_target_xss": training_advice.get("original_target_xss"),
        "training_advice_as_of": training_advice.get("training_advice_as_of"),
        "training_advice_as_of_val": training_advice.get("training_advice_as_of_val"),
        "daily_goal_complete": training_advice.get("daily_goal_complete"),
        "recovery_needed": training_advice.get("recovery_needed"),
        "availability": training_advice.get("availability"),
        "is_availability_restricted": training_advice.get("is_availability_restricted"),
        "xss_deficit": training_advice.get("xss_deficit"),
        "xss_goal": training_advice.get("xss_goal"),
        "hours_deficit": training_advice.get("hours_deficit"),
        "activity_deficit": training_advice.get("activity_deficit"),
        "targets_source": training_advice.get("targets_source"),
        "based_on_day": training_advice.get("based_on_day"),
        "improvement_rate": training_advice.get("improvement_rate"),
        "weekly_hours": training_advice.get("weekly_hours"),
        "training_gradient": training_advice.get("training_gradient"),
        "phase": training_advice.get("phase"),
        "recommended_athlete": training_advice.get("recommended_athlete"),
        "debug": xert.get("training_advice_debug"),
        "meaning": training_advice.get("meaning"),
    }


def input_freshness(
    *,
    garmin: dict[str, Any],
    xert: dict[str, Any] | None,
    now: datetime,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    return {
        "garmin_stress_latest": freshness_from_point(
            latest_nested(garmin, "stress", "latest"),
            now=now,
            local_timezone=local_timezone,
        ),
        "garmin_heart_rate_latest": freshness_from_point(
            latest_nested(garmin, "heart_rate", "latest"),
            now=now,
            local_timezone=local_timezone,
        ),
        "garmin_body_battery_latest": freshness_from_point(
            latest_nested(garmin, "body_battery", "latest"),
            now=now,
            local_timezone=local_timezone,
        ),
        "xert_readiness_data": freshness_from_local_time(
            xert.get("source_time_local") if xert else None,
            now=now,
            local_timezone=local_timezone,
        ),
    }


def validate_garmin_wellness_signals(
    *,
    day: str,
    now: datetime,
    freshness: dict[str, Any],
    values: dict[str, Any],
    source_context: dict[str, Any],
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    """Remove Garmin values that cannot truthfully describe the target day.

    Daily signals remain usable after a complete morning sync. Continuously
    changing signals require a current-day point no more than 90 minutes old.
    Invalid signals are reported for sync guidance but never become negative
    readiness evidence.
    """

    result = dict(values)
    status: dict[str, dict[str, Any]] = {}

    hrv_date = source_context.get("hrv_observation_date")
    data_cutoff = optional_local_datetime(
        source_context.get("data_cutoff_local"),
        local_timezone=local_timezone,
    )
    hrv_observation_time = parse_garmin_utc_datetime(
        source_context.get("hrv_observation_time_utc")
    )
    hrv_valid = (
        hrv_date == day
        and positive_number(result.get("hrv_last_night_avg")) is not None
        and (
            data_cutoff is None
            or (
                hrv_observation_time is not None
                and hrv_observation_time <= data_cutoff
            )
        )
    )
    status["hrv"] = garmin_signal_status(
        valid=hrv_valid,
        reason="observed_current_day" if hrv_valid else "missing_or_wrong_day",
        observed_date=hrv_date,
    )
    if not hrv_valid:
        for key in (
            "hrv_status",
            "hrv_last_night_avg",
            "hrv_3day_mean",
            "hrv_nights_used_3d",
        ):
            result[key] = None

    sleep_date = source_context.get("sleep_calendar_date") or local_date_from_value(
        source_context.get("sleep_end_local")
    )
    sleep_seconds = positive_number(result.get("sleep_time_seconds"))
    sleep_complete = bool(
        source_context.get("sleep_start_utc")
        and source_context.get("sleep_end_utc")
    ) and sleep_seconds is not None
    sleep_end = parse_garmin_utc_datetime(source_context.get("sleep_end_utc"))
    sleep_valid = (
        sleep_date == day
        and sleep_complete
        and (
            data_cutoff is None
            or (sleep_end is not None and sleep_end <= data_cutoff)
        )
    )
    status["sleep"] = garmin_signal_status(
        valid=sleep_valid,
        reason=(
            "observed_current_day"
            if sleep_valid
            else "incomplete_sleep"
            if sleep_date == day
            else "missing_or_wrong_day"
        ),
        observed_date=sleep_date,
    )
    if not sleep_valid:
        result["sleep_score"] = None
        result["sleep_time_seconds"] = None

    rhr_date = (
        source_context.get("summary_calendar_date")
        or source_context.get("heart_rate_calendar_date")
    )
    rhr_valid = (
        rhr_date == day
        and positive_number(result.get("resting_hr")) is not None
        and (sleep_valid or hrv_valid)
    )
    status["resting_hr"] = garmin_signal_status(
        valid=rhr_valid,
        reason=(
            "observed_current_day"
            if rhr_valid
            else "morning_sync_incomplete"
            if rhr_date == day
            else "missing_or_wrong_day"
        ),
        observed_date=rhr_date,
    )
    if not rhr_valid:
        result["resting_hr"] = None

    body_battery_date = source_context.get("body_battery_calendar_date")
    wake_valid = (
        body_battery_date == day
        and positive_number(result.get("body_battery_at_wake")) is not None
        and (data_cutoff is None or sleep_valid or hrv_valid)
    )
    status["body_battery_at_wake"] = garmin_signal_status(
        valid=wake_valid,
        reason="observed_current_day" if wake_valid else "missing_or_wrong_day",
        observed_date=body_battery_date,
    )
    if not wake_valid:
        result["body_battery_at_wake"] = None

    body_freshness = freshness.get("garmin_body_battery_latest") or {}
    body_latest_date = local_date_from_value(body_freshness.get("latest_local"))
    body_current_valid = (
        body_battery_date == day
        and body_latest_date == day
        and body_freshness.get("freshness") in {"fresh", "aging"}
        and number(result.get("body_battery_most_recent")) is not None
    )
    status["body_battery_current"] = {
        **garmin_signal_status(
            valid=body_current_valid,
            reason=(
                "observed_within_90_minutes"
                if body_current_valid
                else "stale_or_wrong_day"
            ),
            observed_date=body_latest_date or body_battery_date,
        ),
        "age_minutes": body_freshness.get("age_minutes"),
        "ttl_minutes": 90,
    }
    if not body_current_valid:
        result["body_battery_most_recent"] = None
        result["body_battery_latest"] = None

    result["garmin_signal_status"] = status
    result["garmin_sync_recommended"] = any(
        not entry.get("usable_for_downgrade") for entry in status.values()
    )
    result["garmin_signal_rule"] = (
        "A Garmin signal may downgrade training only when it belongs to the "
        "target local day, is complete, and is fresh enough for its signal type. "
        "Unavailable or stale signals are excluded rather than scored negatively."
    )
    return result


def garmin_signal_status(
    *,
    valid: bool,
    reason: str,
    observed_date: str | None,
) -> dict[str, Any]:
    return {
        "usable_for_downgrade": valid,
        "status": "observed" if valid else "unavailable",
        "reason": reason,
        "observed_date": observed_date,
    }


def positive_number(value: Any) -> float | None:
    parsed = number(value)
    return parsed if parsed is not None and parsed > 0 else None


def local_date_from_value(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    return None


def freshness_from_point(
    point: dict[str, Any] | None,
    *,
    now: datetime,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    if not point or point.get("timestamp_ms") is None:
        return {"latest_local": None, "age_minutes": None, "freshness": "missing"}
    timestamp = datetime.fromtimestamp(
        point["timestamp_ms"] / 1000,
        tz=timezone.utc,
    )
    return freshness_from_datetime(
        timestamp,
        now=now,
        local_timezone=local_timezone,
    )


def freshness_from_local_time(
    raw: str | None,
    *,
    now: datetime,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    if not raw:
        return {"latest_local": None, "age_minutes": None, "freshness": "missing"}
    return freshness_from_datetime(
        parse_local_datetime(raw, local_timezone=local_timezone),
        now=now,
        local_timezone=local_timezone,
    )


def freshness_from_datetime(
    timestamp: datetime,
    *,
    now: datetime,
    local_timezone: ZoneInfo,
) -> dict[str, Any]:
    age_minutes = round((now - timestamp).total_seconds() / 60, 1)
    if age_minutes <= 30:
        freshness = "fresh"
    elif age_minutes <= 90:
        freshness = "aging"
    else:
        freshness = "stale"
    return {
        "latest_local": format_local(
            timestamp,
            local_timezone=local_timezone,
        ),
        "age_minutes": age_minutes,
        "freshness": freshness,
    }


def latest_nested(source: dict[str, Any], *keys: str) -> Any:
    value: Any = source
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def pick(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys if key in source}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_input(raw_path: str | None) -> Any:
    if not raw_path:
        return None
    return load_json(Path(raw_path))


def load_xert_input(
    raw_path: str | None,
    *,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise SystemExit(f"Xert readiness JSON must be an object: {path}")
    payload.setdefault("source_file", str(path))
    payload.setdefault(
        "source_time_local",
        format_local(
            file_modified_time(path),
            local_timezone=local_timezone,
        ),
    )
    return payload


def load_garmin_input(
    raw_path: str | None,
    *,
    local_timezone: ZoneInfo,
) -> dict[str, Any] | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise SystemExit(f"Garmin Connect JSON must be an object: {path}")
    payload.setdefault("source_file", str(path))
    payload.setdefault(
        "source_time_local",
        format_local(
            file_modified_time(path),
            local_timezone=local_timezone,
        ),
    )
    return payload


def latest_row(rows: Any) -> dict[str, Any] | None:
    if isinstance(rows, list) and rows:
        return max(
            rows,
            key=lambda item: item.get("timestamp") or "",
        )
    if isinstance(rows, dict):
        return rows
    return None


def latest_row_at_or_before(
    rows: Any,
    data_cutoff: datetime | None,
) -> dict[str, Any] | None:
    if data_cutoff is None:
        return latest_row(rows)
    if isinstance(rows, dict):
        timestamp = parse_garmin_utc_datetime(rows.get("timestamp"))
        return rows if timestamp is not None and timestamp <= data_cutoff else None
    if not isinstance(rows, list):
        return None
    eligible = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = parse_garmin_utc_datetime(row.get("timestamp"))
        if timestamp is not None and timestamp <= data_cutoff:
            eligible.append(row)
    return latest_row(eligible)


def number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def minutes(seconds: float | None) -> float | None:
    return round(seconds / 60, 1) if seconds is not None else None


def project_hours(current_hours: Any, hours_until: Any) -> float | None:
    current = number(current_hours)
    delta = number(hours_until)
    if current is None or delta is None:
        return None
    return round(current - delta, 1)


def project_garmin_recovery_hours(
    current_hours: Any,
    hours_until: Any,
) -> float | None:
    """Project Garmin Recovery Time without allowing an elapsed timer below zero."""

    projected = project_hours(current_hours, hours_until)
    return max(0.0, projected) if projected is not None else None


def hours_since_local(
    raw: Any,
    now: datetime,
    *,
    local_timezone: ZoneInfo,
) -> float | None:
    if not raw:
        return None
    return round(
        (
            now
            - parse_local_datetime(
                str(raw),
                local_timezone=local_timezone,
            )
        ).total_seconds()
        / 3600,
        1,
    )


def hours_since_garmin_timestamp(
    raw_utc: Any,
    *,
    now: datetime,
) -> float | None:
    timestamp = parse_garmin_utc_datetime(raw_utc)
    if timestamp is None:
        return None
    return round((now - timestamp).total_seconds() / 3600, 1)


def file_modified_time(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def parse_local_datetime(raw: str, *, local_timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(local_timezone)


def parse_cli_local_datetime(
    raw: str,
    *,
    default_day: str,
    local_timezone: ZoneInfo,
) -> datetime:
    """Parse CLI local datetime, accepting HH:MM as a same-day shorthand."""

    if looks_like_clock_time(raw):
        raw = f"{default_day}T{raw}"
    return parse_local_datetime(raw, local_timezone=local_timezone)


def looks_like_clock_time(raw: str) -> bool:
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        return False
    if not all(part.isdigit() for part in parts):
        return False
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    return 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59


def format_local(
    value: datetime | None,
    *,
    local_timezone: ZoneInfo,
) -> str | None:
    if value is None:
        return None
    local = value if value.tzinfo else value.replace(tzinfo=local_timezone)
    return local.astimezone(local_timezone).isoformat(timespec="seconds")


def as_utc(value: datetime, *, local_timezone: ZoneInfo) -> datetime:
    """Return one aware instant in UTC, assuming explicit local time if naive."""

    aware = value if value.tzinfo else value.replace(tzinfo=local_timezone)
    return aware.astimezone(timezone.utc)


def format_utc(
    value: datetime | None,
    *,
    local_timezone: ZoneInfo,
) -> str | None:
    if value is None:
        return None
    return as_utc(
        value,
        local_timezone=local_timezone,
    ).isoformat(timespec="seconds").replace("+00:00", "Z")


def timezone_name(value: Any) -> str:
    return getattr(value, "key", None) or str(value)


def add_seconds(
    local_iso: str,
    seconds: float | None,
    *,
    local_timezone: ZoneInfo,
) -> str | None:
    if not local_iso or seconds is None:
        return None
    start_utc = as_utc(
        parse_local_datetime(
            local_iso,
            local_timezone=local_timezone,
        ),
        local_timezone=local_timezone,
    )
    return format_local(
        start_utc + timedelta(seconds=seconds),
        local_timezone=local_timezone,
    )


def activity_timestamp_utc(
    raw_utc: Any,
    raw_local: Any,
    *,
    local_timezone: ZoneInfo,
) -> datetime | None:
    """Resolve an activity time to UTC, treating naive local values in location time."""

    timestamp = parse_garmin_utc_datetime(raw_utc)
    if timestamp is not None:
        return timestamp
    if raw_local in (None, ""):
        return None
    return as_utc(
        parse_local_datetime(
            str(raw_local),
            local_timezone=local_timezone,
        ),
        local_timezone=local_timezone,
    )


def same_local_date(left: Any, right: Any) -> bool:
    return bool(left and right and str(left)[:10] == str(right)[:10])


def local_timestamp_ms(local_iso: str, *, local_timezone: ZoneInfo) -> int:
    parsed = datetime.fromisoformat(local_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_timezone)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def datetime_timestamp_ms(value: datetime, *, local_timezone: ZoneInfo) -> int:
    local = value if value.tzinfo else value.replace(tzinfo=local_timezone)
    return int(local.astimezone(timezone.utc).timestamp() * 1000)


def optional_local_datetime(
    raw: Any,
    *,
    local_timezone: ZoneInfo,
) -> datetime | None:
    if raw in (None, ""):
        return None
    numeric = number(raw)
    if numeric is not None and not isinstance(raw, str):
        seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
        return datetime.fromtimestamp(
            seconds,
            tz=timezone.utc,
        ).astimezone(local_timezone)
    try:
        return parse_local_datetime(
            str(raw),
            local_timezone=local_timezone,
        )
    except (TypeError, ValueError):
        return None


def parse_garmin_utc_datetime(raw: Any) -> datetime | None:
    """Parse Garmin GMT/UTC fields as absolute instants."""

    if raw in (None, ""):
        return None
    numeric = number(raw)
    if numeric is not None and not isinstance(raw, str):
        seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def valid_series_values(raw_values: Any) -> list[tuple[int, float]]:
    if not isinstance(raw_values, list):
        return []
    values = []
    for row in raw_values:
        if not isinstance(row, list) or len(row) < 2:
            continue
        timestamp = int(row[0])
        value = number(row[1])
        if value is None or value < 0:
            continue
        values.append((timestamp, value))
    return values


def points_at_or_before(
    values: list[tuple[int, float]],
    cutoff_ms: int | None,
) -> list[tuple[int, float]]:
    if cutoff_ms is None:
        return values
    return [point for point in values if point[0] <= cutoff_ms]


def latest_point(values: list[tuple[int, float]]) -> dict[str, Any] | None:
    if not values:
        return None
    timestamp, value = values[-1]
    return {"timestamp_ms": timestamp, "value": value}


def timestamp_ms_to_local(
    timestamp_ms: int | None,
    *,
    local_timezone: ZoneInfo,
) -> str | None:
    if timestamp_ms is None:
        return None
    return format_local(
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc),
        local_timezone=local_timezone,
    )


def series_stats(values: list[tuple[int, float]]) -> dict[str, Any] | None:
    if not values:
        return None
    series = [value for _, value in values]
    lowest_rolling = rolling_window_extremes(values, mode="min")
    highest_rolling = rolling_window_extremes(values, mode="max")
    return {
        "count": len(series),
        "min": min(series),
        "max": max(series),
        "avg": round(sum(series) / len(series), 1),
        "lowest_rolling_avg": lowest_rolling,
        "highest_rolling_avg": highest_rolling,
        "lowest_5min_avg": lowest_rolling.get("5min"),
        "highest_5min_avg": highest_rolling.get("5min"),
        "latest": latest_point(values),
    }


def post_activity_hr_signal(values: list[tuple[int, float]]) -> dict[str, Any] | None:
    stats = series_stats(values)
    if not stats:
        return None
    return {
        "interpretation": (
            "Use these rolling lows for readiness instead of latest HR or average post-workout HR. "
            "Longer windows are only meaningful if the user was actually resting."
        ),
        "lowest_value": stats["min"],
        "lowest_rolling_avg": stats["lowest_rolling_avg"],
        "lowest_5min_avg": stats["lowest_5min_avg"],
    }


def rolling_window_extremes(
    values: list[tuple[int, float]],
    *,
    mode: str,
) -> dict[str, Any]:
    return {
        f"{minutes}min": rolling_window_extreme(values, minutes=minutes, mode=mode)
        for minutes in [5, 10, 15, 20, 30]
    }


def rolling_window_extreme(
    values: list[tuple[int, float]],
    *,
    minutes: int,
    mode: str,
) -> dict[str, Any] | None:
    if not values:
        return None
    window_ms = minutes * 60 * 1000
    minimum_span_ms = window_ms * 0.8
    best: tuple[float, int, int, int] | None = None
    start = 0
    total = 0.0
    for end, (timestamp, value) in enumerate(values):
        total += value
        while start <= end and timestamp - values[start][0] > window_ms:
            total -= values[start][1]
            start += 1
        count = end - start + 1
        if count <= 1:
            continue
        span_ms = timestamp - values[start][0]
        if span_ms < minimum_span_ms:
            continue
        avg = total / count
        if best is None:
            best = (avg, values[start][0], timestamp, count)
        elif mode == "min" and avg < best[0]:
            best = (avg, values[start][0], timestamp, count)
        elif mode == "max" and avg > best[0]:
            best = (avg, values[start][0], timestamp, count)
    if best is None:
        return None
    avg, start_ms, end_ms, count = best
    return {
        "avg": round(avg, 1),
        "start_timestamp_ms": start_ms,
        "end_timestamp_ms": end_ms,
        "count": count,
    }


def first_mapping_value(mapping: Any) -> dict[str, Any] | None:
    if not isinstance(mapping, dict):
        return None
    for value in mapping.values():
        if isinstance(value, dict):
            return value
    return None


if __name__ == "__main__":
    main()
