#!/usr/bin/env python3
"""Suggest the next sensible workout progression step for a workout family."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


SCHEMA = "training-ai-progression-advisor-v1"
DEFAULT_ARTIFACTS_DIR = Path("outputs/intervals")
DEFAULT_RECOMMENDATIONS_DIR = Path("outputs/recommendations")


@dataclass(frozen=True)
class CandidateActivity:
    activity_dir: Path
    activity_id: str
    name: str
    start: datetime
    elapsed_seconds: float | None
    training_load: float | None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Suggest a progression step for VT2 or VO2Max. This script does not "
            "choose today's training; it provides structured coach input."
        )
    )
    parser.add_argument("--type", choices=("vt2", "vo2max"), required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--max-sessions", type=int, default=6)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    parser.add_argument("--recommendations-dir", type=Path, default=DEFAULT_RECOMMENDATIONS_DIR)
    parser.add_argument("--xert-recommended-training-json", type=Path)
    parser.add_argument("--vt2-watts", type=float, default=295.0)
    parser.add_argument("--vo2max-watts", type=float, default=380.0)
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
    )
    inspected = [
        inspect_activity(activity, args=args)
        for activity in activities
    ]
    xmb_workouts = load_xmb_workouts(args, day=day)
    if args.type == "vt2":
        advice = advise_vt2(inspected, target_power_w=args.vt2_watts)
    else:
        advice = advise_vo2max(inspected, target_power_w=args.vo2max_watts)
    advice["matching_existing_workouts"] = match_existing_xmb_workouts(
        advice.get("next_step", {}).get("prescription") or {},
        xmb_workouts,
        workout_type=args.type,
    )
    advice["xmb_workout_source"] = xmb_workout_source(args, day=day)

    payload = {
        "schema": SCHEMA,
        "date": day.isoformat(),
        "type": args.type,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
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
        if not name_matches_type(name, workout_type):
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
            )
        )
    return sorted(candidates, key=lambda item: item.start, reverse=True)[:max_sessions]


def inspect_activity(activity: CandidateActivity, *, args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        "scripts/activity_inspect_pipeline.py",
        str(activity.activity_dir),
        "--mode",
        args.type,
        "--shape",
        "brief",
        "--print-results",
    ]
    if args.type == "vt2":
        command.extend(["--vt2-watts", format_number(args.vt2_watts)])
    if args.force_inspect:
        command.append("--force")
    completed = subprocess.run(
        command,
        check=True,
        cwd=repo_root(),
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    prescription = parse_completed_prescription(activity.name, workout_type=args.type)
    return {
        "activity_id": activity.activity_id,
        "name": activity.name,
        "date": activity.start.date().isoformat(),
        "elapsed_minutes": round(activity.elapsed_seconds / 60, 1)
        if activity.elapsed_seconds is not None
        else None,
        "training_load": activity.training_load,
        "completed_prescription": prescription,
        "inspect_summary": compact_inspect_summary(result, workout_type=args.type),
    }


def advise_vt2(sessions: list[dict[str, Any]], *, target_power_w: float) -> dict[str, Any]:
    if not sessions:
        prescription = vt2_prescription(sets=2, minutes=12, target_power_w=target_power_w)
        return advice_payload(
            status="not_enough_data",
            prescription=prescription,
            reason="No recent VT2 sessions found in the local activity artifacts.",
            avoid=[],
        )
    latest = sessions[0]
    current = latest.get("completed_prescription") or {}
    sets = int(current.get("sets") or 2)
    minutes = int(current.get("rep_minutes") or 12)
    total_work = sets * minutes
    stability = latest.get("inspect_summary", {}).get("stability")
    cost = latest.get("inspect_summary", {}).get("physiological_cost")

    if stability == "unstable_or_failed":
        next_sets, next_minutes, status = sets, max(10, minutes - 2), "reduce"
        reason = "Latest VT2-like session looked unstable; reduce the work step before progressing."
        prescription = vt2_prescription(
            sets=next_sets,
            minutes=next_minutes,
            target_power_w=target_power_w,
        )
    elif cost == "high":
        status = "repeat_or_bridge"
        prescription = vt2_bridge_prescription(
            sets=sets,
            minutes=minutes,
            add_minutes=5,
            target_power_w=target_power_w,
        )
        reason = (
            "Latest VT2 was completed but physiologically costly; if progressing, "
            "use a small add-on rather than adding a full extra interval."
        )
    elif sets < 3 and total_work < 54:
        status = "small_bridge_progression"
        prescription = vt2_bridge_prescription(
            sets=sets,
            minutes=minutes,
            add_minutes=10,
            target_power_w=target_power_w,
        )
        reason = (
            "Latest VT2 was not yet a full three-set step; add a short bridge "
            "interval rather than jumping directly to a full extra interval."
        )
    elif minutes < 30:
        next_sets, next_minutes, status = sets, minutes + 2, "small_progression"
        reason = "Latest VT2 looked controlled enough for a small duration progression."
        prescription = vt2_prescription(
            sets=next_sets,
            minutes=next_minutes,
            target_power_w=target_power_w,
        )
    else:
        next_sets, next_minutes, status = sets, minutes, "hold"
        reason = "Current VT2 volume is already substantial; hold the level rather than increasing."
        prescription = vt2_prescription(
            sets=next_sets,
            minutes=next_minutes,
            target_power_w=target_power_w,
        )
    avoid = []
    prescription_work = number(prescription.get("total_work_minutes")) or total_work
    if minutes + 4 <= 30:
        avoid.append(
            {
                "prescription": vt2_prescription(
                    sets=max(3, sets),
                    minutes=minutes + 4,
                    target_power_w=target_power_w,
                ),
                "reason": (
                    "Too large a VT2 duration jump from the latest completed step "
                    f"({round(prescription_work)} min planned vs {max(3, sets) * (minutes + 4)} min)."
                ),
            }
        )
    return advice_payload(
        status=status,
        prescription=prescription,
        reason=reason,
        avoid=avoid,
        current_level=current,
    )


def advise_vo2max(sessions: list[dict[str, Any]], *, target_power_w: float) -> dict[str, Any]:
    if not sessions:
        prescription = vo2max_prescription(sets=1, reps=8, seconds=60, target_power_w=target_power_w)
        return advice_payload(
            status="not_enough_data",
            prescription=prescription,
            reason="No recent VO2Max sessions found in the local activity artifacts.",
            avoid=[],
        )
    latest = sessions[0]
    current = latest.get("completed_prescription") or {}
    sets = int(current.get("sets") or 1)
    reps = int(current.get("reps_per_set") or current.get("total_reps") or 8)
    seconds = int(current.get("rep_seconds") or 60)
    stability = latest.get("inspect_summary", {}).get("stability")
    cost = latest.get("inspect_summary", {}).get("physiological_cost")

    if stability == "unstable_or_failed":
        next_sets, next_reps, status = sets, max(6, reps - 1), "reduce"
        reason = "Latest VO2Max session showed instability or fade; reduce before progressing."
    elif cost == "high":
        next_sets, next_reps, status = sets, reps, "repeat"
        reason = "Latest VO2Max session was costly; repeat before adding reps or sets."
    elif sets == 1 and reps < 10:
        next_sets, next_reps, status = sets, reps + 1, "small_progression"
        reason = "Latest VO2Max work looked good enough for one additional rep."
    elif sets == 1:
        next_sets, next_reps, status = 2, 6, "small_progression"
        reason = "Move from one longer set to two smaller sets rather than a large total-volume jump."
    elif reps < 9:
        next_sets, next_reps, status = sets, reps + 1, "small_progression"
        reason = "Progress VO2Max by one rep per set, not by adding a full set."
    else:
        next_sets, next_reps, status = sets, reps, "hold"
        reason = "Current VO2Max level is substantial; hold before progressing."

    prescription = vo2max_prescription(
        sets=next_sets,
        reps=next_reps,
        seconds=seconds,
        target_power_w=target_power_w,
    )
    avoid = [
        {
            "prescription": vo2max_prescription(
                sets=next_sets + 1,
                reps=next_reps,
                seconds=seconds,
                target_power_w=target_power_w,
            ),
            "reason": "Adding a full extra set is a larger progression than needed.",
        }
    ]
    return advice_payload(
        status=status,
        prescription=prescription,
        reason=reason,
        avoid=avoid,
        current_level=current,
    )


def advice_payload(
    *,
    status: str,
    prescription: dict[str, Any],
    reason: str,
    avoid: list[dict[str, Any]],
    current_level: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "current_level": current_level,
        "next_step": {
            "prescription": prescription,
            "reason": reason,
        },
        "avoid": avoid,
        "coach_summary": f"{status}: {prescription.get('summary')}. {reason}",
    }


def compact_inspect_summary(result: dict[str, Any], *, workout_type: str) -> dict[str, Any]:
    beta_summary = result.get("beta_summary") or {}
    vt2_quality = result.get("vt2_quality") or {}
    hardest = result.get("hardest_block") or {}
    total = result.get("total") or {}
    stability = "unknown"
    physiological_cost = "unknown"

    verdict = str(vt2_quality.get("verdict") or beta_summary.get("status") or "").lower()
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
    if max_drift is not None:
        physiological_cost = "high" if max_drift >= 12 else "moderate" if max_drift >= 6 else "low"
    if max_core is not None and max_core >= 38.3 and physiological_cost != "high":
        physiological_cost = "moderate"

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


def vt2_prescription(*, sets: int, minutes: int, target_power_w: float) -> dict[str, Any]:
    return {
        "type": "vt2",
        "structure": f"{sets}x{minutes} min",
        "sets": sets,
        "rep_minutes": minutes,
        "total_work_minutes": sets * minutes,
        "target_power_w": round(target_power_w),
        "recoveries": "5 min easy between intervals",
        "summary": f"VT2 {sets}x{minutes} min @ {round(target_power_w)}W",
    }


def vt2_bridge_prescription(
    *,
    sets: int,
    minutes: int,
    add_minutes: int,
    target_power_w: float,
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
        "target_power_w": round(target_power_w),
        "recoveries": "5 min easy between intervals; add-on after final recovery if controlled",
        "summary": f"VT2 {structure} @ {round(target_power_w)}W",
    }


def vo2max_prescription(*, sets: int, reps: int, seconds: int, target_power_w: float) -> dict[str, Any]:
    total_reps = sets * reps
    return {
        "type": "vo2max",
        "structure": f"{sets}x{reps}x{seconds}/{seconds}",
        "sets": sets,
        "reps_per_set": reps,
        "total_reps": total_reps,
        "rep_seconds": seconds,
        "target_power_w": round(target_power_w),
        "recoveries": f"{seconds}s easy between reps; 5 min easy between sets",
        "summary": f"VO2Max {sets}x{reps}x{seconds}/{seconds} @ {round(target_power_w)}W",
    }


def parse_completed_prescription(name: str, *, workout_type: str) -> dict[str, Any]:
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
                target_power_w=295.0,
            )
        match = re.search(r"\bVT2\s+(\d+)x(\d+)\s*min\b", name, flags=re.IGNORECASE)
        if match:
            sets = int(match.group(1))
            minutes = int(match.group(2))
            return vt2_prescription(sets=sets, minutes=minutes, target_power_w=295.0)
        plus = re.search(r"\bVT2\s+(\d+)\+(\d+)\s*min\b", name, flags=re.IGNORECASE)
        if plus:
            values = [int(plus.group(1)), int(plus.group(2))]
            return {
                **vt2_prescription(sets=len(values), minutes=round(sum(values) / len(values)), target_power_w=295.0),
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
                target_power_w=380.0,
            )
        match = re.search(r"\bVO2Max\s+(\d+)x(\d+)\s*sec\b", name, flags=re.IGNORECASE)
        if match:
            return vo2max_prescription(
                sets=1,
                reps=int(match.group(1)),
                seconds=int(match.group(2)),
                target_power_w=380.0,
            )
    return {"type": workout_type, "summary": f"unparsed: {name}"}


def load_xmb_workouts(args: argparse.Namespace, *, day: date) -> list[dict[str, Any]]:
    path = args.xert_recommended_training_json or (
        args.recommendations_dir / day.isoformat() / f"xert-recommended-training-{day.isoformat()}.json"
    )
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("exercises") or []:
        if not isinstance(row, dict) or row.get("exerciseType") != "Workout":
            continue
        name = str(row.get("name") or "")
        if not name.startswith("XMB:"):
            continue
        rows.append(
            {
                "name": name,
                "url": row.get("url"),
                "duration_minutes": round((number(row.get("duration")) or 0) / 60, 1),
                "xss": row.get("xss"),
                "high_xss": row.get("xhss"),
                "peak_xss": row.get("xpss"),
                "difficulty": row.get("difficulty"),
            }
        )
    return rows


def match_existing_xmb_workouts(
    prescription: dict[str, Any],
    workouts: list[dict[str, Any]],
    *,
    workout_type: str,
) -> dict[str, Any]:
    if not workouts:
        return {"available": False, "reason": "No XMB workout list available."}
    target_power = number(prescription.get("target_power_w"))
    candidates = [
        (workout_match_score(prescription, row, workout_type=workout_type, target_power=target_power), row)
        for row in workouts
        if workout_type in str(row.get("name") or "").lower()
    ]
    candidates = [(score, row) for score, row in candidates if score < 100]
    if not candidates:
        return {
            "available": False,
            "reason": f"No XMB workout found matching {prescription.get('summary')}.",
        }
    score, best = min(candidates, key=lambda item: item[0])
    return {
        "available": True,
        "match_quality": "exact_or_close" if score <= 6 else "loose",
        "best": best,
        "alternatives": [row for _, row in sorted(candidates, key=lambda item: item[0])[1:4]],
    }


def workout_match_score(
    prescription: dict[str, Any],
    workout: dict[str, Any],
    *,
    workout_type: str,
    target_power: float | None,
) -> float:
    name = str(workout.get("name") or "")
    score = 0.0
    if workout_type == "vt2":
        sets = prescription.get("sets")
        minutes = prescription.get("rep_minutes")
        add_on = number(prescription.get("add_on_minutes")) or 0.0
        bridge = re.search(
            r"\bVT2\s+(\d+)x(\d+)\s*(?:min)?\s*\+\s*(\d+)\s*min\b",
            name,
            flags=re.IGNORECASE,
        )
        match = bridge or re.search(r"\bVT2\s+(\d+)x(\d+)\s*min\b", name, flags=re.IGNORECASE)
        if match is None:
            return 999
        score += abs(int(match.group(1)) - int(sets or 0)) * 10
        score += abs(int(match.group(2)) - int(minutes or 0)) * 2
        workout_add_on = int(bridge.group(3)) if bridge is not None else 0
        score += abs(workout_add_on - add_on) * 1.5
    else:
        reps = prescription.get("reps_per_set")
        sets = prescription.get("sets")
        match = re.search(r"(\d+)x(\d+)x60/60", name, flags=re.IGNORECASE)
        if match:
            score += abs(int(match.group(1)) - int(sets or 0)) * 10
            score += abs(int(match.group(2)) - int(reps or 0)) * 2
        else:
            match = re.search(r"\b(\d+)x60/60", name, flags=re.IGNORECASE)
            if not match:
                return 999
            score += abs(1 - int(sets or 1)) * 10
            score += abs(int(match.group(1)) - int(reps or 0)) * 2
    if target_power is not None:
        power_match = re.search(r"@ ?(\d+)W|\((\d+)W\)", name)
        if power_match:
            power = number(power_match.group(1) or power_match.group(2))
            if power is not None:
                score += abs(power - target_power) / 10
    return score


def name_matches_type(name: str, workout_type: str) -> bool:
    lowered = name.lower()
    if workout_type == "vt2":
        return "vt2" in lowered or "threshold" in lowered or "terskel" in lowered
    return "vo2" in lowered or "vo2max" in lowered


def xmb_workout_source(args: argparse.Namespace, *, day: date) -> str:
    path = args.xert_recommended_training_json or (
        args.recommendations_dir / day.isoformat() / f"xert-recommended-training-{day.isoformat()}.json"
    )
    return str(path)


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
