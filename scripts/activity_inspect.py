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
    brief = {
        "activity": brief_activity(result["activity"]),
        "streams": {
            "rows": result["streams"]["rows"],
            "ignored_fields": result["streams"].get("ignored_fields", []),
            "data_quality_issues": compact_quality(result["streams"]["data_quality"]),
        },
        "total": brief_total(result["total"]),
        "long_pauses": detect_pause_segments(rows, min_seconds=60),
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
    return brief


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
