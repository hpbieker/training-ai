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
    detect_pause_segments,
    detect_power_blocks,
    detect_stable_power_blocks,
    detect_steady_power_segment,
    recovery_reoxygenation,
    resolve_activity_ref,
    summarize_block,
    summarize_rows,
    half_drift,
    half_relative_to_power_drift,
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
        "--auto-blocks",
        action="store_true",
        help="Detect sustained stable power blocks without a known workout target",
    )
    parser.add_argument("--auto-min-power", type=float, default=120.0)
    parser.add_argument("--auto-min-block", default="8m")
    parser.add_argument("--auto-max-gap", default="60s")
    parser.add_argument("--auto-smoothing", default="30s")
    parser.add_argument("--auto-tolerance", type=float, default=12.0)
    parser.add_argument(
        "--steady-vt1",
        action="store_true",
        help="Also run steady VT1-style work segment detection",
    )
    parser.add_argument(
        "--outdoor-vt1",
        action="store_true",
        help="Include outdoor VT1/endurance pacing analysis in brief output",
    )
    parser.add_argument(
        "--no-auto-outdoor-vt1",
        action="store_true",
        help="Do not auto-add outdoor VT1 pacing analysis for qualifying brief ride activities",
    )
    parser.add_argument(
        "--indoor-vt1",
        action="store_true",
        help="Include indoor VT1/endurance quality analysis in brief output",
    )
    parser.add_argument(
        "--no-auto-indoor-vt1",
        action="store_true",
        help="Do not auto-add indoor VT1 quality analysis for qualifying brief trainer activities",
    )
    parser.add_argument(
        "--vt1-watts",
        type=float,
        help="Working VT1 anchor for VT1 quality caps; caller should pass this from preferences",
    )
    parser.add_argument(
        "--vt2-watts",
        type=float,
        help=(
            "Working VT2 anchor for VT2 quality diagnostics. If omitted, brief output "
            "still evaluates blocks that look VT2-like from activity name or power."
        ),
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
            "relative_to_power_drift": half_relative_to_power_drift(rows),
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
        result["steady_vt1_segment"]["relative_to_power_drift"] = half_relative_to_power_drift(
            segment_rows
        )

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

    if args.auto_blocks:
        blocks = detect_stable_power_blocks(
            rows,
            min_power=args.auto_min_power,
            min_seconds=parse_duration(args.auto_min_block),
            max_gap_seconds=parse_duration(args.auto_max_gap),
            smoothing_seconds=parse_duration(args.auto_smoothing),
            tolerance=args.auto_tolerance,
        )
        result["auto_power_blocks"] = [
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
        result["_outdoor_vt1_requested"] = args.outdoor_vt1
        result["_outdoor_vt1_disabled"] = args.no_auto_outdoor_vt1
        result["_indoor_vt1_requested"] = args.indoor_vt1
        result["_indoor_vt1_disabled"] = args.no_auto_indoor_vt1
        result["_vt1_watts"] = args.vt1_watts
        result["_vt2_watts"] = args.vt2_watts
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
        "trainer": metadata.get("trainer"),
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
        "auto_power_blocks": [
            {
                "label": block["label"],
                "start_time": block["start_time"],
                "end_time": block["end_time"],
                "duration_minutes": block["duration_minutes"],
                "detection": block["detection"],
                **compact_summary_block(block, fields),
            }
            for block in result.get("auto_power_blocks", [])
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
    auto_blocks = result.get("auto_power_blocks") or []
    saved_work_intervals = [
        interval
        for interval in result.get("intervals", [])
        if str(interval.get("type") or "").upper() == "WORK"
    ]
    work_blocks = detected_blocks or auto_blocks or saved_work_intervals
    if detected_blocks:
        block_source = "detected_power_blocks"
    elif auto_blocks:
        block_source = "auto_power_blocks"
    else:
        block_source = "intervals_icu_work_intervals"
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
    vo2_recoveries = brief_recoveries(
        saved_recovery_intervals,
        moxy_recoveries=result.get("moxy", {}).get("recovery_reoxygenation", []),
        work_block_count=len(saved_work_intervals),
    )
    post_work_blocks = brief_post_work_blocks(
        saved_recovery_intervals,
        work_block_count=len(work_blocks),
    )
    hard_block = hardest_block(work_blocks)
    beta_stability = beta_stability_debug(result["activity"], work_blocks, recoveries)
    beta_vo2 = beta_vo2_debug(result["activity"], rows, saved_work_intervals, vo2_recoveries)
    long_pauses = detect_pause_segments(rows, min_seconds=60)
    include_outdoor_vt1 = should_include_outdoor_vt1(
        result["activity"],
        rows,
        force=bool(result.get("_outdoor_vt1_requested")),
        disabled=bool(result.get("_outdoor_vt1_disabled")),
    )
    include_indoor_vt1 = should_include_indoor_vt1(
        result["activity"],
        rows,
        force=bool(result.get("_indoor_vt1_requested")),
        disabled=bool(result.get("_indoor_vt1_disabled")),
    )
    brief = {
        "activity": brief_activity(result["activity"]),
        "streams": {
            "rows": result["streams"]["rows"],
            "ignored_fields": result["streams"].get("ignored_fields", []),
            "data_quality_issues": compact_quality(result["streams"]["data_quality"]),
        },
        "total": brief_total(result["total"]),
        "long_pauses": long_pauses,
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
        "beta_stability": beta_stability,
        "beta_vo2": beta_vo2,
        "beta_summary": beta_summary(result["activity"], beta_stability, beta_vo2),
        "steady_vt1_segment": (
            brief_work_block(result["steady_vt1_segment"], index=1)
            if "steady_vt1_segment" in result
            else None
        ),
    }
    if post_work_blocks:
        brief["post_work_blocks"] = post_work_blocks
    vt1_watts = result.get("_vt1_watts")
    outdoor_vt1_requested = bool(result.get("_outdoor_vt1_requested"))
    indoor_vt1_requested = bool(result.get("_indoor_vt1_requested"))
    if include_outdoor_vt1 and isinstance(vt1_watts, (int, float)):
        brief["outdoor_vt1_pacing"] = outdoor_vt1_pacing(
            rows,
            vt1_watts=float(vt1_watts),
            pauses=long_pauses,
            auto_triggered=not outdoor_vt1_requested,
        )
    elif include_outdoor_vt1 and outdoor_vt1_requested:
        brief["outdoor_vt1_pacing"] = {
            "error": "missing_vt1_anchor_watts",
            "message": "Pass --vt1-watts from caller-level preferences.",
        }
    if include_indoor_vt1 and isinstance(vt1_watts, (int, float)):
        brief["indoor_vt1_quality"] = indoor_vt1_quality(
            rows,
            work_blocks=work_blocks,
            vt1_watts=float(vt1_watts),
            pauses=long_pauses,
            auto_triggered=not indoor_vt1_requested,
        )
    elif include_indoor_vt1 and indoor_vt1_requested:
        brief["indoor_vt1_quality"] = {
            "error": "missing_vt1_anchor_watts",
            "message": "Pass --vt1-watts from caller-level preferences.",
        }
    vt2_quality_result = vt2_quality(
        result["activity"],
        rows,
        work_blocks,
        recoveries,
        vt2_watts=result.get("_vt2_watts"),
        beta_stability=beta_stability,
    )
    if vt2_quality_result:
        brief["vt2_quality"] = vt2_quality_result
    return brief


def vt2_quality(
    activity: dict[str, Any],
    rows: list[dict[str, str]],
    work_blocks: list[dict[str, Any]],
    recoveries: list[dict[str, Any]],
    *,
    vt2_watts: Any,
    beta_stability: dict[str, Any],
) -> dict[str, Any] | None:
    """Return VT2/threshold-control diagnostics without touching VT1 scoring."""

    candidates = vt2_candidate_blocks(activity, work_blocks, vt2_watts, beta_stability)
    if not candidates:
        return None

    blocks = [
        vt2_block_quality(
            rows,
            block,
            index=index,
            target_watts=vt2_target_watts(block, vt2_watts),
            anchor_watts=vt2_watts,
        )
        for index, block in candidates
    ]
    blocks = [block for block in blocks if block]
    if not blocks:
        return None

    ratings = [block.get("combined_score") for block in blocks if isinstance(block.get("combined_score"), (int, float))]
    heat_adjusted = [
        block.get("heat_adjusted_response_score")
        for block in blocks
        if isinstance(block.get("heat_adjusted_response_score"), (int, float))
    ]
    limiter_hints: list[str] = []
    for block in blocks:
        limiter_hints.extend(block.get("limiter_hints") or [])
    best = max(blocks, key=lambda block: block.get("duration_s") or 0)

    return drop_none(
        {
            "status": "experimental",
            "meaning": (
                "VT2/threshold control diagnostics. Execution and physiological cost are "
                "scored separately so heat or respiration can explain high cost without "
                "marking the power control itself as poor."
            ),
            "anchor_watts": rounded(vt2_watts, digits=0) if isinstance(vt2_watts, (int, float)) else None,
            "mode": "trainer" if activity.get("trainer") else "outdoor_or_variable",
            "block_count": len(blocks),
            "best_duration_block": best,
            "avg_combined_score": rounded(sum(ratings) / len(ratings), digits=1) if ratings else None,
            "avg_heat_adjusted_response_score": (
                rounded(sum(heat_adjusted) / len(heat_adjusted), digits=1) if heat_adjusted else None
            ),
            "limiter_hints": unique(limiter_hints),
            "blocks": blocks,
        }
    )


def vt2_candidate_blocks(
    activity: dict[str, Any],
    work_blocks: list[dict[str, Any]],
    vt2_watts: Any,
    beta_stability: dict[str, Any],
) -> list[tuple[int, dict[str, Any]]]:
    name = str(activity.get("name") or "").lower().replace("₂", "2")
    assessments = beta_stability.get("blocks") or []
    beta_by_index = {
        int(assessment.get("n")): assessment
        for assessment in assessments
        if isinstance(assessment.get("n"), int)
    }
    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, block in enumerate(work_blocks, start=1):
        summary = block.get("summary") or {}
        watts = stat(summary, "watts", "avg", digits=1)
        duration = block.get("duration_seconds") or 0
        assessment = beta_by_index.get(index) or {}
        zone = str(assessment.get("intended_zone") or "")
        if vt2_candidate_power(watts, vt2_watts, activity_name=name, zone=zone, duration=duration):
            candidates.append((index, block))
    return candidates


def vt2_candidate_power(
    watts: Any,
    vt2_watts: Any,
    *,
    activity_name: str,
    zone: str,
    duration: Any,
) -> bool:
    if not isinstance(watts, (int, float)) or not isinstance(duration, (int, float)):
        return False
    if duration < 5 * 60:
        return False
    if zone in {"vt2", "vt2_like"}:
        return True
    if "vt2" in activity_name and watts >= 250:
        return True
    if isinstance(vt2_watts, (int, float)):
        return vt2_watts - 35 <= watts <= vt2_watts + 25
    return 260 <= watts <= 320


def vt2_target_watts(block: dict[str, Any], vt2_watts: Any) -> float | None:
    if isinstance(vt2_watts, (int, float)):
        return float(vt2_watts)
    watts = stat(block.get("summary") or {}, "watts", "avg", digits=1)
    return float(watts) if isinstance(watts, (int, float)) else None


def vt2_block_quality(
    rows: list[dict[str, str]],
    block: dict[str, Any],
    *,
    index: int,
    target_watts: float | None,
    anchor_watts: Any,
) -> dict[str, Any] | None:
    start = block.get("start_index")
    end = block.get("end_index")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        return None
    segment = rows[start:end]
    pedaling = [row for row in segment if outdoor_pedaling_row(row)]
    if len(pedaling) < 5 * 60:
        return None

    stats = indoor_segment_stats(pedaling)
    summary = block.get("summary") or {}
    drift = block.get("drift") or {}
    relative_drift = block.get("relative_to_power_drift") or {}
    watts_avg = stat(summary, "watts", "avg", digits=1)
    watts_max = stat(summary, "watts", "max", digits=0)
    duration_s = rounded(block.get("duration_seconds"), digits=0)
    stability = vt2_power_stability(segment, target_watts)
    response = vt2_response_scores(
        hr_per_w_drift=relative_drift.get("heartrate"),
        ve_per_w_drift=relative_drift.get("tidal_volume_min"),
        br_per_w_drift=relative_drift.get("respiration"),
        smo2_min=stat(summary, "smo2", "min", digits=1),
        smo2_drift=drift.get("smo2"),
        core_temp_max=stat(summary, "core_temperature", "max", digits=2),
        core_temp_drift=drift.get("core_temperature"),
        vt_drift=drift.get("tidal_volume"),
    )
    recovery = hr_recovery_after_block(rows, block)
    recovery_score = vt2_recovery_score(recovery)
    execution_score = stability.get("execution_score")
    response_score = response.get("response_score")
    heat_adjusted = response.get("heat_adjusted_response_score")
    combined_score = None
    if isinstance(execution_score, (int, float)) and isinstance(response_score, (int, float)):
        recovery_component = recovery_score if isinstance(recovery_score, (int, float)) else response_score
        combined_score = clamp(execution_score * 0.45 + response_score * 0.40 + recovery_component * 0.15, 0, 100)

    limiter_hints = []
    limiter_hints.extend(stability.get("limiter_hints") or [])
    limiter_hints.extend(response.get("limiter_hints") or [])
    if isinstance(recovery_score, (int, float)) and recovery_score < 60:
        limiter_hints.append("slow_hr_recovery")

    return drop_none(
        {
            "n": index,
            "label": brief_block_label(block, index=index),
            "duration_s": duration_s,
            "target_watts": rounded(target_watts, digits=0),
            "target_source": "vt2_anchor" if isinstance(anchor_watts, (int, float)) else "block_average",
            "watts_avg": rounded(watts_avg, digits=0),
            "watts_max": watts_max,
            "execution_score": execution_score,
            "response_score": response_score,
            "heat_adjusted_response_score": heat_adjusted,
            "recovery_score": recovery_score,
            "combined_score": rounded(combined_score, digits=1),
            "rating": vt2_score_rating(combined_score) if isinstance(combined_score, (int, float)) else None,
            "verdict": vt2_verdict(stability, response, combined_score),
            "limiter_hints": unique(limiter_hints) or ["stable"],
            "power_control": stability,
            "physiology": drop_none(
                {
                    **response,
                    "hr_avg": stat(summary, "heartrate", "avg", digits=0),
                    "hr_max": stat(summary, "heartrate", "max", digits=0),
                    "ve_avg": stat(summary, "tidal_volume_min", "avg", digits=1),
                    "ve_max": stat(summary, "tidal_volume_min", "max", digits=1),
                    "br_avg": stat(summary, "respiration", "avg", digits=1),
                    "br_max": stat(summary, "respiration", "max", digits=1),
                    "vt_avg": stat(summary, "tidal_volume", "avg", digits=0),
                    "smo2_avg": stat(summary, "smo2", "avg", digits=1),
                    "core_temp_avg": stat(summary, "core_temperature", "avg", digits=2),
                }
            ),
            "recovery": recovery,
            "segment_stats": stats,
        }
    )


def vt2_power_stability(
    rows: list[dict[str, str]],
    target_watts: float | None,
) -> dict[str, Any]:
    watts = [sample for row in rows if (sample := value(row, "watts")) is not None]
    if not watts:
        return {}
    avg_w = sum(watts) / len(watts)
    target = target_watts if isinstance(target_watts, (int, float)) else avg_w
    within_10 = pct_watts_between(watts, target - 10, target + 10)
    within_20 = pct_watts_between(watts, target - 20, target + 20)
    below_20 = pct_watts_below(watts, target - 20)
    above_20 = pct_watts_above(watts, target + 20)
    avg_delta = avg_w - target
    penalty = min(30, abs(avg_delta) * 1.2)
    if isinstance(within_20, (int, float)):
        penalty += max(0, 75 - within_20) * 0.45
    if isinstance(above_20, (int, float)):
        penalty += above_20 * 0.12
    if isinstance(below_20, (int, float)):
        penalty += below_20 * 0.08
    score = clamp(100 - penalty, 0, 100)
    limiter_hints = []
    if abs(avg_delta) > 15:
        limiter_hints.append("target_mismatch")
    if isinstance(within_20, (int, float)) and within_20 < 65:
        limiter_hints.append("variable_power")
    return drop_none(
        {
            "avg_w": rounded(avg_w, digits=0),
            "target_watts": rounded(target, digits=0),
            "avg_delta_w": rounded(avg_delta, digits=0),
            "pct_within_target_10w": rounded(within_10, digits=1),
            "pct_within_target_20w": rounded(within_20, digits=1),
            "pct_below_target_minus_20w": rounded(below_20, digits=1),
            "pct_above_target_plus_20w": rounded(above_20, digits=1),
            "execution_score": rounded(score, digits=1),
            "limiter_hints": limiter_hints,
        }
    )


def vt2_response_scores(
    *,
    hr_per_w_drift: Any,
    ve_per_w_drift: Any,
    br_per_w_drift: Any,
    smo2_min: Any,
    smo2_drift: Any,
    core_temp_max: Any,
    core_temp_drift: Any,
    vt_drift: Any,
) -> dict[str, Any]:
    penalty = 0.0
    heat_penalty = 0.0
    limiter_hints: list[str] = []
    watch_notes: list[str] = []

    if isinstance(hr_per_w_drift, (int, float)) and hr_per_w_drift > 4:
        amount = min(25, (hr_per_w_drift - 4) * 2.5)
        penalty += amount
        limiter_hints.append("cardiac_drift" if hr_per_w_drift > 8 else "cardiac_drift_watch")
    if isinstance(ve_per_w_drift, (int, float)) and ve_per_w_drift > 6:
        amount = min(25, (ve_per_w_drift - 6) * 2.0)
        penalty += amount
        limiter_hints.append("ventilation_drift" if ve_per_w_drift > 12 else "ventilation_drift_watch")
    if isinstance(br_per_w_drift, (int, float)) and br_per_w_drift > 8:
        amount = min(20, (br_per_w_drift - 8) * 1.8)
        penalty += amount
        limiter_hints.append("breathing_rate_drift" if br_per_w_drift > 14 else "breathing_rate_drift_watch")
    if isinstance(smo2_min, (int, float)):
        if smo2_min < 10:
            penalty += 12
            limiter_hints.append("very_low_smo2")
        elif smo2_min < 18:
            penalty += 6
            watch_notes.append("low_smo2")
    if isinstance(smo2_drift, (int, float)) and smo2_drift < -4:
        penalty += min(12, abs(smo2_drift) * 1.5)
        limiter_hints.append("falling_smo2")
    if isinstance(vt_drift, (int, float)) and vt_drift < -12:
        penalty += min(10, abs(vt_drift + 12) * 0.7)
        limiter_hints.append("falling_tidal_volume")
    if isinstance(core_temp_max, (int, float)):
        if core_temp_max >= 38.3:
            heat_penalty += 14
            limiter_hints.append("heat_cost")
        elif core_temp_max >= 38.0:
            heat_penalty += 8
            watch_notes.append("heat_cost_watch")
    if isinstance(core_temp_drift, (int, float)) and core_temp_drift > 0.4:
        heat_penalty += min(10, (core_temp_drift - 0.4) * 20)
        if "heat_cost" not in limiter_hints:
            limiter_hints.append("heat_cost")

    raw_penalty = penalty + heat_penalty
    response_score = clamp(100 - raw_penalty, 0, 100)
    heat_adjusted_score = clamp(100 - penalty - heat_penalty * 0.35, 0, 100)
    return drop_none(
        {
            "response_score": rounded(response_score, digits=1),
            "heat_adjusted_response_score": rounded(heat_adjusted_score, digits=1),
            "heat_penalty_points": rounded(heat_penalty, digits=1),
            "hr_per_watt_drift_pct": rounded(hr_per_w_drift, digits=1),
            "ve_per_watt_drift_pct": rounded(ve_per_w_drift, digits=1),
            "br_per_watt_drift_pct": rounded(br_per_w_drift, digits=1),
            "smo2_min": rounded(smo2_min, digits=1),
            "smo2_drift": rounded(smo2_drift, digits=1),
            "vt_drift": rounded(vt_drift, digits=1),
            "core_temp_max": rounded(core_temp_max, digits=2),
            "core_temp_drift": rounded(core_temp_drift, digits=2),
            "limiter_hints": unique(limiter_hints),
            "watch_notes": unique(watch_notes),
        }
    )


def vt2_recovery_score(recovery: dict[str, Any] | None) -> float | None:
    if not recovery:
        return None
    drop = recovery.get("drop_bpm")
    if not isinstance(drop, (int, float)):
        return None
    if drop >= 30:
        return 100.0
    if drop >= 20:
        return 85.0
    if drop >= 12:
        return 65.0
    return 45.0


def vt2_verdict(
    stability: dict[str, Any],
    response: dict[str, Any],
    combined_score: float | None,
) -> str | None:
    execution = stability.get("execution_score")
    heat_penalty = response.get("heat_penalty_points")
    heat_adjusted = response.get("heat_adjusted_response_score")
    raw_response = response.get("response_score")
    if not isinstance(combined_score, (int, float)):
        return None
    if isinstance(execution, (int, float)) and execution < 65:
        return "variable_or_off_target_vt2"
    if (
        isinstance(heat_penalty, (int, float))
        and heat_penalty >= 8
        and isinstance(heat_adjusted, (int, float))
        and isinstance(raw_response, (int, float))
        and heat_adjusted - raw_response >= 5
    ):
        return "heat_limited_controlled_vt2"
    if combined_score >= 82:
        return "controlled_vt2"
    if combined_score >= 68:
        return "controlled_high_cost_vt2"
    if combined_score >= 55:
        return "near_upper_control_limit"
    return "above_control_limit"


def vt2_score_rating(score: float | None) -> str | None:
    if not isinstance(score, (int, float)):
        return None
    if score >= 88:
        return "A"
    if score >= 78:
        return "B"
    if score >= 68:
        return "C"
    if score >= 58:
        return "D"
    return "E"


def should_include_indoor_vt1(
    activity: dict[str, Any],
    rows: list[dict[str, str]],
    *,
    force: bool,
    disabled: bool,
) -> bool:
    """Return true when a brief result should include indoor VT1 quality."""

    if force:
        return True
    if disabled:
        return False
    name = str(activity.get("name") or "").lower().replace("₂", "2")
    if "vt1" not in name:
        return False
    if any(token in name for token in ("vo2", "vt2", "anaerob", "sprint")):
        return False
    if not is_indoor_activity(activity, rows):
        return False
    moving_time = activity.get("moving_time")
    elapsed_time = activity.get("elapsed_time")
    duration = moving_time if isinstance(moving_time, (int, float)) else elapsed_time
    if not isinstance(duration, (int, float)) or duration < 20 * 60:
        return False
    intensity = activity.get("icu_intensity")
    if isinstance(intensity, (int, float)) and intensity > 75:
        return False
    return True


def is_indoor_activity(activity: dict[str, Any], rows: list[dict[str, str]]) -> bool:
    if activity.get("trainer") is True:
        return True
    if str(activity.get("type") or "").lower() == "virtualride" and not has_gps_like_stream(rows):
        return True
    return False


def should_include_outdoor_vt1(
    activity: dict[str, Any],
    rows: list[dict[str, str]],
    *,
    force: bool,
    disabled: bool,
) -> bool:
    """Return true when a brief result should include outdoor endurance pacing."""

    if force:
        return True
    if disabled:
        return False
    if str(activity.get("type") or "").lower() not in {"ride", "virtualride"}:
        return False
    name = str(activity.get("name") or "").lower().replace("₂", "2")
    if any(token in name for token in ("vo2", "vt2", "anaerob", "sprint")):
        return False
    moving_time = activity.get("moving_time")
    if not isinstance(moving_time, (int, float)) or moving_time < 90 * 60:
        return False
    intensity = activity.get("icu_intensity")
    if isinstance(intensity, (int, float)) and intensity > 78:
        return False
    return has_gps_like_stream(rows)


def has_gps_like_stream(rows: list[dict[str, str]]) -> bool:
    gps_rows = 0
    for row in rows:
        if value(row, "distance") is None:
            continue
        if value(row, "altitude") is None and value(row, "velocity_smooth") is None:
            continue
        gps_rows += 1
        if gps_rows >= 60:
            return True
    return False


def indoor_vt1_quality(
    rows: list[dict[str, str]],
    *,
    work_blocks: list[dict[str, Any]] | None = None,
    vt1_watts: float,
    pauses: list[dict[str, Any]],
    auto_triggered: bool,
) -> dict[str, Any]:
    """Return indoor VT1 quality diagnostics for steady trainer work."""

    pause_ranges = [
        (int(pause.get("start_s") or 0), int(pause.get("end_s") or 0))
        for pause in pauses
        if pause.get("start_s") is not None and pause.get("end_s") is not None
    ]
    moving_rows = [row for row in rows if outdoor_moving_row(row, pause_ranges)]
    analysis_rows, analysis_window = indoor_vt1_analysis_rows(
        rows,
        moving_rows=moving_rows,
        work_blocks=work_blocks or [],
        vt1_watts=vt1_watts,
    )
    analysis_moving_rows = [
        row for row in analysis_rows if outdoor_moving_row(row, pause_ranges)
    ]
    pedaling_rows = [row for row in analysis_moving_rows if outdoor_pedaling_row(row)]
    vt1_stability_rows = indoor_vt1_power_window_rows(pedaling_rows, vt1_watts)
    caps = indoor_vt1_caps(vt1_watts)
    rolling = {
        "30s": rolling_power_by_time(analysis_rows, 30, pause_ranges),
        "60s": rolling_power_by_time(analysis_rows, 60, pause_ranges),
    }
    first, middle, final = split_rows_by_count(pedaling_rows, parts=3)
    vt1_first, vt1_middle, vt1_final = split_rows_by_count(vt1_stability_rows, parts=3)
    segment_stats = {
        "first_third": indoor_segment_stats(first),
        "middle_third": indoor_segment_stats(middle),
        "final_third": indoor_segment_stats(final),
    }
    vt1_segment_stats = {
        "first_third": indoor_segment_stats(vt1_first),
        "middle_third": indoor_segment_stats(vt1_middle),
        "final_third": indoor_segment_stats(vt1_final),
    }
    stability = indoor_stability(vt1_first, vt1_final)
    assessment = indoor_vt1_assessment(
        vt1_watts=vt1_watts,
        rolling_60=rolling["60s"],
        moving_rows=analysis_moving_rows,
        pedaling_rows=pedaling_rows,
        stability=stability,
    )

    return drop_none(
        {
            "vt1_watts": rounded(vt1_watts, digits=0),
            "caps_watts": caps,
            "auto_triggered": auto_triggered,
            "analysis_window": analysis_window,
            "duration": {
                "moving_min": rounded(len(analysis_moving_rows) / 60, digits=1),
                "pedaling_min": rounded(len(pedaling_rows) / 60, digits=1),
                "vt1_stability_min": rounded(len(vt1_stability_rows) / 60, digits=1),
            },
            "power_control": indoor_power_control(pedaling_rows, vt1_watts),
            "rolling_power_cap_compliance": {
                window: {
                    str(cap): rolling_cap_summary(
                        series,
                        analysis_rows,
                        analysis_moving_rows,
                        pedaling_rows,
                        cap,
                        pause_ranges,
                    )
                    for cap in caps
                    if cap >= vt1_watts
                }
                for window, series in rolling.items()
            },
            "segment_stability": segment_stats,
            "vt1_filtered_segment_stability": vt1_segment_stats,
            "drift": stability,
            "assessment": assessment,
        }
    )


def indoor_vt1_analysis_rows(
    rows: list[dict[str, str]],
    *,
    moving_rows: list[dict[str, str]],
    work_blocks: list[dict[str, Any]],
    vt1_watts: float,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    work_rows = indoor_vt1_rows_from_work_blocks(rows, work_blocks, vt1_watts)
    if work_rows:
        return work_rows

    detected_rows = detect_indoor_vt1_power_segment(rows, moving_rows, vt1_watts)
    if detected_rows:
        return detected_rows

    return moving_rows, {
        "source": "full_moving_window_fallback",
        "start_s": rounded(row_time_value(moving_rows[0]), digits=0) if moving_rows else None,
        "end_s": rounded(row_time_value(moving_rows[-1]), digits=0) if moving_rows else None,
        "duration_min": rounded(len(moving_rows) / 60, digits=1),
        "meaning": "No usable WORK interval or steady VT1 segment was found.",
    }


def indoor_vt1_rows_from_work_blocks(
    rows: list[dict[str, str]],
    work_blocks: list[dict[str, Any]],
    vt1_watts: float,
) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    candidates = [
        block
        for block in work_blocks
        if indoor_vt1_work_block_candidate(block, vt1_watts)
    ]
    if not candidates:
        return None
    starts = [block.get("start_index") for block in candidates]
    ends = [block.get("end_index") for block in candidates]
    if not all(isinstance(index, int) for index in starts + ends):
        return None
    start = max(0, min(starts))
    end = min(len(rows), max(ends))
    if end <= start:
        return None
    selected = rows[start:end]
    pedaling_min = len([row for row in selected if outdoor_pedaling_row(row)]) / 60
    if pedaling_min < 20:
        return None
    return selected, {
        "source": "work_intervals",
        "work_interval_count": len(candidates),
        "start_s": rounded(row_time(rows, start), digits=0),
        "end_s": rounded(row_time(rows, end - 1), digits=0),
        "duration_min": rounded(len(selected) / 60, digits=1),
        "meaning": "Indoor VT1 metrics are computed from matching WORK interval rows.",
    }


def indoor_vt1_work_block_candidate(block: dict[str, Any], vt1_watts: float) -> bool:
    start = block.get("start_index")
    end = block.get("end_index")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        return False
    duration = block.get("duration_seconds")
    if isinstance(duration, (int, float)) and duration < 10 * 60:
        return False
    watts = stat(block.get("summary") or {}, "watts", "avg", digits=1)
    if not isinstance(watts, (int, float)):
        return False
    return vt1_watts - 20 <= watts <= vt1_watts + 15


def detect_indoor_vt1_power_segment(
    rows: list[dict[str, str]],
    moving_rows: list[dict[str, str]],
    vt1_watts: float,
    *,
    tolerance_watts: float = 10,
    max_gap_seconds: int = 30,
    min_duration_seconds: int = 20 * 60,
) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    moving_ids = {id(row) for row in moving_rows}
    lower = vt1_watts - tolerance_watts
    upper = vt1_watts + tolerance_watts
    best: tuple[int, int, int] | None = None
    start: int | None = None
    last_good: int | None = None
    gap = 0

    for index, row in enumerate(rows):
        watts = value(row, "watts")
        good = (
            id(row) in moving_ids
            and watts is not None
            and lower <= watts <= upper
            and outdoor_pedaling_row(row)
        )
        if good:
            if start is None:
                start = index
            last_good = index
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap <= max_gap_seconds:
            continue
        if last_good is not None:
            candidate = (last_good - start + 1, start, last_good)
            if best is None or candidate[0] > best[0]:
                best = candidate
        start = None
        last_good = None
        gap = 0

    if start is not None and last_good is not None:
        candidate = (last_good - start + 1, start, last_good)
        if best is None or candidate[0] > best[0]:
            best = candidate

    if best is None or best[0] < min_duration_seconds:
        return None

    _, start_index, end_index = best
    selected = rows[start_index : end_index + 1]
    return selected, {
        "source": "detected_steady_vt1_power_segment",
        "target_window_watts": [rounded(lower, digits=0), rounded(upper, digits=0)],
        "max_gap_seconds": max_gap_seconds,
        "start_s": rounded(row_time(rows, start_index), digits=0),
        "end_s": rounded(row_time(rows, end_index), digits=0),
        "duration_min": rounded(len(selected) / 60, digits=1),
        "meaning": "Indoor VT1 metrics are computed from the longest steady power segment near the VT1 target.",
    }


def indoor_vt1_power_window_rows(
    rows: list[dict[str, str]],
    vt1_watts: float,
) -> list[dict[str, str]]:
    lower = vt1_watts - 20
    upper = vt1_watts + 10
    filtered = [
        row
        for row in rows
        if (watts := value(row, "watts")) is not None and lower <= watts <= upper
    ]
    return filtered or rows


def indoor_vt1_caps(vt1_watts: float) -> list[int]:
    return [round(vt1_watts + offset) for offset in (-10, 0, 10, 20, 30, 50)]


def indoor_power_control(rows: list[dict[str, str]], vt1_watts: float) -> dict[str, Any]:
    watts = [sample for row in rows if (sample := value(row, "watts")) is not None]
    if not watts:
        return {}
    within_10 = sum(1 for sample in watts if abs(sample - vt1_watts) <= 10)
    below_10 = sum(1 for sample in watts if sample < vt1_watts - 10)
    above_10 = sum(1 for sample in watts if sample > vt1_watts + 10)
    above_20 = sum(1 for sample in watts if sample > vt1_watts + 20)
    return {
        "avg_w": rounded(sum(watts) / len(watts), digits=0),
        "pct_within_vt1_10w": rounded(within_10 / len(watts) * 100, digits=1),
        "pct_below_vt1_minus_10w": rounded(below_10 / len(watts) * 100, digits=1),
        "pct_above_vt1_plus_10w": rounded(above_10 / len(watts) * 100, digits=1),
        "pct_above_vt1_plus_20w": rounded(above_20 / len(watts) * 100, digits=1),
    }


def split_rows_by_count(
    rows: list[dict[str, str]],
    *,
    parts: int,
) -> list[list[dict[str, str]]]:
    if parts <= 0:
        return []
    if not rows:
        return [[] for _ in range(parts)]
    size = len(rows)
    return [
        rows[round(size * index / parts): round(size * (index + 1) / parts)]
        for index in range(parts)
    ]


def indoor_segment_stats(segment: list[dict[str, str]]) -> dict[str, Any]:
    stats = outdoor_segment_stats(segment)
    watts = average_field(segment, "watts")
    hr = average_field(segment, "heartrate")
    ve = average_field(segment, "tidal_volume_min")
    br = average_field(segment, "respiration")
    vt = average_field(segment, "tidal_volume")
    return drop_none(
        {
            **stats,
            "hr_per_w": rounded(hr / watts, digits=3) if hr and watts else None,
            "ve_per_w": rounded(ve / watts, digits=3) if ve and watts else None,
            "br_per_w": rounded(br / watts, digits=3) if br and watts else None,
            "vt_avg": rounded(vt, digits=0),
            "core_avg": rounded(average_field(segment, "core_temperature"), digits=2),
        }
    )


def indoor_stability(
    first: list[dict[str, str]],
    final: list[dict[str, str]],
) -> dict[str, Any]:
    first_stats = indoor_segment_stats(first)
    final_stats = indoor_segment_stats(final)
    return drop_none(
        {
            "hr_per_w_delta_pct": pct_delta(
                first_stats.get("hr_per_w"),
                final_stats.get("hr_per_w"),
            ),
            "ve_per_w_delta_pct": pct_delta(
                first_stats.get("ve_per_w"),
                final_stats.get("ve_per_w"),
            ),
            "br_per_w_delta_pct": pct_delta(
                first_stats.get("br_per_w"),
                final_stats.get("br_per_w"),
            ),
            "w_per_hr_delta_pct": pct_delta(
                first_stats.get("w_per_hr"),
                final_stats.get("w_per_hr"),
            ),
            "core_temp_delta_c": rounded(
                final_stats.get("core_avg") - first_stats.get("core_avg"),
                digits=2,
            )
            if isinstance(first_stats.get("core_avg"), (int, float))
            and isinstance(final_stats.get("core_avg"), (int, float))
            else None,
            "watts_delta": rounded(
                final_stats.get("avg_w") - first_stats.get("avg_w"),
                digits=0,
            )
            if isinstance(first_stats.get("avg_w"), (int, float))
            and isinstance(final_stats.get("avg_w"), (int, float))
            else None,
        }
    )


def pct_delta(start: Any, end: Any) -> float | int | None:
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start == 0:
        return None
    return rounded(((end / start) - 1) * 100, digits=1)


def indoor_vt1_assessment(
    *,
    vt1_watts: float,
    rolling_60: dict[int, float | None],
    moving_rows: list[dict[str, str]],
    pedaling_rows: list[dict[str, str]],
    stability: dict[str, Any],
) -> dict[str, Any]:
    cap10 = round(vt1_watts + 10)
    cap20 = round(vt1_watts + 20)
    cap30 = round(vt1_watts + 30)
    cap50 = round(vt1_watts + 50)
    cap10_pct = rolling_time_over(rolling_60, pedaling_rows, cap10).get("pct") or 0
    cap20_min = rolling_time_over(rolling_60, moving_rows, cap20).get("min") or 0
    cap30_min = rolling_time_over(rolling_60, moving_rows, cap30).get("min") or 0
    cap50_min = rolling_time_over(rolling_60, moving_rows, cap50).get("min") or 0
    duration_min = len(pedaling_rows) / 60
    hr_drift = stability.get("hr_per_w_delta_pct")
    ve_drift = stability.get("ve_per_w_delta_pct")
    br_drift = stability.get("br_per_w_delta_pct")
    core_delta = stability.get("core_temp_delta_c")
    core_max = max_field(pedaling_rows, "core_temperature")

    score = 0
    limiter_hints: list[str] = []
    watch_notes: list[str] = []
    notes: list[str] = []

    if cap50_min > 1 or cap30_min > max(3, duration_min * 0.03):
        score += 2
        limiter_hints.append("power_above_vt1")
    elif cap20_min > max(5, duration_min * 0.08) or cap10_pct > 30:
        score += 1
        limiter_hints.append("upper_vt1_power")

    if isinstance(hr_drift, (int, float)):
        if hr_drift > 6:
            score += 2
            limiter_hints.append("cardiac_drift")
        elif hr_drift > 3:
            score += 1
            watch_notes.append("cardiac_drift_watch")
        notes.append(f"HR/W drift {hr_drift:.1f}%")

    if isinstance(ve_drift, (int, float)):
        if ve_drift > 12:
            score += 2
            limiter_hints.append("ventilation_drift")
        elif ve_drift > 6:
            score += 1
            watch_notes.append("ventilation_drift_watch")
        notes.append(f"VE/W drift {ve_drift:.1f}%")

    if isinstance(br_drift, (int, float)):
        if br_drift > 10:
            if not any("ventilation" in hint for hint in limiter_hints):
                score += 1
                limiter_hints.append("breathing_rate_drift")
            else:
                watch_notes.append("breathing_rate_drift_watch")
        notes.append(f"BR/W drift {br_drift:.1f}%")

    if isinstance(core_max, (int, float)):
        if core_max >= 38.3:
            score += 2
            limiter_hints.append("heat_cost")
        elif core_max >= 38.0 or (
            core_max >= 37.9
            and isinstance(core_delta, (int, float))
            and core_delta > 0.5
        ):
            score += 1
            watch_notes.append("heat_cost_watch")
        notes.append(f"core max {core_max:.2f} C")

    if cap10_pct:
        notes.append(f"60s power over VT1+10 for {cap10_pct:.1f}% of pedaling time")
    if cap30_min:
        notes.append(f"60s power over VT1+30 for {cap30_min:.1f} min")

    if duration_min >= 150 and score == 1:
        score = 0
        notes.append("duration-adjusted: small drift accepted for long VT1")

    if score <= 0:
        rating = "A"
        verdict = "controlled_indoor_vt1"
    elif score == 1:
        rating = "A-"
        verdict = "controlled_with_minor_cost"
    elif score == 2:
        rating = "B"
        verdict = "controlled_but_costly"
    elif score <= 4:
        rating = "C"
        verdict = "too_costly_for_clean_vt1"
    else:
        rating = "D"
        verdict = "likely_above_vt1_or_poorly_controlled"

    if not limiter_hints and score > 0:
        limiter_hints.append("combined_sensor_drift")
    elif not limiter_hints:
        limiter_hints.append("stable")

    return {
        "rating": rating,
        "verdict": verdict,
        "limiter_hints": unique(limiter_hints),
        "watch_notes": unique(watch_notes),
        "score": score,
        "notes": notes,
    }


def unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value_ in values:
        if value_ in seen:
            continue
        seen.add(value_)
        result.append(value_)
    return result


def outdoor_vt1_pacing(
    rows: list[dict[str, str]],
    *,
    vt1_watts: float,
    pauses: list[dict[str, Any]],
    auto_triggered: bool,
) -> dict[str, Any]:
    """Return outdoor VT1/endurance pacing diagnostics for variable terrain."""

    pause_ranges = [
        (int(pause.get("start_s") or 0), int(pause.get("end_s") or 0))
        for pause in pauses
        if pause.get("start_s") is not None and pause.get("end_s") is not None
    ]
    moving_rows = [row for row in rows if outdoor_moving_row(row, pause_ranges)]
    pedaling_rows = [row for row in moving_rows if outdoor_pedaling_row(row)]
    caps = outdoor_vt1_caps(vt1_watts)
    rolling = {
        "30s": rolling_power_by_time(rows, 30, pause_ranges),
        "60s": rolling_power_by_time(rows, 60, pause_ranges),
    }
    rolling_compliance = {
        window: {
            str(cap): rolling_cap_summary(
                series,
                rows,
                moving_rows,
                pedaling_rows,
                cap,
                pause_ranges,
            )
            for cap in caps
        }
        for window, series in rolling.items()
    }
    climbs = detect_outdoor_climbs(rows, pause_ranges)
    climb_times = {
        second
        for climb in climbs
        for second in range(int(climb["start_s"]), int(climb["end_s"]) + 1)
    }
    climb_rows = [row for row in moving_rows if int(row_time_value(row) or -1) in climb_times]
    nonclimb_rows = [row for row in moving_rows if int(row_time_value(row) or -1) not in climb_times]
    post_pause = post_pause_reset(rows, pause_ranges)
    matched_drift = matched_power_drift(pedaling_rows, vt1_watts=vt1_watts)
    experimental_metrics = outdoor_vt1_experimental_metrics(
        rows=rows,
        pedaling_rows=pedaling_rows,
        rolling_30=rolling["30s"],
        rolling_60=rolling["60s"],
        pause_ranges=pause_ranges,
        vt1_watts=vt1_watts,
    )
    quality_scores = outdoor_vt1_quality_scores(
        pedaling_rows=pedaling_rows,
        moving_rows=moving_rows,
        rolling_60_compliance=rolling_compliance.get("60s") or {},
        vt1_watts=vt1_watts,
        matched_drift=matched_drift,
    )
    assessment = outdoor_vt1_assessment(
        vt1_watts=vt1_watts,
        rolling_60=rolling["60s"],
        moving_rows=moving_rows,
        pedaling_rows=pedaling_rows,
        post_pause=post_pause,
    )

    return drop_none(
        {
            "vt1_watts": rounded(vt1_watts, digits=0),
            "caps_watts": caps,
            "auto_triggered": auto_triggered,
            "duration": {
                "moving_min": rounded(len(moving_rows) / 60, digits=1),
                "pedaling_min": rounded(len(pedaling_rows) / 60, digits=1),
            },
            "pedaling_normalized": outdoor_pedaling_normalized(moving_rows, pedaling_rows, vt1_watts),
            "rolling_power_cap_compliance": rolling_compliance,
            "climbs": {
                "count": len(climbs),
                "total_moving_min": rounded(
                    sum((climb["end_s"] - climb["start_s"] + 1) for climb in climbs) / 60,
                    digits=1,
                ),
                "total_gain_m": rounded(
                    sum(climb.get("pos_gain_m") or 0 for climb in climbs),
                    digits=0,
                ),
                "top_by_duration": sorted(
                    climbs,
                    key=lambda climb: climb.get("duration_s") or 0,
                    reverse=True,
                )[:10],
            },
            "climb_vs_nonclimb": {
                "climb": outdoor_segment_stats(climb_rows),
                "nonclimb": outdoor_segment_stats(nonclimb_rows),
            },
            "post_pause_reset": post_pause,
            "matched_power_drift": matched_drift,
            "experimental_metrics": experimental_metrics,
            "quality_scores": quality_scores,
            "training_characterization": outdoor_endurance_characterization(
                assessment=assessment,
                quality_scores=quality_scores,
                rolling_60_compliance=rolling_compliance.get("60s") or {},
                climbs=climbs,
                pedaling_rows=pedaling_rows,
                moving_rows=moving_rows,
                vt1_watts=vt1_watts,
                matched_drift=matched_drift,
            ),
            "assessment": assessment,
        }
    )


def outdoor_vt1_experimental_metrics(
    *,
    rows: list[dict[str, str]],
    pedaling_rows: list[dict[str, str]],
    rolling_30: dict[int, float | None],
    rolling_60: dict[int, float | None],
    pause_ranges: list[tuple[int, int]],
    vt1_watts: float,
) -> dict[str, Any]:
    return drop_none(
        {
            "best_continuous_vt1_blocks": outdoor_best_continuous_vt1_blocks(
                rows,
                pause_ranges=pause_ranges,
                vt1_watts=vt1_watts,
            ),
            "power_bin_physiology": outdoor_power_bin_physiology(pedaling_rows, vt1_watts),
            "late_session_control": outdoor_late_session_control(
                pedaling_rows,
                rolling_60=rolling_60,
                vt1_watts=vt1_watts,
            ),
            "traffic_restart_spikes": outdoor_traffic_restart_spikes(
                rows,
                rolling_30=rolling_30,
                pause_ranges=pause_ranges,
                vt1_watts=vt1_watts,
            ),
            "smo2_response": outdoor_smo2_response(pedaling_rows, vt1_watts),
            "spike_aftereffects": outdoor_spike_aftereffects(
                rows,
                rolling_60=rolling_60,
                pause_ranges=pause_ranges,
                vt1_watts=vt1_watts,
            ),
        }
    )


def outdoor_best_continuous_vt1_blocks(
    rows: list[dict[str, str]],
    *,
    pause_ranges: list[tuple[int, int]],
    vt1_watts: float,
    durations_min: tuple[int, ...] = (60, 90, 120, 150),
    step_seconds: int = 60,
) -> dict[str, Any]:
    moving_rows = [row for row in rows if outdoor_moving_row(row, pause_ranges)]
    if not moving_rows:
        return {}
    rolling_60 = rolling_power_by_time(rows, 60, pause_ranges)
    by_duration = []
    for duration_min in durations_min:
        duration_seconds = duration_min * 60
        if len(moving_rows) < duration_seconds:
            continue
        best = best_continuous_vt1_block_for_duration(
            rows,
            moving_rows=moving_rows,
            rolling_60=rolling_60,
            duration_seconds=duration_seconds,
            step_seconds=step_seconds,
            vt1_watts=vt1_watts,
        )
        if best:
            by_duration.append(best)
    return drop_none(
        {
            "duration_options_min": list(durations_min),
            "step_seconds": step_seconds,
            "best_by_duration": by_duration,
        }
    )


def best_continuous_vt1_block_for_duration(
    rows: list[dict[str, str]],
    *,
    moving_rows: list[dict[str, str]],
    rolling_60: dict[int, float | None],
    duration_seconds: int,
    step_seconds: int,
    vt1_watts: float,
) -> dict[str, Any] | None:
    candidates: list[tuple[float, int, int]] = []
    step = max(1, step_seconds)
    for start_index in range(0, len(moving_rows) - duration_seconds + 1, step):
        window_rows = moving_rows[start_index: start_index + duration_seconds]
        if not window_rows:
            continue
        start = row_time_value(window_rows[0])
        end = row_time_value(window_rows[-1])
        if start is None or end is None:
            continue
        prescore = outdoor_vt1_block_prescore(
            window_rows,
            rolling_60=rolling_60,
            vt1_watts=vt1_watts,
        )
        candidates.append((prescore, start, end))

    best: dict[str, Any] | None = None
    for _, start, end in sorted(candidates, reverse=True)[:5]:
        segment_rows = rows_in_elapsed_range(rows, start, end)
        moving_segment = [
            row
            for row in moving_rows
            if (time := row_time_value(row)) is not None and start <= time <= end
        ]
        candidate = outdoor_vt1_block_quality(
            segment_rows,
            moving_rows=moving_segment,
            vt1_watts=vt1_watts,
            duration_seconds=duration_seconds,
        )
        if not candidate:
            continue
        if best is None or vt1_block_sort_key(candidate) > vt1_block_sort_key(best):
            best = candidate
    return best


def outdoor_vt1_block_prescore(
    moving_rows: list[dict[str, str]],
    *,
    rolling_60: dict[int, float | None],
    vt1_watts: float,
) -> float:
    pedaling_rows = [row for row in moving_rows if outdoor_pedaling_row(row)]
    if not pedaling_rows:
        return -1.0
    cap10 = round(vt1_watts + 10)
    cap30 = round(vt1_watts + 30)
    cap50 = round(vt1_watts + 50)
    cap10_pct = rolling_time_over(rolling_60, pedaling_rows, cap10).get("pct") or 0
    cap30_min = rolling_time_over(rolling_60, moving_rows, cap30).get("min") or 0
    cap50_min = rolling_time_over(rolling_60, moving_rows, cap50).get("min") or 0
    pedaling_pct = len(pedaling_rows) / len(moving_rows) * 100 if moving_rows else 0
    watts = [sample for row in pedaling_rows if (sample := value(row, "watts")) is not None]
    avg_w = sum(watts) / len(watts) if watts else 0
    avg_penalty = abs(avg_w - vt1_watts) * 0.3
    cap_penalty = cap10_pct * 0.45 + cap30_min * 2.0 + cap50_min * 4.0
    continuity_bonus = min(10.0, pedaling_pct / 10)
    return 100 - cap_penalty - avg_penalty + continuity_bonus


def outdoor_vt1_block_quality(
    rows: list[dict[str, str]],
    *,
    moving_rows: list[dict[str, str]],
    vt1_watts: float,
    duration_seconds: int,
) -> dict[str, Any] | None:
    pedaling_rows = [row for row in moving_rows if outdoor_pedaling_row(row)]
    if len(pedaling_rows) < duration_seconds * 0.75:
        return None
    rolling_60 = rolling_power_by_time(rows, 60, [])
    caps = outdoor_vt1_caps(vt1_watts)
    compliance = {
        str(cap): rolling_cap_summary(
            rolling_60,
            rows,
            moving_rows,
            pedaling_rows,
            cap,
            [],
        )
        for cap in caps
    }
    matched = matched_power_drift(pedaling_rows, vt1_watts=vt1_watts)
    quality = outdoor_vt1_quality_scores(
        pedaling_rows=pedaling_rows,
        moving_rows=moving_rows,
        rolling_60_compliance=compliance,
        vt1_watts=vt1_watts,
        matched_drift=matched,
    )
    start_row = moving_rows[0]
    end_row = moving_rows[-1]
    start = row_time_value(start_row)
    end = row_time_value(end_row)
    pedaling = outdoor_pedaling_normalized(moving_rows, pedaling_rows, vt1_watts)
    components = quality.get("components") or {}
    return drop_none(
        {
            "duration_min": rounded(duration_seconds / 60, digits=0),
            "start_s": start,
            "end_s": end,
            "start_min": rounded(start / 60, digits=1) if start is not None else None,
            "end_min": rounded(end / 60, digits=1) if end is not None else None,
            "distance_start_km": rounded(value(start_row, "distance") / 1000, digits=2)
            if value(start_row, "distance") is not None
            else None,
            "distance_end_km": rounded(value(end_row, "distance") / 1000, digits=2)
            if value(end_row, "distance") is not None
            else None,
            "lat_start": rounded(value(start_row, "lat"), digits=5),
            "lng_start": rounded(value(start_row, "lng"), digits=5),
            "lat_end": rounded(value(end_row, "lat"), digits=5),
            "lng_end": rounded(value(end_row, "lng"), digits=5),
            "rating": quality.get("rating"),
            "combined_score": quality.get("combined_score"),
            "control_score": quality.get("control_score"),
            "session_value_score": quality.get("session_value_score"),
            "pedaling_avg_w": pedaling.get("pedaling_avg_w"),
            "pct_in_180_210w": pedaling.get("pct_in_endurance_window"),
            "pct_above_210w": pedaling.get("pct_above_target_window"),
            "cap_vt1_plus_10_pct": components.get("cap_vt1_plus_10_pct"),
            "cap_vt1_plus_30_min": components.get("cap_vt1_plus_30_min"),
            "cap_vt1_plus_50_min": components.get("cap_vt1_plus_50_min"),
            "matched_hr_per_w_delta_pct": components.get("matched_hr_per_w_delta_pct"),
            "matched_ve_per_w_delta_pct": components.get("matched_ve_per_w_delta_pct"),
        }
    )


def vt1_block_sort_key(block: dict[str, Any]) -> tuple[float, float, float]:
    combined = block.get("combined_score")
    control = block.get("control_score")
    value_ = block.get("session_value_score")
    return (
        float(combined) if isinstance(combined, (int, float)) else -1.0,
        float(control) if isinstance(control, (int, float)) else -1.0,
        float(value_) if isinstance(value_, (int, float)) else -1.0,
    )


def rows_in_elapsed_range(
    rows: list[dict[str, str]],
    start: int,
    end: int,
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if (time := row_time_value(row)) is not None and start <= time <= end
    ]


def outdoor_power_bin_physiology(
    pedaling_rows: list[dict[str, str]],
    vt1_watts: float,
) -> list[dict[str, Any]]:
    bins = [
        ("below_vt1_minus_20", None, vt1_watts - 20),
        ("vt1_minus_20_to_vt1", vt1_watts - 20, vt1_watts),
        ("vt1_to_vt1_plus_10", vt1_watts, vt1_watts + 10),
        ("vt1_plus_10_to_30", vt1_watts + 10, vt1_watts + 30),
        ("above_vt1_plus_30", vt1_watts + 30, None),
    ]
    total = len(pedaling_rows)
    result = []
    for label, low, high in bins:
        segment = [
            row
            for row in pedaling_rows
            if power_in_bin(value(row, "watts"), low, high)
        ]
        if not segment:
            continue
        stats = outdoor_segment_stats(segment)
        result.append(
            drop_none(
                {
                    "bin": label,
                    "watts": [
                        rounded(low, digits=0) if low is not None else None,
                        rounded(high, digits=0) if high is not None else None,
                    ],
                    "pedaling_min": rounded(len(segment) / 60, digits=1),
                    "pct_pedaling": rounded(len(segment) / total * 100, digits=1) if total else None,
                    **stats,
                }
            )
        )
    return result


def power_in_bin(
    watts: float | None,
    low: float | None,
    high: float | None,
) -> bool:
    if watts is None:
        return False
    if low is not None and watts < low:
        return False
    if high is not None and watts >= high:
        return False
    return True


def outdoor_late_session_control(
    pedaling_rows: list[dict[str, str]],
    *,
    rolling_60: dict[int, float | None],
    vt1_watts: float,
) -> dict[str, Any]:
    first, middle, final = split_rows_by_count(pedaling_rows, parts=3)
    cap10 = round(vt1_watts + 10)
    cap30 = round(vt1_watts + 30)
    cap50 = round(vt1_watts + 50)
    segments = {
        "first_third": first,
        "middle_third": middle,
        "final_third": final,
    }
    summary = {
        name: drop_none(
            {
                **outdoor_segment_stats(segment),
                "cap_vt1_plus_10_pct": rolling_time_over(rolling_60, segment, cap10).get("pct"),
                "cap_vt1_plus_30_min": rolling_time_over(rolling_60, segment, cap30).get("min"),
                "cap_vt1_plus_50_min": rolling_time_over(rolling_60, segment, cap50).get("min"),
            }
        )
        for name, segment in segments.items()
    }
    first_stats = summary["first_third"]
    final_stats = summary["final_third"]
    summary["final_vs_first"] = drop_none(
        {
            "avg_w_delta": numeric_delta(first_stats.get("avg_w"), final_stats.get("avg_w")),
            "hr_per_w_delta_pct": pct_delta(
                first_stats.get("hr_per_w"),
                final_stats.get("hr_per_w"),
            ),
            "ve_per_w_delta_pct": pct_delta(
                first_stats.get("ve_per_w"),
                final_stats.get("ve_per_w"),
            ),
            "cap_vt1_plus_10_pct_delta": numeric_delta(
                first_stats.get("cap_vt1_plus_10_pct"),
                final_stats.get("cap_vt1_plus_10_pct"),
            ),
            "cap_vt1_plus_30_min_delta": numeric_delta(
                first_stats.get("cap_vt1_plus_30_min"),
                final_stats.get("cap_vt1_plus_30_min"),
            ),
        }
    )
    return summary


def outdoor_traffic_restart_spikes(
    rows: list[dict[str, str]],
    *,
    rolling_30: dict[int, float | None],
    pause_ranges: list[tuple[int, int]],
    vt1_watts: float,
) -> dict[str, Any]:
    stop_segments = detect_traffic_stop_segments(rows, pause_ranges)
    spikes = [
        restart_spike_after_stop(rows, stop, rolling_30, vt1_watts)
        for stop in stop_segments
    ]
    spikes = [spike for spike in spikes if spike is not None]
    spike_cap = vt1_watts + 50
    return {
        "stop_count": len(stop_segments),
        "stop_time_min": rounded(
            sum(stop["end_s"] - stop["start_s"] + 1 for stop in stop_segments) / 60,
            digits=1,
        ),
        "restart_spike_threshold_w": rounded(spike_cap, digits=0),
        "restart_spike_count": len(spikes),
        "restart_spike_max_30s_w": rounded(
            max((spike.get("max_30s_w") or 0 for spike in spikes), default=0),
            digits=0,
        ),
        "top_restart_spikes": sorted(
            spikes,
            key=lambda spike: spike.get("max_30s_w") or 0,
            reverse=True,
        )[:8],
    }


def outdoor_smo2_response(
    pedaling_rows: list[dict[str, str]],
    vt1_watts: float,
) -> dict[str, Any] | None:
    if sum(1 for row in pedaling_rows if value(row, "smo2") is not None) < 10 * 60:
        return None
    low = vt1_watts - 20
    high = vt1_watts + 10
    matched = [
        row
        for row in pedaling_rows
        if (watts := value(row, "watts")) is not None
        and low <= watts <= high
        and value(row, "smo2") is not None
    ]
    if len(matched) < 10 * 60:
        return None
    early, late = split_rows_by_count(matched, parts=2)
    early_smo2 = average_field(early, "smo2")
    late_smo2 = average_field(late, "smo2")
    all_smo2 = [sample for row in pedaling_rows if (sample := value(row, "smo2")) is not None]
    low_smo2 = sum(1 for sample in all_smo2 if sample < 20)
    return drop_none(
        {
            "power_window_watts": [round(low), round(high)],
            "matched_min": rounded(len(matched) / 60, digits=1),
            "early_avg_smo2": rounded(early_smo2, digits=1),
            "late_avg_smo2": rounded(late_smo2, digits=1),
            "smo2_delta": numeric_delta(early_smo2, late_smo2),
            "min_smo2": rounded(min(all_smo2), digits=1) if all_smo2 else None,
            "pct_pedaling_below_20_smo2": rounded(low_smo2 / len(all_smo2) * 100, digits=1)
            if all_smo2
            else None,
        }
    )


def outdoor_spike_aftereffects(
    rows: list[dict[str, str]],
    *,
    rolling_60: dict[int, float | None],
    pause_ranges: list[tuple[int, int]],
    vt1_watts: float,
) -> dict[str, Any]:
    cap = round(vt1_watts + 30)
    bouts = rolling_bouts_over(
        rolling_60,
        rows,
        cap,
        pause_ranges,
        min_seconds=30,
        max_gap_seconds=10,
    )
    effects = [
        spike_aftereffect(rows, start, end)
        for start, end in bouts
    ]
    effects = [effect for effect in effects if effect is not None]
    response_scores = [
        effect["response_score"]
        for effect in effects
        if isinstance(effect.get("response_score"), (int, float))
    ]
    return {
        "cap_watts": cap,
        "bout_count": len(bouts),
        "scored_bout_count": len(effects),
        "avg_response_score": rounded(sum(response_scores) / len(response_scores), digits=1)
        if response_scores
        else None,
        "max_response_score": rounded(max(response_scores), digits=1) if response_scores else None,
        "top_aftereffects": sorted(
            effects,
            key=lambda effect: effect.get("response_score") or 0,
            reverse=True,
        )[:8],
    }


def spike_aftereffect(
    rows: list[dict[str, str]],
    start: int,
    end: int,
) -> dict[str, Any] | None:
    before = rows_in_elapsed_range(rows, max(0, start - 180), start - 1)
    during = rows_in_elapsed_range(rows, start, end)
    after = rows_in_elapsed_range(rows, end + 1, end + 300)
    if len(during) < 20 or len(after) < 60:
        return None
    before_stats = outdoor_segment_stats(before)
    during_stats = outdoor_segment_stats(during)
    after_stats = outdoor_segment_stats(after)
    ve_delta = pct_delta(before_stats.get("ve_per_w"), after_stats.get("ve_per_w"))
    br_delta = pct_delta(before_stats.get("br_per_w"), after_stats.get("br_per_w"))
    hr_delta = pct_delta(before_stats.get("hr_per_w"), after_stats.get("hr_per_w"))
    smo2_delta = numeric_delta(
        average_field(before, "smo2"),
        average_field(after, "smo2"),
    )
    score = 0.0
    if isinstance(ve_delta, (int, float)) and ve_delta > 0:
        score += min(20, ve_delta)
    if isinstance(br_delta, (int, float)) and br_delta > 0:
        score += min(15, br_delta)
    if isinstance(hr_delta, (int, float)) and hr_delta > 0:
        score += min(15, hr_delta)
    if isinstance(smo2_delta, (int, float)) and smo2_delta < 0:
        score += min(10, abs(smo2_delta) * 2)
    return drop_none(
        {
            "start_s": start,
            "end_s": end,
            "duration_s": end - start + 1,
            "duration_min": rounded((end - start + 1) / 60, digits=1),
            "avg_w": during_stats.get("avg_w"),
            "response_score": rounded(score, digits=1),
            "after_ve_per_w_delta_pct": rounded(ve_delta, digits=1),
            "after_br_per_w_delta_pct": rounded(br_delta, digits=1),
            "after_hr_per_w_delta_pct": rounded(hr_delta, digits=1),
            "after_smo2_delta": rounded(smo2_delta, digits=1),
        }
    )


def detect_traffic_stop_segments(
    rows: list[dict[str, str]],
    pause_ranges: list[tuple[int, int]],
    *,
    min_seconds: int = 8,
    max_seconds: int = 180,
) -> list[dict[str, Any]]:
    stops: list[dict[str, Any]] = []
    start: int | None = None
    last: int | None = None
    for row in rows:
        time = row_time_value(row)
        if time is None:
            continue
        stopped = is_traffic_stop_row(row, pause_ranges)
        if stopped:
            if start is None:
                start = time
            last = time
            continue
        if start is not None and last is not None:
            append_traffic_stop(stops, rows, start, last, min_seconds, max_seconds)
        start = None
        last = None
    if start is not None and last is not None:
        append_traffic_stop(stops, rows, start, last, min_seconds, max_seconds)
    return stops


def is_traffic_stop_row(row: dict[str, str], pause_ranges: list[tuple[int, int]]) -> bool:
    time = row_time_value(row)
    if time is None:
        return False
    if any(start <= time <= end for start, end in pause_ranges):
        return False
    speed = value(row, "velocity_smooth")
    watts = value(row, "watts")
    return (
        speed is not None
        and speed < 1.2
        and (watts is None or watts < 40)
    )


def append_traffic_stop(
    stops: list[dict[str, Any]],
    rows: list[dict[str, str]],
    start: int,
    end: int,
    min_seconds: int,
    max_seconds: int,
) -> None:
    duration = end - start + 1
    if duration < min_seconds or duration > max_seconds:
        return
    stats = outdoor_range_stats(rows, start, end)
    stops.append(
        {
            "start_s": start,
            "end_s": end,
            "duration_s": duration,
            "duration_min": rounded(duration / 60, digits=1),
            "distance_km": stats.get("distance_km"),
        }
    )


def restart_spike_after_stop(
    rows: list[dict[str, str]],
    stop: dict[str, Any],
    rolling_30: dict[int, float | None],
    vt1_watts: float,
    *,
    lookahead_seconds: int = 90,
) -> dict[str, Any] | None:
    start = int(stop["end_s"]) + 1
    end = start + lookahead_seconds - 1
    segment = [
        row
        for row in rows
        if (time := row_time_value(row)) is not None and start <= time <= end
    ]
    if not segment:
        return None
    best_time: int | None = None
    best_power: float | None = None
    for row in segment:
        time = row_time_value(row)
        if time is None:
            continue
        power = rolling_30.get(time)
        if not isinstance(power, (int, float)):
            continue
        if best_power is None or power > best_power:
            best_power = power
            best_time = time
    if best_power is None or best_power < vt1_watts + 50:
        return None
    best_row = row_at_time(rows, best_time)
    return drop_none(
        {
            "stop_start_s": stop.get("start_s"),
            "stop_end_s": stop.get("end_s"),
            "stop_duration_s": stop.get("duration_s"),
            "restart_peak_time_s": best_time,
            "max_30s_w": rounded(best_power, digits=0),
            "distance_km": rounded(value(best_row, "distance") / 1000, digits=2)
            if best_row and value(best_row, "distance") is not None
            else None,
            "lat": rounded(value(best_row, "lat"), digits=5) if best_row else None,
            "lng": rounded(value(best_row, "lng"), digits=5) if best_row else None,
        }
    )


def row_at_time(rows: list[dict[str, str]], time: int | None) -> dict[str, str] | None:
    if time is None:
        return None
    for row in rows:
        if row_time_value(row) == time:
            return row
    return None


def numeric_delta(start: Any, end: Any) -> float | int | None:
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return rounded(end - start, digits=1)


def outdoor_vt1_caps(vt1_watts: float) -> list[int]:
    return [round(vt1_watts + offset) for offset in (10, 20, 30, 50, 90)]


def outdoor_pedaling_normalized(
    moving_rows: list[dict[str, str]],
    pedaling_rows: list[dict[str, str]],
    vt1_watts: float,
) -> dict[str, Any]:
    moving_count = len(moving_rows)
    pedaling_count = len(pedaling_rows)
    coasting_count = max(0, moving_count - pedaling_count)
    watts = [sample for row in pedaling_rows if (sample := value(row, "watts")) is not None]
    low = vt1_watts - 20
    high = vt1_watts + 10
    target_low = vt1_watts - 10
    target_high = vt1_watts + 10

    return drop_none(
        {
            "pedaling_avg_w": rounded(sum(watts) / len(watts), digits=0) if watts else None,
            "pedaling_time_pct_of_moving": (
                rounded(pedaling_count / moving_count * 100, digits=1) if moving_count else None
            ),
            "coasting_or_soft_pedaling_min": rounded(coasting_count / 60, digits=1),
            "coasting_or_soft_pedaling_pct": (
                rounded(coasting_count / moving_count * 100, digits=1) if moving_count else None
            ),
            "endurance_window_watts": [round(low), round(high)],
            "pct_in_endurance_window": pct_watts_between(watts, low, high),
            "target_window_watts": [round(target_low), round(target_high)],
            "pct_in_target_window": pct_watts_between(watts, target_low, target_high),
            "pct_below_endurance_window": pct_watts_below(watts, low),
            "pct_above_target_window": pct_watts_above(watts, target_high),
        }
    )


def pct_watts_between(watts: list[float], low: float, high: float) -> float | int | None:
    if not watts:
        return None
    return rounded(sum(1 for sample in watts if low <= sample <= high) / len(watts) * 100, digits=1)


def pct_watts_below(watts: list[float], low: float) -> float | int | None:
    if not watts:
        return None
    return rounded(sum(1 for sample in watts if sample < low) / len(watts) * 100, digits=1)


def pct_watts_above(watts: list[float], high: float) -> float | int | None:
    if not watts:
        return None
    return rounded(sum(1 for sample in watts if sample > high) / len(watts) * 100, digits=1)


def matched_power_drift(
    pedaling_rows: list[dict[str, str]],
    *,
    vt1_watts: float,
) -> dict[str, Any] | None:
    low = vt1_watts - 20
    high = vt1_watts + 10
    matched = [
        row
        for row in pedaling_rows
        if (watts := value(row, "watts")) is not None and low <= watts <= high
    ]
    if len(matched) < 10 * 60:
        return None
    midpoint = len(matched) // 2
    early = matched[:midpoint]
    late = matched[midpoint:]
    early_stats = outdoor_segment_stats(early)
    late_stats = outdoor_segment_stats(late)
    return drop_none(
        {
            "power_window_watts": [round(low), round(high)],
            "matched_min": rounded(len(matched) / 60, digits=1),
            "early": early_stats,
            "late": late_stats,
            "hr_per_w_delta_pct": pct_delta(
                early_stats.get("hr_per_w"),
                late_stats.get("hr_per_w"),
            ),
            "w_per_hr_delta_pct": pct_delta(
                early_stats.get("w_per_hr"),
                late_stats.get("w_per_hr"),
            ),
            "ve_per_w_delta_pct": pct_delta(
                early_stats.get("ve_per_w"),
                late_stats.get("ve_per_w"),
            ),
            "br_per_w_delta_pct": pct_delta(
                early_stats.get("br_per_w"),
                late_stats.get("br_per_w"),
            ),
        }
    )


def outdoor_vt1_quality_scores(
    *,
    pedaling_rows: list[dict[str, str]],
    moving_rows: list[dict[str, str]],
    rolling_60_compliance: dict[str, Any],
    vt1_watts: float,
    matched_drift: dict[str, Any] | None,
) -> dict[str, Any]:
    pedaling_min = len(pedaling_rows) / 60
    moving_min = len(moving_rows) / 60
    cap10 = rolling_cap_metric(rolling_60_compliance, round(vt1_watts + 10), "pct")
    cap30 = rolling_cap_metric(rolling_60_compliance, round(vt1_watts + 30), "min")
    cap50 = rolling_cap_metric(rolling_60_compliance, round(vt1_watts + 50), "min")
    cap30_longest = rolling_cap_longest(rolling_60_compliance, round(vt1_watts + 30))
    cap50_longest = rolling_cap_longest(rolling_60_compliance, round(vt1_watts + 50))
    hr_drift = (matched_drift or {}).get("hr_per_w_delta_pct")
    ve_drift = (matched_drift or {}).get("ve_per_w_delta_pct")
    br_drift = (matched_drift or {}).get("br_per_w_delta_pct")

    execution_penalty = (
        cap10 * 0.45
        + cap30 * 2.0
        + cap50 * 4.0
        + cap30_longest * 1.5
        + cap50_longest * 3.0
    )
    execution_score = clamp(100 - execution_penalty, 0, 100)

    duration_score = clamp(pedaling_min / 150 * 45, 0, 45)
    continuity_score = clamp((pedaling_min / moving_min * 100) / 100 * 15, 0, 15) if moving_min else 0
    response_penalty = 0.0
    if isinstance(hr_drift, (int, float)) and hr_drift > 3:
        response_penalty += min(35, (hr_drift - 3) * 4.0)
    if isinstance(ve_drift, (int, float)) and ve_drift > 6:
        response_penalty += min(35, (ve_drift - 6) * 2.5)
    if isinstance(br_drift, (int, float)) and br_drift > 8:
        response_penalty += min(20, (br_drift - 8) * 2.0)
    response_score = clamp(100 - response_penalty, 0, 100)
    stability_score = response_score * 0.25
    execution_value_score = execution_score * 0.15
    session_value_score = clamp(
        duration_score + continuity_score + stability_score + execution_value_score,
        0,
        100,
    )
    combined_score = clamp(execution_score * 0.45 + response_score * 0.30 + session_value_score * 0.25, 0, 100)

    return {
        "execution_score": rounded(execution_score, digits=1),
        "response_score": rounded(response_score, digits=1),
        "control_score": rounded(execution_score, digits=1),
        "session_value_score": rounded(session_value_score, digits=1),
        "combined_score": rounded(combined_score, digits=1),
        "rating": outdoor_score_rating(combined_score),
        "components": {
            "pedaling_min": rounded(pedaling_min, digits=1),
            "cap_vt1_plus_10_pct": rounded(cap10, digits=1),
            "cap_vt1_plus_30_min": rounded(cap30, digits=1),
            "cap_vt1_plus_50_min": rounded(cap50, digits=1),
            "longest_vt1_plus_30_bout_min": rounded(cap30_longest, digits=1),
            "longest_vt1_plus_50_bout_min": rounded(cap50_longest, digits=1),
            "matched_hr_per_w_delta_pct": rounded(hr_drift, digits=1),
            "matched_ve_per_w_delta_pct": rounded(ve_drift, digits=1),
            "matched_br_per_w_delta_pct": rounded(br_drift, digits=1),
        },
    }


def outdoor_endurance_characterization(
    *,
    assessment: dict[str, Any],
    quality_scores: dict[str, Any],
    rolling_60_compliance: dict[str, Any],
    climbs: list[dict[str, Any]],
    pedaling_rows: list[dict[str, str]],
    moving_rows: list[dict[str, str]],
    vt1_watts: float,
    matched_drift: dict[str, Any] | None,
) -> dict[str, Any]:
    """Classify outdoor endurance rides separately from strict VT1 execution."""

    pedaling_min = len(pedaling_rows) / 60
    moving_min = len(moving_rows) / 60
    climb_min = sum((climb["end_s"] - climb["start_s"] + 1) for climb in climbs) / 60
    cap10_pct = rolling_cap_metric(rolling_60_compliance, round(vt1_watts + 10), "pct")
    cap30_min = rolling_cap_metric(rolling_60_compliance, round(vt1_watts + 30), "min")
    cap50_min = rolling_cap_metric(rolling_60_compliance, round(vt1_watts + 50), "min")
    cap90_min = rolling_cap_metric(rolling_60_compliance, round(vt1_watts + 90), "min")
    execution_score = quality_scores.get("execution_score")
    response_score = quality_scores.get("response_score")
    session_value_score = quality_scores.get("session_value_score")

    strict_vt1_fit = "controlled"
    if assessment.get("verdict") == "too_hard_for_strict_vt1":
        strict_vt1_fit = "poor"
    elif assessment.get("verdict") == "upper_endurance":
        strict_vt1_fit = "partial"

    if cap90_min > 1 or cap50_min > 10 or cap30_min > 20:
        stimulus = "hilly_endurance_with_surges"
    elif cap30_min > 10 or cap10_pct > 20:
        stimulus = "upper_endurance"
    else:
        stimulus = "controlled_endurance"

    physiological_response = "unknown"
    if isinstance(response_score, (int, float)):
        if response_score >= 85:
            physiological_response = "controlled"
        elif response_score >= 65:
            physiological_response = "moderate_drift"
        else:
            physiological_response = "high_cost"

    summary = stimulus
    if strict_vt1_fit == "controlled" and physiological_response == "high_cost":
        summary = "controlled_high_cost_endurance"
    if (
        strict_vt1_fit in {"poor", "partial"}
        and physiological_response in {"controlled", "moderate_drift"}
        and isinstance(session_value_score, (int, float))
        and session_value_score >= 68
    ):
        summary = "not_strict_vt1_but_useful_endurance"

    notes = []
    if strict_vt1_fit == "poor":
        notes.append("strict VT1 execution is poor; do not use the VT1 rating as the whole ride verdict")
    if physiological_response == "controlled":
        notes.append("matched-power physiological response stayed controlled")
    if physiological_response == "high_cost":
        notes.append("power control was acceptable but physiological response was high-cost")
    if cap50_min > 10:
        notes.append(f"substantial time above VT1+50: {cap50_min:.1f} min")
    if climb_min > 30:
        notes.append(f"hilly route: {climb_min:.1f} moving min detected as climbs")

    return drop_none(
        {
            "summary": summary,
            "stimulus": stimulus,
            "strict_vt1_fit": strict_vt1_fit,
            "physiological_response": physiological_response,
            "climb_moving_min": rounded(climb_min, digits=1),
            "climb_moving_pct": rounded((climb_min / moving_min) * 100, digits=1) if moving_min else None,
            "pedaling_min": rounded(pedaling_min, digits=1),
            "cap_vt1_plus_10_pct": rounded(cap10_pct, digits=1),
            "cap_vt1_plus_30_min": rounded(cap30_min, digits=1),
            "cap_vt1_plus_50_min": rounded(cap50_min, digits=1),
            "cap_vt1_plus_90_min": rounded(cap90_min, digits=1),
            "execution_score": rounded(execution_score, digits=1),
            "response_score": rounded(response_score, digits=1),
            "session_value_score": rounded(session_value_score, digits=1),
            "matched_hr_per_w_delta_pct": rounded((matched_drift or {}).get("hr_per_w_delta_pct"), digits=1),
            "matched_ve_per_w_delta_pct": rounded((matched_drift or {}).get("ve_per_w_delta_pct"), digits=1),
            "matched_br_per_w_delta_pct": rounded((matched_drift or {}).get("br_per_w_delta_pct"), digits=1),
            "notes": notes,
        }
    )


def rolling_cap_metric(compliance: dict[str, Any], cap: int, metric: str) -> float:
    data = compliance.get(str(cap)) or {}
    time_over = data.get("time_over_pedaling") or data.get("time_over_moving") or {}
    value_ = time_over.get(metric)
    return float(value_) if isinstance(value_, (int, float)) else 0.0


def rolling_cap_longest(compliance: dict[str, Any], cap: int) -> float:
    data = compliance.get(str(cap)) or {}
    value_ = data.get("longest_bout_min")
    return float(value_) if isinstance(value_, (int, float)) else 0.0


def clamp(value_: float, low: float, high: float) -> float:
    return max(low, min(high, value_))


def outdoor_score_rating(score: float) -> str:
    if score >= 88:
        return "A"
    if score >= 78:
        return "B"
    if score >= 68:
        return "C"
    if score >= 58:
        return "D"
    return "E"


def outdoor_moving_row(row: dict[str, str], pauses: list[tuple[int, int]]) -> bool:
    time = row_time_value(row)
    if time is None:
        return False
    return not any(start <= time <= end for start, end in pauses)


def outdoor_pedaling_row(row: dict[str, str]) -> bool:
    watts = value(row, "watts") or 0
    return watts >= 20


def row_time_value(row: dict[str, str]) -> int | None:
    parsed = value(row, "time")
    return int(parsed) if isinstance(parsed, (int, float)) else None


def rolling_power_by_time(
    rows: list[dict[str, str]],
    window_seconds: int,
    pauses: list[tuple[int, int]],
) -> dict[int, float | None]:
    queue: list[tuple[int, float]] = []
    running_sum = 0.0
    rolled: dict[int, float | None] = {}
    min_samples = max(5, window_seconds // 2)
    for row in rows:
        time = row_time_value(row)
        if time is None:
            continue
        watts = value(row, "watts")
        if not outdoor_moving_row(row, pauses):
            queue.clear()
            running_sum = 0.0
        elif watts is not None:
            queue.append((time, watts))
            running_sum += watts
        while queue and queue[0][0] < time - window_seconds + 1:
            _, old = queue.pop(0)
            running_sum -= old
        rolled[time] = running_sum / len(queue) if len(queue) >= min_samples else None
    return rolled


def rolling_cap_summary(
    series: dict[int, float | None],
    rows: list[dict[str, str]],
    moving_rows: list[dict[str, str]],
    pedaling_rows: list[dict[str, str]],
    cap: int,
    pauses: list[tuple[int, int]],
) -> dict[str, Any]:
    bouts = rolling_bouts_over(series, rows, cap, pauses)
    bout_stats = [outdoor_range_stats(rows, start, end) for start, end in bouts]
    return {
        "time_over_moving": rolling_time_over(series, moving_rows, cap),
        "time_over_pedaling": rolling_time_over(series, pedaling_rows, cap),
        "bout_count": len(bouts),
        "total_bout_min": rounded(sum(end - start + 1 for start, end in bouts) / 60, digits=1),
        "longest_bout_min": rounded(
            max((end - start + 1 for start, end in bouts), default=0) / 60,
            digits=1,
        ),
        "top_bouts": sorted(
            bout_stats,
            key=lambda bout: bout.get("duration_s") or 0,
            reverse=True,
        )[:5],
    }


def rolling_time_over(
    series: dict[int, float | None],
    rows: list[dict[str, str]],
    cap: int,
) -> dict[str, Any]:
    times = [row_time_value(row) for row in rows]
    values = [series.get(time) for time in times if time is not None and series.get(time) is not None]
    count = sum(1 for sample in values if isinstance(sample, (int, float)) and sample >= cap)
    return {
        "min": rounded(count / 60, digits=1),
        "pct": rounded(count / len(values) * 100, digits=1) if values else None,
    }


def rolling_bouts_over(
    series: dict[int, float | None],
    rows: list[dict[str, str]],
    cap: int,
    pauses: list[tuple[int, int]],
    *,
    min_seconds: int = 20,
    max_gap_seconds: int = 10,
) -> list[tuple[int, int]]:
    bouts: list[tuple[int, int]] = []
    start: int | None = None
    last: int | None = None
    gap = 0
    for row in rows:
        time = row_time_value(row)
        if time is None:
            continue
        sample = series.get(time)
        over = (
            outdoor_moving_row(row, pauses)
            and isinstance(sample, (int, float))
            and sample >= cap
        )
        if over:
            if start is None:
                start = time
            last = time
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap > max_gap_seconds:
            if last is not None and last - start + 1 >= min_seconds:
                bouts.append((start, last))
            start = None
            last = None
            gap = 0
    if start is not None and last is not None and last - start + 1 >= min_seconds:
        bouts.append((start, last))
    return bouts


def detect_outdoor_climbs(
    rows: list[dict[str, str]],
    pauses: list[tuple[int, int]],
    *,
    min_seconds: int = 90,
    min_distance_m: float = 250,
    min_grade_pct: float = 2.0,
    max_gap_seconds: int = 20,
) -> list[dict[str, Any]]:
    by_time = {row_time_value(row): row for row in rows if row_time_value(row) is not None}
    climbs: list[dict[str, Any]] = []
    start: int | None = None
    last: int | None = None
    gap = 0
    for row in rows:
        time = row_time_value(row)
        if time is None:
            continue
        previous = by_time.get(time - 60)
        uphill = False
        if previous and outdoor_moving_row(row, pauses):
            distance = value(row, "distance")
            previous_distance = value(previous, "distance")
            altitude = value(row, "altitude")
            previous_altitude = value(previous, "altitude")
            if None not in (distance, previous_distance, altitude, previous_altitude):
                delta_distance = distance - previous_distance
                delta_altitude = altitude - previous_altitude
                grade = 100 * delta_altitude / delta_distance if delta_distance > 0 else 0
                uphill = (
                    delta_distance >= 80
                    and grade >= min_grade_pct
                    and (value(row, "velocity_smooth") or 0) >= 1.2
                )
        if uphill:
            if start is None:
                start = max(0, time - 60)
            last = time
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap > max_gap_seconds:
            append_outdoor_climb(
                climbs,
                rows,
                start=start,
                end=last,
                min_seconds=min_seconds,
                min_distance_m=min_distance_m,
                min_grade_pct=min_grade_pct,
            )
            start = None
            last = None
            gap = 0
    if start is not None:
        append_outdoor_climb(
            climbs,
            rows,
            start=start,
            end=last,
            min_seconds=min_seconds,
            min_distance_m=min_distance_m,
            min_grade_pct=min_grade_pct,
        )
    return merge_nearby_climbs(climbs, rows, max_gap_seconds=45)


def append_outdoor_climb(
    climbs: list[dict[str, Any]],
    rows: list[dict[str, str]],
    *,
    start: int,
    end: int | None,
    min_seconds: int,
    min_distance_m: float,
    min_grade_pct: float,
) -> None:
    if end is None:
        return
    stats = outdoor_range_stats(rows, start, end)
    if (stats.get("duration_s") or 0) < min_seconds:
        return
    if (stats.get("distance_km") or 0) * 1000 < min_distance_m:
        return
    if (stats.get("net_grade_pct") or 0) < min_grade_pct:
        return
    climbs.append(stats)


def merge_nearby_climbs(
    climbs: list[dict[str, Any]],
    rows: list[dict[str, str]],
    *,
    max_gap_seconds: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for climb in climbs:
        if merged and climb["start_s"] - merged[-1]["end_s"] <= max_gap_seconds:
            merged[-1] = outdoor_range_stats(rows, merged[-1]["start_s"], climb["end_s"])
        else:
            merged.append(climb)
    return merged


def outdoor_range_stats(rows: list[dict[str, str]], start: int, end: int) -> dict[str, Any]:
    segment = [
        row
        for row in rows
        if (time := row_time_value(row)) is not None and start <= time <= end
    ]
    stats = outdoor_segment_stats(segment)
    distance_start = first_numeric(segment, "distance")
    distance_end = last_numeric(segment, "distance")
    altitude_start = first_numeric(segment, "altitude")
    altitude_end = last_numeric(segment, "altitude")
    distance_m = (
        distance_end - distance_start
        if distance_start is not None and distance_end is not None
        else None
    )
    net_altitude = (
        altitude_end - altitude_start
        if altitude_start is not None and altitude_end is not None
        else None
    )
    positive_gain = positive_altitude_gain(segment)
    grade = (
        100 * net_altitude / distance_m
        if distance_m and distance_m > 0 and net_altitude is not None
        else None
    )
    return drop_none(
        {
            "start_s": start,
            "end_s": end,
            "duration_s": end - start + 1,
            "duration_min": rounded((end - start + 1) / 60, digits=1),
            "distance_km": rounded(distance_m / 1000, digits=2) if distance_m is not None else None,
            "net_alt_m": rounded(net_altitude, digits=1),
            "pos_gain_m": rounded(positive_gain, digits=1),
            "net_grade_pct": rounded(grade, digits=1),
            **stats,
        }
    )


def outdoor_segment_stats(segment: list[dict[str, str]]) -> dict[str, Any]:
    pedaling = [row for row in segment if outdoor_pedaling_row(row)]
    watts = average_field(pedaling, "watts")
    hr = average_field(pedaling, "heartrate")
    ve = average_field(pedaling, "tidal_volume_min")
    br = average_field(pedaling, "respiration")
    return drop_none(
        {
            "moving_min": rounded(len(segment) / 60, digits=1),
            "pedaling_min": rounded(len(pedaling) / 60, digits=1),
            "avg_w": rounded(watts, digits=0),
            "avg_hr": rounded(hr, digits=0),
            "w_per_hr": rounded(watts / hr, digits=3) if watts and hr else None,
            "hr_per_w": rounded(hr / watts, digits=3) if watts and hr else None,
            "ve_per_w": rounded(ve / watts, digits=3) if ve and watts else None,
            "br_per_w": rounded(br / watts, digits=3) if br and watts else None,
            "smo2_min": rounded(min_field(pedaling, "smo2"), digits=1),
            "core_max": rounded(max_field(pedaling, "core_temperature"), digits=2),
        }
    )


def post_pause_reset(
    rows: list[dict[str, str]],
    pauses: list[tuple[int, int]],
) -> dict[str, Any] | None:
    if not pauses:
        return None
    long_pause = max(pauses, key=lambda pause: pause[1] - pause[0])
    if long_pause[1] - long_pause[0] < 10 * 60:
        return None
    start = long_pause[1] + 1
    first_end = time_after_moving_seconds(rows, start, 20 * 60, pauses)
    second_end = time_after_moving_seconds(rows, first_end + 1, 60 * 60, pauses)
    return {
        "first_20min_after_pause": outdoor_segment_stats(
            rows_in_time_range(rows, start, first_end, pauses)
        ),
        "next_60min_after_that": outdoor_segment_stats(
            rows_in_time_range(rows, first_end + 1, second_end, pauses)
        ),
    }


def time_after_moving_seconds(
    rows: list[dict[str, str]],
    start: int,
    seconds: int,
    pauses: list[tuple[int, int]],
) -> int:
    count = 0
    last = start
    for row in rows:
        time = row_time_value(row)
        if time is None or time < start:
            continue
        last = time
        if outdoor_moving_row(row, pauses):
            count += 1
        if count >= seconds:
            return time
    return last


def rows_in_time_range(
    rows: list[dict[str, str]],
    start: int,
    end: int,
    pauses: list[tuple[int, int]],
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if (time := row_time_value(row)) is not None
        and start <= time <= end
        and outdoor_moving_row(row, pauses)
    ]


def outdoor_vt1_assessment(
    *,
    vt1_watts: float,
    rolling_60: dict[int, float | None],
    moving_rows: list[dict[str, str]],
    pedaling_rows: list[dict[str, str]],
    post_pause: dict[str, Any] | None,
) -> dict[str, Any]:
    cap10 = round(vt1_watts + 10)
    cap30 = round(vt1_watts + 30)
    cap50 = round(vt1_watts + 50)
    cap10_pct = rolling_time_over(rolling_60, pedaling_rows, cap10).get("pct") or 0
    cap30_min = rolling_time_over(rolling_60, moving_rows, cap30).get("min") or 0
    cap50_min = rolling_time_over(rolling_60, moving_rows, cap50).get("min") or 0
    verdict = "controlled_outdoor_vt1"
    if cap50_min > 3 or cap30_min > 10:
        verdict = "upper_endurance"
    if cap10_pct > 20 and cap30_min > 5:
        verdict = "upper_endurance"
    if cap50_min > 10:
        verdict = "too_hard_for_strict_vt1"

    notes = []
    if cap10_pct:
        notes.append(f"60s power over VT1+10 for {cap10_pct:.1f}% of pedaling time")
    if cap30_min:
        notes.append(f"60s power over VT1+30 for {cap30_min:.1f} min")
    if cap50_min:
        notes.append(f"60s power over VT1+50 for {cap50_min:.1f} min")
    if post_pause:
        first = (post_pause.get("first_20min_after_pause") or {}).get("w_per_hr")
        second = (post_pause.get("next_60min_after_that") or {}).get("w_per_hr")
        if isinstance(first, (int, float)) and isinstance(second, (int, float)) and first:
            notes.append(f"post-pause W/HR changed {((second / first) - 1) * 100:.1f}%")
    return {"verdict": verdict, "notes": notes}


def first_numeric(rows: list[dict[str, str]], field: str) -> float | None:
    for row in rows:
        parsed = value(row, field)
        if parsed is not None:
            return parsed
    return None


def last_numeric(rows: list[dict[str, str]], field: str) -> float | None:
    for row in reversed(rows):
        parsed = value(row, field)
        if parsed is not None:
            return parsed
    return None


def average_field(rows: list[dict[str, str]], field: str) -> float | None:
    values = [parsed for row in rows if (parsed := value(row, field)) is not None]
    return sum(values) / len(values) if values else None


def min_field(rows: list[dict[str, str]], field: str) -> float | None:
    values = [parsed for row in rows if (parsed := value(row, field)) is not None]
    return min(values) if values else None


def max_field(rows: list[dict[str, str]], field: str) -> float | None:
    values = [parsed for row in rows if (parsed := value(row, field)) is not None]
    return max(values) if values else None


def positive_altitude_gain(rows: list[dict[str, str]]) -> float:
    gain = 0.0
    previous: float | None = None
    for row in rows:
        altitude = value(row, "altitude")
        if altitude is None:
            continue
        if previous is not None and altitude > previous:
            gain += altitude - previous
        previous = altitude
    return gain


def beta_summary(
    activity: dict[str, Any],
    beta_stability: dict[str, Any],
    beta_vo2: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a compact table-oriented summary of beta analysis sections."""

    activity_name = str(activity.get("name") or "")
    lower_name = activity_name.lower().replace("₂", "2")
    if beta_vo2:
        summary = beta_vo2.get("summary") or {}
        stimulus = summary.get("stimulus") or {}
        return drop_none(
            {
                "category": "VO2",
                "unit_label": "reps",
                "unit_count": beta_vo2.get("rep_count") or summary.get("rep_count"),
                "status": join_status(summary.get("verdict"), stimulus.get("verdict")),
                "parts": [
                    drop_none(
                        {
                            "kind": "vo2",
                            "unit_label": "reps",
                            "unit_count": beta_vo2.get("rep_count") or summary.get("rep_count"),
                            "verdict": summary.get("verdict"),
                            "stimulus": stimulus.get("verdict"),
                            "watts_falloff": summary.get("watts_falloff"),
                        }
                    )
                ],
            }
        )

    assessments = beta_stability.get("blocks") or []
    parts = beta_zone_parts(assessments)
    if "vt2" in lower_name:
        category = "VT2"
    elif "vt1" in lower_name or lower_name.startswith("vt "):
        category = "VT1"
    else:
        category = "Beta"
    return drop_none(
        {
            "category": category,
            "unit_label": "blocks",
            "unit_count": len(assessments),
            "status": beta_parts_status(parts) if parts else "ingen segmenter",
            "parts": parts,
        }
    )


def beta_zone_parts(assessments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = ["vt2", "vt2_like", "vt1", "vt1_like", "unknown_stable", "unknown"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for assessment in assessments:
        grouped.setdefault(str(assessment.get("intended_zone") or "unknown"), []).append(assessment)
    parts = []
    for zone in order:
        blocks = grouped.pop(zone, [])
        if blocks:
            parts.append(beta_zone_part(zone, blocks))
    for zone, blocks in sorted(grouped.items()):
        parts.append(beta_zone_part(zone, blocks))
    return parts


def beta_zone_part(zone: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = {}
    for block in blocks:
        verdict = str(block.get("verdict") or "unknown")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
    return {
        "kind": zone,
        "unit_label": "blocks",
        "unit_count": len(blocks),
        "status": verdict_counts_status(verdicts),
        "verdict_counts": verdicts,
    }


def beta_parts_status(parts: list[dict[str, Any]]) -> str:
    named_parts = [
        f"{part.get('kind')}: {part.get('status')}"
        for part in parts
        if part.get("kind") not in {"unknown", "unknown_stable"}
    ]
    if named_parts:
        return " + ".join(named_parts)
    return "unknown/debug"


def verdict_counts_status(verdicts: dict[str, int]) -> str:
    fragments = []
    controlled = sum(
        verdicts.get(verdict, 0)
        for verdict in (
            "controlled_but_high_cost",
            "controlled_at_intent",
            "stable_at_intent",
            "watch_drift_but_probably_controlled",
        )
    )
    near = verdicts.get("near_upper_control_limit", 0)
    above = verdicts.get("likely_above_intent_late", 0)
    unknown = verdicts.get("mechanically_stable_unknown_intensity", 0)
    if controlled:
        fragments.append(f"{controlled} controlled")
    if near:
        fragments.append(f"{near} near upper")
    if above:
        fragments.append(f"{above} above intent")
    if unknown and not fragments:
        fragments.append(f"{unknown} unknown")
    return ", ".join(fragments) if fragments else "unknown"


def join_status(*values: Any) -> str:
    return "; ".join(str(value) for value in values if value)


def beta_vo2_debug(
    activity: dict[str, Any],
    rows: list[dict[str, str]],
    saved_work_intervals: list[dict[str, Any]],
    recoveries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return experimental VO2Max repeatability signals for short hard reps."""

    activity_name = str(activity.get("name") or "")
    if not vo2_activity_name(activity_name):
        return None

    reps, source = vo2_rep_blocks(
        rows,
        saved_work_intervals,
        activity_name=activity_name,
    )
    if not reps:
        return {
            "status": "experimental",
            "meaning": "Experimental VO2Max repeatability assessment.",
            "reps": [],
            "summary": {"verdict": "no_vo2_reps_detected"},
        }

    assessments = [
        vo2_rep_assessment(rep, index=index, recovery=vo2_recovery_after_rep(recoveries, index))
        for index, rep in enumerate(reps, start=1)
    ]
    summary = vo2_summary(assessments)
    return {
        "status": "experimental",
        "meaning": (
            "Experimental VO2Max repeatability assessment. Use for development/debug "
            "and rep-to-rep pattern checks, not threshold diagnosis."
        ),
        "rep_source": source,
        "assumptions": [
            "VO2Max intent is inferred from the activity name.",
            "Short hard reps are taken from saved WORK intervals when available.",
            "If saved reps are not available, reps are detected from high-power stream sections.",
            "Power repeatability uses a robust first-vs-last portion comparison for short reps.",
            "Respiratory and Moxy signals are reported when present, but not required.",
        ],
        "rep_count": summary.get("rep_count"),
        "summary": summary,
        "reps": assessments,
    }


def vo2_activity_name(activity_name: str) -> bool:
    normalized = activity_name.lower().replace("₂", "2")
    return "vo2" in normalized or "vo₂" in activity_name.lower()


def vo2_rep_blocks(
    rows: list[dict[str, str]],
    saved_work_intervals: list[dict[str, Any]],
    *,
    activity_name: str,
) -> tuple[list[dict[str, Any]], str]:
    expected_reps = vo2_expected_rep_count(activity_name)
    saved_reps = [
        block
        for block in saved_work_intervals
        if vo2_candidate_rep(block)
    ]
    if len(saved_reps) >= 3:
        if expected_reps and len(saved_reps) > expected_reps:
            return saved_reps[:expected_reps], "intervals_icu_work_intervals_capped_to_name"
        return saved_reps, "intervals_icu_work_intervals"

    detected = detect_power_blocks(
        rows,
        threshold=330,
        min_seconds=20,
        max_gap_seconds=8,
        smoothing_seconds=5,
    )
    detected_reps = [
        summarize_block(
            rows,
            start_index=block.start_index,
            end_index=block.end_index,
            label=block.label,
            fields=CORE_STREAMS,
            detection={**block.detection, "source": "vo2_power_detection"},
        )
        for block in detected
    ]
    detected_reps = [
        block
        for block in detected_reps
        if vo2_candidate_rep(block, max_seconds=140)
    ]
    if detected_reps:
        if expected_reps and len(detected_reps) > expected_reps:
            return detected_reps[:expected_reps], "detected_high_power_reps_capped_to_name"
        return detected_reps, "detected_high_power_reps"
    return saved_reps, "intervals_icu_work_intervals"


def vo2_expected_rep_count(activity_name: str) -> int | None:
    normalized = activity_name.lower().replace("₂", "2")
    if "vo2" not in normalized:
        return None
    grouped = re.search(r"\(([^)]+)\)\s*x\s*\d+", normalized)
    if grouped:
        total = 0
        for term in re.split(r"\s*\+\s*", grouped.group(1)):
            try:
                parsed = float(term.replace(",", "."))
            except ValueError:
                continue
            total += int(parsed) if parsed.is_integer() else 1
        return total or None
    single = re.search(r"\b(\d+)\s*x\s*\d+", normalized)
    return int(single.group(1)) if single else None


def vo2_candidate_rep(
    block: dict[str, Any],
    *,
    min_seconds: int = 20,
    max_seconds: int = 120,
    min_watts: int = 300,
) -> bool:
    duration = block.get("duration_seconds")
    watts = stat(block.get("summary") or {}, "watts", "avg", digits=0)
    return (
        isinstance(duration, (int, float))
        and min_seconds <= duration <= max_seconds
        and isinstance(watts, (int, float))
        and watts >= min_watts
    )


def vo2_recovery_after_rep(recoveries: list[dict[str, Any]], rep_index: int) -> dict[str, Any] | None:
    for recovery in recoveries:
        if recovery.get("after_work_block") == rep_index:
            return recovery
    return None


def vo2_rep_assessment(
    block: dict[str, Any],
    *,
    index: int,
    recovery: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = block.get("summary") or {}
    drift = block.get("drift") or {}
    return drop_none(
        {
            "n": index,
            "label": brief_block_label(block, index=index),
            "duration_s": rounded(block.get("duration_seconds"), digits=0),
            "watts_avg": stat(summary, "watts", "avg", digits=0),
            "watts_max": stat(summary, "watts", "max", digits=0),
            "watts_drift": rounded(drift.get("watts"), digits=1),
            "hr_start": stat(summary, "heartrate", "start", digits=0),
            "hr_end": stat(summary, "heartrate", "end", digits=0),
            "hr_max": stat(summary, "heartrate", "max", digits=0),
            "ve_max": stat(summary, "tidal_volume_min", "max", digits=1),
            "br_max": stat(summary, "respiration", "max", digits=1),
            "smo2_min": stat(summary, "smo2", "min", digits=1),
            "smo2_end": stat(summary, "smo2", "end", digits=1),
            "smo2_drift": rounded(drift.get("smo2"), digits=1),
            "recovery_hr_drop": recovery.get("hr_drop_start_to_min") if recovery else None,
            "recovery_smo2_rise": recovery.get("smo2_rise_min_to_peak") if recovery else None,
            "recovery_smo2_peak": recovery.get("smo2_peak") if recovery else None,
        }
    )


def vo2_summary(reps: list[dict[str, Any]]) -> dict[str, Any]:
    rep_sets = vo2_duration_groups(reps)
    trend_reps = vo2_trend_reps(reps)
    watts = numeric_values(trend_reps, "watts_avg")
    power_trend = vo2_power_trend(trend_reps)
    hr_end = numeric_values(trend_reps, "hr_end")
    ve_max = numeric_values(reps, "ve_max")
    br_max = numeric_values(reps, "br_max")
    smo2_min = numeric_values(reps, "smo2_min")
    hr_drops = numeric_values(reps, "recovery_hr_drop")
    verdict, reasons = vo2_verdict(trend_reps, all_reps=reps)
    stimulus = vo2_stimulus(reps)
    return drop_none(
        {
            "rep_count": len(reps),
            "trend_basis": vo2_trend_basis(trend_reps, reps),
            "verdict": verdict,
            "reasons": reasons,
            "stimulus": stimulus,
            "rep_sets": rep_sets if len(rep_sets) > 1 else None,
            "watts_start": power_trend.get("watts_start"),
            "watts_end": power_trend.get("watts_end"),
            "watts_falloff": power_trend.get("watts_falloff"),
            "watts_trend_method": power_trend.get("method"),
            "watts_avg": rounded(sum(watts) / len(watts), digits=0) if watts else None,
            "hr_end_start": hr_end[0] if hr_end else None,
            "hr_end_final": hr_end[-1] if hr_end else None,
            "hr_end_rise": rounded(hr_end[-1] - hr_end[0], digits=0) if len(hr_end) >= 2 else None,
            "ve_max_peak": max(ve_max) if ve_max else None,
            "br_max_peak": max(br_max) if br_max else None,
            "smo2_min_lowest": min(smo2_min) if smo2_min else None,
            "recovery_hr_drop_avg": rounded(sum(hr_drops) / len(hr_drops), digits=1) if hr_drops else None,
        }
    )


def vo2_duration_groups(reps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for rep in reps:
        duration = rep.get("duration_s")
        if not isinstance(duration, (int, float)):
            continue
        bucket = max(15, round(duration / 15) * 15)
        groups.setdefault(bucket, []).append(rep)
    summaries = []
    for duration, group in sorted(groups.items()):
        watts = numeric_values(group, "watts_avg")
        hr_end = numeric_values(group, "hr_end")
        summaries.append(
            drop_none(
                {
                    "duration_s": duration,
                    "rep_count": len(group),
                    "watts_start": watts[0] if watts else None,
                    "watts_end": watts[-1] if watts else None,
                    "watts_falloff": (
                        rounded(watts[-1] - watts[0], digits=0)
                        if len(watts) >= 2
                        else None
                    ),
                    "hr_end_start": hr_end[0] if hr_end else None,
                    "hr_end_final": hr_end[-1] if hr_end else None,
                    "hr_end_rise": (
                        rounded(hr_end[-1] - hr_end[0], digits=0)
                        if len(hr_end) >= 2
                        else None
                    ),
                }
            )
        )
    return summaries


def vo2_trend_reps(reps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = vo2_reps_by_duration(reps)
    if len(groups) <= 1:
        return reps
    longest_duration = max(groups)
    return groups[longest_duration]


def vo2_reps_by_duration(reps: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for rep in reps:
        duration = rep.get("duration_s")
        if not isinstance(duration, (int, float)):
            continue
        bucket = max(15, round(duration / 15) * 15)
        groups.setdefault(bucket, []).append(rep)
    return groups


def vo2_trend_basis(trend_reps: list[dict[str, Any]], all_reps: list[dict[str, Any]]) -> str:
    if len(trend_reps) == len(all_reps):
        return "all_reps"
    durations = numeric_values(trend_reps, "duration_s")
    if not durations:
        return "comparable_reps"
    return f"{round(sum(durations) / len(durations))}s_reps"


def vo2_verdict(
    reps: list[dict[str, Any]],
    *,
    all_reps: list[dict[str, Any]] | None = None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    power_trend = vo2_power_trend(reps)
    hr_end = numeric_values(reps, "hr_end")
    all_reps = all_reps or reps
    smo2_min = numeric_values(all_reps, "smo2_min")
    hr_drops = numeric_values(all_reps, "recovery_hr_drop")
    falloff = power_trend.get("watts_falloff")
    hr_rise = hr_end[-1] - hr_end[0] if len(hr_end) >= 2 else None
    lowest_smo2 = min(smo2_min) if smo2_min else None
    avg_hr_drop = sum(hr_drops) / len(hr_drops) if hr_drops else None

    if isinstance(falloff, (int, float)) and falloff < -35:
        reasons.append("average rep power fades materially across comparable reps")
    elif isinstance(falloff, (int, float)):
        reasons.append("average rep power is broadly repeatable across comparable reps")

    if isinstance(hr_rise, (int, float)) and hr_rise >= 8:
        reasons.append("end-of-rep HR rises across the set")
    elif isinstance(hr_rise, (int, float)):
        reasons.append("end-of-rep HR does not rise much across the set")

    if isinstance(lowest_smo2, (int, float)) and lowest_smo2 < 18:
        reasons.append("SmO2 reaches low values during the reps")

    if isinstance(avg_hr_drop, (int, float)) and avg_hr_drop < 18:
        reasons.append("HR recovery between reps is limited")

    if isinstance(falloff, (int, float)) and falloff < -35:
        return "fading_late", reasons
    if isinstance(avg_hr_drop, (int, float)) and avg_hr_drop < 18:
        return "limited_recovery", reasons
    if isinstance(lowest_smo2, (int, float)) and lowest_smo2 < 18:
        return "high_cost_but_repeatable", reasons
    return "well_controlled", reasons


def vo2_power_trend(reps: list[dict[str, Any]]) -> dict[str, Any]:
    watts = numeric_values(reps, "watts_avg")
    if len(watts) < 2:
        return {}
    if len(watts) >= 6:
        window = max(3, len(watts) // 3)
        start = median(watts[:window])
        end = median(watts[-window:])
        method = f"median_first_last_{window}_reps"
    else:
        start = watts[0]
        end = watts[-1]
        method = "first_last_rep"
    return drop_none(
        {
            "watts_start": rounded(start, digits=0),
            "watts_end": rounded(end, digits=0),
            "watts_falloff": rounded(end - start, digits=0) if start is not None and end is not None else None,
            "method": method,
        }
    )


def vo2_stimulus(reps: list[dict[str, Any]]) -> dict[str, Any]:
    """Assess whether short reps look hard enough to be a VO2Max stimulus."""

    trend_reps = vo2_trend_reps(reps)
    watts = numeric_values(reps, "watts_avg")
    hr_end = numeric_values(reps, "hr_end")
    trend_hr_end = numeric_values(trend_reps, "hr_end")
    ve_max = numeric_values(reps, "ve_max")
    br_max = numeric_values(reps, "br_max")
    smo2_min = numeric_values(reps, "smo2_min")
    smo2_drift = numeric_values(reps, "smo2_drift")

    peak_ve = max(ve_max) if ve_max else None
    peak_br = max(br_max) if br_max else None
    lowest_smo2 = min(smo2_min) if smo2_min else None
    median_power = median(watts)
    peak_hr_end = max(hr_end) if hr_end else None
    hr_rise = trend_hr_end[-1] - trend_hr_end[0] if len(trend_hr_end) >= 2 else None
    desaturating_reps = sum(1 for value_ in smo2_drift if value_ <= -8)

    signals: list[str] = []
    missing: list[str] = []
    score = 0

    if isinstance(median_power, (int, float)) and median_power >= 360:
        score += 1
        signals.append("rep power is clearly above threshold/VT2 range")
    elif median_power is None:
        missing.append("rep power")

    if isinstance(peak_ve, (int, float)) and peak_ve >= 150:
        score += 1
        signals.append("ventilation reaches a high VO2-style level")
    elif peak_ve is None:
        missing.append("ventilation")

    if isinstance(peak_br, (int, float)) and peak_br >= 60:
        score += 1
        signals.append("breathing rate reaches a high VO2-style level")
    elif peak_br is None:
        missing.append("breathing rate")

    if isinstance(lowest_smo2, (int, float)) and lowest_smo2 < 18:
        score += 1
        signals.append("SmO2 reaches low values")
    elif lowest_smo2 is None:
        missing.append("SmO2")

    if desaturating_reps >= max(3, len(reps) // 3):
        score += 1
        signals.append("many reps show clear SmO2 desaturation")

    if isinstance(hr_rise, (int, float)) and hr_rise >= 8:
        score += 1
        signals.append("end-of-rep HR rises across the set")
    elif isinstance(peak_hr_end, (int, float)) and peak_hr_end >= 160:
        score += 1
        signals.append("end-of-rep HR reaches a high absolute level")
    elif not hr_end:
        missing.append("heart rate")

    if score >= 5:
        verdict = "very_strong_vo2_stimulus"
    elif score >= 3:
        verdict = "likely_sufficient_vo2_stimulus"
    elif score >= 2:
        verdict = "possibly_sufficient_but_incomplete"
    else:
        verdict = "questionable_vo2_stimulus"

    return drop_none(
        {
            "verdict": verdict,
            "score": score,
            "signals": signals,
            "missing_signals": missing or None,
            "median_watts": rounded(median_power, digits=0),
            "peak_hr_end": rounded(peak_hr_end, digits=0),
            "hr_end_rise": rounded(hr_rise, digits=0),
            "ve_max_peak": rounded(peak_ve, digits=1),
            "br_max_peak": rounded(peak_br, digits=1),
            "smo2_min_lowest": rounded(lowest_smo2, digits=1),
            "desaturating_rep_count": desaturating_reps if smo2_drift else None,
        }
    )


def numeric_values(blocks: list[dict[str, Any]], key: str) -> list[float | int]:
    return [
        value_
        for block in blocks
        if isinstance((value_ := block.get(key)), (int, float))
    ]


def median(values: list[float | int]) -> float | int | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def beta_stability_debug(
    activity: dict[str, Any],
    work_blocks: list[dict[str, Any]],
    recoveries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return experimental intent-vs-response stability signals.

    This deliberately reports signals and confidence instead of pretending to
    prove ventilatory thresholds from one workout.
    """

    assessments = [
        beta_block_stability(block, index=index, activity_name=str(activity.get("name") or ""))
        for index, block in enumerate(work_blocks, start=1)
    ]
    return {
        "status": "experimental",
        "meaning": (
            "Experimental intent-vs-response assessment. Use as decision support, "
            "not as a threshold diagnosis."
        ),
        "assumptions": [
            "Intent is inferred from activity name and stable power level.",
            "Power stability and physiological drift are evaluated separately.",
            "Respiratory and Moxy signals are ignored when missing or clearly unusable.",
        ],
        "blocks": assessments,
        "groups": beta_stability_groups(assessments, recoveries),
    }


def beta_block_stability(
    block: dict[str, Any],
    *,
    index: int,
    activity_name: str,
) -> dict[str, Any]:
    summary = block.get("summary") or {}
    drift = block.get("drift") or {}
    relative_drift = block.get("relative_to_power_drift") or {}
    watts = stat(summary, "watts", "avg", digits=0)
    hr = stat(summary, "heartrate", "avg", digits=0)
    ve = stat(summary, "tidal_volume_min", "avg", digits=1)
    br = stat(summary, "respiration", "avg", digits=1)
    w_per_hr = beta_w_per_hr(summary)
    intended_zone, intent_reasons = beta_intended_zone(activity_name, watts)
    signals = beta_stability_signals(summary, drift, relative_drift)
    verdict, confidence, verdict_reasons = beta_stability_verdict(intended_zone, signals)
    return drop_none(
        {
            "n": index,
            "label": block.get("label"),
            "intended_zone": intended_zone,
            "intent_reasons": intent_reasons,
            "verdict": verdict,
            "confidence": confidence,
            "reasons": verdict_reasons,
            "duration_s": rounded(block.get("duration_seconds"), digits=0),
            "watts_avg": watts,
            "hr_avg": hr,
            "w_per_hr": w_per_hr,
            "ve_avg": ve,
            "br_avg": br,
            "signals": signals,
        }
    )


def beta_intended_zone(activity_name: str, watts: float | int | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    name = activity_name.lower()
    if watts is None:
        return "unknown", ["missing power average"]

    if "vt2" in name and watts >= 260:
        reasons.append("activity name contains VT2 and block power is high")
        return "vt2", reasons
    if ("vt1" in name or name.startswith("vt ")) and 170 <= watts <= 230:
        reasons.append("activity name contains VT1/VT and block power is in known steady range")
        return "vt1", reasons
    if 185 <= watts <= 220:
        reasons.append("stable power is near the user's typical VT1 range")
        return "vt1_like", reasons
    if 270 <= watts <= 315:
        reasons.append("stable power is near the user's typical VT2 range")
        return "vt2_like", reasons
    reasons.append("power does not match a configured VT1/VT2 heuristic")
    return "unknown_stable", reasons


def beta_stability_signals(
    summary: dict[str, Any],
    drift: dict[str, Any],
    relative_drift: dict[str, Any],
) -> dict[str, Any]:
    return drop_none(
        {
            "mechanical_power": beta_power_signal(drift.get("watts")),
            "hr_drift": beta_drift_signal(drift.get("heartrate"), stable=3, elevated=6),
            "hr_per_watt_drift": beta_drift_signal(
                relative_drift.get("heartrate"),
                stable=3,
                elevated=6,
            ),
            "ve_drift": beta_drift_signal(drift.get("tidal_volume_min"), stable=5, elevated=10),
            "ve_per_watt_drift": beta_drift_signal(
                relative_drift.get("tidal_volume_min"),
                stable=5,
                elevated=10,
            ),
            "br_drift": beta_drift_signal(drift.get("respiration"), stable=3, elevated=6),
            "br_per_watt_drift": beta_drift_signal(
                relative_drift.get("respiration"),
                stable=3,
                elevated=6,
            ),
            "vt_drift": beta_tidal_volume_signal(drift.get("tidal_volume")),
            "smo2_drift": beta_smo2_signal(drift.get("smo2")),
            "smo2_min": beta_smo2_min_signal(stat(summary, "smo2", "min", digits=1)),
        }
    )


def beta_power_signal(drift: Any) -> str | None:
    if not isinstance(drift, (int, float)):
        return None
    if abs(drift) <= 2:
        return "stable"
    if abs(drift) <= 8:
        return "slightly_variable"
    return "variable"


def beta_drift_signal(value_: Any, *, stable: float, elevated: float) -> str | None:
    if not isinstance(value_, (int, float)):
        return None
    if value_ <= stable:
        return "stable_or_falling"
    if value_ <= elevated:
        return "moderate_upward_drift"
    return "high_upward_drift"


def beta_tidal_volume_signal(value_: Any) -> str | None:
    if not isinstance(value_, (int, float)):
        return None
    if value_ < -8:
        return "falling_tidal_volume"
    if value_ > 8:
        return "rising_tidal_volume"
    return "stable"


def beta_smo2_signal(value_: Any) -> str | None:
    if not isinstance(value_, (int, float)):
        return None
    if value_ < -5:
        return "falling_smo2"
    if value_ > 5:
        return "recovering_or_rising_smo2"
    return "stable"


def beta_smo2_min_signal(value_: float | int | None) -> str | None:
    if value_ is None:
        return None
    if value_ < 10:
        return "very_low"
    if value_ < 18:
        return "low"
    return "not_low"


def beta_stability_verdict(
    intended_zone: str,
    signals: dict[str, Any],
) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    drift_fields = beta_effective_drift_fields(signals)
    high_drift = any(
        signals.get(field) == "high_upward_drift"
        for field in drift_fields
    )
    moderate_drift = any(
        signals.get(field) == "moderate_upward_drift"
        for field in drift_fields
    )
    falling_smo2 = signals.get("smo2_drift") == "falling_smo2"
    low_smo2 = signals.get("smo2_min") in {"low", "very_low"}
    power_stable = signals.get("mechanical_power") == "stable"

    if intended_zone in {"vt1", "vt1_like"}:
        if high_drift or falling_smo2:
            reasons.append("VT1-intent shows high upward drift or falling SmO2")
            return "likely_above_intent_late", "medium", reasons
        if moderate_drift:
            reasons.append("VT1-intent has moderate physiological drift")
            return "watch_drift_but_probably_controlled", "medium", reasons
        reasons.append("VT1-intent has stable/falling physiological cost")
        return "stable_at_intent", "medium_high" if power_stable else "medium", reasons

    if intended_zone in {"vt2", "vt2_like"}:
        if high_drift or (falling_smo2 and low_smo2):
            reasons.append("VT2-intent shows high cost accumulation")
            return "near_upper_control_limit", "medium", reasons
        if moderate_drift or low_smo2:
            reasons.append("VT2-intent is controlled mechanically but physiologically costly")
            return "controlled_but_high_cost", "medium_high" if power_stable else "medium", reasons
        reasons.append("VT2-intent appears controlled")
        return "controlled_at_intent", "medium", reasons

    reasons.append("Intent is unclear, so only mechanical stability is assessed")
    return "mechanically_stable_unknown_intensity", "low", reasons


def beta_effective_drift_fields(signals: dict[str, Any]) -> tuple[str, str, str]:
    if signals.get("mechanical_power") in {"slightly_variable", "variable"}:
        return (
            "hr_per_watt_drift",
            "ve_per_watt_drift",
            "br_per_watt_drift",
        )
    return ("hr_drift", "ve_drift", "br_drift")


def beta_stability_groups(
    assessments: list[dict[str, Any]],
    recoveries: list[dict[str, Any]],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for assessment in assessments:
        groups.setdefault(str(assessment.get("intended_zone") or "unknown"), []).append(assessment)

    result: dict[str, Any] = {
        zone: beta_group_summary(zone, blocks)
        for zone, blocks in groups.items()
    }
    if recoveries:
        result["recovery_between_blocks"] = beta_recovery_summary(recoveries)
    return result


def beta_group_summary(zone: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    w_per_hr_values = [
        value_
        for block in blocks
        if isinstance((value_ := block.get("w_per_hr")), (int, float))
    ]
    return drop_none(
        {
            "count": len(blocks),
            "zone": zone,
            "verdicts": [block.get("verdict") for block in blocks],
            "w_per_hr_start": rounded(w_per_hr_values[0], digits=3) if w_per_hr_values else None,
            "w_per_hr_end": rounded(w_per_hr_values[-1], digits=3) if w_per_hr_values else None,
            "w_per_hr_delta": (
                rounded(w_per_hr_values[-1] - w_per_hr_values[0], digits=3)
                if len(w_per_hr_values) >= 2
                else None
            ),
        }
    )


def beta_recovery_summary(recoveries: list[dict[str, Any]]) -> dict[str, Any]:
    lows = [
        value_
        for recovery in recoveries
        if isinstance((value_ := recovery.get("hr_min")), (int, float))
    ]
    drops = [
        value_
        for recovery in recoveries
        if isinstance((value_ := recovery.get("hr_drop_start_to_min")), (int, float))
    ]
    return drop_none(
        {
            "count": len(recoveries),
            "hr_min_lowest": min(lows) if lows else None,
            "hr_drop_avg": rounded(sum(drops) / len(drops), digits=1) if drops else None,
        }
    )


def beta_w_per_hr(summary: dict[str, Any]) -> float | None:
    watts = stat(summary, "watts", "avg", digits=1)
    hr = stat(summary, "heartrate", "avg", digits=1)
    if not watts or not hr:
        return None
    return rounded(watts / hr, digits=3)


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
    relative_drift = block.get("relative_to_power_drift") or {}
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
            "hr_per_watt_drift_pct": rounded(relative_drift.get("heartrate"), digits=1),
            "br_drift": rounded(drift.get("respiration"), digits=1),
            "br_per_watt_drift_pct": rounded(relative_drift.get("respiration"), digits=1),
            "ve_drift": rounded(drift.get("tidal_volume_min"), digits=1),
            "ve_per_watt_drift_pct": rounded(relative_drift.get("tidal_volume_min"), digits=1),
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
    relative_drift = block.get("relative_to_power_drift") or {}
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
            "hr_per_watt_drift_pct": rounded(relative_drift.get("heartrate"), digits=1),
            "br_avg": stat(summary, "respiration", "avg", digits=1),
            "br_max": stat(summary, "respiration", "max", digits=1),
            "br_drift": rounded(drift.get("respiration"), digits=1),
            "br_per_watt_drift_pct": rounded(relative_drift.get("respiration"), digits=1),
            "vt_avg": stat(summary, "tidal_volume", "avg", digits=0),
            "vt_max": stat(summary, "tidal_volume", "max", digits=0),
            "vt_drift": rounded(drift.get("tidal_volume"), digits=1),
            "ve_avg": stat(summary, "tidal_volume_min", "avg", digits=1),
            "ve_max": stat(summary, "tidal_volume_min", "max", digits=1),
            "ve_drift": rounded(drift.get("tidal_volume_min"), digits=1),
            "ve_per_watt_drift_pct": rounded(relative_drift.get("tidal_volume_min"), digits=1),
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
    max_recovery_seconds: int = 10 * 60,
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
        if (block.get("duration_seconds") or 0) > max_recovery_seconds:
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


def brief_post_work_blocks(
    blocks: list[dict[str, Any]],
    *,
    work_block_count: int,
    min_seconds: int = 10 * 60,
) -> list[dict[str, Any]]:
    post_work_blocks = []
    for block in blocks:
        after_work_block = recovery_after_work_block(block)
        if after_work_block != work_block_count:
            continue
        if (block.get("duration_seconds") or 0) <= min_seconds:
            continue
        post_work_blocks.append(brief_post_work_block(block, index=len(post_work_blocks) + 1))
    return post_work_blocks


def brief_post_work_block(block: dict[str, Any], *, index: int) -> dict[str, Any]:
    summary = block.get("summary") or {}
    drift = block.get("drift") or {}
    return drop_none(
        {
            "n": index,
            "source_index": block.get("index"),
            "duration_s": rounded(block.get("duration_seconds"), digits=0),
            "watts_avg": stat(summary, "watts", "avg", digits=0),
            "watts_drift": rounded(drift.get("watts"), digits=1),
            "hr_avg": stat(summary, "heartrate", "avg", digits=0),
            "hr_start": stat(summary, "heartrate", "start", digits=0),
            "hr_min": stat(summary, "heartrate", "min", digits=0),
            "hr_end": stat(summary, "heartrate", "end", digits=0),
            "br_avg": stat(summary, "respiration", "avg", digits=1),
            "ve_avg": stat(summary, "tidal_volume_min", "avg", digits=1),
            "core_temp_max": stat(summary, "core_temperature", "max", digits=2),
        }
    )


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
