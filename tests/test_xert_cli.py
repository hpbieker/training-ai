import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "plugins" / "xert" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
SPEC = importlib.util.spec_from_file_location(
    "xert_cli_under_test",
    SCRIPTS_DIR / "xert_cli.py",
)
assert SPEC is not None and SPEC.loader is not None
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)

import xert_workouts as WORKOUTS


class WorkoutNameFilterTests(unittest.TestCase):
    def test_matches_non_contiguous_keywords_in_any_order(self) -> None:
        workouts = [
            {
                "name": "XMB: VT2 3x23 min @ 280W + VT1 30 min @ 210W - TODAY",
                "path": "vt2-today",
            },
            {"name": "XMB: VO2Max 5x3 min - TODAY", "path": "vo2-today"},
            {"name": "VT2 3x20 min - YESTERDAY", "path": "vt2-yesterday"},
        ]

        for name_filter in ("VT2 TODAY", "today vt2"):
            with self.subTest(name_filter=name_filter):
                self.assertEqual(
                    [row["path"] for row in CLI._filter_workouts(workouts, name_filter)],
                    ["vt2-today"],
                )
                self.assertEqual(
                    [
                        row["path"]
                        for row in WORKOUTS.summarize_workout_library(
                            workouts,
                            name_filter=name_filter,
                        )
                    ],
                    ["vt2-today"],
                )


class WorkoutCalculateRowsTests(unittest.TestCase):
    def test_compact_planned_advice_preserves_target_constraints(self) -> None:
        result = CLI.compact_recommended_training_advice(
            {
                "training_advice": {
                    "targetXSS": {"xlss": 259, "xhss": 5, "xpss": 0.2},
                    "xss_deficit": 507.2084,
                    "xss_goal": 264.2,
                    "availability": 4,
                    "is_availability_restricted": True,
                    "ir": 3,
                    "targets_source": "XATA",
                    "based_on_day": "Saturdays",
                    "phase": "Continuous",
                }
            },
            advice_value="2026-08-08 11:59 pm",
        )

        self.assertEqual(result["target_xss"]["low"], 259)
        self.assertEqual(result["xss_deficit"], 507.2084)
        self.assertEqual(result["xss_goal"], 264.2)
        self.assertTrue(result["is_availability_restricted"])
        self.assertEqual(result["targets_source"], "XATA")
        self.assertEqual(result["improvement_rate"], 3)

    def test_compact_recovery_meaning_describes_projected_field(self) -> None:
        result = CLI.compact_recovery_model({"at_state": {}})

        self.assertIn("recovery_hours_at_advice_time", result["meaning"])
        self.assertIn("raw source-time value", result["meaning"])
        self.assertNotIn("does not project", result["meaning"])

    def test_explicit_workout_capacity_projects_to_as_of(self) -> None:
        model = {
            "at_state": {
                "start_date": "2026-08-07T16:00:00Z",
                "tl": {"ftp": 100, "hie": 2, "pp": 1},
                "rl": {"ftp": 90, "hie": 1.5, "pp": 0.8},
            },
            "ir_params": {
                "ftp": {"tau1": 60, "tau2": 12},
                "hie": {"tau1": 22, "tau2": 5},
                "pp": {"tau1": 22, "tau2": 5},
            },
            "recovery_offset": 0.2,
        }
        with patch.object(
            CLI,
            "calculate_workout_capacity",
            return_value={"lo": 1, "hi": 2, "pk": 3},
        ) as calculate:
            result = CLI.explicit_workout_capacity(
                model,
                as_of="2026-08-07T20:00:00+02:00",
                fresh_at="2026-08-08T07:00:00+02:00",
            )
        self.assertEqual(result["source_state_as_of"], "2026-08-07T16:00:00+00:00")
        self.assertEqual(result["state_as_of"], "2026-08-07T20:00:00+02:00")
        self.assertEqual(result["fresh_at"], "2026-08-08T07:00:00+02:00")
        self.assertAlmostEqual(calculate.call_args.kwargs["next_workout_days"], 11 / 24)
        projected = calculate.call_args.kwargs["at_state"]
        self.assertEqual(projected["start_date"], "2026-08-07T20:00:00+02:00")
        self.assertLess(projected["tl"]["ftp"], 100)

    def test_explicit_workout_capacity_allows_equal_times(self) -> None:
        model = {
            "at_state": {
                "start_date": "2026-08-07T16:00:00Z",
                "tl": {"ftp": 100, "hie": 2, "pp": 1},
                "rl": {"ftp": 90, "hie": 1.5, "pp": 0.8},
            },
            "ir_params": {
                "ftp": {"tau1": 60, "tau2": 12},
                "hie": {"tau1": 22, "tau2": 5},
                "pp": {"tau1": 22, "tau2": 5},
            },
            "recovery_offset": 0.2,
        }
        with patch.object(
            CLI,
            "calculate_workout_capacity",
            return_value={"lo": 1, "hi": 2, "pk": 3},
        ) as calculate:
            CLI.explicit_workout_capacity(
                model,
                as_of="2026-08-07T18:00:00Z",
                fresh_at="2026-08-07T18:00:00Z",
            )
        self.assertEqual(calculate.call_args.kwargs["next_workout_days"], 0)

    def test_projection_horizon_accepts_explicit_timezone(self) -> None:
        days = CLI.projection_horizon_days(
            state_as_of="2026-08-07T15:30:00Z",
            target_at="2026-08-10T09:00:00+02:00",
        )
        self.assertAlmostEqual(days * 24, 63.5)
        self.assertEqual(
            CLI.normalized_target_at("2026-08-10T09:00:00+02:00"),
            "2026-08-10T09:00:00+02:00",
        )

    def test_projection_horizon_uses_machine_timezone_for_naive_target(self) -> None:
        with patch.object(CLI, "datetime", wraps=CLI.datetime) as mocked_datetime:
            # Preserve parsing but make this assertion independent of the
            # machine offset by comparing with Python's own local conversion.
            target = CLI.datetime.fromisoformat("2026-08-10T09:00:00").astimezone()
            source = target.astimezone(CLI.timezone.utc) - CLI.timedelta(hours=4)
            days = CLI.projection_horizon_days(
                state_as_of=source.isoformat(),
                target_at="2026-08-10T09:00:00",
            )
            self.assertAlmostEqual(days * 24, 4.0)
            self.assertTrue(mocked_datetime.fromisoformat.called)

    def test_projection_horizon_rejects_past_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not precede"):
            CLI.projection_horizon_days(
                state_as_of="2026-08-07T15:30:00Z",
                target_at="2026-08-07T15:29:59Z",
            )

    def test_compact_load_model_summary_exposes_decision_fields(self) -> None:
        summary = CLI.compact_load_model_summary(
            {
                "model": "xert_multi_system_impulse_response",
                "state_sync": {"state_as_of": "2026-08-07T15:30:00+00:00"},
                "horizon_days": 2.5,
                "workout_after_days": 0.25,
                "systems": {
                    "low": {
                        "xss": 80,
                        "training_load": {"current": 100, "tau_days": 60},
                        "signature": {
                            "current": 300,
                            "projected": 301,
                            "responsiveness_per_training_load": 0.4,
                            "unit": "W",
                        },
                    },
                    "high": {
                        "xss": 5,
                        "training_load": {"current": 2, "tau_days": 22},
                        "signature": {
                            "current": 15,
                            "projected": 14.9,
                            "responsiveness_per_training_load": 0.75,
                            "unit": "kJ",
                        },
                    },
                    "peak": {
                        "xss": 1,
                        "training_load": {"current": 0.5, "tau_days": 22},
                        "signature": {
                            "current": 900,
                            "projected": 899,
                            "responsiveness_per_training_load": 50,
                            "unit": "W",
                        },
                    },
                },
                "required_to_build": {
                    "ftp": {
                        "desired_gain": 1,
                        "system": "low",
                        "single_impulse_xss_at_workout_time": 456.7,
                    }
                },
                "training_status": {"category": "Elite"},
                "freshness": {"model_status": "Fresh"},
            }
        )

        self.assertEqual(summary["workout_at"], "2026-08-07T21:30:00+00:00")
        self.assertEqual(summary["target_at"], "2026-08-10T03:30:00+00:00")
        self.assertEqual(summary["required_to_build"]["tp"]["target"], 301)
        self.assertEqual(
            summary["required_to_build"]["tp"]["required_xss_at_workout_time"],
            456.7,
        )
        self.assertLess(summary["signature"]["tp"]["no_training_at_target"], 300)

    def test_compact_load_model_summary_preserves_requested_target_timezone(self) -> None:
        payload = {
            "model": "xert_multi_system_impulse_response",
            "target_at": "2026-08-10T09:00:00+02:00",
            "state_sync": {"state_as_of": "2026-08-07T15:30:00Z"},
            "horizon_days": 2.0,
            "workout_after_days": 0.0,
            "systems": {},
            "required_to_build": {},
        }
        self.assertEqual(
            CLI.compact_load_model_summary(payload)["target_at"],
            "2026-08-10T09:00:00+02:00",
        )

    def test_distributed_summary_does_not_label_no_training_status_as_ramp_status(self) -> None:
        payload = {
            "model": "xert_multi_system_impulse_response",
            "state_sync": {"state_as_of": "2026-08-07T15:30:00Z"},
            "horizon_days": 10.0,
            "workout_after_days": 0.0,
            "systems": {},
            "required_to_build": {},
            "distributed_to_build": {
                "distribution": "linear",
                "frequency": "daily",
                "recovery_load_and_status_projected": False,
            },
            "training_status": {"category": "Untrained"},
            "freshness": {"model_status": "Very Fresh"},
        }
        summary = CLI.compact_load_model_summary(payload)
        self.assertNotIn("training_status", summary)
        self.assertNotIn("freshness", summary)

    def test_series_output_writes_full_payload_and_keeps_stdout_compact(self) -> None:
        calculated = {
            "saved": False,
            "signature": {"ftp": 250, "atc": 10000, "pp": 1000},
            "series": [{"time": 1, "power": 300, "mpa": 1000}],
            "calculation_stats": {"xss": 1.25},
            "timeline_summary": {"duration": 60, "segments": []},
            "result": {"stats": {"xss": 1.25}},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "series.json"
            argv = [
                "xert_cli.py",
                "workout-calculate",
                "--duration",
                "01:00",
                "--power",
                "120",
                "--series-output",
                str(output_path),
            ]
            stdout = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    CLI,
                    "load_xert_credentials",
                    return_value=SimpleNamespace(username="user", password="secret"),
                ),
                patch.object(CLI, "calculate_new_workout", return_value=calculated),
                contextlib.redirect_stdout(stdout),
            ):
                CLI.main()

            stored = json.loads(output_path.read_text(encoding="utf-8"))
            printed = json.loads(stdout.getvalue())
            self.assertEqual(
                stored["series"],
                [{"time": 1, "power": 300, "mpa": 1000}],
            )
            self.assertEqual(
                stored["signature"],
                {"ftp": 250, "atc": 10000, "pp": 1000},
            )
            self.assertEqual(stored["calculation_stats"], {"xss": 1.25})
            self.assertNotIn("series", printed)
            self.assertEqual(printed["series_output"], str(output_path))

    def test_signature_overrides_are_forwarded_to_unsaved_calculate(self) -> None:
        argv = [
            "xert_cli.py",
            "workout-calculate",
            "--duration",
            "01:00",
            "--power",
            "120",
            "--signature-tp",
            "250",
            "--signature-hie",
            "10000",
            "--signature-pp",
            "1000",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                CLI,
                "load_xert_credentials",
                return_value=SimpleNamespace(username="user", password="secret"),
            ),
            patch.object(
                CLI,
                "calculate_new_workout",
                return_value={"saved": False, "result": {}},
            ) as calculate,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            CLI.main()

        kwargs = calculate.call_args.kwargs
        self.assertEqual(kwargs["signature_tp"], 250)
        self.assertEqual(kwargs["signature_hie"], 10000)
        self.assertEqual(kwargs["signature_pp"], 1000)
        self.assertTrue(kwargs["include_series"] is False)

    def test_builds_complete_workout_from_compact_steps(self) -> None:
        args = argparse.Namespace(
            row_json=[],
            warmup_step=["10:00@170", "05:00@220"],
            interval_block=["4x04:00@340/03:00@120"],
            cooldown_step=["10:00@140"],
            duration=None,
            power=None,
        )

        rows = CLI.workout_calculate_rows(args)

        self.assertEqual(len(rows), 4)
        self.assertEqual([row["sequence"] for row in rows], [0, 1, 2, 3])
        self.assertEqual(rows[0]["name"], "Warm-up 1")
        self.assertEqual(rows[1]["power"]["value"], 220.0)
        self.assertEqual(rows[2]["interval_count"], "4")
        self.assertEqual(rows[2]["duration"]["value"], "04:00")
        self.assertEqual(rows[2]["power"]["value"], 340.0)
        self.assertEqual(rows[2]["rib_duration"]["value"], "03:00")
        self.assertEqual(rows[2]["rib_power"]["value"], 120.0)
        self.assertEqual(rows[3]["name"], "Cool-down 1")

    def test_builds_ramp_row_from_json_power_object(self) -> None:
        args = argparse.Namespace(
            row_json=[
                '{"name":"Ramp","duration":"10:00",'
                '"power":{"type":"ramp_ftp","value":60,"second_value":100}}'
            ],
            duration=None,
            power=None,
            warmup_step=[],
            interval_block=[],
            cooldown_step=[],
        )

        rows = CLI.workout_calculate_rows(args)

        self.assertEqual(
            rows[0]["power"],
            {"type": "ramp_ftp", "value": 60.0, "second_value": 100.0},
        )

    def test_compact_summary_exposes_calculated_metrics(self) -> None:
        summary = CLI.compact_workout_calculation_summary(
            {
                "saved": False,
                "timeline_summary": {"duration": 3180, "segments": []},
                "result": {
                    "stats": {
                        "duration": 3180,
                        "xss": 71.9,
                        "xlss": 66.5,
                        "xhss": 4.9,
                        "xpss": 0.5,
                        "difficulty": 79.5,
                        "rating": "Difficult",
                        "focus": "GC Specialist",
                        "specificity": 0.76,
                        "specRating": "Pure",
                        "xep": 247.7,
                        "avg_power": 209.1,
                        "max_power": 340,
                    }
                },
            }
        )

        self.assertEqual(summary["duration_minutes"], 53.0)
        self.assertEqual(summary["xss"], 71.9)
        self.assertEqual(summary["low_xss"], 66.5)
        self.assertEqual(summary["difficulty"], 79.5)
        self.assertFalse(summary["saved"])
        self.assertEqual(summary["timeline_summary"], {"duration": 3180, "segments": []})

    def test_builds_multiple_rows_from_repeated_json_arguments(self) -> None:
        args = argparse.Namespace(
            row_json=[
                '{"name":"Warm-up","duration":"15:00","power":180}',
                (
                    '{"name":"4 x 4","duration":"04:00","power":340,'
                    '"interval_count":4,"rib_duration":"03:00","rib_power":120}'
                ),
                '{"name":"Cool-down","duration":"10:00","power":140}',
            ],
            duration=None,
            power=None,
        )

        rows = CLI.workout_calculate_rows(args)

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["sequence"] for row in rows], [0, 1, 2])
        self.assertEqual(rows[1]["interval_count"], "4")
        self.assertEqual(rows[1]["power"], {"type": "absolute", "value": 340.0})
        self.assertEqual(
            rows[1]["rib_duration"],
            {"type": "absolute", "value": "03:00"},
        )
        self.assertEqual(rows[1]["rib_power"], {"type": "absolute", "value": 120.0})

    def test_keeps_single_row_arguments(self) -> None:
        args = argparse.Namespace(
            row_json=[],
            row_name="Probe",
            duration="10:00",
            power=120.0,
            power_type="relative_ftp",
            interval_count="1",
            rib_duration="00:00",
            rib_power=0.0,
            rib_power_type="absolute",
        )

        rows = CLI.workout_calculate_rows(args)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["duration"]["value"], "10:00")
        self.assertEqual(rows[0]["power"]["type"], "relative_ftp")

    def test_rejects_mixing_json_and_single_row_arguments(self) -> None:
        args = argparse.Namespace(
            row_json=['{"duration":"10:00","power":120}'],
            duration="10:00",
            power=120.0,
        )

        with self.assertRaisesRegex(ValueError, "only one workout input form"):
            CLI.workout_calculate_rows(args)

    def test_rejects_invalid_json_row(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required keys: power"):
            CLI.workout_row_from_json(
                '{"name":"Warm-up","duration":"15:00"}',
                sequence=0,
            )


class WorkoutReplacementTests(unittest.TestCase):
    @staticmethod
    def row(name: str = "Warmup") -> dict:
        return {
            "sequence": 0,
            "name": name,
            "duration": {"type": "absolute", "value": "10:00"},
            "power": {"type": "absolute", "value": 170},
            "interval_count": "1",
            "rib_duration": {"type": "absolute", "value": "00:00"},
            "rib_power": {"type": "absolute", "value": 0},
        }

    def test_loads_non_empty_rows_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.json"
            path.write_text(json.dumps([{"name": "Warmup"}]), encoding="utf-8")

            self.assertEqual(CLI.load_workout_rows_file(path), [{"name": "Warmup"}])

    def test_rejects_object_instead_of_rows_array(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.json"
            path.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "non-empty JSON array"):
                CLI.load_workout_rows_file(path)

    def test_builds_replacement_rows_from_repeated_inline_json(self) -> None:
        args = argparse.Namespace(
            rows_json=None,
            row_json=[
                '{"name":"Work","duration":"10:00","power":280}',
                '{"name":"Rest","duration":"05:00","power":50,"power_type":"relative_ftp"}',
            ],
        )

        rows = CLI.workout_replacement_rows(args)

        self.assertEqual([row["sequence"] for row in rows], [0, 1])
        self.assertEqual(rows[0]["power"]["value"], 280.0)
        self.assertEqual(rows[1]["power"]["type"], "relative_ftp")

    def test_builds_replacement_row_from_complete_designer_json(self) -> None:
        row = CLI.workout_replacement_row_from_json(
            json.dumps(
                {
                    "sequence": 9,
                    "name": "Warmup",
                    "duration": {"type": "absolute", "value": "10:00"},
                    "power": {"type": "ramp_ltp", "value": 60, "second_value": 100},
                    "interval_count": "1",
                    "rib_duration": {"type": "absolute", "value": "00:00"},
                    "rib_power": {"type": "absolute", "value": 0},
                }
            ),
            sequence=0,
        )

        self.assertEqual(row["sequence"], 0)
        self.assertEqual(row["power"]["type"], "ramp_ltp")
        self.assertEqual(row["power"]["second_value"], 100)

    def test_normalizes_complete_replacement_rows(self) -> None:
        rows = WORKOUTS.normalize_workout_rows(
            [
                {
                    "sequence": 9,
                    "name": "Warmup",
                    "duration": {"type": "absolute", "value": "10:00"},
                    "power": {"type": "ramp_ltp", "value": 60, "second_value": 100},
                    "interval_count": 1,
                    "rib_duration": {"type": "absolute", "value": "02:00"},
                    "rib_power": {"type": "relative_ftp", "value": 40},
                }
            ]
        )

        self.assertEqual(rows[0]["sequence"], 0)
        self.assertEqual(rows[0]["DT_RowId"], "")
        self.assertEqual(rows[0]["interval_count"], "1")

    def test_expands_repeat_rows_into_compact_timeline_summary(self) -> None:
        repeat = self.row("VT2 4 x 12 min @ 280 W")
        repeat["duration"]["value"] = "12:00"
        repeat["power"]["value"] = 280
        repeat["interval_count"] = "4"
        repeat["rib_duration"] = {"type": "absolute", "value": "05:00"}
        repeat["rib_power"] = {"type": "relative_ftp", "value": 50}
        vt1 = self.row("VT1")
        vt1["duration"]["value"] = "60:00"
        vt1["power"]["value"] = 210

        timeline = WORKOUTS.workout_timeline_summary([repeat, vt1])

        self.assertEqual(timeline["duration"], 7680)
        self.assertEqual(len(timeline["segments"]), 9)
        self.assertEqual(
            timeline["segments"][0],
            {"start": 0, "end": 720, "duration": 720, "name": "VT2 1/4", "power": "280 W"},
        )
        self.assertEqual(
            timeline["segments"][7],
            {
                "start": 3780,
                "end": 4080,
                "duration": 300,
                "name": "Rest after VT2 4/4",
                "power": "50 % FTP",
            },
        )
        self.assertEqual(
            timeline["segments"][8],
            {"start": 4080, "end": 7680, "duration": 3600, "name": "VT1", "power": "210 W"},
        )

    def test_timeline_formats_ramp_power_as_text(self) -> None:
        warmup = self.row("Warmup")
        warmup["power"] = {
            "type": "ramp_ltp",
            "value": 60,
            "second_value": 100,
        }

        timeline = WORKOUTS.workout_timeline_summary([warmup])

        self.assertEqual(timeline["segments"][0]["power"], "60–100 % LTP")

    def test_update_result_does_not_expose_data_point_count(self) -> None:
        compact = WORKOUTS.summarize_workout_update_result(
            {
                "result": False,
                "redirect": "",
                "error": "",
                "info": "",
                "data": [1, 2, 3],
                "stats": {"duration": 3},
            }
        )

        self.assertNotIn("data_points", compact)
        self.assertNotIn("result", compact)
        self.assertNotIn("redirect", compact)
        self.assertNotIn("error", compact)
        self.assertNotIn("info", compact)

    def test_update_result_keeps_non_empty_response_fields(self) -> None:
        compact = WORKOUTS.summarize_workout_update_result(
            {
                "redirect": "https://www.xertonline.com/workout/path",
                "error": "warning",
                "info": "Workout saved",
            }
        )

        self.assertEqual(
            compact,
            {
                "redirect": "https://www.xertonline.com/workout/path",
                "error": "warning",
                "info": "Workout saved",
            },
        )

    def test_normalizes_long_mm_ss_duration_to_hh_mm_ss(self) -> None:
        self.assertEqual(
            WORKOUTS.normalize_workout_duration("149:00"),
            "02:29:00",
        )

    def test_preserves_valid_hh_mm_ss_duration(self) -> None:
        self.assertEqual(
            WORKOUTS.normalize_workout_duration("02:29:00"),
            "02:29:00",
        )

    def test_rejects_invalid_duration_seconds(self) -> None:
        with self.assertRaisesRegex(ValueError, "seconds must be between"):
            WORKOUTS.normalize_workout_duration("10:75")

    def test_rejects_invalid_hh_mm_ss_minutes(self) -> None:
        with self.assertRaisesRegex(ValueError, "minutes must be between"):
            WORKOUTS.normalize_workout_duration("01:75:00")

    def test_allows_zero_only_for_recovery_duration(self) -> None:
        self.assertEqual(
            WORKOUTS.normalize_workout_duration("00:00", allow_zero=True),
            "00:00",
        )
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            WORKOUTS.normalize_workout_duration("00:00")

    def test_form_payload_normalizes_every_duration_before_post(self) -> None:
        row = self.row()
        row["duration"]["value"] = "149:00"
        row["rib_duration"]["value"] = 0

        form = WORKOUTS.workout_designer_form_payload(
            {"token": "token"},
            rows=[row],
            submit="calculate",
        )

        submitted = json.loads(form["rows"])
        self.assertEqual(submitted[0]["duration"]["value"], "02:29:00")
        self.assertEqual(submitted[0]["rib_duration"]["value"], "00:00")

    def test_canonical_rows_ignore_transport_only_duration_fields(self) -> None:
        base = {
            "sequence": 0,
            "name": "Warmup",
            "duration": {"type": "absolute", "value": "10:00"},
            "power": {"type": "absolute", "value": 170},
            "interval_count": "1",
            "rib_duration": {"type": "absolute", "value": "00:00"},
            "rib_power": {"type": "absolute", "value": 0},
        }
        returned = json.loads(json.dumps(base))
        returned["duration"]["seconds"] = 600

        self.assertEqual(
            WORKOUTS.canonical_workout_rows([base]),
            WORKOUTS.canonical_workout_rows([returned]),
        )

    def test_compact_verification_omits_readback_rows(self) -> None:
        verification = {
            "name": "Workout",
            "row_count": 1,
            "rows_match": True,
            "rows": [self.row()],
        }

        compact = WORKOUTS.compact_workout_verification(verification)

        self.assertEqual(
            compact,
            {"name": "Workout", "row_count": 1, "rows_match": True},
        )

    def test_row_update_requires_selector(self) -> None:
        with self.assertRaisesRegex(ValueError, "require --match-name"):
            WORKOUTS.update_workout(
                "path",
                username="user",
                password="secret",
                set_duration="10:00",
                submit="calculate",
            )

    def test_row_update_rejects_unexpected_multiple_matches(self) -> None:
        rows = [self.row("Rest"), self.row("Rest")]
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(
                WORKOUTS,
                "fetch_workout_designer_page",
                return_value={"token": "t", "name": "n", "description": "", "pp": "", "atc": "", "ftp": ""},
            ),
            patch.object(WORKOUTS, "fetch_workout_designer_rows", return_value=rows),
        ):
            with self.assertRaisesRegex(ValueError, "Expected 1 matching.*found 2"):
                WORKOUTS.update_workout(
                    "path",
                    username="user",
                    password="secret",
                    match_name="Rest",
                    set_duration="02:00",
                    submit="calculate",
                )

    def test_atomic_replace_fails_closed_on_readback_mismatch(self) -> None:
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(
                WORKOUTS,
                "fetch_workout_designer_page",
                return_value={"token": "t", "name": "n", "description": "", "pp": "", "atc": "", "ftp": ""},
            ),
            patch.object(WORKOUTS, "post_workout_designer_form", return_value={}),
            patch.object(WORKOUTS, "verify_saved_workout", return_value={"rows_match": False}),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not match"):
                WORKOUTS.replace_workout(
                    "path",
                    username="user",
                    password="secret",
                    rows=[self.row()],
                    submit="save",
                )

    def test_atomic_replace_fails_closed_on_metadata_mismatch(self) -> None:
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(
                WORKOUTS,
                "fetch_workout_designer_page",
                return_value={"token": "t", "name": "old", "description": "old"},
            ),
            patch.object(WORKOUTS, "post_workout_designer_form", return_value={}),
            patch.object(
                WORKOUTS,
                "verify_saved_workout",
                return_value={
                    "rows_match": True,
                    "name": "old",
                    "description": "new description",
                },
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "name did not match"):
                WORKOUTS.replace_workout(
                    "path",
                    username="user",
                    password="secret",
                    rows=[self.row()],
                    name="new name",
                    description="new description",
                    submit="save",
                )

    def test_adds_one_row_at_one_based_position(self) -> None:
        rows = [self.row("Warmup"), self.row("Cooldown")]
        added = self.row("Work")
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(WORKOUTS, "fetch_workout_designer_page", return_value={"token": "t"}),
            patch.object(WORKOUTS, "fetch_workout_designer_rows", return_value=rows),
            patch.object(WORKOUTS, "post_workout_designer_form", return_value={}) as post,
        ):
            result = WORKOUTS.mutate_workout_row(
                "path",
                username="user",
                password="secret",
                operation="add",
                row_number=2,
                row=added,
                submit="calculate",
            )

        submitted = json.loads(post.call_args.args[2]["rows"])
        self.assertEqual([row["name"] for row in submitted], ["Warmup", "Work", "Cooldown"])
        self.assertEqual([row["sequence"] for row in submitted], [0, 1, 2])
        self.assertEqual(result["row_count"], 3)
        self.assertNotIn("verification", result)

    def test_updates_only_fields_explicitly_supplied_by_row_number(self) -> None:
        target = self.row("VT1")
        target["duration"]["value"] = "05:00"
        target["power"] = {"type": "relative_ftp", "value": 69}
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(WORKOUTS, "fetch_workout_designer_page", return_value={"token": "t"}),
            patch.object(WORKOUTS, "fetch_workout_designer_rows", return_value=[target]),
            patch.object(WORKOUTS, "post_workout_designer_form", return_value={}),
        ):
            result = WORKOUTS.mutate_workout_row(
                "path",
                username="user",
                password="secret",
                operation="update",
                row_number=1,
                set_duration="15:00",
                set_power=205,
                submit="calculate",
            )

        self.assertEqual(result["after"]["duration"]["value"], "15:00")
        self.assertEqual(result["after"]["power"], {"type": "relative_ftp", "value": 205})
        self.assertEqual(result["after"]["name"], "VT1")
        self.assertEqual(result["after"]["rib_duration"]["value"], "00:00")

    def test_removes_one_row_and_renumbers_remaining_rows(self) -> None:
        rows = [self.row("Warmup"), self.row("Work"), self.row("Cooldown")]
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(WORKOUTS, "fetch_workout_designer_page", return_value={"token": "t"}),
            patch.object(WORKOUTS, "fetch_workout_designer_rows", return_value=rows),
            patch.object(WORKOUTS, "post_workout_designer_form", return_value={}) as post,
        ):
            result = WORKOUTS.mutate_workout_row(
                "path",
                username="user",
                password="secret",
                operation="remove",
                row_number=2,
                submit="calculate",
            )

        submitted = json.loads(post.call_args.args[2]["rows"])
        self.assertEqual([row["name"] for row in submitted], ["Warmup", "Cooldown"])
        self.assertEqual([row["sequence"] for row in submitted], [0, 1])
        self.assertEqual(result["before"]["name"], "Work")

    def test_delete_reads_target_and_verifies_absence(self) -> None:
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(WORKOUTS, "verify_workout_page", return_value={"name": "Target"}),
            patch.object(WORKOUTS, "_open_text", return_value="{}"),
            patch.object(WORKOUTS, "list_workouts", return_value=[]),
        ):
            result = WORKOUTS.delete_workout(
                "path",
                username="user",
                password="secret",
            )

        self.assertEqual(result["target"], {"name": "Target"})
        self.assertTrue(result["verified_absent"])


if __name__ == "__main__":
    unittest.main()
