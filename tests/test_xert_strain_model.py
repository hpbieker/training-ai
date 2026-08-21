import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "xert"
CALCULATE_FIXTURES = ROOT / "tests" / "fixtures" / "xert_calculate"
STRAIN_FIXTURES = ROOT / "tests" / "fixtures" / "xert_strain"
sys.path.insert(0, str(PLUGIN_ROOT))

from xert_strain_model import (
    calculate_workout,
    solve_segment_duration,
    work_allocation,
)


class XertStrainModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.representative = json.loads(
            (STRAIN_FIXTURES / "representative_workouts.json").read_text(
                encoding="utf-8"
            )
        )

    def representative_result(self, name: str) -> dict:
        return calculate_workout(
            signature=self.representative["signature"],
            segments=self.representative["cases"][name]["segments"],
            include_series=False,
        )

    def test_one_hour_at_tp_is_100_low_xss(self) -> None:
        result = calculate_workout(
            signature={"tp": 300, "hie": 14000, "pp": 800},
            segments=[{"duration_seconds": 3600, "power": 300}],
            include_series=False,
        )

        self.assertAlmostEqual(result["xss"]["total"], 100.0, places=9)
        self.assertAlmostEqual(result["xss"]["low"], 100.0, places=9)
        self.assertEqual(result["xss"]["high"], 0.0)
        self.assertEqual(result["xss"]["peak"], 0.0)
        self.assertAlmostEqual(
            result["difficulty"], 100 * (1 - math.exp(-2)), places=9
        )
        self.assertEqual(
            result["interpretation"]["training_domain"],
            "not_inferred_from_xss_alone",
        )
        self.assertIn(
            "does not identify",
            result["interpretation"]["xss_system_statement"],
        )

    def test_zero_duration_segment_is_retained_without_load(self) -> None:
        result = calculate_workout(
            signature={"tp": 300, "hie": 14000, "pp": 800},
            segments=[{"name": "optional", "duration_seconds": 0, "power": 210}],
            include_series=False,
        )

        self.assertEqual(result["duration_seconds"], 0)
        self.assertEqual(result["xss"]["total"], 0)
        self.assertEqual(result["segments"][0]["duration_seconds"], 0)
        self.assertIsNone(result["segments"][0]["xss_rate_per_hour"]["average"])

    def test_endurance_solver_adjusts_only_marked_segment_to_match_low_xss(self) -> None:
        result = solve_segment_duration(
            signature={"tp": 300, "hie": 14000, "pp": 800},
            segments=[
                {"name": "warmup", "duration_seconds": 900, "power": 150},
                {"name": "endurance", "duration_seconds": 3600, "power": 210},
                {"name": "cooldown", "duration_seconds": 900, "power": 120},
            ],
            adjustable_segment_index=1,
            target_metric="low_xss",
            target_value=200.0,
        )

        self.assertTrue(result["matched_within_tolerance"])
        self.assertAlmostEqual(result["achieved_xss"]["low"], 200.0, delta=0.05)
        self.assertEqual(result["achieved_xss"]["high"], 0.0)
        self.assertEqual(result["achieved_xss"]["peak"], 0.0)
        self.assertEqual(result["segments"][0]["duration_seconds"], 900)
        self.assertEqual(result["segments"][2]["duration_seconds"], 900)
        self.assertNotEqual(result["adjustable_duration_seconds"], 3600)

    def test_segment_solver_allows_zero_duration_for_adjustable_segment(self) -> None:
        signature = {"tp": 300, "hie": 14000, "pp": 800}
        fixed_segments = [{"name": "warmup", "duration_seconds": 900, "power": 150}]
        fixed_load = calculate_workout(
            signature=signature,
            segments=fixed_segments,
            include_series=False,
        )["xss"]["low"]

        result = solve_segment_duration(
            signature=signature,
            segments=[
                *fixed_segments,
                {"name": "optional endurance", "duration_seconds": 900, "power": 210},
            ],
            adjustable_segment_index=1,
            target_metric="low_xss",
            target_value=fixed_load,
            minimum_duration_seconds=0,
            maximum_duration_seconds=0,
        )

        self.assertEqual(result["adjustable_duration_seconds"], 0)
        self.assertEqual(result["segments"][1]["duration_seconds"], 0)
        self.assertTrue(result["matched_within_tolerance"])

    def test_segment_solver_supports_high_xss(self) -> None:
        result = solve_segment_duration(
            signature={"tp": 300, "hie": 14000, "pp": 800},
            segments=[{"duration_seconds": 600, "power": 400}],
            adjustable_segment_index=0,
            target_metric="high_xss",
            target_value=10.0,
        )

        self.assertTrue(result["matched_within_tolerance"])
        self.assertAlmostEqual(result["achieved_target_value"], 10.0, delta=0.05)

    def test_above_tp_allocation_adds_high_and_peak_to_low(self) -> None:
        allocation = work_allocation(400, tp=300, pp=500)

        self.assertEqual(allocation["low"], 300)
        self.assertEqual(allocation["high"], 50)
        self.assertEqual(allocation["peak"], 50)
        self.assertEqual(sum(allocation.values()), 400)

    def test_point_of_failure_and_post_failure_branch_match_probe(self) -> None:
        result = calculate_workout(
            signature={"tp": 300, "hie": math.sqrt(2) * 1000, "pp": 500},
            segments=[{"duration_seconds": 15, "power": 400}],
        )

        failure = result["feasibility"]["first_point_of_failure"]
        self.assertEqual(failure["time_seconds"], 10)
        self.assertAlmostEqual(failure["mpa_watts"], 400.0, places=9)
        self.assertAlmostEqual(result["series"][11]["mpa"], 379.0, places=9)
        self.assertAlmostEqual(result["series"][11]["xssr"], 210.5555555556)
        self.assertTrue(result["feasibility"]["post_failure_is_hypothetical"])

    def test_permanent_calculate_fixture_matches_local_sample_equations(self) -> None:
        fixture = json.loads(
            (CALCULATE_FIXTURES / "point_of_failure_segment.json").read_text(
                encoding="utf-8"
            )
        )
        signature = {
            "tp": float(fixture["signature"]["ftp"]),
            "hie": float(fixture["signature"]["atc"]),
            "pp": float(fixture["signature"]["pp"]),
        }

        for sample in fixture["series"]:
            wexp = sample["wexp"]
            expected_mpa = max(
                signature["tp"],
                signature["pp"]
                - (signature["pp"] - signature["tp"])
                * (wexp / signature["hie"]) ** 2,
            )
            coefficient = (
                sample["mpa"] / sample["power"]
                if sample["power"] >= sample["mpa"]
                else (
                    signature["pp"] - sample["mpa"] + signature["tp"]
                )
                / (
                    signature["pp"] - sample["power"] + signature["tp"]
                )
            )
            expected_xssr = (
                coefficient
                * sample["power"]
                * signature["pp"]
                / signature["tp"] ** 2
                * 100
            )

            self.assertAlmostEqual(sample["mpa"], expected_mpa, places=9)
            self.assertAlmostEqual(sample["xssr"], expected_xssr, places=9)

    def test_hie_exhaustion_floors_mpa_at_tp(self) -> None:
        result = calculate_workout(
            signature={"tp": 300, "hie": math.sqrt(2) * 1000, "pp": 500},
            segments=[{"duration_seconds": 25, "power": 400}],
        )

        self.assertAlmostEqual(result["series"][20]["wexp"], math.sqrt(2) * 1000)
        self.assertAlmostEqual(result["series"][20]["mpa"], 300.0)
        self.assertAlmostEqual(result["series"][20]["xssr"], 500 / 3)

    def test_power_above_pp_is_invalid_even_when_calculated(self) -> None:
        result = calculate_workout(
            signature={"tp": 300, "hie": 2000, "pp": 500},
            segments=[{"duration_seconds": 1, "power": 501}],
            include_series=False,
        )

        self.assertFalse(result["feasibility"]["valid"])
        self.assertTrue(result["feasibility"]["invalid_power_above_pp"])
        self.assertLess(result["xss"]["high"], 0)

    def test_representative_sub_tp_profiles_are_low_only_but_not_equivalent(self) -> None:
        vt1 = self.representative_result("vt1")
        tempo = self.representative_result("tempo")
        vt2 = self.representative_result("vt2")

        for result in (vt1, tempo, vt2):
            self.assertEqual(result["xss"]["high"], 0.0)
            self.assertEqual(result["xss"]["peak"], 0.0)
        self.assertGreater(
            tempo["maximum_xss_rate_per_hour"],
            vt1["maximum_xss_rate_per_hour"],
        )
        self.assertGreater(vt2["difficulty"], vt1["difficulty"])

    def test_representative_vo2_and_sprint_profiles_have_distinct_strain(self) -> None:
        vo2 = self.representative_result("vo2max")
        sprint = self.representative_result("sprint")

        self.assertGreater(vo2["xss"]["high"], 0)
        self.assertGreater(vo2["xss"]["peak"], 0)
        self.assertGreater(sprint["xss"]["peak"], sprint["xss"]["high"])
        self.assertGreater(vo2["difficulty"], sprint["difficulty"])

    def test_representative_fatigue_recovery_and_ramp_expose_dynamics(self) -> None:
        fatigue = self.representative_result("work_under_fatigue")
        recovery = self.representative_result("recovery")
        ramp = self.representative_result("ramp")

        self.assertGreater(
            fatigue["strain_summary"]["mpa"][
                "maximum_same_power_strain_amplification"
            ],
            1.05,
        )
        self.assertGreater(
            recovery["strain_summary"]["mpa"]["end_watts"],
            recovery["strain_summary"]["mpa"]["minimum_watts"],
        )
        self.assertGreater(ramp["xss"]["high"], 0)
        self.assertGreater(ramp["xss"]["peak"], 0)

    def test_strain_summary_identifies_largest_system_contributors(self) -> None:
        result = self.representative_result("vo2max")
        contributors = result["strain_summary"]["largest_system_contributors"]

        self.assertEqual(contributors["high"]["segment_name"], "VO2 4")
        self.assertEqual(contributors["peak"]["segment_name"], "VO2 4")
        self.assertIn("multiplier", result["interpretation"]["mpa_statement"])

if __name__ == "__main__":
    unittest.main()
