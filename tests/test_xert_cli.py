import concurrent.futures
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
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
import xert_common as COMMON
import xert_service as SERVICE


class CliSurfaceTests(unittest.TestCase):
    def test_mcp_covered_commands_are_not_exposed(self) -> None:
        removed = (
            "activities",
            "activity-loads",
            "activity",
            "training-info",
            "training-forecast",
            "calendar-notes",
            "calendar-note-set",
            "recommended-training",
            "workouts",
            "workout",
            "workout-rows",
            "workout-update",
            "workout-replace",
            "workout-row-add",
            "workout-row-update",
            "workout-row-remove",
            "workout-copy",
            "workout-delete",
            "recovery-model",
            "workout-capacity",
            "load-model",
            "workout-calculate",
        )
        for command in removed:
            with self.subTest(command=command), patch.object(
                sys, "argv", ["xert_cli.py", command]
            ), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    CLI.main()
                self.assertEqual(raised.exception.code, 2)


class AuthenticationCacheTests(unittest.TestCase):
    def test_bearer_token_is_reused_within_one_service_session(self) -> None:
        auth = SERVICE.XertAuthSession(
            COMMON.XertCredentials(username="cache-user", password="cache-pass")
        )
        with patch.object(
            SERVICE,
            "request_xert_token",
            return_value={"access_token": "cached-token", "expires_in": 3600},
        ) as request_token:
            self.assertEqual(auth.bearer_token(), "cached-token")
            self.assertEqual(auth.bearer_token(), "cached-token")

        request_token.assert_called_once()

    def test_parallel_web_session_requests_share_one_login(self) -> None:
        opener = object()
        auth = SERVICE.XertAuthSession(
            COMMON.XertCredentials(username="parallel-user", password="parallel-pass")
        )
        with patch.object(
            SERVICE,
            "xert_web_login",
            return_value=opener,
        ) as login:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                sessions = list(executor.map(lambda _: auth.web_opener(), range(8)))

        self.assertTrue(all(session is opener for session in sessions))
        login.assert_called_once()


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

    def test_preserves_disabled_row_but_omits_it_from_timeline(self) -> None:
        active = self.row("VT2")
        disabled = self.row("Endurance")
        disabled["duration"]["value"] = "30:00"
        disabled["power"]["value"] = 210
        disabled["interval_count"] = 0

        normalized = WORKOUTS.normalize_workout_rows([active, disabled])
        timeline = WORKOUTS.workout_timeline_summary(normalized)

        self.assertEqual(normalized[1]["interval_count"], "0")
        self.assertEqual([segment["name"] for segment in timeline["segments"]], ["VT2"])

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

    def test_create_workout_saves_blank_designer_and_verifies_readback(self) -> None:
        rows = [self.row("Endurance")]
        verification = {
            "path": "created-path",
            "name": "Created workout",
            "description": "Description",
            "row_count": 1,
            "rows_match": True,
            "rows": rows,
        }
        with (
            patch.object(WORKOUTS, "xert_web_login", return_value=object()),
            patch.object(
                WORKOUTS,
                "fetch_workout_designer_page",
                return_value={"token": "t", "name": "", "description": "", "pp": "", "atc": "", "ftp": ""},
            ),
            patch.object(
                WORKOUTS,
                "post_workout_designer_form",
                return_value={"redirect": "/workout/created-path"},
            ) as post,
            patch.object(WORKOUTS, "verify_saved_workout", return_value=verification),
        ):
            result = WORKOUTS.create_workout(
                username="user",
                password="secret",
                name="Created workout",
                description="Description",
                rows=rows,
            )
        self.assertEqual(result["path"], "created-path")
        self.assertTrue(result["saved"])
        self.assertEqual(post.call_args.args[1], "")
        self.assertEqual(post.call_args.args[2]["submit"], "save")

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
