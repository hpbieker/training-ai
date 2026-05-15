#!/usr/bin/env python3
"""Cache Garmin Connect health data via gccli.

This script expects ``gccli auth login`` to have been completed outside the
project. Credentials are managed by gccli/keyring, not by this repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_GCCLI = "/opt/homebrew/bin/gccli"
DEFAULT_OUTPUT_DIR = Path("data/garmin")
GARMIN_ACTIVITY_DETAILS_MAX_POINTS = 2000
DAILY_SPEC_CHOICES = [
    "heart-rate",
    "hrv",
    "sleep",
    "stress",
    "summary",
    "training-readiness",
    "training-status",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache Garmin Connect health/readiness data using gccli.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    day = subparsers.add_parser("day", help="Cache Garmin health data for one day")
    day.add_argument("date", nargs="?", default=date.today().isoformat())
    day.add_argument(
        "--only",
        action="append",
        choices=DAILY_SPEC_CHOICES,
        help="Cache only one daily source. Can be repeated.",
    )

    recent = subparsers.add_parser("recent", help="Cache Garmin health data for recent days")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--until", default=date.today().isoformat())

    activity = subparsers.add_parser(
        "activity",
        help="Cache one Garmin activity file and summary metadata",
    )
    activity.add_argument(
        "activity",
        help="Garmin activity id, Intervals activity id, or cached Intervals activity dir",
    )
    subparsers.add_parser("status", help="Show gccli auth status")

    args = parser.parse_args()
    gccli = _resolve_gccli()

    if args.command == "status":
        subprocess.run([gccli, "auth", "status"], check=True)
        return

    if args.command == "day":
        artifacts = cache_day(args.date, gccli=gccli, only=args.only)
        _print_artifacts(artifacts)
        return

    if args.command == "recent":
        until = date.fromisoformat(args.until)
        artifacts = []
        for offset in range(args.days - 1, -1, -1):
            current = until - timedelta(days=offset)
            artifacts.extend(cache_day(current.isoformat(), gccli=gccli).values())
        body_battery = cache_body_battery_range(
            (until - timedelta(days=args.days - 1)).isoformat(),
            until.isoformat(),
            gccli=gccli,
        )
        artifacts.append(body_battery)
        for path in artifacts:
            print(path)
        return

    if args.command == "activity":
        artifacts = cache_activity(
            args.activity,
            gccli=gccli,
        )
        _print_artifacts(artifacts)
        return


def cache_day(
    day: str,
    *,
    gccli: str,
    only: Iterable[str] | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Cache useful Garmin daily health endpoints for one date."""

    output_path = Path(output_dir)
    specs = _daily_specs(day)
    if only:
        wanted = {_daily_spec_key(name) for name in only}
        specs = {name: command for name, command in specs.items() if name in wanted}
    artifacts = {}
    for name, command in specs.items():
        target = output_path / name / f"{day}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _run_gccli_json(gccli, command)
        _write_json(target, payload)
        artifacts[name] = target
    return artifacts


def _daily_specs(day: str) -> dict[str, list[str]]:
    return {
        "training_readiness": ["health", "training-readiness", day],
        "stress": ["health", "stress", "view", day],
        "heart_rate": ["health", "hr", day],
        "hrv": ["health", "hrv", day],
        "sleep": ["health", "sleep", day],
        "summary": ["health", "summary", day],
        "training_status": ["health", "training-status", day],
    }


def _daily_spec_key(name: str) -> str:
    return name.replace("-", "_")


def cache_body_battery_range(
    start: str,
    end: str,
    *,
    gccli: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Cache Garmin Body Battery data for a date range."""

    target = Path(output_dir) / "body_battery" / f"{start}_{end}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _run_gccli_json(
        gccli,
        ["health", "body-battery", "range", "--start", start, "--end", end],
    )
    _write_json(target, payload)
    return target


def cache_activity(
    activity: str,
    *,
    gccli: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Cache one Garmin activity's summary/details metadata.

    ``activity`` may be a Garmin activity id, an Intervals.icu activity id, or a
    cached Intervals.icu activity directory. Intervals caches from Garmin expose
    the Garmin activity id as ``external_id``.
    """

    resolved = resolve_garmin_activity(activity)
    target_dir = Path(output_dir) / "activities" / f"{resolved['date']}_{resolved['garmin_id']}"
    target_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, Path] = {}

    summary = _run_gccli_json(gccli, ["activity", "summary", resolved["garmin_id"]])
    summary_json = target_dir / "summary.json"
    _write_json(summary_json, summary)
    artifacts["summary_json"] = summary_json

    details = _run_gccli_json(
        gccli,
        [
            "activity",
            "details",
            resolved["garmin_id"],
            "--max-chart",
            str(GARMIN_ACTIVITY_DETAILS_MAX_POINTS),
        ],
    )
    details_json = target_dir / "details.json"
    _write_json(details_json, details)
    artifacts["details_json"] = details_json

    metrics_json = target_dir / "metrics_summary.json"
    _write_json(metrics_json, garmin_activity_metrics(summary, details))
    artifacts["metrics_summary_json"] = metrics_json

    manifest = {
        "garmin_id": resolved["garmin_id"],
        "source": resolved["source"],
        "intervals_activity": resolved.get("intervals_activity"),
        "date": resolved["date"],
        "summary_json": str(summary_json),
        "details_json": str(details_json),
        "metrics_summary_json": str(metrics_json),
    }
    manifest_json = target_dir / "manifest.json"
    _write_json(manifest_json, manifest)
    artifacts["manifest_json"] = manifest_json

    return artifacts


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
    """Resolve Garmin activity id from a Garmin id or cached Intervals activity."""

    candidate_path = Path(activity)
    if candidate_path.exists():
        metadata_path = candidate_path / "activity.json"
    elif activity.startswith("i"):
        matches = sorted((Path("data") / "activities").glob(f"*_{activity}"))
        metadata_path = matches[-1] / "activity.json" if matches else Path()
    else:
        metadata_path = Path()

    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
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

    return {
        "garmin_id": activity,
        "source": "garmin_activity_id",
        "date": date.today().isoformat(),
    }


def _run_gccli_json(gccli: str, args: list[str]) -> Any:
    result = subprocess.run(
        [gccli, "--json", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _resolve_gccli() -> str:
    if Path(DEFAULT_GCCLI).exists():
        return DEFAULT_GCCLI
    resolved = shutil.which("gccli")
    if resolved:
        return resolved
    raise SystemExit("gccli not found. Install it and run `gccli auth login` first.")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _print_artifacts(artifacts: dict[str, Path]) -> None:
    for name, path in artifacts.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
