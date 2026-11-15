import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, call, patch


SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1] / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

import garmin_connect_api as API  # noqa: E402


class GarminDirectReadTests(unittest.TestCase):
    def test_first_request_logs_in_from_config_and_next_request_reuses_tokens(self):
        with TemporaryDirectory() as workspace:
            config = Path(workspace) / "config.json"
            config.write_text(json.dumps({"username": "test@example.com", "password": "example"}))
            store = Path(workspace) / "session"
            garmin = Mock()
            garmin.login.return_value = (None, None)
            garmin.client.dump.side_effect = lambda directory: (
                Path(directory) / "garmin_tokens.json"
            ).write_text("{}")
            garmin.client.request.return_value.content = b'{"ok": true}'
            factory = Mock(return_value=garmin)
            with (
                patch.dict("os.environ", {"GARMIN_MCP_CONFIG": str(config)}),
                patch.dict(sys.modules, {"garminconnect": SimpleNamespace(Garmin=factory)}),
            ):
                for _ in range(2):
                    self.assertEqual(API.garmin_api_json("/test", token_store=str(store)), {"ok": True})

            garmin.login.assert_called_once_with("{}")
            garmin.client.dump.assert_called_once_with(str(store))
            self.assertEqual(garmin.client.load.call_args_list, [call(str(store)), call(str(store))])
            self.assertEqual(
                [entry for entry in factory.call_args_list if entry.args],
                [call("test@example.com", "example", return_on_mfa=True)],
            )

    def test_mfa_stops_health_fetch_without_prompting_or_retrying(self):
        garmin = Mock()
        garmin.login.return_value = ("needs_mfa", {})

        with (
            TemporaryDirectory() as workspace,
            patch("garmin_connect_auth.load_credentials", return_value=("user", "example")) as config,
            patch("garmin_connect_auth.getpass") as getpass,
            patch.dict(sys.modules, {"garminconnect": SimpleNamespace(Garmin=Mock(return_value=garmin))}),
        ):
            with self.assertRaisesRegex(API.GarminLoginError, "requires MFA"):
                API.fetch_day("2026-11-10", token_store=workspace, tolerate_errors=True)
            config.assert_called_once_with(interactive=False)
            garmin.login.assert_called_once_with("{}")
            getpass.assert_not_called()
            self.assertFalse((Path(workspace) / "garmin_tokens.json").exists())

    @patch.object(API, "garmin_api_json")
    def test_fetch_day_reuses_profile_and_keeps_other_sources_on_error(self, request):
        day = "2026-11-10"
        request.side_effect = [
            {"displayName": "test/profile"},
            {"heartRateValues": []},
            RuntimeError("sleep unavailable"),
            {"calendarDate": day},
        ]

        payload = API.fetch_day(
            day, token_store="token_store", only=["heart_rate", "sleep", "summary"],
            tolerate_errors=True,
        )

        self.assertEqual(payload["sources"]["sleep"]["error"]["type"], "garmin_read_failed")
        self.assertEqual(payload["sources"]["summary"], {"calendarDate": day})
        self.assertEqual(request.call_args_list, [
            call("/userprofile-service/userprofile/settings", token_store="token_store"),
            call(f"/wellness-service/wellness/dailyHeartRate/test%2Fprofile?date={day}", token_store="token_store"),
            call(
                f"/wellness-service/wellness/dailySleepData/test%2Fprofile?date={day}"
                "&nonSleepBufferMinutes=60", token_store="token_store",
            ),
            call(
                f"/usersummary-service/usersummary/daily/test%2Fprofile?calendarDate={day}",
                token_store="token_store",
            ),
        ])

    @patch.object(API, "garmin_api_request")
    def test_fit_download_writes_the_fit_member(self, request):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as files:
            files.writestr("metadata.txt", b"metadata")
            files.writestr("nested/activity.FIT", b"fit bytes")
        request.return_value = archive.getvalue()

        with TemporaryDirectory() as directory:
            output = Path(directory) / "activity.fit"
            path = API.download_activity_file(
                "123", token_store="token_store", file_format="fit", output_path=output
            )
            self.assertEqual(path, output)
            self.assertEqual(output.read_bytes(), b"fit bytes")

        request.assert_called_once_with("/download-service/files/activity/123", token_store="token_store")


class GarminCompactHealthTests(unittest.TestCase):
    def test_training_load_survives_compaction_and_cutoff(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from scripts.readiness_snapshot import compact_training_status

        status = self.payload["sources"]["training_status"]
        row = status["mostRecentTrainingStatus"]["latestTrainingStatusData"]["12345"]
        row.update(trainingStatus=2, trainingStatusFeedbackPhrase="PRODUCTIVE", acuteTrainingLoadDTO={
            "dailyTrainingLoadAcute": 900, "dailyTrainingLoadChronic": 850,
            "dailyAcuteChronicWorkloadRatio": 1.06, "acwrPercent": 45,
            "acwrStatus": "OPTIMAL",
        })
        status["mostRecentTrainingLoadBalance"] = {"metricsTrainingLoadBalanceDTOMap": {
            "12345": {"monthlyLoadAerobicLow": 1000, "monthlyLoadAerobicLowTargetMin": 800,
                      "monthlyLoadAerobicLowTargetMax": 1600, "trainingBalanceFeedbackPhrase": "BALANCED"}
        }}
        compact = API.compact_day_payload(self.payload)["sources"]["training_status"]
        kwargs = {"local_timezone": ZoneInfo("Europe/Oslo")}
        full_values = compact_training_status(status, **kwargs)
        compact_values = compact_training_status(compact, **kwargs)
        for key in ["training_status", "feedback", "acute_load", "chronic_load", "acwr", "acwr_status",
                    "monthly_load_aerobic_low", "monthly_load_aerobic_low_target_min", "load_balance_feedback"]:
            self.assertIsNotNone(full_values[key])
            self.assertEqual(full_values[key], compact_values[key], key)
        self.assertIsNone(compact_training_status(
            compact, data_cutoff=datetime.fromisoformat("2026-08-07T12:00:00Z"), **kwargs))

    def test_nested_overnight_sources_survive_compaction_and_readiness(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from scripts.readiness_snapshot import build_readiness_snapshot, readiness_summary

        payload = {
            "date": "2026-08-17",
            "sources": {
                "hrv": {
                    "sleepEndTimestampGMT": "2026-08-17T05:15:00Z",
                    "sleepEndTimestampLocal": "2026-08-17T07:15:00",
                    "hrvSummary": {
                        "calendarDate": "2026-08-17", "lastNightAvg": 65,
                        "weeklyAvg": 68, "status": "BALANCED",
                        "baseline": {"balancedLow": 60, "balancedUpper": 80},
                    },
                    "hrvReadings": [{"hrvValue": 65}],
                },
                "sleep": {
                    "dailySleepDTO": {
                        "calendarDate": "2026-08-17", "sleepTimeSeconds": 27000,
                        "sleepStartTimestampGMT": "2026-08-16T21:30:00Z",
                        "sleepEndTimestampGMT": "2026-08-17T05:15:00Z",
                        "sleepScores": {"overall": {"value": 85}},
                    },
                    "sleepHeartRate": [{"value": 45}],
                },
                "heart_rate": {"calendarDate": "2026-08-17", "restingHeartRate": 43},
                "summary": {"calendarDate": "2026-08-17", "bodyBatteryAtWakeTime": 92},
            },
        }
        compact = API.compact_day_payload(payload)
        self.assertNotIn("hrvReadings", compact["sources"]["hrv"])
        self.assertNotIn("sleepHeartRate", compact["sources"]["sleep"])
        self.assertEqual(compact["sources"]["sleep"]["sleep_score"], 85)
        self.assertEqual(compact["sources"]["hrv"]["baseline"]["balancedLow"], 60)
        with TemporaryDirectory() as directory:
            def snapshot(source, now, day="2026-08-17"):
                return build_readiness_snapshot(
                    day, artifacts_dir=Path(directory),
                    now=datetime.fromisoformat(now), garmin_input=source,
                    local_timezone=ZoneInfo("Europe/Oslo"),
                )
            raw = snapshot(payload, "2026-08-17T12:00:00+02:00")
            result = snapshot(compact, "2026-08-17T12:00:00+02:00")
            wellness = result["recommendation_inputs"]["wellness"]
            for key, expected in {
                "sleep_time_seconds": 27000, "sleep_score": 85,
                "hrv_last_night_avg": 65, "hrv_weekly_avg": 68,
                "hrv_status": "BALANCED", "resting_hr": 43,
                "body_battery_at_wake": 92,
            }.items():
                self.assertEqual(wellness[key], expected, key)
                self.assertEqual(wellness[key], raw["recommendation_inputs"]["wellness"][key])
            for signal in ["sleep", "hrv", "resting_hr", "body_battery_at_wake"]:
                self.assertTrue(wellness["garmin_signal_status"][signal]["usable_for_assessment"])
            brief = readiness_summary(result)
            self.assertEqual(brief["wellness"]["sleep_score"], 85)
            self.assertIn("data_cutoff_local", brief)
            self.assertIn("interpretation_limits", brief)
            for earlier in (
                snapshot(compact, "2026-08-17T06:00:00+02:00"),
                snapshot(compact, "2026-08-18T12:00:00+02:00", "2026-08-18"),
            ):
                values = earlier["recommendation_inputs"]["wellness"]
                for key in ["sleep_time_seconds", "sleep_score", "hrv_last_night_avg", "resting_hr"]:
                    self.assertIsNone(values[key], key)

    def setUp(self) -> None:
        fixture = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "garmin_readiness_status.json"
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

    def test_compact_day_summarizes_stress_and_body_battery_series(self) -> None:
        payload = {
            "source": "garmin_connect",
            "date": "2026-08-17",
            "sources": {
                "stress": {
                    "avgStressLevel": 8,
                    "maxStressLevel": 78,
                    "stressValuesArray": [[1, 8], [2, 12]],
                    "bodyBatteryValueDescriptorsDTOList": [
                        {"bodyBatteryValueDescriptorKey": "timestamp", "bodyBatteryValueDescriptorIndex": 0},
                        {"bodyBatteryValueDescriptorKey": "bodyBatteryLevel", "bodyBatteryValueDescriptorIndex": 1},
                    ],
                    "bodyBatteryValuesArray": [[1, 46], [2, 92], [3, 70]],
                }
            },
        }

        result = API.compact_day_payload(payload)
        stress = result["sources"]["stress"]

        self.assertEqual(stress["avgStressLevel"], 8)
        self.assertEqual(stress["body_battery"]["point_count"], 3)
        self.assertEqual(stress["body_battery"]["maximum"], 92)
        self.assertNotIn("stressValuesArray", stress)
        self.assertNotIn("bodyBatteryValuesArray", stress)

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
            "source": "garmin_connect",
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
            "source": "garmin_connect",
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
    @patch.object(API, "garmin_api_json")
    def test_fetch_courses_normalizes_courses_for_user(
        self,
        garmin_api_json,
        _local_now,
    ) -> None:
        garmin_api_json.return_value = {
            "coursesForUser": [
                {"courseId": 123, "courseName": "Slemdal"},
                "not-a-course",
            ]
        }

        result = API.fetch_courses(token_store="/mock/garmin-tokens")

        garmin_api_json.assert_called_once_with(
            "/web-gateway/course/owner/",
            token_store="/mock/garmin-tokens",
        )
        self.assertEqual(
            result,
            {
                "source": "garmin_connect",
                "source_time_local": "2026-07-26T20:00:00+02:00",
                "courses": [{"courseId": 123, "courseName": "Slemdal"}],
            },
        )

    @patch.object(API, "local_now", return_value="2026-07-26T20:00:00+02:00")
    @patch.object(API, "garmin_api_json")
    def test_fetch_course_preserves_full_geometry(
        self,
        garmin_api_json,
        _local_now,
    ) -> None:
        course = {
            "courseId": 123,
            "courseName": "Slemdal",
            "geoPoints": [{"latitude": 59.95, "longitude": 10.68}],
        }
        garmin_api_json.return_value = course

        result = API.fetch_course("123", token_store="/mock/garmin-tokens")

        garmin_api_json.assert_called_once_with(
            "/course-service/course/123",
            token_store="/mock/garmin-tokens",
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
                token_store="/mock/garmin-tokens",
                course_name="Kopi",
            )

        sent = garmin_api_json.call_args.kwargs["payload"]
        self.assertNotIn("courseId", sent)
        self.assertNotIn("createDate", sent)
        self.assertEqual(sent["courseName"], "Kopi")
        self.assertEqual(sent["rulePK"], 2)
        self.assertEqual(result["course_id"], "123")
        self.assertTrue(result["verification"]["verified"])

    @patch.object(API, "garmin_api_request")
    def test_delete_course_reads_target_and_verifies_absence(self, request) -> None:
        request.side_effect = [
            b'{"courseId": 123, "courseName": "Kopi"}',
            b"",
            b'{"coursesForUser": [{"courseId": 456}]}',
        ]

        result = API.delete_course("123", token_store="token_store", confirmed_course_id="123")

        self.assertEqual(request.call_args_list, [
            call("/course-service/course/123", token_store="token_store", method="GET",
                 payload=None, accept_json=True),
            call("/course-service/course/123", token_store="token_store", method="DELETE",
                 accept_json=True),
            call("/web-gateway/course/owner/", token_store="token_store", method="GET",
                 payload=None, accept_json=True),
        ])
        self.assertTrue(result["deleted"])
        self.assertEqual(result["course_name"], "Kopi")

    @patch.object(API, "garmin_api_request")
    def test_delete_course_fails_when_absence_cannot_be_verified(self, request) -> None:
        for response in (b"{}", b'{"coursesForUser": [{"courseId": 123}]}'):
            with self.subTest(response=response):
                request.side_effect = [b'{"courseId": 123}', b"", response]
                with self.assertRaises(RuntimeError):
                    API.delete_course("123", token_store="token_store", confirmed_course_id="123")

    def test_delete_course_rejects_mismatched_confirmation(self) -> None:
        with self.assertRaises(SystemExit):
            API.delete_course(
                "123",
                token_store="/mock/garmin-tokens",
                confirmed_course_id="321",
            )


if __name__ == "__main__":
    unittest.main()
