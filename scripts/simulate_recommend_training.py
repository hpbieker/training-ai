#!/usr/bin/env python3
"""Run recommend_training.py sequentially and retain planned Xert events."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
XERT_SCRIPTS = ROOT / "plugins" / "xert" / "scripts"
sys.path.insert(0, str(XERT_SCRIPTS))

from xert_calendar import (
    create_calendar_event_with_opener,
    fetch_calendar_events_with_opener,
    update_calendar_event_with_opener,
)
from xert_common import load_xert_credentials, xert_web_login
from plan_state import (
    QUALITY_ROLES,
    apply_activity_classification,
    load_plan_state,
    plan_role_to_intensity_goal,
    write_plan_state,
)
from recommend_training import build_planning_context

OSLO = ZoneInfo("Europe/Oslo")
QUALITY = {
    "source": "xert_workout_calculate",
    "duration_minutes": 53,
    "xss": 71.9,
    "low_xss": 66.5,
    "high_xss": 4.9,
    "peak_xss": 0.5,
}
BASE = ROOT / "outputs" / "recommendations" / "2026-08-01"


def days(first: date, last: date):
    value = first
    while value <= last:
        yield value
        value += timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("start_date")
    parser.add_argument("end_date")
    parser.add_argument(
        "--scenario-state",
        type=Path,
        default=ROOT / "outputs" / "simulations" / "recommend-training" / "scenario-plan-state.json",
    )
    parser.add_argument("--initialize-state", action="store_true")
    parser.add_argument("--update-existing", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        parser.error("use --yes to retain planned Xert events")

    if args.initialize_state:
        args.scenario_state.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "config" / "plan-state.json", args.scenario_state)
    scenario_state = load_plan_state(args.scenario_state)

    creds = load_xert_credentials()
    opener = xert_web_login(username=creds.username, password=creds.password)
    results = []
    for day in days(date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)):
        planned_role = scenario_state["next_role"]
        intensity_goal = plan_role_to_intensity_goal(planned_role)
        title = f"Codex recommend_training simulation {day.isoformat()}"
        existing = next(
            (e for e in fetch_calendar_events_with_opener(opener, day)["events"] if e.get("name") == title),
            None,
        )
        if existing and not args.update_existing:
            raise RuntimeError(
                f"scenario event already exists for {day}; use a matching scenario state or remove the stale event"
            )

        planned = datetime.combine(day, time(9, 0), tzinfo=OSLO)
        context = build_planning_context(
            day=day.isoformat(),
            local_timezone="Europe/Oslo",
            now="2026-07-31T20:30:00+02:00",
            planned_at=planned.isoformat(),
            availability_windows=[{
                "start": planned.isoformat(),
                "end": datetime.combine(day, time(22, 0), tzinfo=OSLO).isoformat(),
            }],
            cycling={
                "available_modalities": ["indoor_cycling"],
                "unavailable_reasons": {
                    "outdoor_cycling": "simulation uses one controlled modality"
                },
            },
            calendar={
                "cleanup_buffer_minutes": 15,
                "assumptions": ["Simulation window is open"],
                "remainder_disposition": "dropped",
            },
        )
        output_root = ROOT / "outputs" / "simulations" / "recommend-training" / day.isoformat()
        quality = quality_calculation(intensity_goal, scenario_state)
        plan_selection = {
            "intensity_goal": intensity_goal,
            "state": str(args.scenario_state),
        }
        command = [
            sys.executable, "-B", "scripts/recommend_training.py",
            "--planning-context-json", json.dumps(context),
            "--plan-selection-json", json.dumps(plan_selection),
            "--source-overrides-json", json.dumps({
                "garmin": str(BASE / "garmin-readiness-2026-08-01.json"),
                "intervals_wellness": str(BASE / "intervals-wellness-recent-2026-08-01.json"),
                "intervals_events": str(BASE / "intervals-events-recent-2026-08-01.json"),
                "weather_home": str(BASE / "yr-home-2026-08-01.json"),
            }),
            "--refresh-json", '{"mode":"selected","sources":["xert"]}',
            "--output-dir", str(output_root), "--summary",
        ]
        if quality is not None:
            command[7:7] = [
                "--quality-workout-json",
                json.dumps({"status": "planned", "calculation": quality}),
            ]
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if completed.returncode:
            raise RuntimeError(completed.stderr or completed.stdout)
        packet_path = output_root / day.isoformat() / "recommendation-packet.json"
        packet = json.loads(packet_path.read_text())
        decision = packet["primary_decision"]
        composition = decision.get("dose_composition") or {}
        total = float(decision["physiological_remaining_dose"]["load_xss"])
        duration_minutes = float(decision["executable_now"]["minutes"])
        quality_base = composition.get("quality_base") or {}
        filler = composition.get("vt1_filler") or {}
        if quality_base:
            low = float(quality_base.get("low_xss") or 0) + float(filler.get("xss") or 0)
            high = float(quality_base.get("high_xss") or 0)
            peak = float(quality_base.get("peak_xss") or 0)
        else:
            low, high, peak = total, 0.0, 0.0
        end = planned + timedelta(minutes=duration_minutes)
        event = {
            "start_date": planned.isoformat(), "end_date": end.isoformat(),
            "duration": round(duration_minutes * 60), "manualExercise": True,
            "sport": "Cycling", "title": title,
            "description": completed.stdout.splitlines()[1] if completed.stdout else "recommend_training.py simulation",
            "focus": "GC Specialist", "sfd": 240, "specificity_rating": "Mixed", "sp": 0.5,
            "xss": total, "xlss": low, "xhss": high, "xpss": peak,
            "options": {"planned": True, "state": ["scheduled", "recommended"]},
        }
        if existing:
            saved = update_calendar_event_with_opener(
                opener,
                day,
                str(existing.get("path") or existing.get("id")),
                event,
            )["event"]
        else:
            saved = create_calendar_event_with_opener(opener, event)["event"]
        selected = decision["selected_intensity"]
        quality_completed = selected in QUALITY_ROLES and bool(quality_base)
        completed_role = selected if quality_completed else "easy_aerobic"
        classification = {
            "activity_id": f"scenario-{day.isoformat()}",
            "activity_name": title,
            "started_at": planned.isoformat(),
            "planned_role": planned_role,
            "completed_role": completed_role,
            "quality_completed": quality_completed,
            "progression_effect": "advance" if quality_completed else "none",
            "reason": "Scenario assumes the complete recommended session is performed as planned.",
            "evidence": [str(packet_path)],
        }
        progression_update = scenario_progression_update(
            completed_role,
            scenario_state,
        )
        if progression_update:
            classification["progression_update"] = progression_update
        scenario_state = apply_activity_classification(scenario_state, classification)
        write_plan_state(args.scenario_state, scenario_state)
        results.append({"date": day.isoformat(), "path": saved["path"], "updated": bool(existing), "planned_role": planned_role, "intensity": selected, "minutes": duration_minutes, "xss": total, "low": low, "high": high, "peak": peak, "next_role": scenario_state["next_role"]})
        print(json.dumps(results[-1]), flush=True)

    print(json.dumps({"results": results, "events_retained": True, "scenario_state": str(args.scenario_state)}, indent=2))


def quality_calculation(intensity_goal: str, state: dict) -> dict | None:
    next_step = str((state.get("progression", {}).get(intensity_goal, {}) or {}).get("next_step") or "")
    if intensity_goal == "vo2max" and next_step.startswith("4 x 4"):
        return dict(QUALITY)
    if intensity_goal != "vt2":
        if intensity_goal == "vo2max" and next_step.startswith("2 x 8 x 60/60"):
            rows = [
                '{"name":"Warm-up 1","duration":"10:00","power":170}',
                '{"name":"Warm-up 2","duration":"05:00","power":220}',
                '{"name":"Set 1","duration":"01:00","power":380,"interval_count":8,"rib_duration":"01:00","rib_power":120}',
                '{"name":"Between sets","duration":"05:00","power":120}',
                '{"name":"Set 2","duration":"01:00","power":380,"interval_count":8,"rib_duration":"01:00","rib_power":120}',
                '{"name":"Cool-down","duration":"10:00","power":140}',
            ]
            return calculate_rows("Scenario VO2 2x8x60/60 @ 380 W", rows)
        if intensity_goal == "vo2max" and next_step.startswith("5 x 3"):
            return calculate_compact("Scenario VO2 5x3 @ 350 W", "5x03:00@350/03:00@120")
        return None
    interval = "3x20:00@290/05:00@120" if "3 x 20" in next_step else "3x18:00@290/05:00@120"
    return calculate_compact(f"Scenario VT2 {next_step}", interval)


def calculate_compact(name: str, interval: str) -> dict:
    command = [sys.executable, "-B", "plugins/xert/scripts/xert_cli.py", "workout-calculate",
        "--name", name, "--warmup-step", "10:00@170", "--warmup-step", "05:00@220",
        "--interval-block", interval, "--cooldown-step", "10:00@140", "--summary"]
    return run_calculation(command)


def calculate_rows(name: str, rows: list[str]) -> dict:
    command = [sys.executable, "-B", "plugins/xert/scripts/xert_cli.py", "workout-calculate", "--name", name]
    for row in rows:
        command.extend(["--row-json", row])
    command.append("--summary")
    return run_calculation(command)


def run_calculation(command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def scenario_progression_update(role: str, state: dict) -> dict:
    next_step = str((state.get("progression", {}).get(role, {}) or {}).get("next_step") or "")
    if role == "vo2max":
        if next_step.startswith("4 x 4"):
            return {"status": "sensor_calibration_2_of_3", "next_step": "2 x 8 x 60/60 @ 380 W"}
        if next_step.startswith("2 x 8 x 60/60"):
            return {"status": "sensor_calibration_3_of_3", "next_step": "5 x 3 min @ 350 W"}
    if role == "vt2":
        if next_step.startswith("3 x 18"):
            return {"status": "progressing_290w_ladder", "next_step": "3 x 20 min @ 290 W"}
        if next_step.startswith("3 x 20"):
            return {"status": "progressing_290w_ladder", "next_step": "3 x 23 min @ 290 W"}
    return {}


if __name__ == "__main__":
    main()
