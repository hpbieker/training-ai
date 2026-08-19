"""Garmin Connect live helpers backed by gccli.

Garmin Connect does not expose a simple public personal API, so this module
uses the local ``gccli`` command as the transport boundary. Credentials remain
managed by ``gccli auth login`` and the local keyring.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_GCCLI = "/opt/homebrew/bin/gccli"
GARMIN_ACTIVITY_DETAILS_MAX_POINTS = 2000
GARMIN_CONNECT_API = "https://connectapi.garmin.com"
GARMIN_MOBILE_USER_AGENT = "com.garmin.android.apps.connectmobile"
COURSE_SAVE_FIELDS = {
    "activityTypePk", "boundingBox", "coordinateSystem", "courseLines",
    "courseName", "coursePoints", "coursePrivacy", "distanceMeter",
    "elapsedSeconds", "elevationGainMeter", "elevationLossMeter", "favorite",
    "geoPoints", "hasPaceBand", "hasPowerGuide", "hasTurnDetectionDisabled",
    "includeLaps", "matchedToSegments", "openStreetMap", "rulePK",
    "sourceTypeId", "speedMeterPerSecond", "startPoint", "userProfilePk",
}
DAILY_SPEC_CHOICES = [
    "body-battery",
    "heart-rate",
    "hrv",
    "sleep",
    "stress",
    "summary",
    "training-readiness",
    "training-status",
]
DAILY_PROFILE_SPECS = {
    "full": DAILY_SPEC_CHOICES,
    "readiness": [
        "heart-rate",
        "hrv",
        "sleep",
        "stress",
        "summary",
        "training-readiness",
        "training-status",
    ],
}


def resolve_gccli() -> str:
    """Return the preferred gccli executable path."""

    if Path(DEFAULT_GCCLI).exists():
        return DEFAULT_GCCLI
    resolved = shutil.which("gccli")
    if resolved:
        return resolved
    raise SystemExit("gccli not found. Install it and run `gccli auth login` first.")


def fetch_day(
    day: str,
    *,
    gccli: str,
    only: Iterable[str] | None = None,
    profile: str = "full",
    tolerate_errors: bool = False,
) -> dict[str, Any]:
    """Fetch useful Garmin daily health endpoints for one date."""

    specs = daily_specs(day)
    wanted = {daily_spec_key(name) for name in DAILY_PROFILE_SPECS[profile]}
    if only:
        wanted &= {daily_spec_key(name) for name in only}
    specs = {name: command for name, command in specs.items() if name in wanted}
    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "date": day,
        "sources": {
            name: run_gccli_json(gccli, command, tolerate_errors=tolerate_errors)
            for name, command in specs.items()
        },
    }


def fetch_recent_days(
    *,
    days: int,
    until: str,
    gccli: str,
    only: Iterable[str] | None = None,
    profile: str = "full",
    tolerate_errors: bool = False,
) -> dict[str, Any]:
    """Fetch daily Garmin health data for a recent date window."""

    until_date = date.fromisoformat(until)
    start_date = until_date - timedelta(days=days - 1)
    result = {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "start_date": start_date.isoformat(),
        "end_date": until_date.isoformat(),
        "days": [
            fetch_day(
                (until_date - timedelta(days=offset)).isoformat(),
                gccli=gccli,
                only=only,
                profile=profile,
                tolerate_errors=tolerate_errors,
            )
            for offset in range(days - 1, -1, -1)
        ],
    }
    requested = (
        {daily_spec_key(name) for name in only}
        if only
        else {daily_spec_key(name) for name in DAILY_PROFILE_SPECS[profile]}
    )
    if "body_battery" in requested:
        result["body_battery_range"] = fetch_body_battery_range(
            start_date.isoformat(),
            until_date.isoformat(),
            gccli=gccli,
        )
    return result


def daily_specs(day: str) -> dict[str, list[str]]:
    return {
        "body_battery": ["health", "body-battery", "range", "--start", day, "--end", day],
        "training_readiness": ["health", "training-readiness", day],
        "stress": ["health", "stress", "view", day],
        "heart_rate": ["health", "hr", day],
        "hrv": ["health", "hrv", day],
        "sleep": ["health", "sleep", day],
        "summary": ["health", "summary", day],
        "training_status": ["health", "training-status", day],
    }


def daily_spec_key(name: str) -> str:
    return name.replace("-", "_")


def compact_day_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Garmin readiness and VO2max without leaking raw payload shape."""

    sources = payload.get("sources") if isinstance(payload, dict) else None
    sources = sources if isinstance(sources, dict) else {}
    result = {
        "source": payload.get("source"),
        "source_time_local": payload.get("source_time_local"),
        "date": payload.get("date"),
        "training_readiness": compact_daily_training_readiness(
            sources.get("training_readiness")
        ),
        "training_readiness_observations": compact_training_readiness_observations(
            sources.get("training_readiness")
        ),
        "vo2max": compact_daily_vo2max(
            sources.get("training_status"), requested_date=payload.get("date")
        ),
        "training_status_context": compact_daily_training_status_context(
            sources.get("training_status")
        ),
        "sources": compact_daily_source_summaries(sources),
    }
    errors = {
        key: value
        for key, value in sources.items()
        if isinstance(value, dict) and value.get("error")
    }
    if errors:
        result["source_errors"] = errors
    return result


def compact_daily_source_summaries(sources: dict[str, Any]) -> dict[str, Any]:
    """Return useful daily scalars without embedding Garmin's raw time series."""

    fields = {
        "heart_rate": (
            "calendarDate", "startTimestampGMT", "endTimestampGMT",
            "startTimestampLocal", "endTimestampLocal", "maxHeartRate",
            "minHeartRate", "restingHeartRate", "lastSevenDaysAvgRestingHeartRate",
        ),
        "hrv": (
            "calendarDate", "lastNightAvg", "lastNight5MinHigh", "weeklyAvg",
            "status", "baselineLowUpper", "baselineBalancedLow",
            "baselineBalancedUpper", "feedbackPhrase", "createTimeStamp",
            "endTimestampGMT", "endTimestampLocal",
        ),
        "sleep": (
            "calendarDate", "sleepTimeSeconds", "napTimeSeconds",
            "sleepStartTimestampGMT", "sleepEndTimestampGMT",
            "sleepStartTimestampLocal", "sleepEndTimestampLocal",
            "averageSpO2Value", "lowestSpO2Value", "averageRespirationValue",
            "lowestRespirationValue", "highestRespirationValue",
        ),
        "stress": (
            "calendarDate", "startTimestampGMT", "endTimestampGMT",
            "startTimestampLocal", "endTimestampLocal", "maxStressLevel",
            "avgStressLevel",
        ),
        "summary": (
            "calendarDate", "totalSteps", "dailyStepGoal", "totalDistanceMeters",
            "activeKilocalories", "bmrKilocalories", "restingHeartRate",
            "minHeartRate", "maxHeartRate", "averageStressLevel",
            "maxStressLevel", "stressDuration", "restStressDuration",
            "lowStressDuration", "mediumStressDuration", "highStressDuration",
        ),
        "training_status": (
            "calendarDate", "timestamp", "timestampLocal", "trainingStatus",
            "trainingStatusFeedbackPhrase", "acuteTrainingLoad",
            "acuteTrainingLoadStatus", "loadRatio", "loadRatioStatus",
        ),
        "body_battery": (
            "calendarDate", "startTimestampGMT", "endTimestampGMT",
            "startTimestampLocal", "endTimestampLocal", "charged", "drained",
            "highestValue", "lowestValue",
        ),
    }
    summaries: dict[str, Any] = {}
    for source, payload in sources.items():
        if source == "training_readiness":
            continue
        if isinstance(payload, dict) and payload.get("error"):
            summaries[source] = {"error": payload.get("error")}
            continue
        row = _first_source_row(payload)
        if row is None:
            summaries[source] = None
            continue
        summary = {key: row[key] for key in fields.get(source, ()) if key in row}
        if source == "sleep":
            score = _nested_value(row, "sleepScores", "overall", "value")
            if score is not None:
                summary["sleep_score"] = score
        if source == "stress":
            battery = _body_battery_series_summary(row)
            if battery:
                summary["body_battery"] = battery
        summaries[source] = summary
    return summaries


def _first_source_row(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return next((row for row in payload if isinstance(row, dict)), None)
    return None


def _nested_value(payload: dict[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _body_battery_series_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    descriptors = {
        row.get("bodyBatteryValueDescriptorKey"): row.get("bodyBatteryValueDescriptorIndex")
        for row in payload.get("bodyBatteryValueDescriptorsDTOList") or []
        if isinstance(row, dict)
    }
    timestamp_index = descriptors.get("timestamp")
    level_index = descriptors.get("bodyBatteryLevel")
    if not isinstance(timestamp_index, int) or not isinstance(level_index, int):
        return None
    points = []
    for row in payload.get("bodyBatteryValuesArray") or []:
        if not isinstance(row, list) or max(timestamp_index, level_index) >= len(row):
            continue
        timestamp, level = row[timestamp_index], row[level_index]
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            points.append((timestamp, level))
    if not points:
        return None
    return {
        "point_count": len(points),
        "first": {"timestamp_ms": points[0][0], "value": points[0][1]},
        "last": {"timestamp_ms": points[-1][0], "value": points[-1][1]},
        "minimum": min(level for _, level in points),
        "maximum": max(level for _, level in points),
    }


def compact_recent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize every day in a Garmin recent-days response."""

    return {
        "source": payload.get("source"),
        "source_time_local": payload.get("source_time_local"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "days": [
            compact_day_payload(day)
            for day in payload.get("days") or []
            if isinstance(day, dict)
        ],
    }


def compact_daily_training_readiness(payload: Any) -> dict[str, Any] | None:
    """Return the latest Garmin Training Readiness row with all six drivers."""

    rows = payload if isinstance(payload, list) else [payload]
    rows = [row for row in rows if isinstance(row, dict) and not row.get("error")]
    if not rows:
        return None
    row = max(
        rows,
        key=lambda item: str(item.get("timestampLocal") or item.get("timestamp") or ""),
    )
    return compact_training_readiness_row(row)


def compact_training_readiness_observations(payload: Any) -> list[dict[str, Any]]:
    """Normalize every timestamped readiness row for historical cutoff selection."""

    rows = payload if isinstance(payload, list) else [payload]
    rows = [row for row in rows if isinstance(row, dict) and not row.get("error")]
    return [
        compact_training_readiness_row(row)
        for row in sorted(
            rows,
            key=lambda item: str(
                item.get("timestampLocal") or item.get("timestamp") or ""
            ),
        )
    ]


def compact_training_readiness_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Garmin Training Readiness observation."""

    recovery_minutes = numeric_value(row.get("recoveryTime"))
    return {
        "score": numeric_value(row.get("score")),
        "level": row.get("level"),
        "feedback_short": row.get("feedbackShort"),
        "feedback_long": row.get("feedbackLong"),
        "observed_at": row.get("timestamp"),
        "observed_at_local": row.get("timestampLocal"),
        "calendar_date": row.get("calendarDate"),
        "input_context": row.get("inputContext"),
        "valid_sleep": row.get("validSleep"),
        "device_context": {
            "device_id": row.get("deviceId"),
            "primary_activity_tracker": row.get("primaryActivityTracker"),
        },
        "drivers": {
            "sleep_score": readiness_driver(
                value=row.get("sleepScore"),
                percent=row.get("sleepScoreFactorPercent"),
                feedback=row.get("sleepScoreFactorFeedback"),
            ),
            "recovery_time": readiness_driver(
                value=recovery_minutes,
                percent=row.get("recoveryTimeFactorPercent"),
                feedback=row.get("recoveryTimeFactorFeedback"),
                unit="minutes",
                extra={
                    "hours": (
                        round(recovery_minutes / 60, 1)
                        if recovery_minutes is not None
                        else None
                    ),
                    "change_phrase": row.get("recoveryTimeChangePhrase"),
                },
            ),
            "hrv_status": readiness_driver(
                value=row.get("hrvWeeklyAverage"),
                percent=row.get("hrvFactorPercent"),
                feedback=row.get("hrvFactorFeedback"),
                unit="ms",
            ),
            "acute_load": readiness_driver(
                value=row.get("acuteLoad"),
                percent=row.get("acwrFactorPercent"),
                feedback=row.get("acwrFactorFeedback"),
            ),
            "sleep_history": readiness_driver(
                percent=row.get("sleepHistoryFactorPercent"),
                feedback=row.get("sleepHistoryFactorFeedback"),
            ),
            "stress_history": readiness_driver(
                percent=row.get("stressHistoryFactorPercent"),
                feedback=row.get("stressHistoryFactorFeedback"),
            ),
        },
        "interpretation": {
            "aggregate_is_diagnostic": True,
            "drivers_are_not_independent": True,
            "not_a_race_performance_forecast": True,
        },
    }


def readiness_driver(
    *,
    value: Any = None,
    percent: Any = None,
    feedback: Any = None,
    unit: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "value": numeric_value(value),
        "factor_percent": numeric_value(percent),
        "feedback": feedback,
    }
    if unit:
        result["unit"] = unit
    if extra:
        result.update(extra)
    return result


def compact_daily_vo2max(
    payload: Any,
    *,
    requested_date: Any = None,
) -> dict[str, Any] | None:
    """Preserve sport/category, date, and precision for Garmin VO2max estimates."""

    if not isinstance(payload, dict) or payload.get("error"):
        return None
    raw_vo2max = payload.get("mostRecentVO2Max")
    if not isinstance(raw_vo2max, dict):
        return None
    estimates = {}
    for category, value in raw_vo2max.items():
        if category in {"userId", "heatAltitudeAcclimation"} or not isinstance(value, dict):
            continue
        calendar_date = value.get("calendarDate")
        estimates[category] = {
            "category": category,
            "value": numeric_value(value.get("vo2MaxValue")),
            "precise_value": numeric_value(value.get("vo2MaxPreciseValue")),
            "unit": "ml/kg/min",
            "calendar_date": calendar_date,
            "age_days_at_requested_date": date_distance_days(
                calendar_date, requested_date
            ),
            "source_device": None,
            "source_device_available": False,
            "source_device_reason": "not_exposed_in_vo2max_record",
            "fitness_age": numeric_value(value.get("fitnessAge")),
            "max_met_category": numeric_value(value.get("maxMetCategory")),
        }
    if not estimates:
        return None
    return {
        "estimates": estimates,
        "category_note": (
            "Preserve Garmin's raw category. Do not relabel `generic` as running "
            "without activity-specific evidence."
        ),
        "interpretation": {
            "modeled_not_measured": True,
            "sport_categories_must_remain_separate": True,
            "trend_preferred_over_single_point": True,
            "max_met_category_is_opaque": True,
        },
    }


def compact_daily_training_status_context(payload: Any) -> dict[str, Any] | None:
    """Keep device metadata as Training Status context, not VO2max provenance."""

    if not isinstance(payload, dict) or payload.get("error"):
        return None
    latest = payload.get("mostRecentTrainingStatus") or {}
    values = latest.get("latestTrainingStatusData") if isinstance(latest, dict) else None
    rows = [row for row in (values or {}).values() if isinstance(row, dict)]
    if not rows:
        return None
    row = max(rows, key=lambda item: numeric_value(item.get("timestamp")) or -1)
    return {
        "calendar_date": row.get("calendarDate"),
        "timestamp_ms": numeric_value(row.get("timestamp")),
        "sport": row.get("sport"),
        "fitness_trend_sport": row.get("fitnessTrendSport"),
        "device_id": row.get("deviceId"),
        "primary_training_device": row.get("primaryTrainingDevice"),
        "provenance_note": "Training Status context; not VO2max source-device proof.",
    }


def numeric_value(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def date_distance_days(observed: Any, requested: Any) -> int | None:
    if not isinstance(observed, str) or not isinstance(requested, str):
        return None
    try:
        return (date.fromisoformat(requested) - date.fromisoformat(observed)).days
    except ValueError:
        return None


def fetch_body_battery_range(start: str, end: str, *, gccli: str) -> Any:
    """Fetch Garmin Body Battery data for a date range."""

    return run_gccli_json(
        gccli,
        ["health", "body-battery", "range", "--start", start, "--end", end],
    )


def fetch_activity(
    activity: str,
    *,
    gccli: str,
    include_details: bool = True,
) -> dict[str, Any]:
    """Fetch one Garmin activity's summary and optional details metadata.

    ``activity`` may be a Garmin activity id, an Intervals.icu activity id, or a
    saved Intervals.icu activity artifact directory. Intervals artifacts from
    Garmin expose the Garmin activity id as ``external_id``.
    """

    resolved = resolve_garmin_activity(activity)
    summary = run_gccli_json(gccli, ["activity", "summary", resolved["garmin_id"]])
    details = (
        run_gccli_json(
            gccli,
            [
                "activity",
                "details",
                resolved["garmin_id"],
                "--max-chart",
                str(GARMIN_ACTIVITY_DETAILS_MAX_POINTS),
            ],
        )
        if include_details
        else {}
    )
    payload = {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "resolved_activity": resolved,
        "metrics_summary": garmin_activity_metrics(summary, details),
    }
    if include_details:
        payload["summary"] = summary
        payload["details"] = details
    return payload


def download_activity_file(
    activity: str,
    *,
    gccli: str,
    file_format: str,
    output_path: Path,
) -> Path:
    """Download one Garmin Connect activity export to an explicit path."""

    resolved = resolve_garmin_activity(activity)
    result = subprocess.run(
        [
            gccli, "activity", "download", resolved["garmin_id"],
            "--format", file_format, "--output", str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("gccli did not create a non-empty activity file")
    return output_path


def fetch_cycling_ftp(*, gccli: str) -> dict[str, Any]:
    """Fetch Garmin Connect's latest cycling FTP payload."""

    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "cycling_ftp": run_gccli_json(gccli, ["health", "cycling-ftp"]),
    }


def fetch_lactate_threshold(*, gccli: str) -> dict[str, Any]:
    """Fetch Garmin Connect's latest lactate-threshold payload."""

    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "lactate_threshold": run_gccli_json(gccli, ["health", "lactate-threshold"]),
    }


def fetch_courses(*, gccli: str) -> dict[str, Any]:
    """Fetch the Garmin Connect user's saved courses (routes)."""

    payload = run_gccli_json(gccli, ["courses", "list"])
    courses = []
    if isinstance(payload, dict) and isinstance(payload.get("coursesForUser"), list):
        courses = [item for item in payload["coursesForUser"] if isinstance(item, dict)]
    elif isinstance(payload, list):
        courses = [item for item in payload if isinstance(item, dict)]
    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "courses": courses,
    }


def fetch_course(course_id: str, *, gccli: str) -> dict[str, Any]:
    """Fetch one Garmin Connect course, including its route geometry."""

    course = run_gccli_json(gccli, ["courses", "detail", course_id])
    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "course_id": str(course_id),
        "course": course,
    }


def upload_course(
    course_json: str | dict[str, Any],
    *,
    gccli: str,
    course_name: str | None = None,
    course_privacy: int = 2,
) -> dict[str, Any]:
    """Create a Garmin course directly from saved course JSON."""

    payload = (
        prepare_course_for_upload(course_json)
        if isinstance(course_json, dict)
        else load_course_for_upload(Path(course_json))
    )
    if course_name:
        payload["courseName"] = course_name
    payload["coursePrivacy"] = course_privacy
    payload.setdefault("rulePK", 2)
    created = garmin_api_json(
        "/course-service/course", gccli=gccli, method="POST", payload=payload
    )
    if not isinstance(created, dict) or created.get("courseId") is None:
        raise RuntimeError("Garmin returned no courseId for the created course.")
    course_id = str(created["courseId"])
    fetched = fetch_course(course_id, gccli=gccli)["course"]
    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "operation": "course_upload",
        "course_id": course_id,
        "course": fetched,
        "verification": verify_uploaded_course(payload, fetched),
    }


def delete_course(
    course_id: str,
    *,
    gccli: str,
    confirmed_course_id: str,
) -> dict[str, Any]:
    """Delete one Garmin course after exact course-ID confirmation."""

    course_id = str(course_id)
    if str(confirmed_course_id) != course_id:
        raise SystemExit(
            f"Refusing deletion: --confirm-course-id must exactly equal {course_id}."
        )
    existing = fetch_course(course_id, gccli=gccli)["course"]
    result = subprocess.run(
        [gccli, "courses", "delete", course_id, "--force"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    remaining_ids = {
        str(course.get("courseId"))
        for course in fetch_courses(gccli=gccli)["courses"]
        if course.get("courseId") is not None
    }
    if course_id in remaining_ids:
        raise RuntimeError(f"Garmin still lists course {course_id} after deletion.")
    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "operation": "course_delete",
        "course_id": course_id,
        "course_name": existing.get("courseName") if isinstance(existing, dict) else None,
        "deleted": True,
    }


def load_course_for_upload(path: Path) -> dict[str, Any]:
    """Load and sanitize a raw course or the wrapper emitted by get_course."""

    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read Garmin course JSON from {path}: {exc}") from exc
    if not isinstance(source, dict):
        raise SystemExit(f"Expected a Garmin course JSON object in {path}.")
    return prepare_course_for_upload(source)


def prepare_course_for_upload(source: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a raw course or the wrapper emitted by get_course."""

    if isinstance(source.get("course"), dict):
        source = source["course"]
    payload = {
        key: value
        for key, value in source.items()
        if key in COURSE_SAVE_FIELDS and value is not None
    }
    if not payload.get("courseName"):
        raise SystemExit("Course JSON has no courseName; pass --name or add courseName.")
    if not isinstance(payload.get("geoPoints"), list) or not payload["geoPoints"]:
        raise SystemExit("Course JSON has no non-empty geoPoints array.")
    return payload


def verify_uploaded_course(expected: dict[str, Any], actual: Any) -> dict[str, Any]:
    """Compare stable course fields after Garmin's read-back."""

    if not isinstance(actual, dict):
        return {"verified": False, "mismatches": ["course response is not an object"]}
    mismatches = []
    for key in (
        "courseName",
        "activityTypePk",
        "distanceMeter",
        "elevationGainMeter",
        "elevationLossMeter",
    ):
        if key in expected and actual.get(key) != expected.get(key):
            mismatches.append(key)
    expected_geo = expected.get("geoPoints") or []
    actual_geo = actual.get("geoPoints") or []
    if expected_geo != actual_geo:
        mismatches.append("geoPoints")
    expected_names = [
        point.get("name")
        for point in expected.get("coursePoints") or []
        if isinstance(point, dict)
    ]
    actual_names = [
        point.get("name")
        for point in actual.get("coursePoints") or []
        if isinstance(point, dict)
    ]
    if expected_names != actual_names:
        mismatches.append("coursePointNames")
    return {
        "verified": not mismatches,
        "mismatches": mismatches,
        "geo_point_count": len(actual_geo),
        "course_point_names": actual_names,
    }


def garmin_api_json(
    path: str,
    *,
    gccli: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    """Call Garmin Connect with the access token managed by gccli."""

    token_result = subprocess.run(
        [gccli, "auth", "token", "--plain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if token_result.returncode != 0:
        raise subprocess.CalledProcessError(
            token_result.returncode,
            token_result.args,
            output=token_result.stdout,
            stderr=token_result.stderr,
        )
    token = token_result.stdout.strip()
    if not token:
        raise RuntimeError("gccli returned an empty Garmin access token.")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{GARMIN_CONNECT_API}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": GARMIN_MOBILE_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def garmin_activity_search(
    gccli: str,
    start_date: str,
    end_date: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    payload = run_gccli_json(
        gccli,
        [
            "activities",
            "search",
            "--start-date",
            start_date,
            "--end-date",
            end_date,
            "--limit",
            str(limit),
        ],
    )
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("activities", "activityList", "results"):
            values = payload.get(key)
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]
    return []


def garmin_activity_metrics(summary: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    """Extract compact Garmin training-effect/performance metadata."""

    summary_dto = summary.get("summaryDTO") or {}
    performance = detail_performance_condition_summary(details)
    stamina = detail_stamina_summary(details)
    stamina.update(
        {
            "beginPotentialStamina": summary_dto.get("beginPotentialStamina"),
            "endPotentialStamina": summary_dto.get("endPotentialStamina"),
            "minAvailableStamina": summary_dto.get("minAvailableStamina"),
        }
    )
    return {
        "activityId": summary.get("activityId"),
        "activityName": summary.get("activityName"),
        "startTimeLocal": summary_dto.get("startTimeLocal"),
        "training_effect": {
            "aerobic": summary_dto.get("trainingEffect"),
            "anaerobic": summary_dto.get("anaerobicTrainingEffect"),
            "label": summary_dto.get("trainingEffectLabel"),
            "aerobic_message": summary_dto.get("aerobicTrainingEffectMessage"),
            "anaerobic_message": summary_dto.get("anaerobicTrainingEffectMessage"),
        },
        "load": {
            "meaning": "Secondary Garmin/Firstbeat load context; prefer Xert XSS for primary load language.",
            "activityTrainingLoad": summary_dto.get("activityTrainingLoad"),
            "trainingStressScore": summary_dto.get("trainingStressScore"),
            "intensityFactor": summary_dto.get("intensityFactor"),
        },
        "stamina": stamina,
        "performance_condition": performance,
    }


def detail_stamina_summary(details: dict[str, Any]) -> dict[str, Any]:
    """Summarize aligned Garmin Stamina series without exposing raw samples."""

    descriptors = {
        descriptor.get("key"): descriptor.get("metricsIndex")
        for descriptor in details.get("metricDescriptors") or []
        if isinstance(descriptor, dict)
    }
    available_index = descriptors.get("directAvailableStamina")
    potential_index = descriptors.get("directPotentialStamina")
    timestamp_index = descriptors.get("directTimestamp")
    power_index = descriptors.get("directPower")
    heart_rate_index = descriptors.get("directHeartRate")
    if available_index is None or potential_index is None:
        return {
            "available": False,
            "reason": "stamina_series_not_exposed",
            "meaning": (
                "Garmin model estimates only; absence is not a physiological value."
            ),
        }

    samples = []
    for row in details.get("activityDetailMetrics") or []:
        metrics = row.get("metrics") or [] if isinstance(row, dict) else []
        available = metric_number(metrics, available_index)
        potential = metric_number(metrics, potential_index)
        if available is None or potential is None:
            continue
        samples.append(
            {
                "available": available,
                "potential": potential,
                "timestamp_ms": metric_number(metrics, timestamp_index),
                "power_w": metric_number(metrics, power_index),
                "heart_rate_bpm": metric_number(metrics, heart_rate_index),
            }
        )
    if not samples:
        return {
            "available": False,
            "reason": "stamina_series_empty",
            "meaning": (
                "Garmin model estimates only; absence is not a physiological value."
            ),
        }

    first = samples[0]
    last = samples[-1]
    minimum = min(enumerate(samples), key=lambda item: item[1]["available"])
    minimum_index, minimum_sample = minimum
    max_gap_index, max_gap_sample = max(
        enumerate(samples),
        key=lambda item: item[1]["potential"] - item[1]["available"],
    )
    potential_min = min(sample["potential"] for sample in samples)
    later_available = [
        sample["available"] for sample in samples[minimum_index:]
    ]
    timestamps = [
        sample["timestamp_ms"]
        for sample in samples
        if sample["timestamp_ms"] is not None
    ]
    intervals_seconds = [
        (current - previous) / 1000
        for previous, current in zip(timestamps, timestamps[1:])
        if current > previous
    ]
    end_gap = last["potential"] - last["available"]
    return {
        "available": True,
        "meaning": (
            "Garmin model estimates for pacing context; not measured glycogen, "
            "muscle damage, or proven remaining race capacity."
        ),
        "coverage": {
            "aligned_point_count": len(samples),
            "timestamp_point_count": len(timestamps),
            "power_point_count": sum(
                sample["power_w"] is not None for sample in samples
            ),
            "heart_rate_point_count": sum(
                sample["heart_rate_bpm"] is not None for sample in samples
            ),
            "median_interval_seconds": median_value(intervals_seconds),
        },
        "available_stamina": {
            "start": first["available"],
            "end": last["available"],
            "min": minimum_sample["available"],
            "min_context": stamina_sample_context(minimum_sample, first),
            "max_rebound_after_min": max(later_available) - minimum_sample["available"],
        },
        "potential_stamina": {
            "start": first["potential"],
            "end": last["potential"],
            "min": potential_min,
            "drawdown": first["potential"] - potential_min,
        },
        "largest_available_potential_gap": {
            "value": max_gap_sample["potential"] - max_gap_sample["available"],
            "context": stamina_sample_context(max_gap_sample, first),
            "sample_index": max_gap_index,
        },
        "end_gap": end_gap,
        "available_rejoined_potential_at_end": abs(end_gap) <= 1.0,
    }


def metric_number(metrics: list[Any], index: Any) -> float | None:
    if not isinstance(index, int) or index < 0 or index >= len(metrics):
        return None
    value = metrics[index]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def stamina_sample_context(sample: dict[str, Any], first: dict[str, Any]) -> dict[str, Any]:
    timestamp_ms = sample.get("timestamp_ms")
    first_timestamp_ms = first.get("timestamp_ms")
    elapsed_seconds = None
    if timestamp_ms is not None and first_timestamp_ms is not None:
        elapsed_seconds = round((timestamp_ms - first_timestamp_ms) / 1000, 1)
    return {
        "timestamp_ms": timestamp_ms,
        "elapsed_seconds": elapsed_seconds,
        "power_w": sample.get("power_w"),
        "heart_rate_bpm": sample.get("heart_rate_bpm"),
        "potential_stamina": sample.get("potential"),
    }


def median_value(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[midpoint], 3)
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2, 3)


def detail_performance_condition_summary(details: dict[str, Any]) -> dict[str, Any]:
    """Summarize Garmin Performance Condition as an early level and later trend."""

    descriptors = {
        descriptor.get("key"): descriptor.get("metricsIndex")
        for descriptor in details.get("metricDescriptors") or []
        if isinstance(descriptor, dict)
    }
    condition_index = descriptors.get("directPerformanceCondition")
    if condition_index is None:
        return {
            "available": False,
            "reason": "performance_condition_series_not_exposed",
            "meaning": "Absence is not evidence of poor performance condition.",
        }
    timestamp_index = descriptors.get("directTimestamp")
    power_index = descriptors.get("directPower")
    heart_rate_index = descriptors.get("directHeartRate")
    temperature_index = next(
        (
            descriptors[key]
            for key in ("directTemperature", "directAirTemperature")
            if key in descriptors
        ),
        None,
    )
    first_activity_timestamp = None
    samples = []
    for row in details.get("activityDetailMetrics") or []:
        metrics = row.get("metrics") or [] if isinstance(row, dict) else []
        timestamp = metric_number(metrics, timestamp_index)
        if first_activity_timestamp is None and timestamp is not None:
            first_activity_timestamp = timestamp
        condition = metric_number(metrics, condition_index)
        if condition is None:
            continue
        samples.append(
            {
                "value": condition,
                "timestamp_ms": timestamp,
                "power_w": metric_number(metrics, power_index),
                "heart_rate_bpm": metric_number(metrics, heart_rate_index),
                "temperature_c": metric_number(metrics, temperature_index),
            }
        )
    if not samples:
        return {
            "available": False,
            "reason": "performance_condition_series_empty",
            "meaning": "Absence is not evidence of poor performance condition.",
        }

    for sample in samples:
        timestamp = sample["timestamp_ms"]
        sample["elapsed_seconds"] = (
            round((timestamp - first_activity_timestamp) / 1000, 1)
            if timestamp is not None and first_activity_timestamp is not None
            else None
        )
    values = [sample["value"] for sample in samples]
    minimum = min(samples, key=lambda sample: sample["value"])
    maximum = max(samples, key=lambda sample: sample["value"])
    first_reported_elapsed = samples[0]["elapsed_seconds"]
    early_samples = [
        sample
        for sample in samples
        if first_reported_elapsed is None
        or sample["elapsed_seconds"] is None
        or sample["elapsed_seconds"] <= first_reported_elapsed + 60
    ]
    if not early_samples:
        early_samples = samples[:1]
    largest_drop = performance_condition_largest_drop(samples)
    thirds = performance_condition_thirds(samples)
    timestamps = [sample["timestamp_ms"] for sample in samples if sample["timestamp_ms"] is not None]
    intervals_seconds = [
        (current - previous) / 1000
        for previous, current in zip(timestamps, timestamps[1:])
        if current > previous
    ]
    return {
        "available": True,
        "meaning": (
            "Garmin's real-time estimate of deviation from the athlete's VO2max-based "
            "performance baseline; each point is approximately 1%, not a measured VO2max change."
        ),
        "coverage": {
            "point_count": len(samples),
            "timestamp_point_count": len(timestamps),
            "power_point_count": sum(sample["power_w"] is not None for sample in samples),
            "heart_rate_point_count": sum(
                sample["heart_rate_bpm"] is not None for sample in samples
            ),
            "temperature_point_count": sum(
                sample["temperature_c"] is not None for sample in samples
            ),
            "median_interval_seconds": median_value(intervals_seconds),
        },
        "count": len(samples),
        "min": minimum["value"],
        "max": maximum["value"],
        "avg": round(sum(values) / len(values), 3),
        "start": samples[0]["value"],
        "end": samples[-1]["value"],
        "first_to_last_change": samples[-1]["value"] - samples[0]["value"],
        "early_stable": {
            "value": median_value([sample["value"] for sample in early_samples]),
            "sample_count": len(early_samples),
            "first_elapsed_seconds": early_samples[0]["elapsed_seconds"],
            "last_elapsed_seconds": early_samples[-1]["elapsed_seconds"],
            "window_seconds": 60,
            "meaning": "Median of the first reported minute after Garmin begins scoring.",
        },
        "minimum_context": performance_condition_context(minimum),
        "maximum_context": performance_condition_context(maximum),
        "thirds": thirds,
        "largest_peak_to_later_trough_drop": largest_drop,
        "interpretation_rule": (
            "Separate the early level from the later within-session trend. Align changes "
            "with workout structure and sensor/environment context before attributing fatigue."
        ),
    }


def performance_condition_context(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        key: sample.get(key)
        for key in (
            "value",
            "timestamp_ms",
            "elapsed_seconds",
            "power_w",
            "heart_rate_bpm",
            "temperature_c",
        )
    }


def performance_condition_thirds(samples: list[dict[str, Any]]) -> dict[str, Any]:
    groups = []
    for index in range(3):
        start = len(samples) * index // 3
        end = len(samples) * (index + 1) // 3
        group = samples[start:end]
        if not group:
            groups.append(None)
            continue
        groups.append(
            {
                "avg": round(sum(sample["value"] for sample in group) / len(group), 3),
                "sample_count": len(group),
                "first_elapsed_seconds": group[0]["elapsed_seconds"],
                "last_elapsed_seconds": group[-1]["elapsed_seconds"],
            }
        )
    first_avg = groups[0]["avg"] if groups[0] else None
    final_avg = groups[2]["avg"] if groups[2] else None
    return {
        "basis": "reported_sample_count",
        "first": groups[0],
        "middle": groups[1],
        "final": groups[2],
        "final_minus_first": (
            round(final_avg - first_avg, 3)
            if first_avg is not None and final_avg is not None
            else None
        ),
    }


def performance_condition_largest_drop(samples: list[dict[str, Any]]) -> dict[str, Any]:
    peak = samples[0]
    best_peak = peak
    best_trough = peak
    largest_drop = 0.0
    for sample in samples[1:]:
        drop = peak["value"] - sample["value"]
        if drop > largest_drop:
            largest_drop = drop
            best_peak = peak
            best_trough = sample
        if sample["value"] > peak["value"]:
            peak = sample
    return {
        "value": largest_drop,
        "from": performance_condition_context(best_peak),
        "to": performance_condition_context(best_trough),
    }


def detail_metric_stats(details: dict[str, Any], metric_key: str) -> dict[str, Any] | None:
    index = None
    for descriptor in details.get("metricDescriptors") or []:
        if descriptor.get("key") == metric_key:
            index = descriptor.get("metricsIndex")
            break
    if index is None:
        return None

    values = []
    for row in details.get("activityDetailMetrics") or []:
        metrics = row.get("metrics") or []
        if len(metrics) <= index:
            continue
        parsed = metrics[index]
        if parsed is not None:
            values.append(float(parsed))
    if not values:
        return None
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
        "start": values[0],
        "end": values[-1],
    }


def resolve_garmin_activity(activity: str) -> dict[str, str]:
    """Resolve Garmin activity id from a Garmin id or saved Intervals activity."""

    candidate_path = Path(activity)
    metadata_path: Path | None = None
    if candidate_path.exists():
        metadata_path = candidate_path / "activity.json"
    elif activity.startswith("i"):
        matches = sorted((Path("outputs/intervals") / "activities").glob(f"*_{activity}"))
        metadata_path = matches[-1] / "activity.json" if matches else None

    if metadata_path and metadata_path.exists():
        metadata = load_activity_metadata(metadata_path)
        garmin_id = metadata.get("external_id")
        if not garmin_id:
            raise SystemExit(f"No Garmin external_id found in {metadata_path}")
        start_date = str(metadata.get("start_date_local") or date.today().isoformat())[:10]
        return {
            "garmin_id": str(garmin_id),
            "source": "intervals_external_id",
            "intervals_activity": str(metadata.get("id") or activity),
            "date": start_date,
        }

    if activity.startswith("i"):
        raise SystemExit(
            f"Could not resolve Garmin activity id from Intervals activity {activity}. "
            "Pass a Garmin activity id or a saved activity artifact that contains a Garmin external_id."
        )

    return {
        "garmin_id": activity,
        "source": "garmin_activity_id",
        "date": date.today().isoformat(),
    }


def load_activity_metadata(metadata_path: Path) -> dict[str, Any]:
    """Load Intervals activity metadata from either flat or wrapped JSON."""

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("activity"), dict):
        return payload["activity"]
    if isinstance(payload, dict):
        return payload
    raise SystemExit(f"Expected JSON object in {metadata_path}")


def run_gccli_json(
    gccli: str,
    args: list[str],
    *,
    tolerate_errors: bool = False,
) -> Any:
    result = subprocess.run(
        [gccli, "--json", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    if not tolerate_errors:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return {
        "error": {
            "type": "gccli_failed",
            "returncode": result.returncode,
            "command": [gccli, "--json", *args],
            "stderr": result.stderr.strip(),
            "stdout": result.stdout.strip(),
        }
    }


def local_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
