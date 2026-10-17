from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from activity_inspect import (  # noqa: E402
    add_environmental_derivatives,
    beta_intensity_detection,
    beta_summary,
    beta_vo2_debug,
    default_output_path,
    thermal_evidence_assessment,
    vt2_session_quality,
    vt2_execution_verdict,
)


class EnvironmentalDerivativeTests(unittest.TestCase):
    def test_adds_dewpoint_and_skin_air_vapor_pressure_gradient(self):
        rows = [
            {
                "RuuviTemperature": "17.18",
                "RuuviHumidity": "52.2",
                "skin_temperature": "29.1",
            }
        ]

        add_environmental_derivatives(rows)

        self.assertAlmostEqual(float(rows[0]["dewpoint_c"]), 7.28, places=1)
        self.assertAlmostEqual(
            float(rows[0]["skin_air_vapor_pressure_gradient_kpa"]),
            3.0,
            places=1,
        )

    def test_keeps_dewpoint_when_skin_temperature_is_missing(self):
        rows = [{"RuuviTemperature": "17.18", "RuuviHumidity": "52.2"}]

        add_environmental_derivatives(rows)

        self.assertIn("dewpoint_c", rows[0])
        self.assertNotIn("skin_air_vapor_pressure_gradient_kpa", rows[0])


def block(n, *, watts=290, execution=98):
    return {"n": n, "label": f"block-{n}", "duration_s": 1200,
            "watts_avg": watts, "execution_score": execution,
            "verdict": vt2_execution_verdict({"execution_score": execution})}


class DefaultOutputPathTests(unittest.TestCase):
    def test_default_output_timestamp_is_utc(self):
        activity = type(
            "Activity",
            (),
            {"id": "i123", "activity_dir": Path("unused")},
        )()

        path = default_output_path(activity)

        self.assertRegex(
            path.name,
            r"^i123_\d{8}T\d{12}Z\.json$",
        )


class Vt2SessionQualityTests(unittest.TestCase):
    def test_session_tracks_mechanical_execution_without_cost_grade(self):
        result = vt2_session_quality([block(1), block(2), block(3, watts=282, execution=60)], [])
        self.assertEqual(result["verdict"], "power_execution_variable_or_off_target")
        self.assertEqual(result["worst_execution_block"]["n"], 3)
        self.assertAlmostEqual(result["power_fade_pct"], 2.8)
        self.assertNotIn("combined_score", result)
        self.assertNotIn("response_score", result)

    def test_recovery_extrema_do_not_become_recovery_grade(self):
        result = vt2_session_quality([block(1), block(2)],
                                     [{"after_work_block": 1, "hr_drop_start_to_min": 40}])
        self.assertEqual(result["verdict"], "power_execution_controlled")
        self.assertNotIn("recovery_score", result)
        self.assertNotIn("recovery_trend", result)


class ThermalEvidenceAssessmentTests(unittest.TestCase):
    def test_temperature_alone_is_context_only(self):
        result = thermal_evidence_assessment(
            core_temp_max=38.8,
            core_temp_drift=0.8,
        )

        self.assertEqual(result["grade"], "thermal_context_present")

    def test_aligned_environment_pattern_and_physiology_support_thermal_cost(self):
        result = thermal_evidence_assessment(
            core_temp_max=38.8,
            core_temp_drift=0.8,
            ambient_temp_max=30,
            hr_per_w_drift=9,
            execution_score=95,
        )

        self.assertEqual(result["grade"], "thermal_cost_supported")

    def test_heat_limited_requires_mechanical_and_athlete_evidence(self):
        without_report = thermal_evidence_assessment(
            core_temp_max=38.8,
            core_temp_drift=0.8,
            ambient_temp_max=30,
            hr_per_w_drift=9,
            execution_score=75,
        )
        with_report = thermal_evidence_assessment(
            core_temp_max=38.8,
            core_temp_drift=0.8,
            ambient_temp_max=30,
            hr_per_w_drift=9,
            execution_score=75,
            athlete_heat_report=True,
        )

        self.assertEqual(without_report["grade"], "thermal_cost_supported")
        self.assertEqual(with_report["grade"], "heat_limited")


class IntensityDetectionTests(unittest.TestCase):
    def test_vt1_and_vt2_can_be_detected_without_name_signal(self):
        vt1 = beta_intensity_detection("Innendørssykling", 205)
        vt2 = beta_intensity_detection("Innendørssykling", 290)

        self.assertEqual(vt1["zone"], "vt1_like")
        self.assertEqual(vt1["sources"], ["observed_power_level"])
        self.assertFalse(vt1["name_signal"])
        self.assertEqual(vt2["zone"], "vt2_like")
        self.assertEqual(vt2["sources"], ["observed_power_level"])
        self.assertFalse(vt2["name_signal"])

    def test_summary_uses_detected_zones_before_activity_name(self):
        result = beta_summary(
            {"name": "Innendørssykling"},
            {
                "blocks": [
                    {
                        "intended_zone": "vt2_like",
                        "verdict": "controlled_at_intent",
                    }
                ]
            },
            None,
        )

        self.assertEqual(result["category"], "VT2")

    def test_three_saved_hard_reps_detect_vo2max_without_name_signal(self):
        reps = [
            {
                "duration_seconds": 60,
                "label": f"rep-{index}",
                "summary": {"watts": {"avg": 365, "max": 390}},
                "drift": {},
            }
            for index in range(1, 4)
        ]

        result = beta_vo2_debug(
            {"name": "Innendørssykling"},
            [],
            reps,
            [],
        )

        self.assertIsNotNone(result)
        detection = result["intensity_detection"]
        self.assertEqual(detection["classification"], "vo2max_like")
        self.assertEqual(
            detection["sources"],
            ["saved_work_intervals", "observed_power_pattern"],
        )
        self.assertFalse(detection["name_signal"])
        self.assertTrue(detection["structured_interval_signal"])
        self.assertTrue(detection["observed_power_signal"])

    def test_single_unnamed_hard_rep_is_not_classified_as_vo2max(self):
        result = beta_vo2_debug(
            {"name": "Innendørssykling"},
            [],
            [
                {
                    "duration_seconds": 60,
                    "summary": {"watts": {"avg": 365}},
                    "drift": {},
                }
            ],
            [],
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
