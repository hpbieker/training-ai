import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "xert"
sys.path.insert(0, str(PLUGIN_ROOT))

import xert_mcp as MCP  # noqa: E402
import xert_service as SERVICE  # noqa: E402


class FakeXertService:
    def __init__(self) -> None:
        self.calls = []

    def list_activities(self, start_date, end_date, *, view="summary"):
        self.calls.append(("list_activities", start_date, end_date, view))
        if view == "loads":
            return {"activities": [{"path": "a1", "xss": {"low": 10}}]}
        return [{"path": "a1", "name": "Ride"}]

    def get_activity(self, path, *, view="summary"):
        self.calls.append(("get_activity", path, view))
        return {"path": path, "summary": {"xss": 12}}

    def list_workouts(self, *, name_keywords=None, view="summary"):
        self.calls.append(("list_workouts", name_keywords, view))
        return [{"path": "w1", "name": "XMB VT1"}]

    def get_workout(self, path, *, view="resolved"):
        self.calls.append(("get_workout", path, view))
        return [{"name": "Warm-up"}] if view == "editable" else {"path": path}

    def list_notes(self, start_date, end_date):
        self.calls.append(("list_notes", start_date, end_date))
        return [{"date": start_date, "text": "Easy day"}]

    def get_note(self, note_date):
        self.calls.append(("get_note", note_date))
        return {"date": note_date, "exists": False, "text": None}

    def set_note(self, note_date, text):
        self.calls.append(("set_note", note_date, text))
        return {"date": note_date, "exists": bool(text), "text": text or None, "success": True}

    def get_training_state(self, *, view="summary"):
        self.calls.append(("get_training_state", view))
        return {"as_of": "2026-08-17T09:00:00+02:00"} if view == "summary" else {"training_info": {}}

    def get_training_advice(self, *, at=None, view="summary", include_recommendations=False):
        self.calls.append(("get_training_advice", at, view, include_recommendations))
        return {
            "source_scope": "planned_time" if at else "current",
            "at": at,
            "recommendations": [] if include_recommendations else None,
        }

    def get_training_forecast(self, start_date, end_date, *, view="summary"):
        self.calls.append(("get_training_forecast", start_date, end_date, view))
        return {"days": []}

    def create_workout(self, *, name, rows, description=""):
        self.calls.append(("create_workout", name, rows, description))
        return {"path": "new-workout", "saved": True}

    def delete_workout(self, path):
        self.calls.append(("delete_workout", path))
        return {"path": path, "verified_absent": True}

    def update_workout(self, path, *, name=None, description=None, rows=None):
        self.calls.append(("update_workout", path, name, description, rows))
        return {"path": path, "submit": "save"}


class XertMcpSchemaTests(unittest.TestCase):
    def test_exposes_only_selected_activity_workout_and_note_tools(self) -> None:
        self.assertEqual(
            MCP.ALL_TOOL_NAMES,
            (
                "list_activities",
                "get_activity",
                "list_workouts",
                "get_workout",
                "list_notes",
                "get_note",
                "set_note",
                "get_training_state",
                "get_training_advice",
                "create_workout",
                "delete_workout",
                "update_workout",
                "get_training_forecast",
            ),
        )
        self.assertEqual(set(MCP.TOOL_SPECS), set(MCP.ALL_TOOL_NAMES))

    def test_every_tool_has_closed_described_inputs_and_expected_annotations(self) -> None:
        for name in MCP.ALL_TOOL_NAMES:
            definition = MCP.TOOL_DEFINITIONS[name]
            self.assertFalse(definition["inputSchema"]["additionalProperties"], name)
            for field, schema in definition["inputSchema"]["properties"].items():
                self.assertTrue(schema.get("description"), f"{name}.{field}")
            writes_session_file = name == "get_activity"
            writes_note = name == "set_note"
            creates_workout = name == "create_workout"
            deletes_workout = name == "delete_workout"
            updates_workout = name == "update_workout"
            self.assertEqual(
                definition["annotations"],
                {
                    "title": MCP.TOOL_ANNOTATIONS[name]["title"],
                    "readOnlyHint": not (
                        writes_session_file
                        or writes_note
                        or creates_workout
                        or deletes_workout
                        or updates_workout
                    ),
                    "destructiveHint": writes_note or deletes_workout or updates_workout,
                    "idempotentHint": not (
                        writes_session_file or creates_workout or deletes_workout
                    ),
                    "openWorldHint": True,
                },
            )

    def test_sdk_accepts_every_tool_definition(self) -> None:
        server = MCP.create_sdk_server(MCP.XertToolService(FakeXertService))
        self.assertIsNotNone(server)


class XertMcpHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_initialize_and_list_tools(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "./xert_mcp.py"],
            cwd=str(PLUGIN_ROOT),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()

        self.assertEqual([tool.name for tool in result.tools], list(MCP.ALL_TOOL_NAMES))


class XertMcpDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeXertService()
        self.tools = MCP.XertToolService(lambda: self.fake)

    def test_list_activity_loads_and_editable_workout(self) -> None:
        activities = self.tools.call_tool(
            "list_activities",
            {"start_date": "2026-08-01", "end_date": "2026-08-02", "view": "loads"},
        )
        workout = self.tools.call_tool(
            "get_workout", {"workout_path": "w1", "view": "editable"}
        )
        self.assertEqual(activities["count"], 1)
        self.assertEqual(workout["rows"], [{"name": "Warm-up"}])

    def test_session_view_writes_private_file_instead_of_returning_series(self) -> None:
        result = self.tools.call_tool(
            "get_activity", {"activity_path": "a1", "view": "session"}
        )
        path = Path(result["session_file"])
        try:
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["path"], "a1")
            self.assertNotIn("activity", result)
        finally:
            path.unlink(missing_ok=True)

    def test_rejects_unknown_and_missing_arguments(self) -> None:
        with self.assertRaisesRegex(MCP.ToolFailure, "unknown argument"):
            self.tools.call_tool(
                "list_workouts", {"view": "summary", "surprise": True}
            )
        with self.assertRaisesRegex(MCP.ToolFailure, "missing required"):
            self.tools.call_tool("get_activity", {})

    def test_note_tools_dispatch_normalized_contracts(self) -> None:
        listed = self.tools.call_tool(
            "list_notes", {"start_date": "2026-08-01", "end_date": "2026-08-31"}
        )
        missing = self.tools.call_tool("get_note", {"date": "2026-08-17"})
        saved = self.tools.call_tool(
            "set_note", {"date": "2026-08-17", "text": "Recovery day"}
        )
        self.assertEqual(listed["count"], 1)
        self.assertFalse(missing["exists"])
        self.assertEqual(saved["text"], "Recovery day")

    def test_training_state_dispatches_requested_view(self) -> None:
        result = self.tools.call_tool("get_training_state", {"view": "full"})
        self.assertEqual(result["view"], "full")
        self.assertEqual(result["state"], {"training_info": {}})

    def test_training_advice_dispatches_optional_time_and_view(self) -> None:
        result = self.tools.call_tool(
            "get_training_advice",
            {
                "at": "2026-08-18T09:00:00+02:00",
                "view": "full",
                "include_recommendations": True,
            },
        )
        self.assertEqual(result["view"], "full")
        self.assertEqual(result["advice"]["source_scope"], "planned_time")
        self.assertEqual(result["advice"]["recommendations"], [])

    def test_training_forecast_dispatches_range_and_view(self) -> None:
        result = self.tools.call_tool(
            "get_training_forecast",
            {"start_date": "2026-08-17", "end_date": "2026-08-24"},
        )
        self.assertEqual(result["forecast"], {"days": []})

    def test_create_workout_dispatches_complete_rows(self) -> None:
        result = self.tools.call_tool(
            "create_workout",
            {
                "name": "Endurance",
                "description": "Steady",
                "rows": [{"duration_seconds": 600, "power": 200}],
            },
        )
        self.assertEqual(result["workout"]["path"], "new-workout")

    def test_delete_workout_dispatches_path(self) -> None:
        result = self.tools.call_tool(
            "delete_workout", {"workout_path": "old-workout"}
        )
        self.assertTrue(result["deletion"]["verified_absent"])

    def test_update_workout_dispatches_metadata_and_complete_rows(self) -> None:
        result = self.tools.call_tool(
            "update_workout",
            {
                "workout_path": "workout",
                "name": "Updated",
                "rows": [{"duration_seconds": 600, "power": 200}],
            },
        )
        self.assertEqual(result["workout"]["submit"], "save")


class XertServiceTests(unittest.TestCase):
    @staticmethod
    def _service(credentials):
        service = SERVICE.XertService(lambda: credentials)
        service._auth._token = "token"
        service._auth._token_expires_at = float("inf")
        service._auth._opener = object()
        return service

    def test_service_routes_activity_and_workout_views(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        with (
            patch.object(SERVICE, "fetch_activities", return_value=[{"path": "a1"}]),
            patch.object(SERVICE, "fetch_activity_detail", return_value={"summary": {"xss": 4}}),
            patch.object(SERVICE, "fetch_workouts", return_value=[{"name": "XMB VT1", "path": "w1"}]),
            patch.object(SERVICE, "fetch_workout", return_value={"path": "w1"}),
        ):
            self.assertEqual(
                service.list_activities("2026-08-01", "2026-08-01"), [{"path": "a1"}]
            )
            self.assertEqual(service.get_activity("a1")["xss"]["total"], 4)
            self.assertEqual(service.list_workouts(name_keywords="vt1", view="full")[0]["path"], "w1")
            self.assertEqual(service.get_workout("w1"), {"path": "w1"})

    def test_credentials_support_mcp_config_with_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "xert.json"
            config.write_text(
                json.dumps({"username": "config-user", "password": "config-password"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "XERT_MCP_CONFIG": str(config),
                    "XERT_USERNAME": "environment-user",
                    "XERT_PASSWORD": "environment-password",
                },
                clear=False,
            ):
                credentials = SERVICE.discover_xert_credentials()
        self.assertEqual(credentials.username, "environment-user")
        self.assertEqual(credentials.password, "environment-password")

    def test_note_service_filters_normalizes_and_sets_without_weight(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        notes = {
            "2026-08-01": {"notes": "First", "weight": 80},
            "2026-08-02": {"notes": ""},
            "2026-09-01": {"notes": "Outside"},
        }
        with (
            patch.object(SERVICE, "xert_web_login", return_value=object()),
            patch.object(SERVICE, "fetch_calendar_notes_with_opener", return_value=notes),
            patch.object(
                SERVICE,
                "set_calendar_note",
                return_value={"success": True, "verified_notes": "Changed"},
            ) as set_note,
        ):
            self.assertEqual(
                service.list_notes("2026-08-01", "2026-08-31"),
                [{"date": "2026-08-01", "text": "First"}],
            )
            self.assertEqual(
                service.get_note("2026-08-02"),
                {"date": "2026-08-02", "exists": False, "text": None},
            )
            self.assertEqual(
                service.set_note("2026-08-03", "Changed"),
                {"date": "2026-08-03", "exists": True, "text": "Changed", "success": True},
            )
        set_note.assert_called_once_with(
            SERVICE.date(2026, 8, 3),
            "Changed",
            username="user",
            password="secret",
            opener=ANY,
        )

    def test_training_state_combines_oauth_and_recovery_sources(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        training_info = {
            "signature": {"ftp": 300, "ltp": 265, "hie": 14.2, "pp": 800},
            "status": "Fresh",
        }
        recovery_model = {
            "at_state": {
                "start_date": "2026-08-17T09:00:00+02:00",
                "tl": {"ftp": 70, "hie": 8, "pp": 2},
                "rl": {"ftp": 65, "hie": 7, "pp": 1},
                "form": {"ftp": 5, "hie": 1, "pp": 1},
            },
            "training_status": "Fresh",
            "recovery_hours": {"lo": 0, "hi": 4, "pk": 0},
            "targetXSS": {"xlss": 50, "xhss": 0, "xpss": 0},
        }
        with (
            patch.object(SERVICE, "_request_json", return_value=training_info),
            patch.object(SERVICE, "fetch_recovery_model_with_opener", return_value=recovery_model),
        ):
            summary = service.get_training_state()
            full = service.get_training_state(view="full")
        self.assertEqual(summary["signature"]["tp_watts"], 300)
        self.assertEqual(summary["training_load"], {"low": 70, "high": 8, "peak": 2})
        self.assertEqual(summary["recovery_hours"]["high"], 4)
        self.assertEqual(full["training_info"], training_info)

    def test_training_advice_selects_current_or_planned_source(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        current = {
            "source": "xert_web_direct",
            "training_status": "Fresh",
            "targetXSS": {"xlss": 40, "xhss": 2, "xpss": 0},
            "at_state": {"start_date": "2026-08-17T09:00:00+02:00"},
        }
        planned = {
            "training_advice": {
                "training_status": "Tired",
                "targetXSS": {"xlss": 20, "xhss": 0, "xpss": 0},
                "remainingXSS": {"xlss": 10, "xhss": 0, "xpss": 0},
                "completedXSS": {"xlss": 10, "xhss": 0, "xpss": 0},
            }
        }
        with (
            patch.object(SERVICE, "fetch_recovery_model_with_opener", return_value=current),
            patch.object(
                SERVICE,
                "fetch_recommended_training_with_opener",
                return_value=planned,
            ) as fetch_planned,
        ):
            current_summary = service.get_training_advice()
            planned_summary = service.get_training_advice(at="2026-08-18T09:00:00+02:00")
        self.assertEqual(current_summary["source_scope"], "current")
        self.assertEqual(current_summary["target_xss"]["low"], 40)
        self.assertEqual(planned_summary["source_scope"], "planned_time")
        self.assertEqual(planned_summary["remaining_xss"]["low"], 10)
        fetch_planned.assert_called_once_with(
            ANY,
            date_value="2026-08-18T06:59:59+00:00",
            recent=True,
            additional=False,
            sport=None,
        )

    def test_training_advice_filters_recommendations_to_workouts(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        payload = {
            "training_advice": {},
            "exercises": [
                {"exerciseType": "Workout", "path": "w1", "name": "Workout", "xss": 40},
                {"exerciseType": "Activity", "path": "a1", "name": "Activity"},
            ],
        }
        with patch.object(
            SERVICE, "fetch_recommended_training_with_opener", return_value=payload
        ):
            result = service.get_training_advice(
                at="2026-08-18T09:00:00+02:00",
                include_recommendations=True,
            )
        self.assertEqual([row["path"] for row in result["recommendations"]], ["w1"])

    def test_training_forecast_filters_epoch_days_by_local_date(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        inside = SERVICE.datetime(2026, 8, 18, 8, tzinfo=SERVICE.timezone.utc).timestamp()
        outside = SERVICE.datetime(2026, 8, 25, 8, tzinfo=SERVICE.timezone.utc).timestamp()
        payload = {
            "days": [
                {"t": inside, "xss": 40, "xlss": 35, "xhss": 5, "xpss": 0},
                {"t": outside, "xss": 50},
            ],
            "other": "preserved",
        }
        with patch.object(SERVICE, "fetch_training_forecast_with_opener", return_value=payload):
            summary = service.get_training_forecast("2026-08-17", "2026-08-24")
            full = service.get_training_forecast("2026-08-17", "2026-08-24", view="full")
        self.assertEqual(len(summary["days"]), 1)
        self.assertEqual(summary["days"][0]["xss"]["low"], 35)
        self.assertEqual(len(full["days"]), 1)
        self.assertEqual(full["other"], "preserved")

    def test_create_workout_normalizes_public_rows_and_calls_saved_create(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        with patch.object(
            SERVICE,
            "create_saved_workout",
            return_value={"path": "created", "saved": True},
        ) as create:
            result = service.create_workout(
                name="  4 x 4  ",
                description="Quality",
                rows=[
                    {
                        "name": "Intervals",
                        "duration_seconds": 240,
                        "power": 340,
                        "interval_count": 4,
                        "rib_duration_seconds": 180,
                        "rib_power": 120,
                    }
                ],
            )
        self.assertEqual(result["path"], "created")
        row = create.call_args.kwargs["rows"][0]
        self.assertEqual(row["duration"]["value"], "04:00")
        self.assertEqual(row["interval_count"], "4")
        self.assertEqual(row["rib_duration"]["value"], "03:00")
        self.assertEqual(create.call_args.kwargs["name"], "4 x 4")

    def test_delete_workout_uses_existing_verified_delete(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        with patch.object(
            SERVICE,
            "delete_saved_workout",
            return_value={"path": "old", "verified_absent": True},
        ) as delete:
            result = service.delete_workout(" old ")
        self.assertTrue(result["verified_absent"])
        delete.assert_called_once_with(
            "old",
            username="user",
            password="secret",
            opener=ANY,
            access_token="token",
        )

    def test_update_workout_uses_atomic_replace_for_rows(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        with patch.object(
            SERVICE,
            "replace_saved_workout",
            return_value={"path": "workout", "submit": "save"},
        ) as replace:
            result = service.update_workout(
                "workout",
                name="Updated",
                rows=[{"duration_seconds": 600, "power": 200}],
            )
        self.assertEqual(result["submit"], "save")
        self.assertEqual(replace.call_args.kwargs["rows"][0]["duration"]["value"], "10:00")
        self.assertEqual(replace.call_args.kwargs["name"], "Updated")

    def test_update_workout_uses_metadata_patch_without_rows(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        with patch.object(
            SERVICE,
            "update_saved_workout",
            return_value={"path": "workout", "submit": "save"},
        ) as update:
            service.update_workout("workout", description="")
        update.assert_called_once_with(
            "workout",
            username="user",
            password="secret",
            name=None,
            description="",
            submit="save",
            opener=ANY,
        )


if __name__ == "__main__":
    unittest.main()
