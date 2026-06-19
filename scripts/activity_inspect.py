#!/usr/bin/env python3
"""Inspect a saved Intervals.icu activity artifact for Codex workout analysis.

This script is intentionally optimized for agent use: it writes structured JSON
to a stable file so the chat answer can be written from one inspection result
instead of ad hoc one-off snippets or oversized terminal output.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from analysis import (
    CORE_STREAMS,
    SavedActivity,
    data_quality_summary,
    detect_power_blocks,
    detect_steady_power_segment,
    recovery_reoxygenation,
    resolve_activity_ref,
    summarize_block,
    summarize_rows,
    half_drift,
    usable_analysis_fields,
    value,
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
    parser = argparse.ArgumentParser(description="Inspect a saved Intervals.icu activity artifact.")
    parser.add_argument(
        "activities",
        nargs="+",
        metavar="activity",
        help=(
            "Activity ref(s): saved dir path/name, activity.json/streams.csv path, "
            "or saved Intervals.icu activity id"
        ),
    )
    parser.add_argument("--artifacts-dir", default="outputs/intervals")
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
        "--brief",
        action="store_true",
        help="Write a terse analysis-ready JSON view with total, work blocks, and recoveries",
    )
    parser.add_argument(
        "--no-intervals",
        action="store_true",
        help="Omit saved Intervals.icu interval summaries from the output",
    )
    parser.add_argument(
        "--output",
        help="Write JSON to this path. Defaults to outputs/activity-inspect/<activity>_<timestamp>.json",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print full JSON to stdout instead of writing a file",
    )
    args = parser.parse_args()
    if args.brief and args.compact:
        parser.error("--brief and --compact are alternative output shapes; choose one")
    try:
        inspections = [inspect_activity(activity_ref, args) for activity_ref in args.activities]
    except FileNotFoundError as exc:
        parser.error(str(exc))
    activities = [activity for activity, _ in inspections]
    results = [result for _, result in inspections]
    output_json = json.dumps(results[0] if len(results) == 1 else results, indent=2, sort_keys=True)
    if args.stdout:
        print(output_json)
        return

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json + "\n", encoding="utf-8")
        print(str(output_path.resolve()))
        return

    if len(results) == 1:
        output_path = default_output_path(activities[0])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json + "\n", encoding="utf-8")
        print(str(output_path.resolve()))
        return

    for activity, result in zip(activities, results):
        activity_json = json.dumps(result, indent=2, sort_keys=True)
        output_path = default_output_path(activity)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(activity_json + "\n", encoding="utf-8")
        print(str(output_path.resolve()))


def inspect_activity(activity_ref: str, args: argparse.Namespace) -> tuple[SavedActivity, dict[str, Any]]:
    activity = resolve_activity_ref(activity_ref, artifacts_dir=args.artifacts_dir)
    requested_fields = [field.strip() for field in args.fields.split(",") if field.strip()]
    fields = usable_analysis_fields(activity, requested_fields)
    rows = activity.streams

    result: dict[str, Any] = {
        "activity": activity_metadata(activity),
        "streams": {
            "rows": len(rows),
            "fields": list(rows[0].keys()) if rows else [],
            "ignored_fields": sorted(set(requested_fields) - set(fields)),
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

    if args.brief:
        result["_rows"] = rows
        result = brief_result(result)
    elif args.compact:
        result = compact_result(result, fields)

    return activity, result


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
        "icu_ignore_hr": metadata.get("icu_ignore_hr"),
        "icu_ignore_power": metadata.get("icu_ignore_power"),
    }


def interval_summaries(activity, fields: list[str]) -> list[dict[str, Any]]:
    summaries = []
    for index, interval in enumerate(activity.intervals, start=1):
        start = int(interval.get("start_index") or 0)
        end = int(interval.get("end_index") or start)
        summary = summarize_block(
            activity.streams,
            start_index=start,
            end_index=end,
            label=interval.get("name") or interval.get("type") or f"interval_{index}",
            fields=fields,
            detection={"source": "intervals_icu"},
        )
        summary.update(
            {
                "index": index,
                "type": interval.get("type"),
                "name": interval.get("name"),
                "elapsed_time": interval.get("elapsed_time"),
            }
        )
        summaries.append(summary)
    return summaries


def compact_result(result: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Return a smaller result intended for quick chat analysis."""

    compact = {
        "activity": result["activity"],
        "streams": {
            "rows": result["streams"]["rows"],
            "ignored_fields": result["streams"].get("ignored_fields", []),
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


def brief_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a terse result intended as the first-pass chat analysis input."""

    rows = result.get("_rows") or []
    detected_blocks = result.get("detected_power_blocks") or []
    saved_work_intervals = [
        interval
        for interval in result.get("intervals", [])
        if str(interval.get("type") or "").upper() == "WORK"
    ]
    work_blocks = detected_blocks or saved_work_intervals
    block_source = "detected_power_blocks" if detected_blocks else "intervals_icu_work_intervals"
    saved_recovery_intervals = [
        interval
        for interval in result.get("intervals", [])
        if str(interval.get("type") or "").upper() == "RECOVERY"
    ]
    recoveries = brief_recoveries(
        saved_recovery_intervals,
        moxy_recoveries=result.get("moxy", {}).get("recovery_reoxygenation", []),
        work_block_count=len(work_blocks),
    )
    hard_block = hardest_block(work_blocks)
    return {
        "activity": brief_activity(result["activity"]),
        "streams": {
            "rows": result["streams"]["rows"],
            "ignored_fields": result["streams"].get("ignored_fields", []),
            "data_quality_issues": compact_quality(result["streams"]["data_quality"]),
        },
        "total": brief_total(result["total"]),
        "key_efforts": key_efforts(rows),
        "peaks": peak_summary(rows),
        "hardest_block": (
            {
                **brief_work_block(hard_block, index=work_blocks.index(hard_block) + 1),
                "hr_recovery_after_block": hr_recovery_after_block(rows, hard_block),
            }
            if hard_block
            else None
        ),
        "block_source": block_source,
        "work_blocks": [
            brief_work_block(block, index=index)
            for index, block in enumerate(work_blocks, start=1)
        ],
        "recoveries": recoveries,
        "steady_vt1_segment": (
            brief_work_block(result["steady_vt1_segment"], index=1)
            if "steady_vt1_segment" in result
            else None
        ),
    }


def brief_activity(activity: dict[str, Any]) -> dict[str, Any]:
    elapsed = activity.get("elapsed_time")
    moving = activity.get("moving_time")
    return {
        "id": activity.get("id"),
        "name": activity.get("name"),
        "start_date_local": activity.get("start_date_local"),
        "type": activity.get("type"),
        "duration_min": round(elapsed / 60, 1) if isinstance(elapsed, (int, float)) else None,
        "moving_min": round(moving / 60, 1) if isinstance(moving, (int, float)) else None,
        "icu_training_load": activity.get("icu_training_load"),
        "icu_intensity": activity.get("icu_intensity"),
        "icu_ignore_hr": activity.get("icu_ignore_hr"),
        "icu_ignore_power": activity.get("icu_ignore_power"),
    }


def brief_total(block: dict[str, Any]) -> dict[str, Any]:
    summary = block.get("summary") or {}
    drift = block.get("drift") or {}
    return drop_none(
        {
            "watts_avg": stat(summary, "watts", "avg", digits=0),
            "watts_max": stat(summary, "watts", "max", digits=0),
            "hr_avg": stat(summary, "heartrate", "avg", digits=0),
            "hr_max": stat(summary, "heartrate", "max", digits=0),
            "br_avg": stat(summary, "respiration", "avg", digits=1),
            "br_max": stat(summary, "respiration", "max", digits=1),
            "vt_avg": stat(summary, "tidal_volume", "avg", digits=0),
            "vt_max": stat(summary, "tidal_volume", "max", digits=0),
            "ve_avg": stat(summary, "tidal_volume_min", "avg", digits=1),
            "ve_max": stat(summary, "tidal_volume_min", "max", digits=1),
            "smo2_avg": stat(summary, "smo2", "avg", digits=1),
            "smo2_min": stat(summary, "smo2", "min", digits=1),
            "smo2_max": stat(summary, "smo2", "max", digits=1),
            "thb_avg": stat(summary, "thb", "avg", digits=2),
            "core_temp_avg": stat(summary, "core_temperature", "avg", digits=2),
            "core_temp_max": stat(summary, "core_temperature", "max", digits=2),
            "skin_temp_avg": stat(summary, "skin_temperature", "avg", digits=2),
            "environment_temp_avg": stat(summary, "RuuviTemperature", "avg", digits=1),
            "humidity_avg": stat(summary, "RuuviHumidity", "avg", digits=1),
            "watts_drift": rounded(drift.get("watts"), digits=1),
            "hr_drift": rounded(drift.get("heartrate"), digits=1),
            "br_drift": rounded(drift.get("respiration"), digits=1),
            "ve_drift": rounded(drift.get("tidal_volume_min"), digits=1),
            "smo2_drift": rounded(drift.get("smo2"), digits=1),
            "core_temp_drift": rounded(drift.get("core_temperature"), digits=2),
        }
    )


def key_efforts(rows: list[dict[str, str]]) -> dict[str, Any]:
    return drop_none(
        {
            "best_5m_power": rolling_best(rows, "watts", 5 * 60, digits=0),
            "best_20m_power": rolling_best(rows, "watts", 20 * 60, digits=0),
            "best_5s_ve": rolling_best(rows, "tidal_volume_min", 5, digits=1),
            "best_5m_ve": rolling_best(rows, "tidal_volume_min", 5 * 60, digits=1),
        }
    )


def peak_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    return drop_none(
        {
            "core_temp_peak": field_peak(rows, "core_temperature", digits=2),
            "ve_peak": field_peak(rows, "tidal_volume_min", digits=1),
            "br_peak": field_peak(rows, "respiration", digits=1),
        }
    )


def rolling_best(
    rows: list[dict[str, str]],
    field: str,
    window_seconds: int,
    *,
    digits: int,
) -> dict[str, Any] | None:
    samples = [(index, value(row, field)) for index, row in enumerate(rows)]
    samples = [(index, sample) for index, sample in samples if sample is not None]
    if len(samples) < window_seconds:
        return None

    best: tuple[float, int, int] | None = None
    running_sum = 0.0
    start = 0
    for end, (_, sample) in enumerate(samples):
        running_sum += sample
        if end - start + 1 > window_seconds:
            running_sum -= samples[start][1]
            start += 1
        if end - start + 1 != window_seconds:
            continue
        average = running_sum / window_seconds
        if best is None or average > best[0]:
            best = (average, samples[start][0], samples[end][0])

    if best is None:
        return None
    average, start_index, end_index = best
    return {
        "avg": rounded(average, digits=digits),
        "start_s": rounded(row_time(rows, start_index), digits=0),
        "end_s": rounded(row_time(rows, end_index), digits=0),
    }


def field_peak(rows: list[dict[str, str]], field: str, *, digits: int) -> dict[str, Any] | None:
    best: tuple[float, int] | None = None
    for index, row in enumerate(rows):
        sample = value(row, field)
        if sample is None:
            continue
        if best is None or sample > best[0]:
            best = (sample, index)
    if best is None:
        return None
    sample, index = best
    return {"value": rounded(sample, digits=digits), "time_s": rounded(row_time(rows, index), digits=0)}


def hardest_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not blocks:
        return None

    def score(block: dict[str, Any]) -> float:
        summary = block.get("summary") or {}
        watts = stat(summary, "watts", "avg", digits=1) or 0
        duration = block.get("duration_seconds") or 0
        hr = stat(summary, "heartrate", "avg", digits=1) or 0
        return float(watts) * min(float(duration), 30 * 60) + float(hr)

    return max(blocks, key=score)


def hr_recovery_after_block(
    rows: list[dict[str, str]],
    block: dict[str, Any],
    *,
    window_seconds: int = 60,
) -> dict[str, Any] | None:
    end_index = block.get("end_index")
    if not isinstance(end_index, int) or end_index >= len(rows):
        return None
    start_hr = value(rows[max(0, end_index - 1)], "heartrate")
    if start_hr is None:
        return None
    window = rows[end_index : min(len(rows), end_index + window_seconds)]
    hr_values = [sample for row in window if (sample := value(row, "heartrate")) is not None]
    if not hr_values:
        return None
    low = min(hr_values)
    return {
        "window_s": window_seconds,
        "start_hr": rounded(start_hr, digits=0),
        "low_hr": rounded(low, digits=0),
        "drop_bpm": rounded(start_hr - low, digits=0),
    }


def row_time(rows: list[dict[str, str]], index: int) -> float | None:
    if index < 0 or index >= len(rows):
        return None
    parsed = value(rows[index], "time")
    return parsed if parsed is not None else float(index)


def brief_work_block(block: dict[str, Any], *, index: int) -> dict[str, Any]:
    summary = block.get("summary") or {}
    drift = block.get("drift") or {}
    source = block.get("detection", {}).get("source")
    watts_avg = stat(summary, "watts", "avg", digits=1)
    hr_avg = stat(summary, "heartrate", "avg", digits=1)
    return drop_none(
        {
            "n": index,
            "label": brief_block_label(block, index=index),
            "source": source,
            "source_index": block.get("index"),
            "duration_s": rounded(block.get("duration_seconds"), digits=0),
            "watts_avg": rounded(watts_avg, digits=0),
            "watts_max": stat(summary, "watts", "max", digits=0),
            "hr_avg": rounded(hr_avg, digits=0),
            "hr_max": stat(summary, "heartrate", "max", digits=0),
            "hr_end": stat(summary, "heartrate", "end", digits=0),
            "w_per_hr": rounded(watts_avg / hr_avg, digits=3) if watts_avg and hr_avg else None,
            "watts_drift": rounded(drift.get("watts"), digits=1),
            "hr_drift": rounded(drift.get("heartrate"), digits=1),
            "br_avg": stat(summary, "respiration", "avg", digits=1),
            "br_max": stat(summary, "respiration", "max", digits=1),
            "br_drift": rounded(drift.get("respiration"), digits=1),
            "vt_avg": stat(summary, "tidal_volume", "avg", digits=0),
            "vt_max": stat(summary, "tidal_volume", "max", digits=0),
            "vt_drift": rounded(drift.get("tidal_volume"), digits=1),
            "ve_avg": stat(summary, "tidal_volume_min", "avg", digits=1),
            "ve_max": stat(summary, "tidal_volume_min", "max", digits=1),
            "ve_drift": rounded(drift.get("tidal_volume_min"), digits=1),
            "smo2_avg": stat(summary, "smo2", "avg", digits=1),
            "smo2_min": stat(summary, "smo2", "min", digits=1),
            "smo2_end": stat(summary, "smo2", "end", digits=1),
            "smo2_drift": rounded(drift.get("smo2"), digits=1),
            "thb_avg": stat(summary, "thb", "avg", digits=2),
            "core_temp_max": stat(summary, "core_temperature", "max", digits=2),
            "core_temp_drift": rounded(drift.get("core_temperature"), digits=2),
        }
    )


def brief_block_label(block: dict[str, Any], *, index: int) -> str | None:
    label = block.get("label")
    source = block.get("detection", {}).get("source")
    if source == "intervals_icu" and label == "WORK":
        return f"saved_interval_{index}"
    return label


def brief_recoveries(
    blocks: list[dict[str, Any]],
    *,
    moxy_recoveries: list[dict[str, Any]],
    work_block_count: int,
) -> list[dict[str, Any]]:
    moxy_by_after_work_block = {}
    for moxy_recovery in moxy_recoveries:
        after_work_block = recovery_after_work_block(moxy_recovery)
        if after_work_block is not None:
            moxy_by_after_work_block[after_work_block] = moxy_recovery

    recoveries = []
    for block in blocks:
        after_work_block = recovery_after_work_block(block)
        if after_work_block is None:
            continue
        if after_work_block < 1 or after_work_block > work_block_count:
            continue
        recoveries.append(
            brief_recovery(
                block,
                index=len(recoveries) + 1,
                after_work_block=after_work_block,
                moxy_recovery=moxy_by_after_work_block.get(after_work_block),
            )
        )
    return recoveries


def recovery_after_work_block(block: dict[str, Any]) -> int | None:
    source_index = block.get("index")
    return max(0, (source_index - 1) // 2) if isinstance(source_index, int) else None


def brief_recovery(
    block: dict[str, Any],
    *,
    index: int,
    after_work_block: int,
    moxy_recovery: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = block.get("summary") or {}
    moxy = moxy_recovery or {}
    return drop_none(
        {
            "n": index,
            "after_work_block": after_work_block,
            "duration_s": rounded(block.get("duration_seconds"), digits=0),
            "watts_avg": stat(summary, "watts", "avg", digits=0),
            "hr_start": stat(summary, "heartrate", "start", digits=0),
            "hr_min": stat(summary, "heartrate", "min", digits=0),
            "hr_end": stat(summary, "heartrate", "end", digits=0),
            "hr_drop_start_to_min": recovery_drop(summary, "heartrate"),
            "ve_min": stat(summary, "tidal_volume_min", "min", digits=1),
            "ve_end": stat(summary, "tidal_volume_min", "end", digits=1),
            "smo2_start": rounded(moxy.get("smo2_start"), digits=1),
            "smo2_min": rounded(moxy.get("smo2_min"), digits=1),
            "smo2_peak": rounded(moxy.get("smo2_peak"), digits=1),
            "smo2_end": rounded(moxy.get("smo2_end"), digits=1),
            "smo2_rise_min_to_peak": rounded(moxy.get("smo2_rise_min_to_peak"), digits=1),
            "smo2_rise_start_to_peak": rounded(moxy.get("smo2_rise_start_to_peak"), digits=1),
            "thb_avg": rounded(moxy.get("thb_avg"), digits=2),
        }
    )


def recovery_drop(summary: dict[str, Any], field: str) -> float | int | None:
    stats = summary.get(field) or {}
    start = stats.get("start")
    minimum = stats.get("min")
    if not isinstance(start, (int, float)) or not isinstance(minimum, (int, float)):
        return None
    return rounded(start - minimum, digits=0)


def stat(
    summary: dict[str, Any],
    field: str,
    key: str,
    *,
    digits: int,
) -> float | int | None:
    stats = summary.get(field) or {}
    return rounded(stats.get(key), digits=digits)


def rounded(value: Any, *, digits: int) -> float | int | None:
    if not isinstance(value, (int, float)):
        return None
    rounded_value = round(value, digits)
    return int(rounded_value) if digits == 0 else rounded_value


def drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


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


def default_output_path(activity) -> Path:
    activity_id = sanitize_filename(activity.id or activity.activity_dir.name)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    return Path("outputs/activity-inspect") / f"{activity_id}_{timestamp}.json"


def sanitize_filename(raw: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw.strip())
    return clean.strip("-") or "activity"


if __name__ == "__main__":
    main()
