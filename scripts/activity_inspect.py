#!/usr/bin/env python3
"""Inspect a cached activity for Codex workout analysis.

This script is intentionally optimized for agent use: it prints structured JSON
to stdout so the chat answer can be written from one stable inspection result
instead of ad hoc one-off snippets.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from analysis import (
    CORE_STREAMS,
    data_quality_summary,
    detect_power_blocks,
    detect_steady_power_segment,
    interval_rows,
    recovery_reoxygenation,
    resolve_activity_ref,
    summarize_block,
    summarize_rows,
    half_drift,
)


DEFAULT_FIELDS = [
    "watts",
    "heartrate",
    "cadence",
    "torque",
    "respiration",
    "tidal_volume",
    "tidal_volume_min",
    "smo2",
    "thb",
    "core_temperature",
    "skin_temperature",
    "heat_strain_index",
    "temp",
    "RuuviTemperature",
    "Humidity",
    "RuuviHumidity",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a cached Intervals.icu activity.")
    parser.add_argument(
        "activity",
        help="Activity ref: latest, cached dir path/name, or Intervals.icu activity id",
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--target", type=float, help="Detect blocks near target watts")
    parser.add_argument("--threshold", type=float, help="Detect blocks above watts threshold")
    parser.add_argument("--tolerance", type=float, default=10.0)
    parser.add_argument("--min-block", default="3m", help="Minimum detected block duration")
    parser.add_argument("--max-gap", default="20s", help="Allowed short gap inside block")
    parser.add_argument("--smoothing", default="15s", help="Rolling power smoothing window")
    parser.add_argument(
        "--steady-vt1",
        action="store_true",
        help="Also run steady VT1-style work segment detection",
    )
    parser.add_argument(
        "--fields",
        default=",".join(DEFAULT_FIELDS),
        help="Comma-separated stream fields to summarize",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print a smaller chat-oriented JSON view",
    )
    parser.add_argument(
        "--no-intervals",
        action="store_true",
        help="Omit cached Intervals.icu interval summaries from the output",
    )
    args = parser.parse_args()

    fields = [field.strip() for field in args.fields.split(",") if field.strip()]
    activity = resolve_activity_ref(args.activity, data_dir=args.data_dir)
    rows = activity.streams

    result: dict[str, Any] = {
        "activity": activity_metadata(activity),
        "streams": {
            "rows": len(rows),
            "fields": list(rows[0].keys()) if rows else [],
            "data_quality": data_quality_summary(rows, fields),
        },
        "total": {
            "summary": summarize_rows(rows, fields),
            "drift": half_drift(rows, fields),
        },
        "moxy": {
            "recovery_reoxygenation": recovery_reoxygenation(activity),
        },
    }
    if not args.no_intervals:
        result["intervals"] = interval_summaries(activity, fields)

    if args.steady_vt1:
        segment_rows, start, end, target = detect_steady_power_segment(rows)
        result["steady_vt1_segment"] = summarize_block(
            rows,
            start_index=start,
            end_index=end,
            label="steady_vt1",
            fields=fields,
            detection={"target": target, "method": "detect_steady_power_segment"},
        )
        result["steady_vt1_segment"]["summary"] = summarize_rows(segment_rows, fields)
        result["steady_vt1_segment"]["drift"] = half_drift(segment_rows, fields)

    if args.target is not None or args.threshold is not None:
        blocks = detect_power_blocks(
            rows,
            target=args.target,
            threshold=args.threshold,
            tolerance=args.tolerance,
            min_seconds=parse_duration(args.min_block),
            max_gap_seconds=parse_duration(args.max_gap),
            smoothing_seconds=parse_duration(args.smoothing),
        )
        result["detected_power_blocks"] = [
            summarize_block(
                rows,
                start_index=block.start_index,
                end_index=block.end_index,
                label=block.label,
                fields=fields,
                detection=block.detection,
            )
            for block in blocks
        ]

    if args.compact:
        result = compact_result(result, fields)

    print(json.dumps(result, indent=2, sort_keys=True))


def activity_metadata(activity) -> dict[str, Any]:
    metadata = activity.metadata
    return {
        "activity_dir": str(activity.activity_dir),
        "id": activity.id,
        "name": activity.name,
        "start_date_local": activity.start_date_local,
        "type": metadata.get("type"),
        "elapsed_time": metadata.get("elapsed_time"),
        "moving_time": metadata.get("moving_time"),
        "external_id": metadata.get("external_id"),
        "icu_training_load": metadata.get("icu_training_load"),
        "icu_intensity": metadata.get("icu_intensity"),
        "average_watts": metadata.get("average_watts"),
        "weighted_average_watts": metadata.get("weighted_average_watts"),
        "average_heartrate": metadata.get("average_heartrate"),
        "max_heartrate": metadata.get("max_heartrate"),
    }


def interval_summaries(activity, fields: list[str]) -> list[dict[str, Any]]:
    summaries = []
    for index, interval in enumerate(activity.intervals, start=1):
        start = int(interval.get("start_index") or 0)
        end = int(interval.get("end_index") or start)
        rows = interval_rows(activity, interval)
        summaries.append(
            {
                "index": index,
                "type": interval.get("type"),
                "name": interval.get("name"),
                "start_index": start,
                "end_index": end,
                "elapsed_time": interval.get("elapsed_time"),
                "summary": summarize_rows(rows, fields),
                "drift": half_drift(rows, fields),
                "data_quality": data_quality_summary(rows, fields),
            }
        )
    return summaries


def compact_result(result: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Return a smaller result intended for quick chat analysis."""

    compact = {
        "activity": result["activity"],
        "streams": {
            "rows": result["streams"]["rows"],
            "data_quality_flags": compact_quality(result["streams"]["data_quality"]),
        },
        "total": compact_summary_block(result["total"], fields),
        "detected_power_blocks": [
            {
                "label": block["label"],
                "start_time": block["start_time"],
                "end_time": block["end_time"],
                "duration_minutes": block["duration_minutes"],
                "detection": block["detection"],
                **compact_summary_block(block, fields),
            }
            for block in result.get("detected_power_blocks", [])
        ],
        "steady_vt1_segment": (
            {
                "start_time": result["steady_vt1_segment"]["start_time"],
                "end_time": result["steady_vt1_segment"]["end_time"],
                "duration_minutes": result["steady_vt1_segment"]["duration_minutes"],
                "detection": result["steady_vt1_segment"]["detection"],
                **compact_summary_block(result["steady_vt1_segment"], fields),
            }
            if "steady_vt1_segment" in result
            else None
        ),
        "moxy": result.get("moxy", {}),
    }
    if "intervals" in result:
        compact["intervals"] = [
            {
                "index": interval["index"],
                "type": interval["type"],
                "start_index": interval["start_index"],
                "end_index": interval["end_index"],
                **compact_summary_block(interval, fields),
            }
            for interval in result["intervals"]
        ]
    return compact


def compact_summary_block(block: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    summary = block.get("summary") or {}
    drift = block.get("drift") or {}
    return {
        "summary": {
            field: compact_stats(summary.get(field))
            for field in fields
            if summary.get(field)
        },
        "drift": {
            field: round(value, 3)
            for field, value in drift.items()
            if value is not None and field in fields
        },
        "data_quality_flags": compact_quality(block.get("data_quality") or {}),
    }


def compact_stats(stats: dict[str, Any] | None) -> dict[str, Any] | None:
    if not stats:
        return None
    return {
        "avg": round(stats["avg"], 3),
        "min": round(stats["min"], 3),
        "max": round(stats["max"], 3),
        "start": round(stats["start"], 3),
        "end": round(stats["end"], 3),
        "count": int(stats["count"]),
    }


def compact_quality(quality: dict[str, Any]) -> dict[str, Any]:
    return {
        field: {
            "present": int(stats["present"]),
            "missing": int(stats["missing"]),
            "longest_gap": int(stats["longest_gap"]),
            "meaningful_gap": bool(stats["meaningful_gap"]),
        }
        for field, stats in quality.items()
        if stats.get("meaningful_gap") or not stats.get("has_values")
    }


def parse_duration(raw: str) -> int:
    value = raw.strip().lower()
    if value.endswith("ms"):
        return max(1, round(float(value[:-2]) / 1000))
    if value.endswith("s"):
        return round(float(value[:-1]))
    if value.endswith("m"):
        return round(float(value[:-1]) * 60)
    if value.endswith("h"):
        return round(float(value[:-1]) * 3600)
    return round(float(value))


if __name__ == "__main__":
    main()
