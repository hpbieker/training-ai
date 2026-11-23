import json
import subprocess
import sys
import unittest
from argparse import Namespace
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from progression_advisor import (
    CandidateActivity,
    observed_interval_work,
    inspect_activities,
    compact_inspect_summary,
    progression_review,
    recent_relevant_activities,
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
            observed_work={},
        )

    @patch("progression_advisor.subprocess.run")
    def test_inspects_all_activities_in_one_pipeline_call(self, run):
        run.return_value.stdout = '[{"category":"VT2"},{"category":"VT1"}]'
        activities = [self.activity("one"), self.activity("two")]

        results = inspect_activities(
            activities,
            args=Namespace(type="vt2", force_inspect=False),
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
            args=Namespace(type="vt2", force_inspect=True),
        )

        self.assertEqual(results[0]["activity_id"], "one")
        self.assertIn("--force", run.call_args.args[0])

    @patch("progression_advisor.subprocess.run")
    def test_rejects_result_count_mismatch(self, run):
        run.return_value.stdout = '{"category":"VT2"}'

        with self.assertRaisesRegex(RuntimeError, "1 results for 2 activities"):
            inspect_activities(
                [self.activity("one"), self.activity("two")],
                args=Namespace(type="vt2", force_inspect=False),
            )


class ProgressionReviewTests(unittest.TestCase):
    def test_history_cutoff_requires_a_known_completed_ride(self):
        recordings = {
            "finished": {"start_date_local": "2026-11-17T09:00:00", "elapsed_time": 1800},
            "ongoing": {"start_date_local": "2026-11-17T09:45:00", "elapsed_time": 1800},
            "future": {"start_date_local": "2026-11-17T11:00:00", "elapsed_time": 1800},
            "unknown_duration": {"start_date_local": "2026-11-17T08:00:00"},
            "date_only": {"start_date_local": "2026-11-17", "elapsed_time": 1800},
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for activity_id, values in recordings.items():
                path = root / "activities" / activity_id
                path.mkdir(parents=True)
                (path / "activity.json").write_text(json.dumps({
                    "id": activity_id, "name": "VT2", **values,
                }))
            candidates = recent_relevant_activities(
                workout_type="vt2", day=date(2026, 11, 17), lookback_days=10, max_sessions=6,
                artifacts_dir=root, target_power_w=None, reviewed_events={},
                cutoff=datetime.fromisoformat("2026-11-17T10:00:00+01:00"),
                local_timezone=ZoneInfo("Europe/Oslo"),
            )
        self.assertEqual([candidate.activity_id for candidate in candidates], ["finished"])

    def test_neutral_titles_preserve_short_and_long_reps_and_recoveries(self):
        for count, work, rest in [(13, 30, 15), (6, 60, 60), (4, 240, 180)]:
            with self.subTest(work=work):
                laps = []
                for i in range(count):
                    start = i * (work + rest)
                    laps.append({"type": "WORK", "elapsed_time": work, "start_time": start,
                                 "average_watts": 365})
                    if i < count - 1:
                        laps.append({"type": "RECOVERY", "elapsed_time": rest,
                                     "start_time": start + work, "average_watts": 140})
                metadata = {"name": "Bakkedrag", "icu_intervals": laps}
                observed = observed_interval_work(metadata, workout_type="vo2max", target_power_w=360)
                self.assertEqual(observed["matched_work_seconds"], count * work)
                self.assertEqual(observed["work_rows"][0]["gap_to_next_work_s"], rest)
                self.assertEqual(len(observed["recovery_rows"]), count - 1)
                self.assertEqual(observed["recovery_rows"][0]["average_watts"], 140)
                candidate = observed_interval_work(metadata, workout_type="vo2max", target_power_w=None)
                self.assertEqual(len(candidate["pattern_candidate_indices"]), count)
                self.assertIsNone(candidate["matched_work_seconds"])
                self.assertIsNone(observed_interval_work(
                    {**metadata, "icu_ignore_power": True}, workout_type="vo2max", target_power_w=360))
                self.assertIsNone(observed_interval_work(
                    {**metadata, "icu_intervals": laps[:1]}, workout_type="vo2max", target_power_w=360))

    def test_reviewed_role_takes_precedence_even_without_streams_or_laps(self):
        reviewed = {
            "completed_role": "vo2max", "quality_stimulus": True,
            "quality_role_fulfilled": False, "planned_workout_completed": False,
        }
        with TemporaryDirectory() as folder:
            for activity_id, title in [("a", "Bakkedrag"), ("b", "VO2Max")]:
                path = Path(folder, "activities", activity_id)
                path.mkdir(parents=True)
                (path / "activity.json").write_text(json.dumps({
                    "id": activity_id, "name": title, "start_date_local": "2026-11-10T09:00:00"}))
            candidates = recent_relevant_activities(
                workout_type="vo2max", day=date(2026, 11, 17), lookback_days=10, max_sessions=6,
                artifacts_dir=Path(folder), target_power_w=None,
                reviewed_events={"a": reviewed, "b": {**reviewed, "completed_role": "easy_aerobic"}})
            result, = inspect_activities(candidates, args=Namespace(type="vo2max"))
        self.assertEqual(result["activity_id"], "a")
        self.assertEqual(result["selection_basis"], "reviewed_completed_role")
        self.assertEqual(result["reviewed_classification"], reviewed)
        self.assertFalse(result["streams_available"])
        self.assertIsNone(result["observed_work"])

    def test_unknown_or_mechanical_response_never_prescribes_a_dose(self):
        for family, current in (("vt2", {"sets": 3, "rep_minutes": 23}),
                                ("vo2max", {"sets": 1, "reps_per_set": 5, "rep_seconds": 180})):
            for stability in ("unknown", "stable", "unstable_or_failed"):
                with self.subTest(family=family, stability=stability):
                    summary = compact_inspect_summary({}, workout_type=family)
                    summary["stability"] = stability
                    result = progression_review(
                        [{"observed_work": current, "inspect_summary": summary}],
                        plan_progression={})
                    self.assertEqual(result["status"], "requires_review")
                    self.assertIsNone(result["next_step"]["prescription"])
                    self.assertNotIn("looked controlled", result["coach_summary"])
                    self.assertEqual(result["latest_observed_work"], current)

    def test_compact_drift_retains_signal_and_comparison_scope(self):
        scope = "selected_comparison_windows_only"
        result = compact_inspect_summary({
            "hardest_block": {"change_scope": scope, "br_per_watt_drift_pct": 34},
            "total": {"change_scope": scope, "ve_per_watt_drift_pct": 9},
        }, workout_type="vt2")
        self.assertNotIn("max_relative_drift_pct", result)
        self.assertEqual(result["hardest_block"]["br_per_watt_drift_pct"], 34)
        self.assertIsNone(result["hardest_block"]["ve_per_watt_drift_pct"])
        self.assertEqual(result["hardest_block"]["change_scope"], scope)
        self.assertEqual(result["activity_drift"]["ve_per_watt_drift_pct"], 9)
        self.assertIsNone(result["activity_drift"]["br_per_watt_drift_pct"])
        self.assertEqual(result["activity_drift"]["change_scope"], scope)
        self.assertEqual(result["physiological_cost"], "requires_synthesis")

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

    def test_title_cannot_supply_completed_work(self):
        metadata = {"name": "VT2 3x28 min @ 280 W"}
        self.assertIsNone(observed_interval_work(metadata, workout_type="vt2", target_power_w=None))
        metadata["icu_intervals"] = [{"type": "WORK", "elapsed_time": 1680, "average_watts": 279}] * 2
        observed = observed_interval_work(metadata, workout_type="vt2", target_power_w=None)
        self.assertEqual(observed["matched_work_seconds"], 3360)

    def test_unequal_vt2_and_partial_vo2_laps(self):
        for name, family, power, laps, indices, total in [
            ("Innendørssykling", "vt2", 300, [(1375, 299), (1376, 299), (899, 299)],
             [0, 1, 2], 3650),
            ("VO2Max 7x3 min", "vo2max", 350,
             [(216, 217), (179, 349), (179, 348), (178, 349), (179, 350),
              (179, 347), (177, 350), (180, 347), (86, 344)], list(range(1, 9)), 1337),
        ]:
            with self.subTest(family=family):
                metadata = {"name": name, "icu_intervals": [
                    {"type": "WORK", "elapsed_time": seconds, "average_watts": watts}
                    for seconds, watts in laps]}
                observed = observed_interval_work(metadata, workout_type=family, target_power_w=power)
                self.assertEqual(observed["matched_work_seconds"], total)
                self.assertEqual(observed["matched_interval_indices"], indices)
                self.assertEqual([(r["duration_s"], r["average_watts"])
                                  for r in observed["work_rows"]], laps)

    def test_missing_power_preserves_duration_without_a_family_total(self):
        observed = observed_interval_work(
            {"name": "VT2 3x28 min", "icu_intervals": [{"type": "WORK", "elapsed_time": 1680}]},
            workout_type="vt2", target_power_w=300,
        )
        self.assertEqual(observed["work_rows"][0]["duration_s"], 1680)
        self.assertIsNone(observed["matched_work_seconds"])

    def test_named_single_vt2_and_unnamed_partial_rep(self):
        for name, durations in [("VT2 7 min", [424]), ("Indoor ride", [1680, 1677, 89])]:
            with self.subTest(name=name):
                rows = [{"type": "WORK", "elapsed_time": s, "average_watts": 294} for s in durations]
                observed = observed_interval_work(
                    {"name": name, "icu_intervals": rows}, workout_type="vt2", target_power_w=300
                )
                self.assertEqual(observed["matched_work_seconds"], sum(durations))

    def test_plan_structure_survives_recommendation_selection(self):
        from recommend_training import select_intensity_domain
        plan = {"anchor": "8 x 3 min @ 350 W",
                "next_step": "After recovery review, consider 6 x 3 min @ 355 W."}
        advice = progression_review([], plan_progression=plan)
        decision = select_intensity_domain(readiness_ceiling="high_intensity_ok",
            intensity_goal="vo2max", progression_advice={"vo2max": advice},
            plan_progression={"vo2max": plan})
        self.assertEqual(decision["selected_domain"], "vo2max")
        self.assertEqual(decision["progression_next_step"]["summary"], plan["next_step"])
        self.assertEqual(decision["progression_next_step"]["anchor"], plan["anchor"])
        self.assertEqual(decision["progression_next_step"]["source"], "plan_state")

    @patch("progression_advisor.subprocess.run")
    def test_history_uses_plan_power_only_for_discovery(self, run):
        activity = BatchedActivityInspectionTests().activity("one")
        activity.observed_work["reference_power_w"] = 295
        run.return_value.stdout = json.dumps({
            "vt2_quality": {"intensity_classification": "unresolved"}
        })
        result = inspect_activities([activity], args=Namespace(type="vt2", force_inspect=False))
        command = run.call_args.args[0]
        options = json.loads(command[command.index("--analysis-options-json") + 1])
        self.assertNotIn("vt2_watts", options)
        self.assertEqual(result[0]["observed_work"]["reference_power_w"], 295)
        self.assertEqual(result[0]["inspect_summary"]["vt2_intensity_classification"], "unresolved")

    @patch("recommend_training.write_json")
    @patch("recommend_training.run_json", return_value={"status": "requires_review"})
    def test_recommendation_passes_plan_targets_as_plan_context(self, run, write):
        from recommend_training import build_progression_advice
        plan = {"vt2": {"target_power_w": 295}, "vo2max": {"next_step": "Review recovery"}}
        build_progression_advice(day="2026-11-17", cutoff=datetime.fromisoformat("2026-11-17T09:00:00+01:00"),
            local_timezone="Europe/Oslo", plan_progression=plan, plan_state_path=Path("selected-state.json"),
            source_files={"progression_vt2": Path("vt2.json"), "progression_vo2max": Path("vo2.json")})
        for call in run.call_args_list:
            command = call.args[0]
            family = command[command.index("--type") + 1]
            self.assertEqual(command[command.index("--plan-state") + 1], "selected-state.json")
            self.assertEqual(command[command.index("--as-of") + 1], "2026-11-17T09:00:00+01:00")
            self.assertEqual(command[command.index("--local-timezone") + 1], "Europe/Oslo")
            self.assertEqual(json.loads(command[command.index("--plan-progression-json") + 1]), plan[family])
            self.assertNotIn("--vt2-watts", command)
            self.assertNotIn("--vo2max-watts", command)


class InferredVt2PrescriptionTests(unittest.TestCase):
    def test_rejects_long_easy_outdoor_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 936, "average_watts": 149},
                {"type": "WORK", "elapsed_time": 9936, "average_watts": 184},
            ]
        }

        self.assertIsNone(
            observed_interval_work(metadata, workout_type="vt2", target_power_w=295)
        )

    def test_accepts_multiple_threshold_power_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 1080, "average_watts": 294},
                {"type": "WORK", "elapsed_time": 1070, "average_watts": 296},
            ]
        }

        prescription = observed_interval_work(
            metadata, workout_type="vt2", target_power_w=295
        )

        self.assertEqual(prescription["matched_interval_indices"], [0, 1])
        self.assertEqual(prescription["matched_work_seconds"], 2150)

    def test_uses_supplied_vt2_reference_for_inferred_work_rows(self):
        metadata = {
            "icu_intervals": [
                {"type": "WORK", "elapsed_time": 900, "average_watts": 220},
                {"type": "WORK", "elapsed_time": 910, "average_watts": 222},
            ]
        }

        accepted = observed_interval_work(
            metadata,
            workout_type="vt2",
            target_power_w=270,
        )
        rejected = observed_interval_work(
            metadata,
            workout_type="vt2",
            target_power_w=295,
        )

        self.assertIsNotNone(accepted)
        self.assertIsNone(rejected)


if __name__ == "__main__":
    unittest.main()
