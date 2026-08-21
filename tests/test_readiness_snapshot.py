import unittest
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.readiness_snapshot import (
    add_seconds,
    availability_notes,
    build_readiness_snapshot,
    compact_hrv_history,
    compact_xert_advice,
    latest_xert_advice,
    intervals_wellness_context,
    project_garmin_recovery_hours,
    parse_source_inputs_json,
    parse_time_context_json,
    recommendation_inputs,
    format_local,
    validate_garmin_wellness_signals,
)


class AvailabilityNotesTests(unittest.TestCase):
    def test_stale_note_distinguishes_dynamic_and_completed_daily_signals(self):
        notes = availability_notes(
            "2026-07-31",
            activity=None,
            garmin={},
            xert={},
            freshness={
                "garmin_heart_rate_latest": {"freshness": "stale"},
            },
            now=datetime.fromisoformat("2026-07-31T12:00:00+00:00"),
        )

        text = " ".join(notes)
        self.assertIn("Stale dynamic time-series input", text)
        self.assertIn("completed current-day sleep", text)
        self.assertNotIn("before relying on a now-decision", text)


class XertAdviceContractTests(unittest.TestCase):
    def test_accepts_current_mcp_advice_and_state_envelopes(self):
        result = latest_xert_advice(
            now=datetime.fromisoformat("2026-08-08T08:00:00+02:00"),
            planned_at=datetime.fromisoformat("2026-08-08T10:00:00+02:00"),
            xert_input={
                "training_advice": {
                    "view": "summary",
                    "advice": {
                        "source": "xert_recommended_training",
                        "source_scope": "planned_time",
                        "target_xss": {"low": 80, "high": 4, "peak": 0},
                        "remaining_xss": {"low": 50, "high": 2, "peak": 0},
                    },
                },
                "training_state": {
                    "view": "summary",
                    "state": {
                        "source": "xert_plugin_training_state",
                        "as_of": "2026-08-08T08:00:00+02:00",
                        "recovery_hours": {"low": 1, "high": 3, "peak": 0},
                        "training_load": {"low": 70, "high": 8, "peak": 2},
                        "recovery_load": {"low": 68, "high": 9, "peak": 1},
                    },
                },
            },
            local_timezone=ZoneInfo("Europe/Oslo"),
        )

        self.assertEqual(result["training_advice"]["remaining_xss"]["low"], 50)
        self.assertEqual(result["recovery_hours"]["high"], 3)
        self.assertEqual(result["training_load"]["low"], 70)

    def test_accepts_direct_mcp_advice_envelope_without_state(self):
        result = latest_xert_advice(
            now=datetime.fromisoformat("2026-08-08T08:00:00+02:00"),
            planned_at=None,
            xert_input={
                "view": "summary",
                "advice": {
                    "source_scope": "current",
                    "target_xss": {"low": 40, "high": 0, "peak": 0},
                },
            },
            local_timezone=ZoneInfo("Europe/Oslo"),
        )

        self.assertEqual(result["training_advice"]["target_xss"]["low"], 40)

    def test_preserves_xata_context_and_source_projection(self):
        result = compact_xert_advice(
            {
                "source": "xert_web_direct",
                "recovery_hours": {"low": 4, "high": 2, "peak": 1},
                "recovery_hours_at_advice_time": {
                    "low": -2,
                    "high": -4,
                    "peak": -5,
                },
            },
            training_advice={
                "target_xss": {"low": 100, "high": 2, "peak": 0},
                "xss_deficit": 300,
                "xss_goal": 102,
                "availability": 2,
                "is_availability_restricted": True,
                "targets_source": "XATA",
                "improvement_rate": 3,
                "phase": "Continuous",
            },
            training_advice_debug=None,
            now=datetime.fromisoformat("2026-08-08T08:00:00+02:00"),
            planned_at=datetime.fromisoformat("2026-08-08T10:00:00+02:00"),
            source_time_local="2026-08-08T08:00:00+02:00",
            source_file=None,
            local_timezone=ZoneInfo("Europe/Oslo"),
        )

        advice = result["training_advice"]
        self.assertEqual(advice["xss_deficit"], 300)
        self.assertEqual(advice["targets_source"], "XATA")
        self.assertTrue(advice["is_availability_restricted"])
        self.assertEqual(
            result["projected_recovery_hours_at_planned_time"]["low"],
            -2,
        )


class TimeContextContractTests(unittest.TestCase):
    def test_full_time_context_is_normalized(self):
        parsed = parse_time_context_json(
            '{"date":"2026-07-31","local_timezone":"Europe/Lisbon",'
            '"now":"2026-07-31T08:32:00+01:00",'
            '"planned_at":"2026-07-31T10:15:00+01:00"}'
        )
        self.assertEqual(parsed["date"], "2026-07-31")
        self.assertEqual(parsed["now"].isoformat(), "2026-07-31T08:32:00+01:00")

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "explicit UTC offset"):
            parse_time_context_json(
                '{"date":"2026-07-31","local_timezone":"Europe/Lisbon",'
                '"now":"2026-07-31T08:32:00"}'
            )

    def test_offset_must_match_iana_timezone(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "does not match"):
            parse_time_context_json(
                '{"date":"2026-07-31","local_timezone":"Europe/Lisbon",'
                '"now":"2026-07-31T08:32:00+02:00"}'
            )

    def test_timestamp_must_fall_on_context_date(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "must fall on"):
            parse_time_context_json(
                '{"date":"2026-07-31","local_timezone":"Europe/Lisbon",'
                '"now":"2026-07-31T08:32:00+01:00",'
                '"planned_at":"2026-08-01T10:15:00+01:00"}'
            )

    def test_unknown_field_is_rejected(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "unsupported"):
            parse_time_context_json(
                '{"date":"2026-07-31","local_timezone":"Europe/Lisbon",'
                '"now":"2026-07-31T08:32:00+01:00","timezone":"UTC"}'
            )


class SourceInputsContractTests(unittest.TestCase):
    def test_source_inputs_are_validated_as_one_object(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                name: root / f"{name}.json"
                for name in ("garmin", "xert", "wellness", "events")
            }
            for path in paths.values():
                path.write_text("{}", encoding="utf-8")

            parsed = parse_source_inputs_json(
                json.dumps(
                    {
                        "garmin": str(paths["garmin"]),
                        "xert": str(paths["xert"]),
                        "intervals": {
                            "wellness": str(paths["wellness"]),
                            "events": str(paths["events"]),
                        },
                    }
                )
            )

        self.assertEqual(parsed["garmin"], str(paths["garmin"]))
        self.assertEqual(parsed["intervals"]["events"], str(paths["events"]))

    def test_source_inputs_reject_unknown_fields_and_missing_files(self):
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "unsupported source-input field",
        ):
            parse_source_inputs_json('{"garmins":"typo.json"}')
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "file does not exist",
        ):
            parse_source_inputs_json('{"garmin":"/tmp/does-not-exist.json"}')

    def test_empty_source_inputs_are_explicitly_supported(self):
        self.assertEqual(parse_source_inputs_json("{}"), {})


class TimezoneBoundaryTests(unittest.TestCase):
    def test_same_instant_can_have_different_local_calendar_dates(self):
        instant = datetime.fromisoformat("2026-07-28T22:30:00+00:00")
        self.assertEqual(
            format_local(instant, local_timezone=ZoneInfo("Europe/Lisbon")),
            "2026-07-28T23:30:00+01:00",
        )
        self.assertEqual(
            format_local(instant, local_timezone=ZoneInfo("Europe/Oslo")),
            "2026-07-29T00:30:00+02:00",
        )

    def test_elapsed_seconds_cross_midnight(self):
        self.assertEqual(
            add_seconds(
                "2026-07-28T23:30:00",
                7200,
                local_timezone=ZoneInfo("Europe/Lisbon"),
            ),
            "2026-07-29T01:30:00+01:00",
        )

    def test_elapsed_seconds_use_utc_across_dst_jump(self):
        self.assertEqual(
            add_seconds(
                "2026-03-29T00:30:00",
                7200,
                local_timezone=ZoneInfo("Europe/Lisbon"),
            ),
            "2026-03-29T03:30:00+01:00",
        )


class GarminSignalValidationTests(unittest.TestCase):
    def validate(
        self,
        *,
        values=None,
        source_context=None,
        body_freshness=None,
    ):
        return validate_garmin_wellness_signals(
            day="2026-07-26",
            local_timezone=ZoneInfo("Europe/Lisbon"),
            now=datetime.fromisoformat("2026-07-26T15:00:00+01:00"),
            freshness={
                "garmin_body_battery_latest": body_freshness
                or {
                    "latest_local": None,
                    "age_minutes": None,
                    "freshness": "missing",
                }
            },
            values={
                "hrv_last_night_avg": None,
                "hrv_3day_mean": 60,
                "hrv_nights_used_3d": 3,
                "sleep_time_seconds": None,
                "sleep_score": None,
                "resting_hr": None,
                "resting_hr_7day": 45,
                "body_battery_at_wake": None,
                "body_battery_most_recent": None,
                **(values or {}),
            },
            source_context={
                "hrv_observation_date": None,
                "sleep_calendar_date": None,
                "sleep_start_local": None,
                "sleep_end_local": None,
                "summary_calendar_date": None,
                "heart_rate_calendar_date": None,
                "body_battery_calendar_date": None,
                **(source_context or {}),
            },
        )

    def test_reset_zero_sleep_is_unavailable_not_zero_hours(self):
        result = self.validate(
            values={
                "sleep_time_seconds": 0,
                "sleep_score": 0,
                "resting_hr": 58,
            },
            source_context={
                "sleep_calendar_date": "2026-07-26",
                "summary_calendar_date": "2026-07-26",
            },
        )

        self.assertIsNone(result["sleep_time_seconds"])
        self.assertIsNone(result["sleep_score"])
        self.assertIsNone(result["resting_hr"])
        self.assertEqual(
            result["garmin_signal_status"]["sleep"]["reason"],
            "incomplete_sleep",
        )
        self.assertEqual(
            result["garmin_signal_status"]["resting_hr"]["reason"],
            "morning_sync_incomplete",
        )

    def test_previous_day_hrv_and_rhr_are_excluded_from_downgrade(self):
        result = self.validate(
            values={
                "hrv_last_night_avg": 45,
                "hrv_3day_mean": 50,
                "resting_hr": 60,
            },
            source_context={
                "hrv_observation_date": "2026-07-25",
                "summary_calendar_date": "2026-07-25",
            },
        )

        self.assertIsNone(result["hrv_last_night_avg"])
        self.assertIsNone(result["hrv_3day_mean"])
        self.assertIsNone(result["resting_hr"])

    def test_complete_daily_signals_remain_usable_in_afternoon(self):
        result = self.validate(
            values={
                "hrv_last_night_avg": 70,
                "hrv_3day_mean": 68,
                "hrv_nights_used_3d": 3,
                "sleep_time_seconds": 28080,
                "sleep_score": 88,
                "resting_hr": 44,
                "body_battery_at_wake": 92,
            },
            source_context={
                "hrv_observation_date": "2026-07-26",
                "sleep_calendar_date": "2026-07-26",
                "sleep_start_utc": "2026-07-25T21:30:00Z",
                "sleep_end_utc": "2026-07-26T05:50:00Z",
                "sleep_start_local": "2026-07-25T22:30:00",
                "sleep_end_local": "2026-07-26T06:50:00",
                "summary_calendar_date": "2026-07-26",
                "body_battery_calendar_date": "2026-07-26",
            },
        )

        self.assertEqual(result["sleep_time_seconds"], 28080)
        self.assertEqual(result["hrv_last_night_avg"], 70)
        self.assertEqual(result["resting_hr"], 44)
        self.assertEqual(result["body_battery_at_wake"], 92)

    def test_stale_current_body_battery_is_ignored_but_wake_value_remains(self):
        result = self.validate(
            values={
                "body_battery_at_wake": 88,
                "body_battery_most_recent": 25,
                "body_battery_latest": {
                    "timestamp_ms": 1785051000000,
                    "value": 25,
                },
            },
            source_context={"body_battery_calendar_date": "2026-07-26"},
            body_freshness={
                "latest_local": "2026-07-26T07:30:00+01:00",
                "age_minutes": 450,
                "freshness": "stale",
            },
        )

        self.assertEqual(result["body_battery_at_wake"], 88)
        self.assertIsNone(result["body_battery_most_recent"])
        self.assertIsNone(result["body_battery_latest"])
        self.assertEqual(
            result["garmin_signal_status"]["body_battery_current"]["status"],
            "unavailable",
        )

    def test_projects_previous_day_recovery_time_to_future_planned_start(self):
        now = datetime.fromisoformat("2026-07-27T12:38:00+02:00")
        planned = datetime.fromisoformat("2026-07-28T07:00:00+02:00")
        result = recommendation_inputs(
            activity=None,
            garmin={
                "training_readiness": {
                    "timestamp": "2026-07-27T08:03:00Z",
                    "timestampLocal": "2026-07-27T10:03:00+02:00",
                    "recovery_time_hours": 39.1,
                }
            },
            xert=None,
            freshness={},
            now=now,
            planned_at=planned,
            local_timezone=ZoneInfo("Europe/Oslo"),
        )

        recovery = result["garmin_recovery_readiness"]
        self.assertEqual(recovery["projected_recovery_time_hours_now"], 36.5)
        self.assertEqual(recovery["projected_recovery_time_hours_at_planned"], 18.1)
        self.assertIn("no intervening training", recovery["recovery_projection_assumption"])

    def test_garmin_recovery_projection_stops_at_zero(self):
        self.assertEqual(project_garmin_recovery_hours(4, 10), 0.0)


class DataCutoffTests(unittest.TestCase):
    def test_compact_garmin_input_exposes_all_six_readiness_drivers(self):
        fixture = Path(__file__).parent / "fixtures" / "garmin_readiness_status.json"
        raw_payload = json.loads(fixture.read_text(encoding="utf-8"))
        garmin_scripts = (
            Path(__file__).resolve().parents[1]
            / "plugins"
            / "garmin-connect"
            / "scripts"
        )
        sys.path.insert(0, str(garmin_scripts))
        try:
            import garmin_connect_api as garmin_api

            compact = garmin_api.compact_day_payload(raw_payload)
        finally:
            sys.path.pop(0)

        snapshot = build_readiness_snapshot(
            "2026-08-08",
            artifacts_dir=Path("/nonexistent"),
            local_timezone=ZoneInfo("Europe/Oslo"),
            now=datetime.fromisoformat("2026-08-08T09:00:00+02:00"),
            garmin_input=compact,
        )

        readiness = snapshot["recommendation_inputs"]["garmin_recovery_readiness"]
        self.assertEqual(
            set(readiness["training_readiness_drivers"]),
            {
                "sleep_score",
                "recovery_time",
                "hrv_status",
                "acute_load",
                "sleep_history",
                "stress_history",
            },
        )
        self.assertTrue(readiness["training_readiness_diagnostic_only"])
        self.assertIn(
            "not independent decision weights",
            readiness["training_readiness_driver_families"]["meaning"],
        )
        vo2max = snapshot["recommendation_inputs"]["garmin_vo2max"]
        self.assertTrue(vo2max["diagnostic_only"])
        self.assertIn("cycling", vo2max["estimates"])
        self.assertEqual(
            vo2max["estimates"]["cycling"]["precise_value"],
            53.4,
        )
        self.assertIn("not use a single value as acute readiness", vo2max["meaning"])

    def test_algarve_activity_times_drive_xert_match_and_post_activity_window(self):
        lisbon = ZoneInfo("Europe/Lisbon")
        with tempfile.TemporaryDirectory() as raw_dir:
            artifacts_dir = Path(raw_dir)
            activity_dir = artifacts_dir / "activities" / "2026-07-28_ride"
            activity_dir.mkdir(parents=True)
            (activity_dir / "activity.json").write_text(
                json.dumps(
                    {
                        "id": "ride",
                        "name": "Algarve ride",
                        "start_date_local": "2026-07-28T07:13:25",
                        "elapsed_time": 10871,
                    }
                ),
                encoding="utf-8",
            )
            during_ride = datetime.fromisoformat("2026-07-28T09:00:00+00:00")
            after_ride_1 = datetime.fromisoformat("2026-07-28T09:20:00+00:00")
            after_ride_2 = datetime.fromisoformat("2026-07-28T09:30:00+00:00")
            snapshot = build_readiness_snapshot(
                    "2026-07-28",
                    artifacts_dir=artifacts_dir,
                    local_timezone=lisbon,
                    now=datetime.fromisoformat("2026-07-28T12:00:00+01:00"),
                    xert_input={
                        "activity_loads": [
                            {
                                "path": "xert-ride",
                                "name": "Xert Algarve ride",
                                "start_local": "2026-07-28T08:13:25+02:00",
                                "elapsed_minutes": 181.2,
                                "xss": {
                                    "total": 164.7,
                                    "low": 164.2,
                                    "high": 0.4,
                                    "peak": 0.1,
                                },
                            }
                        ]
                    },
                    garmin_input={
                        "sources": {
                            "heart_rate": {
                                "calendarDate": "2026-07-28",
                                "heartRateValues": [
                                    [int(during_ride.timestamp() * 1000), 151],
                                    [int(after_ride_1.timestamp() * 1000), 70],
                                    [int(after_ride_2.timestamp() * 1000), 60],
                                ],
                            }
                        }
                    },
            )

        activity = snapshot["latest_activity"]
        post = snapshot["garmin"]["heart_rate"]["post_activity"]
        self.assertEqual(activity["start_local"], "2026-07-28T07:13:25+01:00")
        self.assertEqual(activity["start_utc"], "2026-07-28T06:13:25Z")
        self.assertEqual(activity["end_local"], "2026-07-28T10:14:36+01:00")
        self.assertEqual(activity["end_utc"], "2026-07-28T09:14:36Z")
        self.assertEqual(activity["xert_load"]["path"], "xert-ride")
        self.assertEqual(activity["xert_load"]["match_delta_minutes"], 0.0)
        self.assertEqual(post["count"], 2)
        self.assertEqual(post["max"], 70.0)
        self.assertEqual(
            snapshot["garmin"]["heart_rate"]["post_activity_window"]["start_local"],
            "2026-07-28T10:14:36+01:00",
        )

    def test_resolved_location_timezone_controls_local_display_and_utc_cutoff(self):
        lisbon = ZoneInfo("Europe/Lisbon")
        snapshot = build_readiness_snapshot(
                "2026-07-28",
                artifacts_dir=Path("/nonexistent"),
                local_timezone=lisbon,
                now=datetime.fromisoformat("2026-07-28T12:00:00+02:00"),
                planned_at=datetime.fromisoformat("2026-07-28T07:00:00+01:00"),
        )

        self.assertEqual(snapshot["local_timezone"], "Europe/Lisbon")
        self.assertEqual(
            snapshot["planned_workout_time_local"],
            "2026-07-28T07:00:00+01:00",
        )
        self.assertEqual(snapshot["planned_workout_time_utc"], "2026-07-28T06:00:00Z")
        self.assertEqual(snapshot["data_cutoff_local"], "2026-07-28T07:00:00+01:00")
        self.assertEqual(snapshot["data_cutoff_utc"], "2026-07-28T06:00:00Z")

    def test_cutoff_is_stored_as_utc_even_when_now_and_plan_use_different_offsets(self):
        now = datetime.fromisoformat("2026-07-28T08:30:00+02:00")
        planned = datetime.fromisoformat("2026-07-28T07:00:00+01:00")
        snapshot = build_readiness_snapshot(
            "2026-07-28",
            artifacts_dir=Path("/nonexistent"),
            local_timezone=ZoneInfo("Europe/Lisbon"),
            now=now,
            planned_at=planned,
        )

        self.assertEqual(snapshot["data_cutoff_utc"], "2026-07-28T06:00:00Z")
        self.assertEqual(
            datetime.fromisoformat(snapshot["data_cutoff_utc"].replace("Z", "+00:00")),
            planned.astimezone(timezone.utc),
        )

    def test_planned_at_caps_activity_and_garmin_series(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            artifacts_dir = Path(raw_dir)
            activities_dir = artifacts_dir / "activities"
            before_dir = activities_dir / "2026-07-28_before"
            after_dir = activities_dir / "2026-07-28_after"
            before_dir.mkdir(parents=True)
            after_dir.mkdir(parents=True)
            (before_dir / "activity.json").write_text(
                json.dumps(
                    {
                        "id": "before",
                        "name": "Before cutoff",
                        "start_date_local": "2026-07-28T05:30:00+02:00",
                        "elapsed_time": 1800,
                    }
                ),
                encoding="utf-8",
            )
            (after_dir / "activity.json").write_text(
                json.dumps(
                    {
                        "id": "after",
                        "name": "After cutoff",
                        "start_date_local": "2026-07-28T08:00:00+02:00",
                        "elapsed_time": 3600,
                    }
                ),
                encoding="utf-8",
            )
            cutoff = datetime.fromisoformat("2026-07-28T07:00:00+02:00")
            after_cutoff = datetime.fromisoformat("2026-07-28T08:00:00+02:00")
            snapshot = build_readiness_snapshot(
                "2026-07-28",
                artifacts_dir=artifacts_dir,
                local_timezone=ZoneInfo("Europe/Oslo"),
                now=datetime.fromisoformat("2026-07-28T12:00:00+02:00"),
                planned_at=cutoff,
                garmin_input={
                    "sources": {
                        "heart_rate": {
                            "calendarDate": "2026-07-28",
                            "heartRateValues": [
                                [int(cutoff.timestamp() * 1000), 50],
                                [int(after_cutoff.timestamp() * 1000), 140],
                            ],
                        },
                        "stress": {
                            "stressValuesArray": [
                                [int(cutoff.timestamp() * 1000), 20],
                                [int(after_cutoff.timestamp() * 1000), 90],
                            ],
                            "bodyBatteryValuesArray": [
                                [int(cutoff.timestamp() * 1000), 0, 80],
                                [int(after_cutoff.timestamp() * 1000), 0, 35],
                            ],
                        },
                        "summary": {
                            "calendarDate": "2026-07-28",
                            "bodyBatteryAtWakeTime": 85,
                            "bodyBatteryMostRecentValue": 35,
                        },
                        "training_readiness": [
                            {
                                "timestamp": "2026-07-28T04:50:00Z",
                                "timestampLocal": "2026-07-28T06:50:00+02:00",
                                "score": 70,
                            },
                            {
                                "timestamp": "2026-07-28T07:00:00Z",
                                "timestampLocal": "2026-07-28T09:00:00+02:00",
                                "score": 30,
                            },
                        ],
                    }
                },
            )

        self.assertEqual(snapshot["data_cutoff_local"], cutoff.isoformat())
        self.assertEqual(snapshot["latest_activity"]["id"], "before")
        self.assertEqual(snapshot["garmin"]["heart_rate"]["latest"]["value"], 50)
        self.assertEqual(snapshot["garmin"]["stress"]["latest"]["value"], 20)
        self.assertEqual(snapshot["garmin"]["body_battery"]["most_recent"], 80)
        self.assertEqual(snapshot["garmin"]["training_readiness"]["score"], 70)

    def test_future_planned_at_uses_now_as_cutoff(self):
        now = datetime.fromisoformat("2026-07-28T07:00:00+02:00")
        planned = datetime.fromisoformat("2026-07-28T19:00:00+02:00")
        snapshot = build_readiness_snapshot(
            "2026-07-28",
            artifacts_dir=Path("/nonexistent"),
            local_timezone=ZoneInfo("Europe/Oslo"),
            now=now,
            planned_at=planned,
        )

        self.assertEqual(snapshot["data_cutoff_local"], now.isoformat())

    def test_historical_cutoff_does_not_fall_back_to_later_daily_body_battery(self):
        cutoff = datetime.fromisoformat("2026-07-28T07:00:00+02:00")
        snapshot = build_readiness_snapshot(
            "2026-07-28",
            artifacts_dir=Path("/nonexistent"),
            local_timezone=ZoneInfo("Europe/Oslo"),
            now=datetime.fromisoformat("2026-07-28T12:00:00+02:00"),
            planned_at=cutoff,
            garmin_input={
                "sources": {
                    "summary": {
                        "calendarDate": "2026-07-28",
                        "bodyBatteryMostRecentValue": 35,
                    },
                    "training_readiness": {
                        "timestampLocal": "2026-07-28T09:00:00+02:00",
                        "score": 30,
                    },
                    "training_status": {"error": {"message": "temporarily unavailable"}},
                }
            },
        )

        self.assertIsNone(snapshot["garmin"]["body_battery"])
        self.assertIsNone(snapshot["garmin"]["training_readiness"])
        self.assertIsNone(snapshot["garmin"]["training_status"])

    def test_garmin_gmt_fields_control_cutoff_across_local_timezones(self):
        snapshot = build_readiness_snapshot(
            "2026-07-28",
            artifacts_dir=Path("/nonexistent"),
            local_timezone=ZoneInfo("Europe/Lisbon"),
            now=datetime.fromisoformat("2026-07-28T12:00:00+02:00"),
            planned_at=datetime.fromisoformat("2026-07-28T07:00:00+01:00"),
            garmin_input={
                "sources": {
                    "summary": {
                        "calendarDate": "2026-07-28",
                        "restingHeartRate": 43,
                        "lastSevenDaysAvgRestingHeartRate": 43,
                        "bodyBatteryAtWakeTime": 84,
                    },
                    "heart_rate": {
                        "calendarDate": "2026-07-28",
                        "restingHeartRate": 43,
                        "lastSevenDaysAvgRestingHeartRate": 43,
                    },
                    "sleep": {
                        "dailySleepDTO": {
                            "calendarDate": "2026-07-28",
                            "sleepStartTimestampGMT": 1785190537000,
                            "sleepEndTimestampGMT": 1785217297000,
                            "sleepStartTimestampLocal": 1785194137000,
                            "sleepEndTimestampLocal": 1785220897000,
                            "sleepTimeSeconds": 25800,
                            "sleepScores": {"overall": {"value": 78}},
                        }
                    },
                    "hrv": {
                        "endTimestampGMT": "2026-07-28T05:40:07.0",
                        "endTimestampLocal": "2026-07-28T06:40:07.0",
                        "hrvSummary": {
                            "calendarDate": "2026-07-28",
                            "lastNightAvg": 73,
                            "weeklyAvg": 72,
                            "status": "BALANCED",
                        },
                    },
                    "training_readiness": [
                        {
                            "timestamp": "2026-07-28T05:51:08.0",
                            "timestampLocal": "2026-07-28T06:51:08.0",
                            "score": 61,
                            "sleepScore": 78,
                        },
                        {
                            "timestamp": "2026-07-28T08:14:07.0",
                            "timestampLocal": "2026-07-28T09:14:07.0",
                            "score": 45,
                            "sleepScore": 78,
                        },
                    ],
                }
            },
        )

        wellness = snapshot["recommendation_inputs"]["wellness"]
        self.assertEqual(snapshot["garmin"]["training_readiness"]["score"], 61)
        self.assertEqual(wellness["sleep_time_seconds"], 25800)
        self.assertEqual(wellness["sleep_score"], 78)
        self.assertEqual(wellness["hrv_last_night_avg"], 73)
        self.assertEqual(wellness["resting_hr"], 43)
        self.assertEqual(
            wellness["garmin_signal_status"]["sleep"]["status"],
            "observed",
        )


class HrvHistoryTests(unittest.TestCase):
    def test_compacts_actual_nightly_values_into_three_and_seven_day_metrics(self):
        values = [64, 64, 54, 62, 68, 69, 65]
        payload = {
            "hrv_history": {
                "days": [
                    {
                        "date": f"2026-07-{18 + offset:02d}",
                        "sources": {
                            "hrv": {
                                "hrvSummary": {"lastNightAvg": value}
                            }
                        },
                    }
                    for offset, value in enumerate(values)
                ]
            }
        }

        result = compact_hrv_history("2026-07-24", payload)

        self.assertEqual(result["mean_3d"], 67.333)
        self.assertEqual(result["mean_7d"], 63.714)
        self.assertEqual(result["median_7d"], 64.0)
        self.assertEqual(result["nights_used_3d"], 3)
        self.assertEqual(result["nights_used_7d"], 7)


class IntervalsWellnessContextTests(unittest.TestCase):
    def test_preserves_supported_subjective_wellness_fields(self) -> None:
        result = intervals_wellness_context(
            "2026-07-22",
            [
                {
                    "id": "2026-07-22",
                    "injury": 1,
                    "fatigue": 2,
                    "soreness": 1,
                    "stress": 3,
                    "mood": 2,
                    "motivation": 2,
                    "hydration": 1,
                }
            ],
        )

        self.assertEqual(
            result["current_day"],
            {
                "date": "2026-07-22",
                "comments": None,
                "illness": False,
                "source": "wellness",
                "injury": 1,
                "fatigue": 2,
                "soreness": 1,
                "stress": 3,
                "mood": 2,
                "motivation": 2,
                "hydration": 1,
            },
        )

    def test_does_not_emit_empty_subjective_wellness_event(self) -> None:
        result = intervals_wellness_context(
            "2026-07-22",
            [{"id": "2026-07-22", "sleepQuality": 2, "sleepScore": 88}],
        )

        self.assertIsNone(result["current_day"])


if __name__ == "__main__":
    unittest.main()
