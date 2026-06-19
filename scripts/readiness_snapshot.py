#!/usr/bin/env python3
"""Build a compact readiness context from cached training data."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize Garmin, Intervals and provided Xert JSON for chat readiness.",
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument(
        "--now",
        help="Current local time for freshness/projection, e.g. 2026-05-20T08:15",
    )
    parser.add_argument(
        "--planned-at",
        help="Planned workout local time, e.g. 2026-05-21T10:00",
    )
    parser.add_argument(
        "--xert-json",
        help=(
            "Path to a normalized readiness-input JSON payload with selected Xert fields. "
            "The payload should contain recovery and optional activity_loads objects."
        ),
    )
    args = parser.parse_args()

    now = parse_local_datetime(args.now) if args.now else datetime.now(LOCAL_TIMEZONE)
    planned_at = parse_local_datetime(args.planned_at) if args.planned_at else None
    snapshot = build_readiness_snapshot(
        args.date,
        data_dir=Path(args.data_dir),
        now=now,
        planned_at=planned_at,
        xert_input=load_xert_input(args.xert_json),
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))


def build_readiness_snapshot(
    day: str,
    *,
    data_dir: Path = DATA_DIR,
    now: datetime | None = None,
    planned_at: datetime | None = None,
    xert_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(LOCAL_TIMEZONE)
    activity = latest_activity_on_or_before(day, data_dir=data_dir)
    xert_activity = matching_xert_activity(
        activity,
        day=day,
        xert_input=xert_input,
    )
    if activity and xert_activity:
        activity["xert_load"] = xert_activity
    garmin = garmin_snapshot(day, activity=activity, data_dir=data_dir)
    xert = latest_xert_advice(
        now=now,
        planned_at=planned_at,
        xert_input=xert_input,
    )
    freshness = cache_freshness(garmin=garmin, xert=xert, now=now)
    return {
        "date": day,
        "snapshot_time_local": format_local(now),
        "planned_workout_time_local": format_local(planned_at) if planned_at else None,
        "latest_activity": activity,
        "garmin": garmin,
        "xert": xert,
        "cache_freshness": freshness,
        "recommendation_inputs": recommendation_inputs(
            activity=activity,
            garmin=garmin,
            xert=xert,
            freshness=freshness,
            now=now,
            planned_at=planned_at,
        ),
        "notes": availability_notes(
            day,
            activity=activity,
            garmin=garmin,
            xert=xert,
            freshness=freshness,
        ),
    }


def latest_activity_on_or_before(day: str, *, data_dir: Path) -> dict[str, Any] | None:
    activities_dir = data_dir / "activities"
    if not activities_dir.exists():
        return None

    candidates = []
    for activity_dir in sorted(activities_dir.iterdir()):
        metadata_path = activity_dir / "activity.json"
        if not metadata_path.exists():
            continue
        metadata = load_json(metadata_path)
        start_local = str(metadata.get("start_date_local") or "")
        if not start_local or start_local[:10] > day:
            continue
        candidates.append((start_local, activity_dir, metadata))

    if not candidates:
        return None

    _, activity_dir, metadata = candidates[-1]
    intervals = metadata.get("icu_intervals") or []
    work_intervals = [
        interval
        for interval in intervals
        if str(interval.get("type") or "").upper() == "WORK"
    ]
    start_local = str(metadata.get("start_date_local") or "")
    elapsed_seconds = number(metadata.get("elapsed_time")) or number(metadata.get("moving_time"))
    end_local = add_seconds(start_local, elapsed_seconds)
    return {
        "id": metadata.get("id"),
        "name": metadata.get("name"),
        "activity_dir": str(activity_dir),
        "start_local": start_local,
        "end_local": end_local,
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
) -> dict[str, Any] | None:
    xert_activities = xert_activities_from_input(xert_input, day=day)
    if not xert_activities:
        return None
    if not activity or not activity.get("start_local"):
        return xert_activities[-1]

    activity_start = datetime.fromisoformat(str(activity["start_local"]))
    candidates = []
    for xert_activity in xert_activities:
        start_local = xert_activity.get("start_local")
        if not start_local:
            continue
        xert_start = datetime.fromisoformat(str(start_local))
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
        normalized = compact_xert_activity_load(payload, source_file=xert_input.get("source_file"))
        if not normalized:
            continue
        start_local = normalized.get("start_local")
        if not start_local or str(start_local)[:10] > day:
            continue
        result.append(normalized)
    return sorted(result, key=lambda item: str(item.get("start_local") or ""))


def compact_xert_activity_load(
    payload: dict[str, Any],
    *,
    source_file: str | None = None,
) -> dict[str, Any] | None:
    start_local = payload.get("start_local")
    if not start_local:
        return None
    result = {
        "source": payload.get("source") or "xert_readiness_json",
        "path": payload.get("path"),
        "name": payload.get("name"),
        "start_local": start_local,
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
    data_dir: Path,
) -> dict[str, Any]:
    summary = load_optional_json(data_dir / "garmin" / "summary" / f"{day}.json")
    hrv = load_optional_json(data_dir / "garmin" / "hrv" / f"{day}.json")
    sleep = load_optional_json(data_dir / "garmin" / "sleep" / f"{day}.json")
    stress = load_optional_json(data_dir / "garmin" / "stress" / f"{day}.json")
    heart_rate = load_optional_json(data_dir / "garmin" / "heart_rate" / f"{day}.json")
    readiness_rows = load_optional_json(
        data_dir / "garmin" / "training_readiness" / f"{day}.json",
    )
    training_status = load_optional_json(
        data_dir / "garmin" / "training_status" / f"{day}.json",
    )
    readiness = latest_row(readiness_rows)

    post_start_ms = None
    if activity and activity.get("end_local"):
        post_start_ms = local_timestamp_ms(str(activity["end_local"]))
    post_end_ms = post_activity_end_ms(post_start_ms=post_start_ms, sleep=sleep)
    stress_for_post = load_post_activity_series(
        data_dir=data_dir,
        day=day,
        current=stress,
        post_start_ms=post_start_ms,
        series_key="stressValuesArray",
        cache_subdir="stress",
    )
    heart_rate_for_post = load_post_activity_series(
        data_dir=data_dir,
        day=day,
        current=heart_rate,
        post_start_ms=post_start_ms,
        series_key="heartRateValues",
        cache_subdir="heart_rate",
    )

    return {
        "summary": compact_summary(summary),
        "hrv": compact_hrv(hrv),
        "sleep": compact_sleep(sleep),
        "training_readiness": compact_training_readiness(readiness),
        "training_status": compact_training_status(training_status),
        "stress": compact_stress(
            stress_for_post,
            post_start_ms=post_start_ms,
            post_end_ms=post_end_ms,
        ),
        "heart_rate": compact_heart_rate(
            heart_rate_for_post,
            post_start_ms=post_start_ms,
            post_end_ms=post_end_ms,
        ),
        "body_battery": compact_body_battery(
            day,
            data_dir=data_dir,
            summary=summary,
            stress=stress,
        ),
    }


def compact_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    return pick(
        summary,
        [
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
            "sleepingSeconds",
            "totalSteps",
        ],
    )


def compact_hrv(hrv: dict[str, Any] | None) -> dict[str, Any] | None:
    if not hrv:
        return None
    summary = hrv.get("hrvSummary") or {}
    return {
        "status": summary.get("status"),
        "lastNightAvg": summary.get("lastNightAvg"),
        "weeklyAvg": summary.get("weeklyAvg"),
        "baseline": summary.get("baseline"),
    }


def compact_sleep(sleep: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sleep:
        return None
    daily = sleep.get("dailySleepDTO") if isinstance(sleep, dict) else None
    source = daily if isinstance(daily, dict) else sleep
    return pick(
        source,
        [
            "calendarDate",
            "sleepStartTimestampLocal",
            "sleepEndTimestampLocal",
            "sleepTimeSeconds",
            "sleepScore",
            "sleepScores",
            "measurableSleepSeconds",
        ],
    )


def compact_training_readiness(readiness: dict[str, Any] | None) -> dict[str, Any] | None:
    if not readiness:
        return None
    result = pick(
        readiness,
        [
            "score",
            "level",
            "feedbackShort",
            "feedbackLong",
            "inputContext",
            "timestampLocal",
            "recoveryTime",
            "recoveryTimeFactorFeedback",
            "hrvFactorFeedback",
            "sleepScore",
            "sleepScoreFactorFeedback",
            "stressHistoryFactorFeedback",
            "acuteLoad",
            "acwrFactorFeedback",
        ],
    )
    recovery_time_minutes = number(result.get("recoveryTime"))
    if recovery_time_minutes is not None:
        result["recovery_time_minutes"] = recovery_time_minutes
        result["recovery_time_hours"] = round(recovery_time_minutes / 60, 1)
    return result


def compact_training_status(status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not status:
        return None
    latest_status = (
        (status.get("mostRecentTrainingStatus") or {})
        .get("latestTrainingStatusData", {})
    )
    latest_device_status = first_mapping_value(latest_status)
    load_balance = (
        (status.get("mostRecentTrainingLoadBalance") or {})
        .get("metricsTrainingLoadBalanceDTOMap", {})
    )
    latest_load_balance = first_mapping_value(load_balance)
    vo2max = status.get("mostRecentVO2Max") or {}
    return {
        "training_status": latest_device_status.get("trainingStatus")
        if latest_device_status
        else None,
        "feedback": latest_device_status.get("trainingStatusFeedbackPhrase")
        if latest_device_status
        else None,
        "fitness_trend": latest_device_status.get("fitnessTrend")
        if latest_device_status
        else None,
        "sport": latest_device_status.get("sport") if latest_device_status else None,
        "acute_load": (
            latest_device_status.get("acuteTrainingLoadDTO", {}).get("dailyTrainingLoadAcute")
            if latest_device_status
            else None
        ),
        "chronic_load": (
            latest_device_status.get("acuteTrainingLoadDTO", {}).get("dailyTrainingLoadChronic")
            if latest_device_status
            else None
        ),
        "acwr_status": (
            latest_device_status.get("acuteTrainingLoadDTO", {}).get("acwrStatus")
            if latest_device_status
            else None
        ),
        "monthly_load_aerobic_low": latest_load_balance.get("monthlyLoadAerobicLow")
        if latest_load_balance
        else None,
        "monthly_load_aerobic_high": latest_load_balance.get("monthlyLoadAerobicHigh")
        if latest_load_balance
        else None,
        "monthly_load_anaerobic": latest_load_balance.get("monthlyLoadAnaerobic")
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
) -> dict[str, Any] | None:
    if not stress:
        return None
    values = valid_series_values(stress.get("stressValuesArray"))
    result = pick(stress, ["avgStressLevel", "maxStressLevel"])
    result["latest"] = latest_point(values)
    if post_start_ms is not None:
        post = points_in_window(values, start_ms=post_start_ms, end_ms=post_end_ms)
        post_30 = points_in_window(
            values,
            start_ms=post_start_ms + 30 * 60 * 1000,
            end_ms=post_end_ms,
        )
        result["post_activity_window"] = post_activity_window(post_start_ms, post_end_ms)
        result["post_activity"] = series_stats(post)
        result["post_activity_after_30min"] = series_stats(post_30)
    return result


def compact_heart_rate(
    heart_rate: dict[str, Any] | None,
    *,
    post_start_ms: int | None,
    post_end_ms: int | None,
) -> dict[str, Any] | None:
    if not heart_rate:
        return None
    values = valid_series_values(heart_rate.get("heartRateValues"))
    result = pick(
        heart_rate,
        [
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
        result["post_activity_window"] = post_activity_window(post_start_ms, post_end_ms)
        result["post_activity"] = series_stats(post)
        result["post_activity_after_30min"] = series_stats(post_30)
        result["post_activity_readiness_signal"] = post_activity_hr_signal(post_30 or post)
    return result


def compact_body_battery(
    day: str,
    *,
    data_dir: Path,
    summary: dict[str, Any] | None,
    stress: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = compact_body_battery_from_daily_cache(summary=summary, stress=stress)
    if result:
        return result

    body_battery_dir = data_dir / "garmin" / "body_battery"
    if not body_battery_dir.exists():
        return None
    candidates = sorted(body_battery_dir.glob(f"*{day}*.json"))
    if not candidates:
        return None
    payload_path, payload, day_payload = latest_body_battery_payload(candidates)
    if not isinstance(day_payload, dict):
        return None
    values = valid_series_values(day_payload.get("bodyBatteryValuesArray"))
    return {
        "source_file": str(payload_path),
        "charged": day_payload.get("charged"),
        "drained": day_payload.get("drained"),
        "latest": latest_point(values),
        "events": day_payload.get("bodyBatteryActivityEvent"),
        "dynamic_feedback": day_payload.get("bodyBatteryDynamicFeedbackEvent"),
    }


def compact_body_battery_from_daily_cache(
    *,
    summary: dict[str, Any] | None,
    stress: dict[str, Any] | None,
) -> dict[str, Any] | None:
    values = body_battery_series_values(
        (stress or {}).get("bodyBatteryValuesArray") if stress else None,
    )
    latest = latest_point(values)
    most_recent = (summary or {}).get("bodyBatteryMostRecentValue") if summary else None
    if not latest and most_recent is None:
        return None

    return {
        "source_file": "daily Garmin summary/stress cache",
        "at_wake": (summary or {}).get("bodyBatteryAtWakeTime") if summary else None,
        "charged": (summary or {}).get("bodyBatteryChargedValue") if summary else None,
        "drained": (summary or {}).get("bodyBatteryDrainedValue") if summary else None,
        "most_recent": most_recent,
        "latest": latest or {"timestamp_ms": None, "value": number(most_recent)},
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
    raw = daily.get("sleepStartTimestampGMT") or daily.get("sleepStartTimestampLocal")
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


def post_activity_window(start_ms: int, end_ms: int | None) -> dict[str, Any]:
    return {
        "start_local": timestamp_ms_to_local(start_ms),
        "end_local": timestamp_ms_to_local(end_ms) if end_ms is not None else None,
        "end_reason": "sleep_start" if end_ms is not None else "open_until_latest_cache",
    }


def latest_body_battery_payload(paths: list[Path]) -> tuple[Path, Any, dict[str, Any] | None]:
    best_path = paths[-1]
    best_payload = load_json(best_path)
    best_day_payload = body_battery_day_payload(best_payload)
    best_timestamp = latest_body_battery_timestamp(best_day_payload)
    for path in paths:
        payload = load_json(path)
        day_payload = body_battery_day_payload(payload)
        timestamp = latest_body_battery_timestamp(day_payload)
        if timestamp > best_timestamp:
            best_path = path
            best_payload = payload
            best_day_payload = day_payload
            best_timestamp = timestamp
    return best_path, best_payload, best_day_payload


def body_battery_day_payload(payload: Any) -> dict[str, Any] | None:
    day_payload = payload[-1] if isinstance(payload, list) and payload else payload
    if not isinstance(day_payload, dict):
        return None
    return day_payload


def latest_body_battery_timestamp(day_payload: dict[str, Any] | None) -> int:
    if not day_payload:
        return 0
    values = valid_series_values(day_payload.get("bodyBatteryValuesArray"))
    return values[-1][0] if values else 0


def latest_xert_advice(
    *,
    now: datetime,
    planned_at: datetime | None,
    xert_input: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not xert_input:
        return None
    recovery = xert_input.get("recovery")
    if not isinstance(recovery, dict):
        return None
    return compact_xert_recovery(
        recovery,
        now=now,
        planned_at=planned_at,
        source_time_local=xert_input.get("source_time_local"),
        source_file=xert_input.get("source_file"),
    )


def compact_xert_recovery(
    recovery: dict[str, Any],
    *,
    now: datetime,
    planned_at: datetime | None,
    source_time_local: Any,
    source_file: str | None,
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
        "source_time_local": format_local(parse_local_datetime(str(source_time_local)))
        if source_time_local
        else None,
        "training_status": recovery.get("training_status"),
        "target_xss": recovery.get("target_xss"),
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
            "low": project_hours(recovery_hours.get("low"), hours_until_planned),
            "high": project_hours(recovery_hours.get("high"), hours_until_planned),
            "peak": project_hours(recovery_hours.get("peak"), hours_until_planned),
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
) -> list[str]:
    notes = []
    if not activity:
        notes.append("No cached Intervals activity found on or before this date.")
    for key, value in garmin.items():
        if value is None:
            notes.append(f"Missing Garmin {key} cache for {day}.")
    if xert is None:
        notes.append("No Xert recovery JSON input provided.")
    stale = [
        key
        for key, value in freshness.items()
        if isinstance(value, dict) and value.get("freshness") == "stale"
    ]
    if stale:
        notes.append(
            "Potentially stale time-series cache: "
            + ", ".join(stale)
            + ". Refresh the affected input before relying on a now-decision."
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
) -> dict[str, Any]:
    """Collect decision inputs without making a training recommendation."""

    training_readiness = garmin.get("training_readiness") or {}
    heart_rate = garmin.get("heart_rate") or {}
    stress = garmin.get("stress") or {}
    body_battery = garmin.get("body_battery") or {}
    summary = garmin.get("summary") or {}
    hrv = garmin.get("hrv") or {}
    sleep = garmin.get("sleep") or {}

    readiness_age_hours = hours_since_local(training_readiness.get("timestampLocal"), now)
    garmin_recovery_hours = training_readiness.get("recovery_time_hours")
    return {
        "purpose": (
            "Input summary only. Use this to make the chat recommendation; "
            "the script intentionally does not conclude whether to train."
        ),
        "time_context": {
            "now_local": format_local(now),
            "planned_workout_time_local": format_local(planned_at) if planned_at else None,
            "hours_until_planned": (
                round((planned_at - now).total_seconds() / 3600, 1)
                if planned_at is not None
                else None
            ),
        },
        "cache_freshness": freshness,
        "latest_activity_load": latest_activity_load_input(activity),
        "xert_recovery": xert_recovery_input(xert),
        "garmin_recovery_readiness": {
            "training_readiness_score": training_readiness.get("score"),
            "training_readiness_level": training_readiness.get("level"),
            "recovery_time_timestamp_local": training_readiness.get("timestampLocal"),
            "recovery_time_hours_at_timestamp": garmin_recovery_hours,
            "projected_recovery_time_hours_now": project_hours(
                garmin_recovery_hours,
                readiness_age_hours,
            ),
            "projected_recovery_time_hours_at_planned": project_hours(
                project_hours(garmin_recovery_hours, readiness_age_hours),
                (
                    round((planned_at - now).total_seconds() / 3600, 1)
                    if planned_at is not None
                    else None
                ),
            ),
            "acute_load": training_readiness.get("acuteLoad"),
            "training_status": (garmin.get("training_status") or {}).get("training_status"),
            "training_status_feedback": (garmin.get("training_status") or {}).get("feedback"),
        },
        "wellness": {
            "hrv_status": hrv.get("status"),
            "hrv_last_night_avg": hrv.get("lastNightAvg"),
            "hrv_weekly_avg": hrv.get("weeklyAvg"),
            "resting_hr": summary.get("restingHeartRate") or heart_rate.get("restingHeartRate"),
            "resting_hr_7day": summary.get("lastSevenDaysAvgRestingHeartRate")
            or heart_rate.get("lastSevenDaysAvgRestingHeartRate"),
            "sleep_score": sleep.get("sleepScore") or training_readiness.get("sleepScore"),
            "sleep_time_seconds": sleep.get("sleepTimeSeconds") or summary.get("sleepingSeconds"),
            "body_battery_at_wake": body_battery.get("at_wake"),
            "body_battery_most_recent": body_battery.get("most_recent"),
            "body_battery_latest": body_battery.get("latest"),
        },
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
        "training_status": xert.get("training_status"),
        "recovery_hours": xert.get("recovery_hours"),
        "projected_recovery_hours_at_planned_time": xert.get(
            "projected_recovery_hours_at_planned_time"
        ),
        "workout_capacity": xert.get("workout_capacity"),
        "training_load": xert.get("training_load"),
        "recovery_load": xert.get("recovery_load"),
    }


def cache_freshness(
    *,
    garmin: dict[str, Any],
    xert: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    return {
        "garmin_stress_latest": freshness_from_point(
            latest_nested(garmin, "stress", "latest"),
            now=now,
        ),
        "garmin_heart_rate_latest": freshness_from_point(
            latest_nested(garmin, "heart_rate", "latest"),
            now=now,
        ),
        "garmin_body_battery_latest": freshness_from_point(
            latest_nested(garmin, "body_battery", "latest"),
            now=now,
        ),
        "xert_recovery_data": freshness_from_local_time(
            xert.get("source_time_local") if xert else None,
            now=now,
        ),
    }


def freshness_from_point(point: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    if not point or point.get("timestamp_ms") is None:
        return {"latest_local": None, "age_minutes": None, "freshness": "missing"}
    timestamp = datetime.fromtimestamp(point["timestamp_ms"] / 1000, tz=timezone.utc).astimezone(
        LOCAL_TIMEZONE
    )
    return freshness_from_datetime(timestamp, now=now)


def freshness_from_local_time(raw: str | None, *, now: datetime) -> dict[str, Any]:
    if not raw:
        return {"latest_local": None, "age_minutes": None, "freshness": "missing"}
    return freshness_from_datetime(parse_local_datetime(raw), now=now)


def freshness_from_datetime(timestamp: datetime, *, now: datetime) -> dict[str, Any]:
    age_minutes = round((now - timestamp).total_seconds() / 60, 1)
    if age_minutes <= 30:
        freshness = "fresh"
    elif age_minutes <= 90:
        freshness = "aging"
    else:
        freshness = "stale"
    return {
        "latest_local": format_local(timestamp),
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


def load_xert_input(raw_path: str | None) -> dict[str, Any] | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise SystemExit(f"Xert readiness JSON must be an object: {path}")
    payload.setdefault("source_file", str(path))
    payload.setdefault("source_time_local", format_local(cache_file_time(path)))
    return payload


def load_optional_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return load_json(path)


def load_post_activity_series(
    *,
    data_dir: Path,
    day: str,
    current: Any,
    post_start_ms: int | None,
    series_key: str,
    cache_subdir: str,
) -> Any:
    if post_start_ms is None or not isinstance(current, dict):
        return current

    post_start_day = timestamp_ms_to_local(post_start_ms)
    if not post_start_day:
        return current
    post_start_date = post_start_day[:10]
    if post_start_date >= day:
        return current

    previous = load_optional_json(data_dir / "garmin" / cache_subdir / f"{post_start_date}.json")
    if not isinstance(previous, dict):
        return current

    merged = dict(current)
    merged_values = []
    for payload in [previous, current]:
        values = payload.get(series_key) if isinstance(payload, dict) else None
        if isinstance(values, list):
            merged_values.extend(values)
    merged[series_key] = sorted(
        merged_values,
        key=lambda row: row[0] if isinstance(row, list) and row else 0,
    )
    merged["post_activity_series_sources"] = [
        f"data/garmin/{cache_subdir}/{post_start_date}.json",
        f"data/garmin/{cache_subdir}/{day}.json",
    ]
    return merged


def latest_row(rows: Any) -> dict[str, Any] | None:
    if isinstance(rows, list) and rows:
        return max(rows, key=lambda item: item.get("timestampLocal") or "")
    if isinstance(rows, dict):
        return rows
    return None


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


def hours_since_local(raw: Any, now: datetime) -> float | None:
    if not raw:
        return None
    return round((now - parse_local_datetime(str(raw))).total_seconds() / 3600, 1)


def cache_file_time(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=LOCAL_TIMEZONE)


def parse_local_datetime(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def format_local(value: datetime | None) -> str | None:
    if value is None:
        return None
    local = value if value.tzinfo else value.replace(tzinfo=LOCAL_TIMEZONE)
    return local.astimezone(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def add_seconds(local_iso: str, seconds: float | None) -> str | None:
    if not local_iso or seconds is None:
        return None
    return (datetime.fromisoformat(local_iso) + timedelta(seconds=seconds)).isoformat()


def same_local_date(left: Any, right: Any) -> bool:
    return bool(left and right and str(left)[:10] == str(right)[:10])


def local_timestamp_ms(local_iso: str) -> int:
    parsed = datetime.fromisoformat(local_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


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


def latest_point(values: list[tuple[int, float]]) -> dict[str, Any] | None:
    if not values:
        return None
    timestamp, value = values[-1]
    return {"timestamp_ms": timestamp, "value": value}


def timestamp_ms_to_local(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return format_local(
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone(
            LOCAL_TIMEZONE
        )
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
