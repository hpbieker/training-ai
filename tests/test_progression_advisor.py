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


class PreferredWorkoutNameTests(unittest.TestCase):
    def test_cli_prefers_name_text_and_falls_back_to_a_matching_workout(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "progression_advisor.py"
        library = "Library VT2 2x12 min @ 250W"
        preferred = "VT2 2x13 min @ 250W (Personal)"
        unrelated = "VO2Max (Personal)"
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / "workouts.json"
            command = [
                sys.executable, "-B", str(script), "--type", "vt2", "--date", "2026-01-15",
                "--vt2-watts", "250", "--artifacts-dir", str(directory),
                "--xert-recommended-training-json", str(source),
            ]
            for preferred_name, names, expected in (
                ("personal", [library, preferred, unrelated], preferred),
                (None, [library, preferred, unrelated], library),
                ("personal", [library, unrelated], library),
            ):
                with self.subTest(preferred_name=preferred_name, expected=expected):
                    source.write_text(json.dumps({
                        "exercises": [{"exerciseType": "Workout", "name": name} for name in names],
                    }))
                    args = command + (
                        ["--preferred-workout-name-contains", preferred_name] if preferred_name else []
                    )
                    result = json.loads(subprocess.check_output(args))
                    self.assertEqual(result["matching_existing_workouts"]["best"]["name"], expected)


class InferredVt2PrescriptionTests(unittest.TestCase):
    def test_rejects_long_easy_outdoor_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 936, "average_watts": 149},
                {"type": "WORK", "elapsed_time": 9936, "average_watts": 184},
            ]
        }

        self.assertIsNone(
            infer_prescription_from_intervals(metadata, workout_type="vt2")
        )

    def test_accepts_multiple_threshold_power_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 1080, "average_watts": 294},
                {"type": "WORK", "elapsed_time": 1070, "average_watts": 296},
            ]
        }

        prescription = infer_prescription_from_intervals(
            metadata, workout_type="vt2"
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
