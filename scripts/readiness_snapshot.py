#!/usr/bin/env python3
"""Build a compact readiness context from cached training data."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DATA_DIR = Path("data")
LOCAL_TIMEZONE = ZoneInfo("Europe/Oslo")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize cached Garmin, Xert and Intervals data for chat readiness.",
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    args = parser.parse_args()

    snapshot = build_readiness_snapshot(args.date, data_dir=Path(args.data_dir))
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))


def build_readiness_snapshot(day: str, *, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    activity = latest_activity_on_or_before(day, data_dir=data_dir)
    xert_activity = latest_xert_activity_on_or_before(day, data_dir=data_dir)
    if activity and xert_activity and same_local_date(activity.get("start_local"), xert_activity.get("start_local")):
        activity["xert_load"] = xert_activity
    garmin = garmin_snapshot(day, activity=activity, data_dir=data_dir)
    return {
        "date": day,
        "latest_activity": activity,
        "garmin": garmin,
        "xert": latest_xert_advice(data_dir=data_dir),
        "notes": availability_notes(day, activity=activity, garmin=garmin, data_dir=data_dir),
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


def latest_xert_activity_on_or_before(day: str, *, data_dir: Path) -> dict[str, Any] | None:
    xert_activities_dir = data_dir / "xert" / "activities"
    if not xert_activities_dir.exists():
        return None

    candidates = []
    for activity_dir in sorted(xert_activities_dir.iterdir()):
        metadata_path = activity_dir / "activity.json"
        if not metadata_path.exists():
            continue
        payload = load_json(metadata_path)
        summary = payload.get("summary") or {}
        start_local = xert_start_local(summary)
        if not start_local or start_local[:10] > day:
            continue
        candidates.append((start_local, activity_dir, payload, summary))

    if not candidates:
        return None

    _, activity_dir, payload, summary = candidates[-1]
    progression = summary.get("progression") or {}
    xss = progression.get("xss") or {}
    session = summary.get("session") or {}
    start_local = xert_start_local(summary)
    duration = number(summary.get("duration") or session.get("total_elapsed_time"))
    return {
        "source_file": str(activity_dir / "activity.json"),
        "name": payload.get("name") or summary.get("name"),
        "start_local": start_local,
        "elapsed_minutes": minutes(duration),
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

    return {
        "summary": compact_summary(summary),
        "hrv": compact_hrv(hrv),
        "sleep": compact_sleep(sleep),
        "training_readiness": compact_training_readiness(readiness),
        "training_status": compact_training_status(training_status),
        "stress": compact_stress(stress, post_start_ms=post_start_ms),
        "heart_rate": compact_heart_rate(heart_rate, post_start_ms=post_start_ms),
        "body_battery": compact_body_battery(day, data_dir=data_dir),
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
    return pick(
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


def compact_training_status(status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not status:
        return None
    latest_status = (
        status.get("mostRecentTrainingStatus", {})
        .get("latestTrainingStatusData", {})
    )
    latest_device_status = first_mapping_value(latest_status)
    load_balance = (
        status.get("mostRecentTrainingLoadBalance", {})
        .get("metricsTrainingLoadBalanceDTOMap", {})
    )
    latest_load_balance = first_mapping_value(load_balance)
    vo2max = status.get("mostRecentVO2Max", {})
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
) -> dict[str, Any] | None:
    if not stress:
        return None
    values = valid_series_values(stress.get("stressValuesArray"))
    result = pick(stress, ["avgStressLevel", "maxStressLevel"])
    result["latest"] = latest_point(values)
    if post_start_ms is not None:
        post = [point for point in values if point[0] >= post_start_ms]
        post_30 = [point for point in values if point[0] >= post_start_ms + 30 * 60 * 1000]
        result["post_activity"] = series_stats(post)
        result["post_activity_after_30min"] = series_stats(post_30)
    return result


def compact_heart_rate(
    heart_rate: dict[str, Any] | None,
    *,
    post_start_ms: int | None,
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
        post = [point for point in values if point[0] >= post_start_ms]
        post_30 = [point for point in values if point[0] >= post_start_ms + 30 * 60 * 1000]
        result["post_activity"] = series_stats(post)
        result["post_activity_after_30min"] = series_stats(post_30)
    return result


def compact_body_battery(day: str, *, data_dir: Path) -> dict[str, Any] | None:
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


def latest_xert_advice(*, data_dir: Path) -> dict[str, Any] | None:
    xert_dir = data_dir / "xert"
    if not xert_dir.exists():
        return None
    candidates = sorted(xert_dir.glob("training_advice_*.json"))
    if not candidates:
        return None
    advice = load_json(candidates[-1])
    return {
        "source_file": str(candidates[-1]),
        "training_status": advice.get("training_status"),
        "focus": advice.get("x_focusName"),
        "targetXSS": advice.get("targetXSS"),
        "completed_xss": advice.get("x_completed_xss"),
        "placeholder_xss": advice.get("x_placeholder_xss"),
        "recovery_days": {
            "low": advice.get("recovery_days_lo"),
            "high": advice.get("recovery_days_hi"),
            "peak": advice.get("recovery_days_pk"),
        },
        "recovery_hours": {
            "meaning": (
                "Positive hours are Xert's recommended wait before more load "
                "in each system: low = any activity that generates low XSS, "
                "high = work over TP that generates high XSS, peak = work over "
                "TP with special relevance to peak-power/peak-XSS work."
            ),
            "low": hours(advice.get("recovery_days_lo")),
            "high": hours(advice.get("recovery_days_hi")),
            "peak": hours(advice.get("recovery_days_pk")),
        },
        "workout_capacity": {
            "meaning": (
                "Training that can be done now while still being just fresh before "
                "the next planned Xert workout."
            ),
            "low": advice.get("workout_capacity_xlss"),
            "high": advice.get("workout_capacity_xhss"),
            "peak": advice.get("workout_capacity_xpss"),
        },
        "training_load": {
            "low": advice.get("trainingload_xlss"),
            "high": advice.get("trainingload_xhss"),
            "peak": advice.get("trainingload_xpss"),
        },
        "recovery_load": {
            "low": advice.get("recoveryload_xlss"),
            "high": advice.get("recoveryload_xhss"),
            "peak": advice.get("recoveryload_xpss"),
        },
    }


def availability_notes(
    day: str,
    *,
    activity: dict[str, Any] | None,
    garmin: dict[str, Any],
    data_dir: Path,
) -> list[str]:
    notes = []
    if not activity:
        notes.append("No cached Intervals activity found on or before this date.")
    for key, value in garmin.items():
        if value is None:
            notes.append(f"Missing Garmin {key} cache for {day}.")
    if not (data_dir / "xert").exists():
        notes.append("No cached Xert directory found.")
    return notes


def pick(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys if key in source}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return load_json(path)


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


def hours(days: Any) -> float | None:
    value = number(days)
    return round(value * 24, 1) if value is not None else None


def add_seconds(local_iso: str, seconds: float | None) -> str | None:
    if not local_iso or seconds is None:
        return None
    return (datetime.fromisoformat(local_iso) + timedelta(seconds=seconds)).isoformat()


def same_local_date(left: Any, right: Any) -> bool:
    return bool(left and right and str(left)[:10] == str(right)[:10])


def xert_start_local(summary: dict[str, Any]) -> str | None:
    start = summary.get("start_date")
    if isinstance(start, dict):
        raw = start.get("date")
        if raw:
            parsed = datetime.fromisoformat(str(raw))
            timezone_name = start.get("timezone")
            if timezone_name == "UTC":
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


def series_stats(values: list[tuple[int, float]]) -> dict[str, Any] | None:
    if not values:
        return None
    series = [value for _, value in values]
    return {
        "count": len(series),
        "min": min(series),
        "max": max(series),
        "avg": round(sum(series) / len(series), 1),
        "latest": latest_point(values),
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
