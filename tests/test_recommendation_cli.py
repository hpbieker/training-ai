"""Exercise the recommendation CLI offline with synthetic sources and plan state.

Run with python3 -B -m unittest discover -s tests -p test_recommendation_cli.py.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/xert"))
from xert_strain_model import calculate_workout, solve_segment_duration

FIXTURE = json.loads((ROOT / "tests/fixtures/recommendation_cli.json").read_text())
SIGNATURE = {"tp": 300, "hie": 14000, "pp": 900}
SEGMENTS = [(600, 150), (480, 270), (180, 130), (480, 270), (300, 120)]
REASON = "Repeat established threshold dose after normal response; no additional endurance needed"
EVIDENCE = ["Synthetic achieved 2x8 minute anchor", "Synthetic current recovery assessment"]
NEXT_WORKOUT = "2026-11-18T10:00:00+01:00"
MOVED_WORKOUT = "2026-11-18T12:00:00+01:00"


class RecommendationCLITests(unittest.TestCase):
    def test_other_chat_constraint_survives_fresh_readiness_until_athlete_reopens_quality(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, "-B", str(ROOT / "scripts/day_constraints.py")]
            def run(*args, check=True):
                return subprocess.run([*command, *args], cwd=root, text=True,
                                      capture_output=True, check=check)

            key = run("record", "--date", "2026-11-17", "--quote", "No quality tomorrow.",
                      "--source", "chat-one/message-1", "--reported-at", "2026-11-16T17:00:00+01:00",
                      "--exclude", "quality").stdout.strip()
            unsupported = run("release", "--id", key, "--kind", "condition", "--evidence", "New HRV is normal",
                              "--source", "garmin-sync", "--reported-at", "2026-11-17T09:00:00+01:00", check=False)
            self.assertNotEqual(unsupported.returncode, 0)
            blocked, packet = self.run_cli(root, NEXT_WORKOUT, False)
            self.assertIn("No quality tomorrow.", blocked.stderr)
            self.assertIsNone(packet)
            self.assertEqual(json.loads(run("show", "--date", "2026-11-18").stdout), [])

            run("release", "--id", key, "--kind", "athlete", "--evidence", "The plan changed. I can do VT2 today.",
                "--source", "chat-two/message-2", "--reported-at", "2026-11-17T09:45:00+01:00")
            old, = json.loads(run("show", "--date", "2026-11-17", "--as-of", "2026-11-17T09:44:59+01:00").stdout)
            self.assertTrue(old["active"])
            self.assertNotIn("release", old)
            accepted, packet = self.run_cli(root, NEXT_WORKOUT, False)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            entry, = packet["plan_context"]["dated_athlete_constraints"]
            self.assertFalse(entry["active"])
            self.assertEqual(entry["release"]["source"], "chat-two/message-2")
            self.assertEqual(packet["primary_decision"]["selected_intensity"], "vt2")

    def test_quality_workout(self):
        self.check_workout(next_workout=NEXT_WORKOUT)

    def test_remaining_xert_hours_preserve_quality_candidate_for_review(self):
        with TemporaryDirectory() as directory:
            result, packet = self.run_cli(Path(directory), NEXT_WORKOUT, False, low_hours=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        primary = packet["primary_decision"]
        self.assertTrue(primary["provisional"])
        self.assertEqual(primary["selected_intensity"], "vt2")
        self.assertIn("xert_low_recovery", primary["readiness_evidence"]["observed_cautions"])
        self.assertIn("PROVISIONAL SESSION:", result.stdout)

    def test_moved_next_workout_rejects_stale_capacity(self):
        self.check_workout(next_workout=MOVED_WORKOUT, expected_error="Capacity timestamps differ")

    def test_moved_next_workout_accepts_recalculated_capacity(self):
        self.check_workout(next_workout=MOVED_WORKOUT, refresh_capacity=True)

    def check_workout(self, *, next_workout, refresh_capacity=False, expected_error=None):
        with TemporaryDirectory() as directory:
            result, packet = self.run_cli(Path(directory), next_workout, refresh_capacity)

        if expected_error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected_error, result.stderr)
            self.assertIsNone(packet)
            return

        self.assertEqual(result.returncode, 0, result.stderr)
        primary = packet["primary_decision"]
        target = packet["target_resolution"]
        self.assertEqual(primary["action"], "train")
        self.assertEqual(primary["selected_intensity"], "vt2")
        self.assertEqual(primary["coaching_selection"]["reason"], REASON)
        self.assertEqual(primary["coaching_selection"]["evidence"], EVIDENCE)
        self.assertIn(REASON, result.stdout)
        self.assertIn("model screening, not confirmed readiness", result.stdout)
        timeline = primary["executable_now"]["timeline"]
        self.assertEqual(timeline["status"], "complete")
        self.assertEqual([(s["duration_seconds"], s["power"]) for s in timeline["segments"]], SEGMENTS)
        dose = primary["physiological_remaining_dose"]
        self.assertEqual(dose["minutes"], 34)
        self.assertEqual(dose["load_xss"], 35.0)
        self.assertNotEqual(dose["load_xss"], primary["xert_comparison"]["suggested_xss"])
        self.assertEqual(target["plan_trace"]["adjustment"]["status"], "unchanged")
        self.assertNotIn("reduced_by_guardrail", result.stdout)
        self.assertEqual(target["volume_density"]["classification"], "unavailable")
        horizon = target["recovery_protection_capacity"]["horizon"]
        self.assertEqual(horizon["status"], "exact")
        self.assertEqual(horizon["calculated_fresh_at"], next_workout)
        self.assertEqual(target["dose_composition"]["vt1_filler"]["duration_minutes"], 0)

    def test_vt1_working_power_uses_the_plan_or_a_reviewed_deviation(self):
        for watts, choice, ok in ((215, None, True), (285, None, False),
                                   (195, {"watts": 195, "reason": "Easy spacing",
                                          "evidence": ["Reviewed late response"]}, True)):
            with self.subTest(watts=watts), TemporaryDirectory() as directory:
                result, packet = self.run_cli(Path(directory), NEXT_WORKOUT, False, vt1_watts=watts, choice=choice)
                if ok:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    primary = packet["primary_decision"]
                    self.assertEqual(primary["vt1_power_review"]["working_power_w"], watts)
                    comparison = primary["vt1_dose_comparison"]
                    self.assertEqual(comparison["status"], "no_reviewed_same_role_ride")
                    self.assertEqual(comparison["prescribed_total_minutes"], 60)
                    self.assertEqual(comparison["prescribed_steady_work_minutes"], 50)
                else:
                    self.assertIn("215 W", result.stderr)
                    self.assertIsNone(packet)

    def test_load_selected_vt1_binds_power_before_and_after_solving(self):
        for watts, mode in ((285, "request"), (215, "request"), (215, "solution")):
            with self.subTest(watts=watts, mode=mode), TemporaryDirectory() as directory:
                result, packet = self.run_cli(Path(directory), NEXT_WORKOUT, False,
                                              vt1_watts=watts, solver_mode=mode)
                if watts == 285:
                    self.assertIn("215 W", result.stderr)
                    self.assertNotEqual(result.returncode, 0)
                elif mode == "request":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["segments"][1]["power"], watts)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    comparison = packet["primary_decision"]["vt1_dose_comparison"]
                    self.assertAlmostEqual(comparison["prescribed_steady_work_minutes"], 50, delta=0.1)

    def test_reviewed_vt1_history_requires_a_dose_comparison_or_reason_to_discard_it(self):
        for review, accepted in [(None, False), ({"activity_id": "wrong", "reason": "Repeat"}, False),
                                 ({"activity_id": "ride", "reason": "Repeat tolerable dose"}, True),
                                 ({"reason": "Only comparable ride lacked watt data"}, True)]:
            with self.subTest(review=review), TemporaryDirectory() as directory:
                result, packet = self.run_cli(Path(directory), NEXT_WORKOUT, False,
                                              vt1_watts=215, history=True, review=review)
                if accepted:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    comparison = packet["primary_decision"]["vt1_dose_comparison"]
                    self.assertEqual(comparison["selection_review"], review)
                    self.assertEqual(comparison["candidates"][0]["activity_id"], "ride")
                else:
                    self.assertIn("vt1_comparison", result.stderr)
                    self.assertIsNone(packet)

    def run_cli(self, workdir, next_workout, refresh_capacity, *, low_hours=None,
                vt1_watts=None, choice=None, solver_mode=None, history=False, review=None):
        if not (workdir / "scripts").exists():
            (workdir / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
        (workdir / "sitecustomize.py").write_text(
            "import socket\n"
            "def denied(*args, **kwargs):\n"
            "    raise RuntimeError('CLI scenario forbids network access')\n"
            "socket.socket.connect = denied\n"
            "socket.create_connection = denied\n"
        )
        sources = deepcopy(FIXTURE["sources"])
        if low_hours is not None:
            sources["xert"]["training_state"]["state"]["recovery_hours"]["low"] = low_hours
        if refresh_capacity:
            sources["xert_workout_capacity"].update(
                fresh_at=next_workout, workout_capacity_xss={"low": 190, "high": 16, "peak": 4}
            )
        state = workdir / "plan-state.json"
        source_paths = {name: workdir / f"{name}.json" for name in sources}
        plan = deepcopy(FIXTURE["plan_state"])
        if vt1_watts:
            plan["progression"]["vt1"] = {"target_power_w": 215}
            plan["next_role"] = "easy_aerobic"
            plan["quality_queue"].update(aerobic_dates_since_quality=[], aerobic_days_since_quality=0)
        if history:
            start = "2026-11-14T10:00:00+01:00"
            plan["activity_cursor"] = {"activity_id": "ride", "started_at": start}
            plan["activity_events"] = [{**plan["activity_cursor"], "activity_name": "Ride",
                "planned_role": "easy_aerobic", "completed_role": "easy_aerobic", "progression_effect": "none",
                "quality_role_fulfilled": False, "quality_stimulus": False, "planned_workout_completed": None,
                "reason": "Reviewed easy session", "evidence": []}]
        inputs = {state: json.dumps(plan)}
        inputs.update({source_paths[name]: json.dumps(payload) for name, payload in sources.items()})
        for path, content in inputs.items():
            path.write_text(content)

        planning = {
            "date": "2026-11-17",
            "local_timezone": "Europe/Oslo",
            "now": "2026-11-17T09:50:00+01:00",
            "planned_at": "2026-11-17T10:00:00+01:00",
            "next_workout_at": next_workout,
            "availability": {"windows": [{
                "start": "2026-11-17T10:00:00+01:00",
                "end": "2026-11-17T12:00:00+01:00",
            }]},
            "cycling": {
                "available_modalities": ["indoor_cycling"],
                "unavailable_reasons": {"outdoor_cycling": "Synthetic indoor scenario"},
            },
        }
        segments = [{"duration_seconds": duration, "power": power} for duration, power in SEGMENTS]
        calculation = calculate_workout(signature=SIGNATURE, segments=segments, include_series=False)
        selection = {
            "minutes": 34, "load": calculation["xss"]["total"],
            "basis": "duration", "reason": REASON, "evidence": EVIDENCE,
        }
        quality = {
            "status": "planned",
            "calculation": calculation,
            "rows": [dict(segment, power_type="absolute", interval_count=1) for segment in segments],
            "signature": SIGNATURE,
            "adjustable_row_index": 1,
        }
        goal = "vt2"
        workout_args = ["--quality-workout-json", json.dumps(quality)]
        if vt1_watts:
            goal = "vt1"
            rows = [{"duration_seconds": 300, "power": 150, "end_power": vt1_watts},
                    {"duration_seconds": 3000, "power": vt1_watts},
                    {"duration_seconds": 300, "power": 130}]
            calc = calculate_workout(signature=SIGNATURE, segments=rows, include_series=False)
            selection.update(minutes=60, load=calc["xss"]["total"])
            if review:
                selection["vt1_comparison"] = review
            if choice:
                selection["vt1_power_choice"] = choice
            structure = {"signature": SIGNATURE, "segments": rows}
            workout = {"structure": structure, "calculation": calc}
            if solver_mode:
                selection["basis"] = "load"
                structure["adjustable_segment_index"] = 1
                if solver_mode == "request":
                    del workout["calculation"]
                else:
                    workout["calculation"] = solve_segment_duration(**structure,
                        target_metric="low_xss", target_value=selection["load"], maximum_duration_seconds=7200)
            workout_args = ["--endurance-workout-json", json.dumps(workout)]
            if solver_mode == "request":
                workout_args.append("--print-endurance-solver-request")
        output = workdir / "reports"
        command = [
            sys.executable, "-B", str(ROOT / "scripts/recommend_training.py"),
            "--planning-context-json", json.dumps(planning),
            "--plan-selection-json", json.dumps({"state": str(state), "intensity_goal": goal}),
            "--source-overrides-json", json.dumps({name: str(path) for name, path in source_paths.items()}),
            "--refresh-json", '{"mode":"none"}',
            "--output-dir", str(output),
            "--training-target-json", json.dumps(selection),
            *workout_args,
            "--summary",
        ]
        env = dict(os.environ, PYTHONPATH=str(workdir), PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(command, cwd=workdir, env=env, text=True, capture_output=True, timeout=30)
        for path, content in inputs.items():
            self.assertEqual(path.read_text(), content, f"CLI modified {path.name}")
        packet_path = output / planning["date"] / "recommendation-packet.json"
        packet = json.loads(packet_path.read_text()) if packet_path.exists() else None
        return result, packet
