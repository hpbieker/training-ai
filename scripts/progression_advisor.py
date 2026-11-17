#!/usr/bin/env python3
"""Collect workout-family evidence for a plan-owned progression decision."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plan_state import DEFAULT_STATE_PATH, load_plan_state, parse_datetime
from readiness_snapshot import completed_activity_start, parse_timezone

SCHEMA = "training-ai-progression-advisor-v3"
DEFAULT_ARTIFACTS_DIR = Path("outputs/intervals")


@dataclass(frozen=True)
class CandidateActivity:
    activity_dir: Path
    activity_id: str
    name: str
    start: datetime
    elapsed_seconds: float | None
    training_load: float | None
    observed_work: dict[str, Any] | None
    reviewed_event: dict[str, Any] | None = None
    has_streams: bool = True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect evidence for VT2 or VO2Max progression. The coach applies the "
            "selected plan; this script never invents a next dose."
        )
    )
    parser.add_argument("--type", choices=("vt2", "vo2max"), required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--as-of", help="Include only rides completed by this offset-aware instant")
    parser.add_argument("--local-timezone", type=parse_timezone)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--max-sessions", type=int, default=6)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    parser.add_argument("--plan-state", type=Path,
                        help="Selected plan state with reviewed roles (default: repository state when present).")
    parser.add_argument("--plan-progression-json", type=parse_plan_progression_json, default={},
                        help="Selected plan-family context, passed explicitly; never parsed from Markdown.")
    parser.add_argument("--force-inspect", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    day = parse_date(args.date)
    if args.as_of and args.local_timezone is None:
        parser.error("--as-of requires --local-timezone for local recording timestamps")
    cutoff = parse_datetime(args.as_of, require_offset=True) if args.as_of else None
    state_path = args.plan_state or DEFAULT_STATE_PATH
    reviewed_events = (
        load_plan_state(state_path)["activity_events"]
        if args.plan_state is not None or state_path.is_file() else []
    )
    activities = recent_relevant_activities(
        workout_type=args.type,
        day=day, cutoff=cutoff, local_timezone=args.local_timezone,
        lookback_days=args.lookback_days,
        max_sessions=args.max_sessions,
        artifacts_dir=args.artifacts_dir,
        target_power_w=number(args.plan_progression_json.get("target_power_w")),
        reviewed_events={event["activity_id"]: event for event in reviewed_events},
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
    cutoff: datetime | None = None,
    local_timezone=None,
    lookback_days: int,
    max_sessions: int,
    artifacts_dir: Path,
    target_power_w: float | None,
    reviewed_events: dict[str, dict[str, Any]],
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
        start = parse_optional_datetime(metadata.get("start_date_local"))
        if cutoff is not None:
            start = completed_activity_start(metadata.get("start_date"), metadata.get("start_date_local"),
                                             metadata.get("elapsed_time"), cutoff=cutoff, local_timezone=local_timezone)
        if start is None or not (since <= start.date() <= day):
            continue
        activity_dir = activity_json.parent
        activity_id = str(metadata.get("id") or activity_dir.name)
        reviewed = reviewed_events.get(activity_id)
        if reviewed is not None and reviewed["completed_role"] != workout_type:
            continue
        observed = observed_interval_work(
            metadata, workout_type=workout_type, target_power_w=target_power_w,
            reviewed_family=reviewed is not None,
        )
        if reviewed is None and not observed and not name_matches_type(name, workout_type):
            continue
        candidates.append(
            CandidateActivity(
                activity_dir=activity_dir,
                activity_id=activity_id,
                name=name,
                start=start,
                elapsed_seconds=number(metadata.get("elapsed_time")),
                training_load=number(metadata.get("icu_training_load")),
                observed_work=observed,
                reviewed_event=reviewed,
                has_streams=(activity_dir / "streams.csv").is_file(),
            )
        )
    return sorted(candidates, key=lambda item: item.start, reverse=True)[:max_sessions]


def inspect_activities(
    activities: list[CandidateActivity], *, args: argparse.Namespace
) -> list[dict[str, Any]]:
    recordings = [activity for activity in activities if activity.has_streams]
    if not recordings:
        return [inspected_activity_payload(activity, {}, workout_type=args.type)
                for activity in activities]
    command = [
        sys.executable,
        "-B",
        "scripts/activity_inspect_pipeline.py",
        *(str(activity.activity_dir) for activity in recordings),
        "--analysis-options-json",
        json.dumps(
            {
                "mode": args.type,
                "shape": "brief",
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
    if len(results) != len(recordings):
        raise RuntimeError(
            "activity inspection returned "
            f"{len(results)} results for {len(recordings)} activities"
        )
    by_dir = {activity.activity_dir: result for activity, result in zip(recordings, results, strict=True)}
    return [inspected_activity_payload(activity, by_dir.get(activity.activity_dir, {}), workout_type=args.type)
            for activity in activities]


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
        "streams_available": activity.has_streams,
        "selection_basis": (
            "reviewed_completed_role" if activity.reviewed_event is not None
            else "activity_name" if name_matches_type(activity.name, workout_type)
            else "interval_pattern_candidate"
        ),
        "reviewed_classification": (
            {key: activity.reviewed_event[key] for key in
             ("completed_role", "quality_stimulus", "quality_role_fulfilled", "planned_workout_completed")}
            if activity.reviewed_event is not None else None
        ),
        "observed_work": activity.observed_work,
        "prescription_evidence_limit": (
            "Laps describe recorded work and recoveries. Pattern and title matches "
            "are candidates for review. Missing or unclassified laps leave the "
            "achieved family dose unresolved."
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
        "latest_observed_work": sessions[0].get("observed_work") if sessions else None,
        "plan_progression": dict(plan_progression),
        "next_step": {"prescription": None, "reason": reason},
        "avoid": [],
        "coach_summary": "requires_review: " + reason,
    }


def compact_inspect_summary(result: dict[str, Any], *, workout_type: str) -> dict[str, Any]:
    beta_summary = result.get("beta_summary") or {}
    vt2 = result.get("vt2_quality") or {}
    vt2_quality = vt2.get("session_quality") or {}
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
        "vt2_intensity_classification": vt2.get("intensity_classification"),
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


def observed_interval_work(
    metadata: dict[str, Any], *, workout_type: str, target_power_w: float | None,
    reviewed_family: bool = False,
) -> dict[str, Any] | None:
    """Retain measured laps and sum only identifiable family work.

    The power screens select plausible laps for review. They do not establish
    a physiological threshold or certify that the planned workout was finished.
    """
    named = name_matches_type(str(metadata.get("name") or ""), workout_type)
    known_family = reviewed_family or named
    rows = []
    recoveries = []
    for index, row in enumerate(metadata.get("icu_intervals") or []):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("type")).upper()
        if kind not in {"WORK", "RECOVERY"}:
            continue
        seconds = interval_seconds(row)
        if seconds is None or not math.isfinite(seconds) or seconds <= 0:
            continue
        watts = None if metadata.get("icu_ignore_power") else number(row.get("average_watts"))
        start_s = number(row.get("start_time"))
        end_s = number(row.get("end_time"))
        elapsed_s = number(row.get("elapsed_time"))
        if end_s is None and start_s is not None and elapsed_s is not None and elapsed_s > 0:
            end_s = start_s + elapsed_s
        target_rows = rows if kind == "WORK" else recoveries
        target_rows.append({
            "interval_index": index,
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": seconds,
            "average_watts": watts if watts is not None and math.isfinite(watts) else None,
        })

    if not rows:
        return None
    reference = target_power_w
    if named:
        title_power = re.search(r"@\s*(\d+(?:\.\d+)?)\s*W\b", str(metadata["name"]), re.I)
        if title_power:
            reference = float(title_power.group(1))

    matched = []
    pattern_candidates = []
    if reference is not None and math.isfinite(reference) and reference > 0:
        if workout_type == "vt2":
            # Long laps establish the work power for this ride. Short laps
            # near that power can then be included without counting warm-up.
            anchors = [r["average_watts"] for r in rows
                       if r["duration_s"] >= (300 if known_family else 600)
                       and r["average_watts"] is not None
                       and 0.8 * reference <= r["average_watts"] <= 1.1 * reference]
            if len(anchors) >= (1 if known_family else 2):
                typical = statistics.median(anchors)
                matched = [r for r in rows if r["average_watts"] is not None
                           and abs(r["average_watts"] - typical) <= 0.10 * typical]
        else:
            matched = [r for r in rows if r["average_watts"] is not None
                       and r["average_watts"] >= 0.9 * reference]
            if not known_family:
                # Retrieval heuristic for repeated efforts, independent of a named
                # protocol. Preserve every recorded lap below for coaching review.
                matched = [r for r in matched if r["duration_s"] >= 20]
                if len(matched) < 3 or sum(r["duration_s"] for r in matched) < 180:
                    matched = []
    elif workout_type == "vo2max" and not known_family:
        # Without a target, retrieve short-to-multiminute repetitions with
        # observed easier recoveries. Their family and achieved dose stay open.
        recovery_watts = {r["interval_index"]: r["average_watts"] for r in recoveries}
        for row in rows:
            index = row["interval_index"]
            neighbors = (recovery_watts.get(index - 1), recovery_watts.get(index + 1))
            if (20 <= row["duration_s"] <= 480 and row["average_watts"] is not None
                    and any(w is not None and 0 <= w < row["average_watts"] for w in neighbors)):
                pattern_candidates.append(row)
        if len(pattern_candidates) < 3 or sum(r["duration_s"] for r in pattern_candidates) < 180:
            pattern_candidates = []
    if not known_family and not matched and not pattern_candidates:
        return None
    for current, following in zip(rows, rows[1:]):
        end_s, next_start = current["end_s"], following["start_s"]
        if end_s is not None and next_start is not None and next_start >= end_s:
            current["gap_to_next_work_s"] = next_start - end_s
    return {
        "source": "icu_intervals",
        "reference_power_w": reference,
        "work_rows": rows,
        "recovery_rows": recoveries,
        "pattern_candidate_indices": [r["interval_index"] for r in pattern_candidates],
        "matched_interval_indices": [r["interval_index"] for r in matched],
        "matched_work_seconds": sum(r["duration_s"] for r in matched) if matched else None,
    }


def interval_seconds(row: dict[str, Any]) -> float | None:
    return (
        number(row.get("elapsed_time"))
        or number(row.get("moving_time"))
        or number(row.get("duration"))
    )


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


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    main()
