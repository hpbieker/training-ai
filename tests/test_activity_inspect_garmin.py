import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from activity_inspect import garmin_analysis_context


class ActivityInspectGarminTests(unittest.TestCase):
    def test_places_stamina_in_separate_analysis_dimensions(self):
        result = garmin_analysis_context(
            {
                "training_effect": {"aerobic": 3.7, "anaerobic": 3.4},
                "stamina": {
                    "available": True,
                    "available_stamina": {"min": 17, "max_rebound_after_min": 42},
                    "potential_stamina": {"drawdown": 41, "end": 59},
                    "largest_available_potential_gap": {"value": 44},
                    "end_gap": 0,
                },
            },
            {"feel": 2, "icu_rpe": 7},
            [{"watts": "244", "temp": "29", "core_temperature": "38.7"}],
            {
                "watts": {"meaningful_gap": False},
                "heartrate": {"meaningful_gap": False},
            },
        )

        self.assertEqual(result["modeled_stimulus"]["available_stamina"]["min"], 17)
        self.assertEqual(result["total_cost_and_recovery"]["potential_stamina"]["drawdown"], 41)
        controls = result["blind_spot_control"]["checks"]
        self.assertEqual(controls["feel_and_rpe"]["status"], "available")
        self.assertEqual(controls["heat_humidity_or_dehydration"]["status"], "environment_data_available")
        self.assertIn("local_muscular_fatigue_or_soreness", result["blind_spot_control"]["unresolved"])
        heat = result["training_effect_context"]["assessments"]["heat_or_humidity"]
        self.assertEqual(heat["status"], "supported")
        self.assertEqual(heat["confidence"], "moderate")

    def test_missing_subjective_context_is_not_treated_as_normal(self):
        result = garmin_analysis_context(
            {"training_effect": {}, "stamina": {"available": False}},
            {},
            [],
            {},
        )

        controls = result["blind_spot_control"]["checks"]
        self.assertEqual(controls["feel_and_rpe"]["status"], "requires_athlete_report")
        self.assertIn("feel_and_rpe", result["blind_spot_control"]["unresolved"])
        assessments = result["training_effect_context"]["assessments"]
        self.assertEqual(assessments["heat_or_humidity"]["status"], "not_assessed")
        self.assertEqual(assessments["illness"]["status"], "not_assessed")

    def test_context_alone_does_not_claim_training_effect_influence(self):
        result = garmin_analysis_context(
            {"training_effect": {}, "stamina": {"available": False}},
            {"average_altitude": 1800},
            [{"temp": "30", "watts": "250", "heartrate": "160"}],
            {
                "watts": {"meaningful_gap": False},
                "heartrate": {"meaningful_gap": True, "missing_fraction": 0.2, "longest_gap": 45},
            },
        )

        assessments = result["training_effect_context"]["assessments"]
        self.assertEqual(assessments["heat_or_humidity"]["status"], "context_present")
        self.assertEqual(assessments["altitude"]["status"], "context_present")
        self.assertEqual(assessments["sensor_quality"]["status"], "supported")


if __name__ == "__main__":
    unittest.main()
