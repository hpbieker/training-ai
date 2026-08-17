import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1] / "plugins" / "garmin-connect" / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

import garmin_connect_api as API  # noqa: E402


class GarminCompactHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "garmin_readiness_status.json"
        self.payload = json.loads(fixture.read_text(encoding="utf-8"))

    def test_compact_day_preserves_all_six_readiness_drivers(self) -> None:
        result = API.compact_day_payload(self.payload)
        readiness = result["training_readiness"]

        self.assertEqual(readiness["score"], 47)
        self.assertEqual(readiness["observed_at_local"], "2026-08-08T06:49:04.0")
        self.assertEqual(
            set(readiness["drivers"]),
            {
                "sleep_score",
                "recovery_time",
                "hrv_status",
                "acute_load",
                "sleep_history",
                "stress_history",
            },
        )
        self.assertEqual(
            readiness["drivers"]["sleep_history"],
            {"value": None, "factor_percent": 72, "feedback": "GOOD"},
        )
        self.assertEqual(readiness["drivers"]["recovery_time"]["value"], 1260)
        self.assertEqual(readiness["drivers"]["recovery_time"]["hours"], 21.0)
        self.assertTrue(readiness["interpretation"]["drivers_are_not_independent"])
        self.assertEqual(len(result["training_readiness_observations"]), 1)
        self.assertNotIn("training_readiness", result["sources"])
        self.assertIn("training_status", result["sources"])

    def test_compact_day_preserves_vo2max_category_date_and_precision(self) -> None:
        result = API.compact_day_payload(self.payload)
        estimates = result["vo2max"]["estimates"]

        self.assertEqual(set(estimates), {"cycling", "generic"})
        self.assertEqual(estimates["cycling"]["value"], 53.0)
        self.assertEqual(estimates["cycling"]["precise_value"], 53.4)
        self.assertEqual(estimates["cycling"]["calendar_date"], "2026-08-07")
        self.assertEqual(estimates["cycling"]["age_days_at_requested_date"], 1)
        self.assertIsNone(estimates["cycling"]["source_device"])
        self.assertFalse(estimates["cycling"]["source_device_available"])
        self.assertEqual(estimates["generic"]["age_days_at_requested_date"], 2)
        self.assertIn("Do not relabel `generic`", result["vo2max"]["category_note"])
        self.assertTrue(
            result["vo2max"]["interpretation"]["max_met_category_is_opaque"]
        )

    def test_training_status_device_is_context_not_vo2max_provenance(self) -> None:
        result = API.compact_day_payload(self.payload)

        self.assertEqual(result["training_status_context"]["device_id"], 12345)
        self.assertIn(
            "not VO2max source-device proof",
            result["training_status_context"]["provenance_note"],
        )
        self.assertIsNone(result["vo2max"]["estimates"]["cycling"]["source_device"])

    def test_missing_fields_remain_null_and_do_not_become_zero(self) -> None:
        payload = {
            "source": "garmin_connect_gccli",
            "date": "2026-08-08",
            "sources": {
                "training_readiness": [{"score": 50, "level": "MODERATE"}],
                "training_status": {
                    "mostRecentVO2Max": {
                        "cycling": {"calendarDate": "2026-08-08"}
                    }
                },
            },
        }

        result = API.compact_day_payload(payload)

        self.assertIsNone(result["training_readiness"]["drivers"]["sleep_score"]["value"])
        self.assertIsNone(result["training_readiness"]["drivers"]["recovery_time"]["hours"])
        self.assertIsNone(result["vo2max"]["estimates"]["cycling"]["value"])

    def test_compact_readiness_selects_latest_timestamped_row(self) -> None:
        rows = [
            {"score": 80, "timestampLocal": "2026-08-08T06:00:00.0"},
            {"score": 42, "timestampLocal": "2026-08-08T12:00:00.0"},
        ]

        result = API.compact_daily_training_readiness(rows)

        self.assertEqual(result["score"], 42)
        self.assertEqual(result["observed_at_local"], "2026-08-08T12:00:00.0")

    def test_compact_recent_normalizes_each_day(self) -> None:
        recent = {
            "source": "garmin_connect_gccli",
            "start_date": "2026-08-08",
            "end_date": "2026-08-08",
            "days": [self.payload],
        }

        result = API.compact_recent_payload(recent)

        self.assertEqual(len(result["days"]), 1)
        self.assertEqual(result["days"][0]["training_readiness"]["score"], 47)


class GarminCourseTests(unittest.TestCase):
    def test_performance_condition_separates_early_level_and_later_trend(self) -> None:
        details = {
            "metricDescriptors": [
                {"key": "directHeartRate", "metricsIndex": 0},
                {"key": "directPerformanceCondition", "metricsIndex": 1},
                {"key": "directTimestamp", "metricsIndex": 2},
                {"key": "directPower", "metricsIndex": 3},
                {"key": "directTemperature", "metricsIndex": 4},
            ],
            "activityDetailMetrics": [
                {"metrics": [110, None, 0, 120, 20]},
                {"metrics": [140, 4, 600000, 230, 21]},
                {"metrics": [142, 5, 660000, 235, 21]},
                {"metrics": [145, 3, 720000, 240, 22]},
                {"metrics": [160, 1, 1800000, 250, 25]},
                {"metrics": [165, -2, 2400000, 245, 27]},
                {"metrics": [158, 0, 3000000, 220, 26]},
            ],
        }

        result = API.detail_performance_condition_summary(details)

        self.assertTrue(result["available"])
        self.assertEqual(result["early_stable"]["value"], 4.5)
        self.assertEqual(result["early_stable"]["first_elapsed_seconds"], 600.0)
        self.assertEqual(result["early_stable"]["last_elapsed_seconds"], 660.0)
        self.assertEqual(result["early_stable"]["window_seconds"], 60)
        self.assertEqual(result["first_to_last_change"], -4.0)
        self.assertEqual(result["minimum_context"]["value"], -2.0)
        self.assertEqual(result["minimum_context"]["power_w"], 245.0)
        self.assertEqual(result["minimum_context"]["temperature_c"], 27.0)
        self.assertEqual(result["largest_peak_to_later_trough_drop"]["value"], 7.0)
        self.assertEqual(result["thirds"]["final_minus_first"], -5.5)

    def test_performance_condition_marks_missing_series_unavailable(self) -> None:
        self.assertEqual(
            API.detail_performance_condition_summary({"metricDescriptors": []}),
            {
                "available": False,
                "reason": "performance_condition_series_not_exposed",
                "meaning": "Absence is not evidence of poor performance condition.",
            },
        )

    def test_stamina_summary_uses_descriptor_indexes_and_aligned_context(self) -> None:
        details = {
            "metricDescriptors": [
                {"key": "directPotentialStamina", "metricsIndex": 0},
                {"key": "directTimestamp", "metricsIndex": 1},
                {"key": "directPower", "metricsIndex": 2},
                {"key": "directAvailableStamina", "metricsIndex": 3},
                {"key": "directHeartRate", "metricsIndex": 4},
            ],
            "activityDetailMetrics": [
                {"metrics": [100, 1000, 200, 100, 120]},
                {"metrics": [90, 3000, 400, 35, 165]},
                {"metrics": [80, 5000, 180, 72, 140]},
                {"metrics": [75, 7000, 120, 75, 110]},
            ],
        }

        result = API.detail_stamina_summary(details)

        self.assertTrue(result["available"])
        self.assertEqual(result["coverage"]["aligned_point_count"], 4)
        self.assertEqual(result["coverage"]["median_interval_seconds"], 2.0)
        self.assertEqual(result["available_stamina"]["min"], 35.0)
        self.assertEqual(result["available_stamina"]["max_rebound_after_min"], 40.0)
        self.assertEqual(
            result["available_stamina"]["min_context"],
            {
                "timestamp_ms": 3000.0,
                "elapsed_seconds": 2.0,
                "power_w": 400.0,
                "heart_rate_bpm": 165.0,
                "potential_stamina": 90.0,
            },
        )
        self.assertEqual(result["largest_available_potential_gap"]["value"], 55.0)
        self.assertEqual(result["potential_stamina"]["drawdown"], 25.0)
        self.assertTrue(result["available_rejoined_potential_at_end"])

    def test_stamina_summary_marks_missing_series_unavailable(self) -> None:
        self.assertEqual(
            API.detail_stamina_summary({"metricDescriptors": []}),
            {
                "available": False,
                "reason": "stamina_series_not_exposed",
                "meaning": (
                    "Garmin model estimates only; absence is not a physiological value."
                ),
            },
        )

    @patch.object(API, "local_now", return_value="2026-07-26T20:00:00+02:00")
    @patch.object(API, "run_gccli_json")
    def test_fetch_courses_normalizes_courses_for_user(
        self,
        run_gccli_json,
        _local_now,
    ) -> None:
        run_gccli_json.return_value = {
            "coursesForUser": [
                {"courseId": 123, "courseName": "Slemdal"},
                "not-a-course",
            ]
        }

        result = API.fetch_courses(gccli="/opt/homebrew/bin/gccli")

        run_gccli_json.assert_called_once_with(
            "/opt/homebrew/bin/gccli",
            ["courses", "list"],
        )
        self.assertEqual(
            result,
            {
                "source": "garmin_connect_gccli",
                "source_time_local": "2026-07-26T20:00:00+02:00",
                "courses": [{"courseId": 123, "courseName": "Slemdal"}],
            },
        )

    @patch.object(API, "local_now", return_value="2026-07-26T20:00:00+02:00")
    @patch.object(API, "run_gccli_json")
    def test_fetch_course_preserves_full_geometry(
        self,
        run_gccli_json,
        _local_now,
    ) -> None:
        course = {
            "courseId": 123,
            "courseName": "Slemdal",
            "geoPoints": [{"latitude": 59.95, "longitude": 10.68}],
        }
        run_gccli_json.return_value = course

        result = API.fetch_course("123", gccli="/opt/homebrew/bin/gccli")

        run_gccli_json.assert_called_once_with(
            "/opt/homebrew/bin/gccli",
            ["courses", "detail", "123"],
        )
        self.assertEqual(result["course_id"], "123")
        self.assertIs(result["course"], course)

    @patch.object(API, "local_now", return_value="2026-07-26T20:00:00+02:00")
    @patch.object(API, "fetch_course")
    @patch.object(API, "garmin_api_json")
    def test_upload_course_sanitizes_and_verifies(
        self,
        garmin_api_json,
        fetch_course,
        _local_now,
    ) -> None:
        source = {
            "course": {
                "courseId": 99,
                "courseName": "Original",
                "activityTypePk": 10,
                "geoPoints": [{"latitude": 59.95, "longitude": 10.68}],
                "coursePoints": [{"name": "Intervall start"}],
                "createDate": "server-owned",
            }
        }
        uploaded = {
            "courseId": 123,
            "courseName": "Kopi",
            "activityTypePk": 10,
            "geoPoints": source["course"]["geoPoints"],
            "coursePoints": source["course"]["coursePoints"],
            "coursePrivacy": 2,
            "rulePK": 2,
        }
        garmin_api_json.return_value = {"courseId": 123}
        fetch_course.return_value = {"course": uploaded}

        with TemporaryDirectory() as directory:
            path = Path(directory) / "course.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            result = API.upload_course(
                str(path),
                gccli="/opt/homebrew/bin/gccli",
                course_name="Kopi",
            )

        sent = garmin_api_json.call_args.kwargs["payload"]
        self.assertNotIn("courseId", sent)
        self.assertNotIn("createDate", sent)
        self.assertEqual(sent["courseName"], "Kopi")
        self.assertEqual(sent["rulePK"], 2)
        self.assertEqual(result["course_id"], "123")
        self.assertTrue(result["verification"]["verified"])

    @patch.object(API, "local_now", return_value="2026-07-26T20:00:00+02:00")
    @patch.object(API, "fetch_courses")
    @patch.object(API, "fetch_course")
    @patch.object(API.subprocess, "run")
    def test_delete_course_requires_id_and_verifies_absence(
        self,
        subprocess_run,
        fetch_course,
        fetch_courses,
        _local_now,
    ) -> None:
        subprocess_run.return_value = SimpleNamespace(
            returncode=0,
            args=[],
            stdout="",
            stderr="",
        )
        fetch_course.return_value = {"course": {"courseId": 123, "courseName": "Kopi"}}
        fetch_courses.return_value = {"courses": [{"courseId": 456}]}

        result = API.delete_course(
            "123",
            gccli="/opt/homebrew/bin/gccli",
            confirmed_course_id="123",
        )

        subprocess_run.assert_called_once_with(
            ["/opt/homebrew/bin/gccli", "courses", "delete", "123", "--force"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertTrue(result["deleted"])

    def test_delete_course_rejects_mismatched_confirmation(self) -> None:
        with self.assertRaises(SystemExit):
            API.delete_course(
                "123",
                gccli="/opt/homebrew/bin/gccli",
                confirmed_course_id="321",
            )


if __name__ == "__main__":
    unittest.main()
