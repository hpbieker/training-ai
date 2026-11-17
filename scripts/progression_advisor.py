#!/usr/bin/env python3
"""Collect workout-family evidence for a plan-owned progression decision."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA = "training-ai-progression-advisor-v2"
DEFAULT_ARTIFACTS_DIR = Path("outputs/intervals")


@dataclass(frozen=True)
class CandidateActivity:
    activity_dir: Path
    activity_id: str
    name: str
    start: datetime
    elapsed_seconds: float | None
    training_load: float | None
    completed_prescription: dict[str, Any]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect evidence for VT2 or VO2Max progression. The coach applies the "
            "selected plan; this script never invents a next dose."
        )
    )
    parser.add_argument("--type", choices=("vt2", "vo2max"), required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--max-sessions", type=int, default=6)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    parser.add_argument("--plan-progression-json", type=parse_plan_progression_json, default={},
                        help="Selected plan-family context, passed explicitly; never parsed from Markdown.")
    parser.add_argument("--vt2-watts", type=float, help="Explicit reference for historical VT2 inspection.")
    parser.add_argument("--vo2max-watts", type=float, help="Explicit reference for historical VO2 inspection.")
    parser.add_argument("--force-inspect", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    day = parse_date(args.date)
    activities = recent_relevant_activities(
        workout_type=args.type,
        day=day,
        lookback_days=args.lookback_days,
        max_sessions=args.max_sessions,
        artifacts_dir=args.artifacts_dir,
        target_power_w=(args.vt2_watts if args.type == "vt2" else args.vo2max_watts),
    )
    inspected = inspect_activities(activities, args=args)
    advice = progression_review(inspected, plan_progression=args.plan_progression_json)

    payload = {
        "schema": SCHEMA,
        "date": day.isoformat(),
        "type": args.type,
        "generated_at": utc_now_iso(),
        "lookback_days": args.lookback_days,
        "sessions_considered": inspected,
        **advice,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


def recent_relevant_activities(
    *,
    workout_type: str,
    day: date,
    lookback_days: int,
    max_sessions: int,
    artifacts_dir: Path,
    target_power_w: float | None,
) -> list[CandidateActivity]:
    since = day - timedelta(days=lookback_days)
    activities_dir = artifacts_dir / "activities"
    candidates: list[CandidateActivity] = []
    for activity_json in activities_dir.glob("*/activity.json"):
        try:
            metadata = load_activity_metadata(activity_json)
        except (OSError, json.JSONDecodeError):
            continue
        name = str(metadata.get("name") or "")
        if not activity_matches_type(
            metadata,
            workout_type,
            target_power_w=target_power_w,
        ):
            continue
        start = parse_optional_datetime(metadata.get("start_date_local"))
        if start is None or not (since <= start.date() <= day):
            continue
        activity_dir = activity_json.parent
        if not (activity_dir / "streams.csv").exists():
            continue
        candidates.append(
            CandidateActivity(
                activity_dir=activity_dir,
                activity_id=str(metadata.get("id") or activity_dir.name),
                name=name,
                start=start,
                elapsed_seconds=number(metadata.get("elapsed_time")),
                training_load=number(metadata.get("icu_training_load")),
                completed_prescription=completed_prescription(
                    name,
                    metadata=metadata,
                    workout_type=workout_type,
                    target_power_w=target_power_w,
                ),
            )
        )
    return sorted(candidates, key=lambda item: item.start, reverse=True)[:max_sessions]


def inspect_activities(
    activities: list[CandidateActivity], *, args: argparse.Namespace
) -> list[dict[str, Any]]:
    if not activities:
        return []
    if args.type == "vt2" and args.vt2_watts is None:
        # Do not let the analysis CLI silently supply a reference power.
        return [inspected_activity_payload(activity, {}, workout_type=args.type)
                for activity in activities]
    command = [
        sys.executable,
        "-B",
        "scripts/activity_inspect_pipeline.py",
        *(str(activity.activity_dir) for activity in activities),
        "--analysis-options-json",
        json.dumps(
            {
                "mode": args.type,
                "shape": "brief",
                **({"vt2_watts": args.vt2_watts} if args.type == "vt2" else {}),
            },
            separators=(",", ":"),
        ),
        "--print-results",
    ]
    if args.force_inspect:
        command.append("--force")
    completed = subprocess.run(
        command,
        check=True,
        cwd=repo_root(),
        text=True,
        capture_output=True,
    )
    raw_results = json.loads(completed.stdout)
    results = raw_results if isinstance(raw_results, list) else [raw_results]
    if len(results) != len(activities):
        raise RuntimeError(
            "activity inspection returned "
            f"{len(results)} results for {len(activities)} activities"
        )
    return [
        inspected_activity_payload(activity, result, workout_type=args.type)
        for activity, result in zip(activities, results, strict=True)
    ]


def inspected_activity_payload(
    activity: CandidateActivity, result: dict[str, Any], *, workout_type: str
) -> dict[str, Any]:
    return {
        "activity_id": activity.activity_id,
        "name": activity.name,
        "date": activity.start.date().isoformat(),
        "elapsed_minutes": round(activity.elapsed_seconds / 60, 1)
        if activity.elapsed_seconds is not None
        else None,
        "training_load": activity.training_load,
        "completed_prescription": activity.completed_prescription,
        "prescription_evidence_limit": (
            "Historical structure inferred from title or intervals; title alone does not "
            "prove completion. This is not a next-workout prescription."
        ),
        "inspect_summary": compact_inspect_summary(result, workout_type=workout_type),
    }


def parse_plan_progression_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("plan progression must be valid JSON") from exc
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("plan progression must be an object")
    return value


def progression_review(
    sessions: list[dict[str, Any]], *, plan_progression: dict[str, Any]
) -> dict[str, Any]:
    """Keep observed execution and existing plan guidance separate from prescription.

    Inspection cannot establish subjective control or subsequent recovery. Even
    mechanically stable work therefore needs synthesis by the coach. Missing
    evidence neither advances nor reduces the achieved anchor. Preserve the
    plan's conditional next-step text verbatim rather than parsing it into watts.
    The concrete workout is supplied separately to recommend_training.py.
    """
    reason = (
        "Review execution, physiological response, athlete feedback and subsequent "
        "recovery against the selected plan before choosing a dose. "
        "No automatic progression, reduction, or repeat is prescribed."
    )
    return {
        "status": "requires_review",
        "current_level": sessions[0].get("completed_prescription") if sessions else None,
        "plan_progression": dict(plan_progression),
        "next_step": {"prescription": None, "reason": reason},
        "avoid": [],
        "coach_summary": "requires_review: " + reason,
    }


def compact_inspect_summary(result: dict[str, Any], *, workout_type: str) -> dict[str, Any]:
    beta_summary = result.get("beta_summary") or {}
    vt2_quality = (result.get("vt2_quality") or {}).get("session_quality") or {}
    hardest = result.get("hardest_block") or {}
    total = result.get("total") or {}
    stability = "unknown"
    physiological_cost = "unknown"

    verdict = str(vt2_quality.get("verdict") or "").lower()
    if any(token in verdict for token in ("failed", "unstable", "variable")):
        stability = "unstable_or_failed"
    elif any(token in verdict for token in ("controlled", "stable")):
        stability = "stable"

    drift_values = [
        number(hardest.get("hr_per_watt_drift_pct")),
        number(hardest.get("ve_per_watt_drift_pct")),
        number(hardest.get("br_per_watt_drift_pct")),
        number(total.get("hr_per_watt_drift_pct")),
        number(total.get("ve_per_watt_drift_pct")),
    ]
    max_drift = max([value for value in drift_values if value is not None], default=None)
    difficulty_markers = [
        number(hardest.get("core_temp_max")),
        number(total.get("core_temp_max")),
    ]
    max_core = max([value for value in difficulty_markers if value is not None], default=None)
    # Drift and wearable temperature remain observations, not cost diagnoses.
    physiological_cost = "requires_synthesis"

    return {
        "category": beta_summary.get("category"),
        "status": beta_summary.get("status"),
        "vt2_verdict": vt2_quality.get("verdict"),
        "stability": stability,
        "physiological_cost": physiological_cost,
        "max_relative_drift_pct": round(max_drift, 1) if max_drift is not None else None,
        "core_temp_max": round(max_core, 2) if max_core is not None else None,
        "hardest_block": {
            "label": hardest.get("label"),
            "duration_s": hardest.get("duration_s"),
            "watts_avg": hardest.get("watts_avg"),
            "watts_drift": hardest.get("watts_drift"),
            "hr_per_watt_drift_pct": hardest.get("hr_per_watt_drift_pct"),
            "ve_per_watt_drift_pct": hardest.get("ve_per_watt_drift_pct"),
        },
    }


def vt2_prescription(*, sets: int, minutes: int, target_power_w: float | None) -> dict[str, Any]:
    return {
        "type": "vt2",
        "structure": f"{sets}x{minutes} min",
        "sets": sets,
        "rep_minutes": minutes,
        "total_work_minutes": sets * minutes,
        "target_power_w": round(target_power_w) if target_power_w is not None else None,
        "recoveries": None,
        "summary": f"VT2 {sets}x{minutes} min @ {format_power(target_power_w)}",
    }


def vt2_bridge_prescription(
    *,
    sets: int,
    minutes: int,
    add_minutes: int,
    target_power_w: float | None,
) -> dict[str, Any]:
    total = sets * minutes + add_minutes
    structure = f"{sets}x{minutes} min + {add_minutes} min"
    return {
        "type": "vt2",
        "structure": structure,
        "sets": sets,
        "rep_minutes": minutes,
        "add_on_minutes": add_minutes,
        "total_work_minutes": total,
        "target_power_w": round(target_power_w) if target_power_w is not None else None,
        "recoveries": None,
        "summary": f"VT2 {structure} @ {format_power(target_power_w)}",
    }


def vo2max_prescription(*, sets: int, reps: int, seconds: int, target_power_w: float | None) -> dict[str, Any]:
    total_reps = sets * reps
    return {
        "type": "vo2max",
        "structure": f"{sets}x{reps}x{seconds}s",
        "sets": sets,
        "reps_per_set": reps,
        "total_reps": total_reps,
        "rep_seconds": seconds,
        "target_power_w": round(target_power_w) if target_power_w is not None else None,
        "recoveries": None,
        "summary": f"VO2Max {sets}x{reps}x{seconds}s @ {format_power(target_power_w)}",
    }


def format_power(value: float | None) -> str:
    return f"{round(value)}W" if value is not None else "unknown power"


def parse_completed_prescription(name: str, *, workout_type: str) -> dict[str, Any]:
    power_match = re.search(r"@\s*(\d+(?:\.\d+)?)\s*W", name, re.IGNORECASE)
    title_power = float(power_match.group(1)) if power_match else None
    if workout_type == "vt2":
        bridge = re.search(
            r"\bVT2\s+(\d+)x(\d+)\s*(?:min)?\s*\+\s*(\d+)\s*min\b",
            name,
            flags=re.IGNORECASE,
        )
        if bridge:
            return vt2_bridge_prescription(
                sets=int(bridge.group(1)),
                minutes=int(bridge.group(2)),
                add_minutes=int(bridge.group(3)),
                target_power_w=title_power,
            )
        match = re.search(r"\bVT2\s+(\d+)x(\d+)\s*min\b", name, flags=re.IGNORECASE)
        if match:
            sets = int(match.group(1))
            minutes = int(match.group(2))
            return vt2_prescription(sets=sets, minutes=minutes, target_power_w=title_power)
        plus = re.search(r"\bVT2\s+(\d+)\+(\d+)\s*min\b", name, flags=re.IGNORECASE)
        if plus:
            values = [int(plus.group(1)), int(plus.group(2))]
            return {
                **vt2_prescription(sets=len(values), minutes=round(sum(values) / len(values)), target_power_w=title_power),
                "structure": "+".join(str(value) for value in values) + " min",
                "total_work_minutes": sum(values),
            }
    else:
        match = re.search(r"\bVO2Max\s+(\d+)x(\d+)x(\d+)", name, flags=re.IGNORECASE)
        if match:
            return vo2max_prescription(
                sets=int(match.group(1)),
                reps=int(match.group(2)),
                seconds=int(match.group(3)),
                target_power_w=title_power,
            )
        match = re.search(r"\bVO2Max\s+(\d+)x(\d+)\s*sec\b", name, flags=re.IGNORECASE)
        if match:
            return vo2max_prescription(
                sets=1,
                reps=int(match.group(1)),
                seconds=int(match.group(2)),
                target_power_w=title_power,
            )
    return {"type": workout_type, "summary": f"unparsed: {name}"}


def completed_prescription(
    name: str,
    *,
    metadata: dict[str, Any],
    workout_type: str,
    target_power_w: float | None,
) -> dict[str, Any]:
    """Use the title when structured, otherwise infer from real interval rows."""

    parsed = parse_completed_prescription(name, workout_type=workout_type)
    if not str(parsed.get("summary") or "").startswith("unparsed:"):
        return parsed
    return infer_prescription_from_intervals(
        metadata,
        workout_type=workout_type,
        target_power_w=target_power_w,
    ) or parsed


def infer_prescription_from_intervals(
    metadata: dict[str, Any],
    *,
    workout_type: str,
    target_power_w: float | None = None,
) -> dict[str, Any] | None:
    intervals = [
        row
        for row in metadata.get("icu_intervals") or []
        if isinstance(row, dict)
    ]
    if workout_type == "vt2":
        if target_power_w is None:
            return None
        # Saved outdoor laps are often labelled WORK even when they are long,
        # easy route sections. Duration alone therefore cannot establish that
        # an activity completed a VT2 prescription. Require the candidate work
        # rows to carry threshold-like power as well.
        work_rows = [
            row
            for row in intervals
            if str(row.get("type") or "").upper() == "WORK"
            and interval_seconds(row) is not None
            and interval_seconds(row) >= 600
            and number(row.get("average_watts")) is not None
            and number(row.get("average_watts")) >= 0.8 * target_power_w
        ]
        if len(work_rows) < 2:
            return None
        work_seconds = [interval_seconds(row) for row in work_rows]
        minutes = round(statistics.median(work_seconds) / 60)
        return vt2_prescription(
            sets=len(work_rows),
            minutes=minutes,
            target_power_w=median_or_default(
                [
                    watts
                    for row in work_rows
                    if (watts := number(row.get("average_watts"))) is not None
                ],
                target_power_w,
            ),
        )

    groups: list[list[float]] = []
    current: list[float] = []
    for row in intervals:
        kind = str(row.get("type") or "").upper()
        seconds = interval_seconds(row)
        if kind == "WORK" and seconds is not None and 45 <= seconds <= 75:
            current.append(seconds)
        elif kind == "RECOVERY" and seconds is not None and seconds > 180 and current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    groups = [group for group in groups if len(group) >= 4]
    total_reps = sum(len(group) for group in groups)
    if total_reps < 6:
        return None
    return vo2max_prescription(
        sets=len(groups),
        reps=round(statistics.median([len(group) for group in groups])),
        seconds=round(statistics.median([seconds for group in groups for seconds in group])),
        target_power_w=median_or_default(
            [
                watts
                for row in intervals
                if str(row.get("type") or "").upper() == "WORK"
                and interval_seconds(row) is not None
                and 45 <= interval_seconds(row) <= 75
                if (watts := number(row.get("average_watts"))) is not None
            ],
            target_power_w,
        ),
    )


def interval_seconds(row: dict[str, Any]) -> float | None:
    return (
        number(row.get("elapsed_time"))
        or number(row.get("moving_time"))
        or number(row.get("duration"))
    )


def median_or_default(values: list[float], default: float | None) -> float | None:
    return statistics.median(values) if values else default


def activity_matches_type(
    metadata: dict[str, Any],
    workout_type: str,
    *,
    target_power_w: float | None,
) -> bool:
    name = str(metadata.get("name") or "")
    if name_matches_type(name, workout_type):
        return True
    return infer_prescription_from_intervals(
        metadata,
        workout_type=workout_type,
        target_power_w=target_power_w,
    ) is not None


def name_matches_type(name: str, workout_type: str) -> bool:
    lowered = name.lower()
    if workout_type == "vt2":
        return "vt2" in lowered or "threshold" in lowered or "terskel" in lowered
    return "vo2" in lowered or "vo2max" in lowered


def load_activity_metadata(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("activity", payload) if isinstance(payload, dict) else {}


def parse_optional_datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def number(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    main()
