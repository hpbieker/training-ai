import json
import subprocess
import sys
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from progression_advisor import (
    CandidateActivity,
    infer_prescription_from_intervals,
    inspect_activities,
    compact_inspect_summary,
    parse_completed_prescription,
    progression_review,
)


class BatchedActivityInspectionTests(unittest.TestCase):
    def activity(self, activity_id):
        return CandidateActivity(
            activity_dir=Path("outputs/intervals/activities") / activity_id,
            activity_id=activity_id,
            name=f"Activity {activity_id}",
            start=datetime(2026, 7, 24),
            elapsed_seconds=3600,
            training_load=80,
            completed_prescription={},
        )

    @patch("progression_advisor.subprocess.run")
    def test_inspects_all_activities_in_one_pipeline_call(self, run):
        run.return_value.stdout = '[{"category":"VT2"},{"category":"VT1"}]'
        activities = [self.activity("one"), self.activity("two")]

        results = inspect_activities(
            activities,
            args=Namespace(type="vt2", vt2_watts=290, force_inspect=False),
        )

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn(str(activities[0].activity_dir), command)
        self.assertIn(str(activities[1].activity_dir), command)
        self.assertEqual([item["activity_id"] for item in results], ["one", "two"])

    @patch("progression_advisor.subprocess.run")
    def test_accepts_single_result_object(self, run):
        run.return_value.stdout = '{"category":"VT2"}'

        results = inspect_activities(
            [self.activity("one")],
            args=Namespace(type="vt2", vt2_watts=290, force_inspect=True),
        )

        self.assertEqual(results[0]["activity_id"], "one")
        self.assertIn("--force", run.call_args.args[0])

    @patch("progression_advisor.subprocess.run")
    def test_rejects_result_count_mismatch(self, run):
        run.return_value.stdout = '{"category":"VT2"}'

        with self.assertRaisesRegex(RuntimeError, "1 results for 2 activities"):
            inspect_activities(
                [self.activity("one"), self.activity("two")],
                args=Namespace(type="vt2", vt2_watts=290, force_inspect=False),
            )


class ProgressionReviewTests(unittest.TestCase):
    def test_unknown_or_mechanical_response_never_prescribes_a_dose(self):
        for family, current in (("vt2", {"sets": 3, "rep_minutes": 23}),
                                ("vo2max", {"sets": 1, "reps_per_set": 5, "rep_seconds": 180})):
            for stability in ("unknown", "stable", "unstable_or_failed"):
                with self.subTest(family=family, stability=stability):
                    summary = compact_inspect_summary({}, workout_type=family)
                    summary["stability"] = stability
                    result = progression_review(
                        [{"completed_prescription": current, "inspect_summary": summary}],
                        plan_progression={})
                    self.assertEqual(result["status"], "requires_review")
                    self.assertIsNone(result["next_step"]["prescription"])
                    self.assertNotIn("looked controlled", result["coach_summary"])
                    self.assertEqual(result["current_level"], current)

    def test_plan_anchor_and_conditional_next_step_are_preserved(self):
        plan = {"anchor": "3 x 28 min @ 300 W", "target_power_w": 295,
                "next_step": "Review recovery before choosing consolidation or 3x30 at 300 W."}
        result = progression_review([], plan_progression=plan)
        self.assertEqual(result["plan_progression"], plan)
        self.assertIsNone(result["next_step"]["prescription"])
        self.assertEqual(result["status"], "requires_review")

    def test_cli_without_history_or_power_does_not_invent_workout(self):
        script = Path(__file__).resolve().parents[1] / "scripts/progression_advisor.py"
        with TemporaryDirectory() as folder:
            for family in ("vt2", "vo2max"):
                result = json.loads(subprocess.check_output([
                    sys.executable, "-B", str(script), "--type", family,
                    "--date", "2026-01-15", "--artifacts-dir", folder,
                    "--plan-progression-json", '{"next_step":"Review recovery"}',
                ]))
                self.assertEqual(result["status"], "requires_review")
                self.assertIsNone(result["next_step"]["prescription"])
                self.assertEqual(result["plan_progression"]["next_step"], "Review recovery")

    def test_history_does_not_invent_power_or_recoveries(self):
        for family, name in (("vt2", "VT2 3x23 min"), ("vo2max", "VO2Max 1x5x180")):
            result = parse_completed_prescription(name, workout_type=family)
            self.assertIsNone(result["target_power_w"])
            self.assertIsNone(result["recoveries"])
            powered = parse_completed_prescription(name + " @ 350 W", workout_type=family)
            self.assertEqual(powered["target_power_w"], 350)

    def test_plan_structure_survives_recommendation_selection(self):
        from recommend_training import select_intensity_domain
        plan = {"anchor": "8 x 3 min @ 350 W",
                "next_step": "After recovery review, consider 6 x 3 min @ 355 W."}
        advice = progression_review([], plan_progression=plan)
        decision = select_intensity_domain(day="2026-11-17", readiness_ceiling="high_intensity_ok",
            intensity_goal="vo2max", progression_advice={"vo2max": advice},
            plan_progression={"vo2max": plan})
        self.assertEqual(decision["selected_domain"], "vo2max")
        self.assertEqual(decision["progression_next_step"]["summary"], plan["next_step"])
        self.assertEqual(decision["progression_next_step"]["anchor"], plan["anchor"])
        self.assertEqual(decision["progression_next_step"]["source"], "plan_state")

    @patch("progression_advisor.subprocess.run")
    def test_missing_vt2_reference_does_not_use_analysis_default(self, run):
        activity = BatchedActivityInspectionTests().activity("one")
        result = inspect_activities([activity], args=Namespace(type="vt2", vt2_watts=None))
        run.assert_not_called()
        self.assertEqual(result[0]["inspect_summary"]["stability"], "unknown")

    @patch("recommend_training.write_json")
    @patch("recommend_training.run_json", return_value={"status": "requires_review"})
    def test_orchestration_passes_both_plan_references_without_defaults(self, run, write):
        from recommend_training import build_progression_advice
        for power in (350, None):
            run.reset_mock()
            plan = {"vt2": {"target_power_w": 300}, "vo2max": {"next_step": "Review recovery"}}
            if power is not None:
                plan["vo2max"]["target_power_w"] = power
            build_progression_advice(day="2026-11-17", plan_progression=plan,
                source_files={"progression_vt2": Path("vt2.json"), "progression_vo2max": Path("vo2.json")})
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][commands[0].index("--vt2-watts") + 1], "300")
            self.assertEqual(json.loads(commands[1][commands[1].index("--plan-progression-json") + 1]), plan["vo2max"])
            if power is None:
                self.assertNotIn("--vo2max-watts", commands[1])
            else:
                self.assertEqual(commands[1][commands[1].index("--vo2max-watts") + 1], "350")
            self.assertNotIn("380", commands[1])


class InferredVt2PrescriptionTests(unittest.TestCase):
    def test_rejects_long_easy_outdoor_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 936, "average_watts": 149},
                {"type": "WORK", "elapsed_time": 9936, "average_watts": 184},
            ]
        }

        self.assertIsNone(
            infer_prescription_from_intervals(metadata, workout_type="vt2", target_power_w=295)
        )

    def test_accepts_multiple_threshold_power_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 1080, "average_watts": 294},
                {"type": "WORK", "elapsed_time": 1070, "average_watts": 296},
            ]
        }

        prescription = infer_prescription_from_intervals(
            metadata, workout_type="vt2", target_power_w=295
        )

        self.assertEqual(prescription["sets"], 2)
        self.assertEqual(prescription["rep_minutes"], 18)
        self.assertEqual(prescription["target_power_w"], 295)

    def test_uses_supplied_vt2_reference_for_inferred_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 900, "average_watts": 220},
                {"type": "WORK", "elapsed_time": 910, "average_watts": 222},
            ]
        }

        accepted = infer_prescription_from_intervals(
            metadata,
            workout_type="vt2",
            target_power_w=270,
        )
        rejected = infer_prescription_from_intervals(
            metadata,
            workout_type="vt2",
            target_power_w=295,
        )

        self.assertIsNotNone(accepted)
        self.assertIsNone(rejected)


if __name__ == "__main__":
    unittest.main()
