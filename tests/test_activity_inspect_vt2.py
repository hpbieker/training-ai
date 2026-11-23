from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from activity_inspect import (  # noqa: E402
    add_environmental_derivatives,
    default_output_path,
    thermal_evidence_context,
    vt2_session_quality,
    vt2_candidate_blocks,
    vt2_quality,
    vt2_execution_verdict,
)


class Vt2AnchorTests(unittest.TestCase):
    def test_candidate_selection_uses_supplied_anchor(self):
        blocks = [{'summary': {'watts': {'avg': watts}}, 'duration_seconds': 600}
                  for watts in [190, 290, 390]]
        self.assertEqual([i for i, _ in vt2_candidate_blocks(blocks, 190)], [1])
        self.assertEqual([i for i, _ in vt2_candidate_blocks(blocks, 390)], [3])
        self.assertEqual(vt2_candidate_blocks(blocks, None), [])

    def test_name_cannot_override_anchor(self):
        block = {'summary': {'watts': {'avg': 290}}, 'duration_seconds': 600}
        self.assertIsNone(vt2_quality({'name': 'VT2 intervals'}, [], [block], [], vt2_watts=390))

    def test_missing_or_invalid_anchor_keeps_intent_separate(self):
        for anchor in [None, 0, -1, True, float('nan'), float('inf')]:
            result = vt2_quality({'name': 'VT₂ intervals'}, [], [], [], vt2_watts=anchor)
            self.assertEqual(result['intended_session_from_name'], 'vt2')
            self.assertEqual(result['intensity_classification'], 'unresolved')
            self.assertEqual(result['blocks'], [])


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


class ThermalEvidenceContextTests(unittest.TestCase):
    def test_thermal_and_physiological_changes_remain_descriptive(self):
        for ve_drift, br_drift in ((12.0, 14.0), (12.1, 14.1), (-1, 0)):
            with self.subTest(ve_drift=ve_drift, br_drift=br_drift):
                result = thermal_evidence_context(
                    core_temp_max=38.5,
                    core_temp_drift=0.45,
                    ambient_temp_c=28,
                    relative_humidity=80,
                    hr_per_w_drift=9,
                    ve_per_w_drift=ve_drift,
                    br_per_w_drift=br_drift,
                )
                self.assertEqual(result["grade"], "thermal_context_present")
                observed = {item["signal"]: item for item in result["observations"]}
                self.assertEqual(observed["wearable_core_temperature"]["statistics_scope"], "whole_work_block")
                self.assertEqual(observed["wearable_core_temperature_change"]["drift"], 0.45)
                self.assertEqual(observed["late_matched_window_environment"]["air_temperature_c"], 28)
                self.assertEqual(observed["ve_per_watt_drift_pct"]["value"], ve_drift)
                self.assertEqual(observed["br_per_watt_drift_pct"]["value"], br_drift)
                self.assertIn("dependence", observed["hr_per_watt_drift_pct"])

    def test_respiratory_change_without_thermal_context_is_still_reported(self):
        result = thermal_evidence_context(core_temp_max=None, core_temp_drift=None, ve_per_w_drift=20)
        self.assertEqual(result["grade"], "not_assessed")
        self.assertFalse(result["wearable_estimate_not_direct_core_measurement"])
        self.assertEqual(result["observations"], [{"signal": "ve_per_watt_drift_pct", "value": 20}])


if __name__ == "__main__":
    unittest.main()
