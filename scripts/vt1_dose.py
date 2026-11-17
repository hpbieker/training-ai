"""Compare an aerobic prescription with reviewed rides of the same purpose."""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from analysis import load_activity, load_activity_metadata
from physiological_evidence import numeric, timeline, vt1_power_band
from plan_state import (AEROBIC_ROLES, QUALITY_ROLES, DEFAULT_ARTIFACTS_DIR,
                        DEFAULT_STATE_PATH, load_plan_state, parse_datetime)


def ride_observations(directory, metadata, watts, cutoff):
    moving = numeric(metadata, "moving_time")
    elapsed = numeric(metadata, "elapsed_time")
    result = {
        "elapsed_minutes": round(elapsed / 60, 1) if elapsed is not None else None,
        "moving_minutes": round(moving / 60, 1) if moving is not None else None,
        "observed_minutes_near_working_power": None,
        "valid_power_minutes": None,
        "whole_session_rpe": metadata.get("icu_rpe"),
        "feel": metadata.get("feel"),
        "athlete_report": None,
    }
    if directory is None:
        return result
    report_path = directory / "athlete-report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text())
        reported_at = report.get("reported_at")
        if not reported_at or parse_datetime(reported_at) <= cutoff:
            result["athlete_report"] = {
                key: report[key] for key in ("report", "athlete_report", "context", "late_response",
                                             "last_rep_effort", "subsequent_recovery") if key in report
            } or None
            for key in ("whole_session_rpe", "feel"):
                if result[key] is None:
                    result[key] = report.get(key)
    if watts is None or not (directory / "streams.csv").is_file() or not metadata:
        return result
    rows = load_activity(directory).streams
    clock = timeline(rows)
    if clock:
        low, high = vt1_power_band(watts)
        valid = matched = 0.0
        for row, seconds in zip(rows, clock[1]):
            power = numeric(row, "watts")
            if power is not None:
                valid += seconds
                if low <= power <= high:
                    matched += seconds
        result["valid_power_minutes"] = round(valid / 60, 1)
        if valid:
            result["observed_minutes_near_working_power"] = round(matched / 60, 1)
    return result


def dose_comparisons(state, role, watts, cutoff, activities_dir=DEFAULT_ARTIFACTS_DIR, *, selected_id=None):
    directories = {}
    if activities_dir.is_dir():
        for path in sorted(activities_dir.iterdir()):
            if path.is_dir():
                directories[path.name.split("_", 1)[-1]] = path
    candidates = []
    next_quality = None
    for event in reversed(state["activity_events"]):
        actual_role = event["completed_role"]
        quality = actual_role in QUALITY_ROLES or event.get("planned_role") in QUALITY_ROLES
        include_ride = actual_role == role and (len(candidates) < 3 or event["activity_id"] == selected_id)
        if not quality and not include_ride:
            continue
        started = parse_datetime(event["started_at"])
        if started >= cutoff:
            continue
        activity_id = event["activity_id"]
        directory = directories.get(activity_id) or directories.get(activity_id.removeprefix("i"))
        metadata = (load_activity_metadata(directory)
                    if directory and (directory / "activity.json").is_file() else {})
        elapsed = numeric(metadata, "elapsed_time")
        if elapsed is not None and started + timedelta(seconds=elapsed) > cutoff:
            continue
        if elapsed is None and started.astimezone(cutoff.tzinfo).date() == cutoff.date():
            continue
        sport = str(metadata.get("type") or "").lower()
        if include_ride and (not sport or "ride" in sport or "cycling" in sport):
            candidates.append({
                "activity_id": activity_id, "started_at": event["started_at"],
                "review": event["reason"], "evidence": event.get("evidence", []),
                **ride_observations(directory, metadata, watts, cutoff),
                "next_quality_session": next_quality,
            })
            if len(candidates) >= 3 and (not selected_id or any(ride["activity_id"] == selected_id for ride in candidates)):
                break
        if quality:
            next_quality = {key: event.get(key) for key in (
                "activity_id", "started_at", "planned_role", "completed_role",
                "quality_role_fulfilled", "planned_workout_completed", "reason")}
    return {"role": role, "as_of": cutoff.isoformat(), "working_power_w": watts,
            "observation_band_w": vt1_power_band(watts) if watts is not None else None,
            "status": "available" if candidates else "no_reviewed_same_role_ride",
            "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--role", choices=sorted(AEROBIC_ROLES), required=True)
    parser.add_argument("--as-of", required=True, help="Decision cutoff, with UTC offset")
    parser.add_argument("--activity-id", help="Also include this older same-role comparison when eligible")
    parser.add_argument("--watts", type=float, help="Use today's chosen working power")
    args = parser.parse_args()
    state = load_plan_state(args.state)
    watts = args.watts if args.watts is not None else state["progression"].get("vt1", {}).get("target_power_w")
    if watts is not None and not 0 < watts < float("inf"):
        parser.error("Working power must be finite and positive")
    cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        parser.error("--as-of requires a UTC offset")
    print(json.dumps(dose_comparisons(state, args.role, watts, cutoff, selected_id=args.activity_id), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
