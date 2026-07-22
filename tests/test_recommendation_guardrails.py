import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from recommend_today import (
    apply_acute_readiness_target_guardrail,
    body_battery_summary_line,
    build_source_refresh_plan,
    compact_xert_workout_recommendations,
    finalize_plan_trace,
    initialize_plan_trace,
    parse_refresh_spec,
    presentation_requirements,
    weather_command,
)
from route_recommendations import surface_classification


class WeatherCommandTests(unittest.TestCase):
    def test_passes_explicit_location_timezone_to_yr(self):
        command = weather_command(
            None,
            planned_at=datetime.fromisoformat("2026-07-25T08:00:00+01:00"),
            hours=4,
            timezone_name="Europe/Lisbon",
            lat=37.125,
            lon=-8.5833,
        )

        self.assertIn("--timezone", command)
        self.assertEqual(command[command.index("--timezone") + 1], "Europe/Lisbon")


class BodyBatteryPresentationTests(unittest.TestCase):
    def test_summary_exposes_wake_and_current_values(self):
        self.assertEqual(
            body_battery_summary_line(
                {
                    "body_battery_at_wake": 84,
                    "body_battery_most_recent": 72,
                }
            ),
            "at wake=84, now=72",
        )

    def test_presentation_contract_requires_both_values_when_present(self):
        requirement = presentation_requirements()["body_battery"]
        self.assertEqual(
            requirement["required_when_present"],
            ["body_battery_at_wake", "body_battery_most_recent"],
        )
        self.assertIn("holistic", requirement["meaning"])


class AcuteReadinessGuardrailTests(unittest.TestCase):
    def test_caps_xert_dose_for_poor_direct_inputs_and_high_cumulative_load(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 221.3,
            "target_load": 221.3,
            "caution_score": 2.55,
            "rolling_7d_load_percentile_this_year": 75.0,
        }
        initialize_plan_trace(target)
        packet = {
            "date": "2026-07-20",
            "recommendation_inputs": {
                "garmin_recovery_readiness": {
                    "training_readiness_score": 1,
                },
                "garmin_load_focus": {"acute_load": 400, "acwr": 1.3},
                "wellness": {
                    "sleep_time_seconds": 21720,
                    "hrv_last_night_avg": 54,
                    "hrv_balanced_low": 67,
                    "hrv_balanced_upper": 84,
                    "resting_hr": 50,
                    "resting_hr_7day": 45,
                    "body_battery_at_wake": 45,
                },
                "latest_activity_load": {
                    "start_local": "2026-07-19T15:45:29",
                    "xert_xss": 192.1,
                },
            },
        }

        apply_acute_readiness_target_guardrail(target, packet)
        finalize_plan_trace(target)

        self.assertEqual(target["target_minutes"], 45.0)
        self.assertEqual(target["target_load"], 30.0)
        self.assertEqual(target["acute_readiness_guardrail"]["level"], "recovery_day")
        self.assertEqual(
            target["dose_position_vs_typical"]["label"], "acute_readiness_capped"
        )
        self.assertFalse(
            target["acute_readiness_guardrail"]["training_readiness_used_for_dose"]
        )
        self.assertEqual(target["plan_trace"]["base_plan"]["load_xss"], 221.3)
        self.assertEqual(target["plan_trace"]["adjustment"]["status"], "reduced")
        self.assertEqual(
            target["plan_trace"]["final_plan"]["relationship_to_base"],
            "reduced_by_guardrail",
        )

    def test_trace_says_xert_plan_is_unchanged_without_guardrail(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 140.2,
            "target_load": 140.2,
            "reason": "target load from Xert's recommended XSS",
        }

        initialize_plan_trace(target)
        apply_acute_readiness_target_guardrail(
            target,
            {
                "recommendation_inputs": {
                    "garmin_recovery_readiness": {"training_readiness_score": 3},
                    "garmin_load_focus": {"acwr": 0.9},
                    "wellness": {
                        "sleep_time_seconds": 27000,
                        "hrv_last_night_avg": 68,
                        "hrv_balanced_low": 67,
                        "hrv_balanced_upper": 83,
                        "body_battery_at_wake": 84,
                    },
                }
            },
        )
        finalize_plan_trace(target)

        self.assertEqual(
            target["plan_trace"]["base_plan"]["label"],
            "xert_recommended_remaining_dose",
        )
        self.assertEqual(target["plan_trace"]["adjustment"]["status"], "unchanged")
        self.assertEqual(
            target["plan_trace"]["final_plan"]["relationship_to_base"],
            "same_as_base",
        )

    def test_low_cumulative_load_uses_easy_endurance_cap_independent_of_yesterday(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 221.3,
            "target_load": 221.3,
            "rolling_7d_load_percentile_this_year": 38.5,
        }
        inputs = {
            "garmin_recovery_readiness": {"training_readiness_score": 1},
            "garmin_load_focus": {"acute_load": 665, "acwr": 0.7},
            "wellness": {
                "sleep_time_seconds": 21720,
                "hrv_weekly_avg": 61,
                "hrv_balanced_low": 67,
                "hrv_balanced_upper": 84,
                "resting_hr": 49,
                "resting_hr_7day": 45,
                "body_battery_at_wake": 60,
            },
            "latest_activity_load": {
                "start_local": "2026-07-19T15:45:29",
                "xert_xss": 192.1,
            },
        }

        apply_acute_readiness_target_guardrail(
            target, {"date": "2026-07-20", "recommendation_inputs": inputs}
        )

        self.assertEqual(target["target_minutes"], 60.0)
        self.assertEqual(target["target_load"], 45.0)
        self.assertEqual(
            target["acute_readiness_guardrail"]["level"], "easy_endurance_only"
        )
        self.assertEqual(target["acute_readiness_guardrail"]["cumulative_load_risk"], 0.0)

        target_with_high_garmin_score = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 221.3,
            "target_load": 221.3,
            "rolling_7d_load_percentile_this_year": 38.5,
        }
        inputs["garmin_recovery_readiness"]["training_readiness_score"] = 99
        inputs["latest_activity_load"]["xert_xss"] = 500.0
        apply_acute_readiness_target_guardrail(
            target_with_high_garmin_score,
            {"date": "2026-07-20", "recommendation_inputs": inputs},
        )
        self.assertEqual(target_with_high_garmin_score["target_minutes"], 60.0)

    def test_does_not_override_explicit_dose(self):
        target = {
            "source": "explicit_cli",
            "target_minutes": 90.0,
            "target_load": 80.0,
            "caution_score": 3.0,
        }
        apply_acute_readiness_target_guardrail(target, {"recommendation_inputs": {}})
        self.assertEqual(target["target_minutes"], 90.0)
        self.assertNotIn("acute_readiness_guardrail", target)


class SourceRefreshPolicyTests(unittest.TestCase):
    def test_auto_reuses_fresh_source_and_fetches_missing_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            garmin = root / "garmin.json"
            garmin.write_text("{}", encoding="utf-8")
            plan = build_source_refresh_plan(
                {"garmin": garmin, "xert": root / "xert.json"},
                required={"garmin", "xert"},
                refresh_spec=parse_refresh_spec("auto"),
                checked_at=datetime.now(timezone.utc),
            )

        self.assertEqual(plan["garmin"]["status"], "reused")
        self.assertFalse(plan["garmin"]["refresh"])
        self.assertEqual(plan["xert"]["reason"], "missing")
        self.assertTrue(plan["xert"]["refresh"])

    def test_selected_source_forces_only_that_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {"garmin": root / "garmin.json", "xert": root / "xert.json"}
            for path in paths.values():
                path.write_text("{}", encoding="utf-8")
            plan = build_source_refresh_plan(
                paths,
                required=set(paths),
                refresh_spec=parse_refresh_spec("garmin"),
                checked_at=datetime.now(timezone.utc),
            )

        self.assertEqual(plan["garmin"]["status"], "forced")
        self.assertTrue(plan["garmin"]["refresh"])
        self.assertEqual(plan["xert"]["status"], "reused")

    def test_none_marks_old_or_missing_source_stale_offline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = build_source_refresh_plan(
                {"weather_home": root / "weather.json"},
                required={"weather_home"},
                refresh_spec=parse_refresh_spec("none"),
                checked_at=datetime.now(timezone.utc),
            )

        self.assertEqual(plan["weather_home"]["status"], "stale_offline")
        self.assertFalse(plan["weather_home"]["refresh"])

    def test_explicit_override_is_not_refetched_in_auto_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "garmin.json"
            path.write_text("{}", encoding="utf-8")
            plan = build_source_refresh_plan(
                {"garmin": path},
                required={"garmin"},
                refresh_spec=parse_refresh_spec("auto"),
                checked_at=datetime.now(timezone.utc),
                overrides={"garmin"},
            )

        self.assertEqual(plan["garmin"]["status"], "provided")
        self.assertFalse(plan["garmin"]["refresh"])


class SurfaceClassificationTests(unittest.TestCase):
    def test_checkpoint_alone_does_not_prove_gravel_surface(self):
        result = surface_classification(
            {
                "name": "Dokka",
                "description": "På piggdekk pga fortsatt litt snø og is på veiene.",
                "gear": {"id": "b11246236", "name": "Trek Checkpoint"},
            }
        )
        self.assertEqual(result["surface"], "unknown")
        self.assertEqual(result["bike_type"], "gravel")

    def test_explicit_gravel_text_is_surface_evidence(self):
        result = surface_classification(
            {
                "name": "Grusrunde",
                "description": "Fin grus hele veien",
                "gear": {"id": "b11246236", "name": "Trek Checkpoint"},
            }
        )
        self.assertEqual(result["surface"], "gravel")
        self.assertEqual(result["confidence"], "activity_text")


class WorkoutReadinessBiasTests(unittest.TestCase):
    def test_easy_vt1_suppresses_openers_but_keeps_vt1(self):
        payload = {
            "exercises": [
                {
                    "exerciseType": "Workout",
                    "name": "XMB: Openers 3x2 min (260W)",
                    "path": "openers",
                    "duration": 2400,
                    "xss": 35,
                    "max_power": 260,
                },
                {
                    "exerciseType": "Workout",
                    "name": "XMB: VT1 30 min (165W)",
                    "path": "vt1",
                    "duration": 2700,
                    "xss": 30,
                    "max_power": 165,
                },
            ]
        }

        result = compact_xert_workout_recommendations(
            payload,
            target_minutes=45,
            target_load=30,
            readiness_bias="easy_vt1",
        )

        self.assertEqual(result["recommended"]["path"], "vt1")
        self.assertEqual(result["higher_intensity_candidates"], [])
        self.assertEqual(
            [row["path"] for row in result["suppressed_by_readiness_bias"]],
            ["openers"],
        )

    def test_rest_keeps_only_explicit_recovery_workouts(self):
        payload = {
            "exercises": [
                {
                    "exerciseType": "Workout",
                    "name": "XMB: Recovery 30 min",
                    "path": "recovery",
                    "duration": 1800,
                    "xss": 18,
                    "max_power": 150,
                },
                {
                    "exerciseType": "Workout",
                    "name": "XMB: VT1 30 min (165W)",
                    "path": "vt1",
                    "duration": 1800,
                    "xss": 24,
                    "max_power": 165,
                },
            ]
        }

        result = compact_xert_workout_recommendations(
            payload,
            target_minutes=30,
            target_load=20,
            readiness_bias="rest",
        )

        self.assertEqual(result["recommended"]["path"], "recovery")
        self.assertEqual(
            [row["path"] for row in result["suppressed_by_readiness_bias"]],
            ["vt1"],
        )


if __name__ == "__main__":
    unittest.main()
