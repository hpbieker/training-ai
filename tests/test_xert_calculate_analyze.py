import json
import math
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "xert"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "xert_activity"
sys.path.insert(0, str(PLUGIN_ROOT))

from xert_calculate_analyze import analyze_calculate_series, summarize_analysis
from xert_strain_model import EMPIRICAL_CALCULATE_RECOVERY_OFFSET_SECONDS


def sample(*, power: float, wexp: float, mpa: float, xssr: float) -> dict:
    return {
        "power": power,
        "wexp": wexp,
        "mpa": mpa,
        "xssr": xssr,
        "xds": 0.0,
    }


class XertCalculateAnalyzeTests(unittest.TestCase):
    def test_default_summary_keeps_authority_and_interpretation(self) -> None:
        payload = {
            "summary": {
                "sig": {"ftp": 100, "atc": 1000, "pp": 300},
                "xss": 1 / 36,
                "xlss": 1 / 36,
                "xhss": 0,
                "xpss": 0,
                "difficulty": 0,
                "sfd": 3600,
                "focus": "Endurance",
                "specificity": "Pure",
            },
            "session_data": [
                {**sample(power=100, wexp=0, mpa=300, xssr=100), "time": 0},
            ],
        }

        summary = summarize_analysis(analyze_calculate_series(payload))

        self.assertTrue(summary["authority"]["xert_summary_authoritative"])
        self.assertEqual(
            summary["interpretation"]["training_domain"],
            "not_inferred_from_xss_alone",
        )
        self.assertIn("does not", summary["interpretation"]["xss_system_statement"])
        self.assertNotIn("model_residuals", summary)

    def test_anonymized_real_depletion_fixture_preserves_activity_mpa_gap(self) -> None:
        payload = json.loads(
            (FIXTURES_DIR / "deep_depletion_segment.json").read_text(
                encoding="utf-8"
            )
        )

        result = analyze_calculate_series(payload)

        self.assertEqual(result["source_kind"], "xert_activity_session")
        self.assertGreater(
            result["model_residuals"]["maximum_absolute_mpa_watts"],
            18.0,
        )
        self.assertLess(
            result["model_residuals"]["maximum_absolute_xssr_per_hour"],
            1e-9,
        )
        self.assertLess(
            result["model_residuals"]["root_mean_square_mpa_watts"],
            result["model_residuals"][
                "root_mean_square_published_linear_mpa_watts"
            ],
        )

    def test_anonymized_real_recovery_fixture_preserves_exponential_recovery(self) -> None:
        payload = json.loads(
            (FIXTURES_DIR / "exponential_recovery_segment.json").read_text(
                encoding="utf-8"
            )
        )

        result = analyze_calculate_series(payload)

        self.assertEqual(
            result["recovery"]["status"],
            "activity_series_pure_exponential",
        )
        self.assertLess(
            result["recovery"][
                "simple_exponential_root_mean_square_residual_joules"
            ],
            1e-9,
        )

    def test_validates_feasible_threshold_series(self) -> None:
        per_sample_xss = (100.0 / 3.0) * (300.0 / 100.0**2 * 100.0 / 3600.0)
        payload = {
            "signature": {"ftp": 100, "atc": 1000, "pp": 300},
            "series": [
                sample(power=100, wexp=0, mpa=300, xssr=100),
                sample(power=100, wexp=0, mpa=300, xssr=100),
            ],
            "calculation_stats": {
                "xlss": 2 * per_sample_xss,
                "xhss": 0,
                "xpss": 0,
                "xss": 2 * per_sample_xss,
                "difficulty": 100 * (1 - math.exp(-2 / 1800)),
                "sfd": 0,
                "focus": "Endurance",
                "specificity": 1,
                "specRating": "Pure",
            },
        }

        result = analyze_calculate_series(payload)

        self.assertTrue(result["feasibility"]["valid"])
        self.assertEqual(result["samples"]["valid_for_fitting"], 2)
        self.assertAlmostEqual(
            result["model_residuals"]["maximum_absolute_mpa_watts"],
            0.0,
        )
        self.assertAlmostEqual(
            result["model_residuals"]["maximum_absolute_xssr_per_hour"],
            0.0,
        )
        self.assertAlmostEqual(
            result["system_xss"]["residual_reconstructed_minus_reported"]["total"],
            0.0,
        )
        self.assertEqual(result["focus"]["status"], "endurance")

    def test_models_calculate_failure_and_later_samples(self) -> None:
        payload = {
            "signature": {"ftp": 100, "atc": 1000, "pp": 300},
            "series": [
                sample(power=301, wexp=0, mpa=300, xssr=900),
                sample(power=50, wexp=0, mpa=300, xssr=300 / 7),
            ],
            "calculation_stats": {},
        }

        result = analyze_calculate_series(payload)

        self.assertFalse(result["feasibility"]["valid"])
        self.assertEqual(result["samples"]["first_failure_index"], 0)
        self.assertEqual(result["samples"]["valid_for_fitting"], 2)
        self.assertEqual(result["samples"]["at_or_above_mpa"], 1)
        self.assertEqual(result["feasibility"]["first_failure_reserve_watts"], -1)
        self.assertEqual(
            result["feasibility"]["minimum_positive_mpa_reserve_watts"],
            250,
        )
        self.assertFalse(result["validity"]["post_failure_samples_excluded"])
        self.assertTrue(result["validity"]["per_sample_model_valid"])
        self.assertAlmostEqual(
            result["model_residuals"]["maximum_absolute_xssr_per_hour"],
            0.0,
        )

    def test_calculate_mpa_floors_at_tp_after_hie_is_exhausted(self) -> None:
        payload = {
            "signature": {"ftp": 300, "atc": 1000, "pp": 500},
            "series": [
                sample(power=400, wexp=1000, mpa=300, xssr=500 / 3),
                sample(power=400, wexp=1000, mpa=300, xssr=500 / 3),
            ],
            "calculation_stats": {},
        }

        result = analyze_calculate_series(payload)

        self.assertEqual(result["samples"]["at_mpa_floor"], 2)
        self.assertAlmostEqual(
            result["model_residuals"]["maximum_absolute_mpa_watts"],
            0.0,
        )
        self.assertAlmostEqual(
            result["model_residuals"]["maximum_absolute_xssr_per_hour"],
            0.0,
        )

    def test_reconstructs_focus_duration_from_peak_to_low_xss(self) -> None:
        payload = {
            "signature": {"ftp": 100, "atc": 1000, "pp": 300},
            "series": [sample(power=100, wexp=0, mpa=300, xssr=100)],
            "calculation_stats": {
                "xlss": 10,
                "xhss": 2,
                "xpss": 5,
                "xss": 17,
                "difficulty": 0,
                "sfd": 5 * math.sqrt(2),
                "focus": "Synthetic",
                "specificity": 8 / 17,
                "specRating": "Mixed",
            },
        }

        result = analyze_calculate_series(payload)

        self.assertAlmostEqual(result["focus"]["peak_to_low_ratio"], 0.5)
        self.assertAlmostEqual(result["focus"]["power_watts"], 200.0)
        self.assertAlmostEqual(result["focus"]["duration_seconds"], 5 * math.sqrt(2))
        self.assertAlmostEqual(result["focus"]["duration_residual_seconds"], 0.0)
        self.assertAlmostEqual(result["specificity"]["calculated"], 8 / 17)
        self.assertAlmostEqual(result["specificity"]["residual"], 0.0)
        self.assertEqual(result["specificity"]["calculated_rating"], "Mixed")

    def test_empirical_recovery_recurrence(self) -> None:
        next_wexp = (
            500 * math.exp(-50 / 1000)
            - EMPIRICAL_CALCULATE_RECOVERY_OFFSET_SECONDS * 50
        )
        payload = {
            "signature": {"ftp": 100, "atc": 1000, "pp": 300},
            "series": [
                sample(power=50, wexp=500, mpa=250, xssr=450 / 7),
                sample(
                    power=50,
                    wexp=next_wexp,
                    mpa=300 - 200 * (next_wexp / 1000) ** 2,
                    xssr=0,
                ),
            ],
            "calculation_stats": {},
        }

        result = analyze_calculate_series(payload)

        self.assertEqual(result["recovery"]["samples"], 1)
        self.assertEqual(
            result["recovery"]["status"],
            "calculate_empirical_affine_exponential_unpublished_origin",
        )
        self.assertAlmostEqual(
            result["recovery"]["maximum_absolute_wexp_residual_joules"],
            0.0,
        )

    def test_accepts_native_activity_session_payload(self) -> None:
        payload = {
            "summary": {
                "sig": {"ftp": 100, "atc": 1000, "pp": 300},
                "xss": 1 / 36,
                "xlss": 1 / 36,
                "xhss": 0,
                "xpss": 0,
                "difficulty": 0,
                "sfd": 3600,
                "focus": "Endurance",
                "specificity": "Pure",
            },
            "session_data": [
                {**sample(power=100, wexp=0, mpa=300, xssr=100), "time": 0},
            ],
        }

        result = analyze_calculate_series(payload)

        self.assertEqual(result["source_kind"], "xert_activity_session")
        self.assertEqual(result["specificity"]["reported_rating"], "Pure")
        self.assertAlmostEqual(result["system_xss"]["reconstructed"]["total"], 1 / 36)

    def test_activity_recovery_uses_pure_exponential_model(self) -> None:
        next_wexp = 500 * math.exp(-50 / 1000)
        payload = {
            "summary": {"sig": {"ftp": 100, "atc": 1000, "pp": 300}},
            "session_data": [
                {
                    **sample(power=50, wexp=500, mpa=250, xssr=450 / 7),
                    "time": 0,
                },
                {
                    **sample(
                        power=50,
                        wexp=next_wexp,
                        mpa=300 - 200 * (next_wexp / 1000) ** 2,
                        xssr=0,
                    ),
                    "time": 1,
                },
            ],
        }

        result = analyze_calculate_series(payload)

        self.assertEqual(
            result["recovery"]["status"],
            "activity_series_pure_exponential",
        )
        self.assertAlmostEqual(
            result["recovery"]["simple_exponential_root_mean_square_residual_joules"],
            0.0,
        )

    def test_integrates_irregular_samples_using_elapsed_time(self) -> None:
        payload = {
            "signature": {"ftp": 100, "atc": 1000, "pp": 300},
            "series": [
                {**sample(power=100, wexp=0, mpa=300, xssr=100), "time": 0},
                {**sample(power=100, wexp=0, mpa=300, xssr=100), "time": 1},
                {**sample(power=100, wexp=0, mpa=300, xssr=100), "time": 4},
            ],
            "calculation_stats": {"xss": 1 / 6, "xlss": 1 / 6, "xhss": 0, "xpss": 0},
        }

        result = analyze_calculate_series(payload)

        self.assertEqual(result["samples"]["irregular_intervals"], 2)
        self.assertEqual(result["samples"]["maximum_interval_seconds"], 3)
        self.assertAlmostEqual(result["system_xss"]["reconstructed"]["total"], 1 / 6)
        self.assertFalse(
            result["system_xss"]["authoritative_summary_comparison"]
        )
        self.assertIn(
            "diagnostic only",
            result["system_xss"]["irregular_sampling_note"],
        )

    def test_rejects_missing_required_activity_sample_field(self) -> None:
        payload = {
            "summary": {"sig": {"ftp": 100, "atc": 1000, "pp": 300}},
            "session_data": [{"time": 0, "power": 100, "mpa": 300}],
        }

        with self.assertRaisesRegex(ValueError, r"series\[0\]\.wexp must be numeric"):
            analyze_calculate_series(payload)

    def test_rejects_missing_signature(self) -> None:
        with self.assertRaisesRegex(ValueError, "signature object"):
            analyze_calculate_series({"series": [{}]})


if __name__ == "__main__":
    unittest.main()
