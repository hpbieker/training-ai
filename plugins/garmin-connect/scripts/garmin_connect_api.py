"""Garmin Connect live helpers backed by gccli.

Garmin Connect does not expose a simple public personal API, so this module
uses the local ``gccli`` command as the transport boundary. Credentials remain
managed by ``gccli auth login`` and the local keyring.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_GCCLI = "/opt/homebrew/bin/gccli"
GARMIN_ACTIVITY_DETAILS_MAX_POINTS = 2000
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


def resolve_gccli() -> str:
    """Return the preferred gccli executable path."""

    if Path(DEFAULT_GCCLI).exists():
        return DEFAULT_GCCLI
    resolved = shutil.which("gccli")
    if resolved:
        return resolved
    raise SystemExit("gccli not found. Install it and run `gccli auth login` first.")


def show_auth_status(*, gccli: str) -> None:
    """Print gccli's Garmin auth status."""

    subprocess.run([gccli, "auth", "status"], check=True)


def fetch_day(
    day: str,
    *,
    gccli: str,
    only: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Fetch useful Garmin daily health endpoints for one date."""

    specs = daily_specs(day)
    if only:
        wanted = {daily_spec_key(name) for name in only}
        specs = {name: command for name, command in specs.items() if name in wanted}
    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "date": day,
        "sources": {
            name: run_gccli_json(gccli, command)
            for name, command in specs.items()
        },
    }


def fetch_recent_days(*, days: int, until: str, gccli: str) -> dict[str, Any]:
    """Fetch daily Garmin health data for a recent date window."""

    until_date = date.fromisoformat(until)
    start_date = until_date - timedelta(days=days - 1)
    return {
        "source": "garmin_connect_gccli",
        "source_time_local": local_now(),
        "start_date": start_date.isoformat(),
        "end_date": until_date.isoformat(),
        "days": [
            fetch_day((until_date - timedelta(days=offset)).isoformat(), gccli=gccli)
            for offset in range(days - 1, -1, -1)
        ],
        "body_battery_range": fetch_body_battery_range(
            start_date.isoformat(),
            until_date.isoformat(),
            gccli=gccli,
        ),
    }


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
    performance = detail_metric_stats(details, "directPerformanceCondition")
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
        "stamina": {
            "beginPotentialStamina": summary_dto.get("beginPotentialStamina"),
            "endPotentialStamina": summary_dto.get("endPotentialStamina"),
            "minAvailableStamina": summary_dto.get("minAvailableStamina"),
        },
        "performance_condition": performance,
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


def run_gccli_json(gccli: str, args: list[str]) -> Any:
    result = subprocess.run(
        [gccli, "--json", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def local_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
