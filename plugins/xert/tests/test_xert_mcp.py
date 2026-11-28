import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import ANY, patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import xert_activities as ACTIVITIES  # noqa: E402
import xert_mcp as MCP  # noqa: E402
import xert_service as SERVICE  # noqa: E402
import xert_recovery as RECOVERY  # noqa: E402


class FakeXertService:
    def __init__(self) -> None:
        self.calls = []

    def list_activities(self, start_date, end_date, *, include_details=True):
        self.calls.append(("list_activities", start_date, end_date, include_details))
        return [{
            "path": "a1", "name": "Ride", "start_local": "2026-08-01T10:00:00",
            "elapsed_minutes": 60.5, "distance_km": 30.25, "map_url": False,
        }]

    def get_activity(self, path, *, view="summary"):
        self.calls.append(("get_activity", path, view))
        summary = {"path": path, "xss": {"total": 12}}
        if view == "summary":
            return summary
        export = {"path": path, "summary": {"xss": 12}, "activity_summary": summary}
        if view == "session":
            export["session_data"] = [{"time": 0, "xds": 0.2}]
        return export

    def list_workouts(self, *, name_keywords=None, view="summary"):
        self.calls.append(("list_workouts", name_keywords, view))
        return [{
            "path": "w1", "name": "XMB VT1", "duration_min": 120.0,
            "work_watts": 210, "xss": 100.0, "difficulty": 55.0,
        }]

    def get_workout(self, path, *, view="resolved"):
        self.calls.append(("get_workout", path, view))
        return [{"name": "Warm-up"}] if view == "editable" else {"path": path}

    def list_planner_events(self, start_date, end_date):
        self.calls.append(("list_planner_events", start_date, end_date))
        return [{"path": "event-1", "name": "Planned ride"}]

    def create_planner_event(self, event):
        self.calls.append(("create_planner_event", event))
        return {"success": True, "response": "ok", "event": {"path": "event-1", **event}}

    def update_planner_event(self, event_date, event_path, patch):
        self.calls.append(("update_planner_event", event_date, event_path, patch))
        return {"success": True, "event": {"path": event_path, **patch}, "payload": patch}

    def delete_planner_event(self, event_date, event_path):
        self.calls.append(("delete_planner_event", event_date, event_path))
        return {"success": True, "response": "ok", "deleted": {"path": event_path}}

    def list_notes(self, start_date, end_date):
        self.calls.append(("list_notes", start_date, end_date))
        return [{"date": start_date, "text": "Easy day"}]

    def get_note(self, note_date):
        self.calls.append(("get_note", note_date))
        return {"date": note_date, "exists": False, "text": None}

    def set_note(self, note_date, text):
        self.calls.append(("set_note", note_date, text))
        return {"date": note_date, "exists": bool(text), "text": text or None, "success": True}

    def get_training_state(self, *, view="summary", capacity_for=None):
        self.calls.append(("get_training_state", view, capacity_for))
        state = {"as_of": "2026-08-17T09:00:00+02:00"} if view == "summary" else {"training_info": {}}
        return {"view": view, "state": state}

    def get_training_advice(self, *, at=None, view="summary"):
        self.calls.append(("get_training_advice", at, view))
        return {
            "source_scope": "planned_time" if at else "current",
            "at": at,
        }

    def list_recommended_workouts(self, *, at=None, limit=10):
        self.calls.append(("list_recommended_workouts", at, limit))
        return [{"path": "w1", "name": "Workout"}]

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

    def calculate_workout_capacity(self, **kwargs):
        self.calls.append(("calculate_workout_capacity", kwargs))
        return {"workout_capacity_xss": {"low": 100, "high": 10, "peak": 1}}

    def calculate_strain(self, **kwargs):
        self.calls.append(("calculate_strain", kwargs))
        return {
            "source": "local_xert_strain_model",
            "network_used": False,
            "xss": {"low": 50, "high": 0, "peak": 0, "total": 50},
            "feasibility": {"valid": False, "first_point_of_failure": {"time_seconds": 300}},
            "segments": [{"duration_seconds": 600, "start_power": 200}],
        }

    def solve_segment_duration(self, **kwargs):
        self.calls.append(("solve_segment_duration", kwargs))
        return {"adjustable_duration_seconds": 3600}

    def project_load_model(self, **kwargs):
        self.calls.append(("project_load_model", kwargs))
        return {"target_at": kwargs["target_at"]}

    def calculate_workout(self, **kwargs):
        self.calls.append(("calculate_workout", kwargs))
        return {"saved": False}

class XertMcpSchemaTests(unittest.TestCase):
    def test_exposes_only_selected_activity_workout_and_note_tools(self) -> None:
        self.assertEqual(
            MCP.ALL_TOOL_NAMES,
            (
                "list_activities",
                "get_activity",
                "summarize_activities_xert_2",
                "analyze_activity_xert_2",
                "calculate_workout_xert_2",
                "list_workouts",
                "get_workout",
                "list_planner_events",
                "create_planner_event",
                "update_planner_event",
                "delete_planner_event",
                "list_notes",
                "get_note",
                "set_note",
                "get_training_state",
                "get_training_advice",
                "list_recommended_workouts",
                "create_workout",
                "delete_workout",
                "update_workout",
                "get_training_forecast",
                "calculate_workout_capacity",
                "calculate_strain",
                "solve_segment_duration",
                "project_load_model",
                "calculate_workout",
            ),
        )
        self.assertEqual(set(MCP.TOOL_SPECS), set(MCP.ALL_TOOL_NAMES))

    def test_update_workout_uses_step_operations_without_a_separate_tool(self) -> None:
        self.assertNotIn("update_workout_row", MCP.ALL_TOOL_NAMES)
        definition = MCP.TOOL_DEFINITIONS["update_workout"]
        variants = definition["inputSchema"]["properties"]["rows"]["items"]["oneOf"]
        self.assertEqual(
            {variant["properties"]["method"]["const"] for variant in variants},
            {"update", "insert", "remove"},
        )
        self.assertFalse(definition["annotations"]["idempotentHint"])

    def test_every_tool_has_closed_described_inputs_and_expected_annotations(self) -> None:
        for name in MCP.ALL_TOOL_NAMES:
            definition = MCP.TOOL_DEFINITIONS[name]
            self.assertFalse(definition["inputSchema"]["additionalProperties"], name)
            for field, schema in definition["inputSchema"]["properties"].items():
                self.assertTrue(schema.get("description"), f"{name}.{field}")
            new_files = {"get_activity", "analyze_activity_xert_2", "calculate_workout_xert_2"}
            destructive = {
                "set_note", "update_workout", "delete_workout", "create_planner_event",
                "update_planner_event", "delete_planner_event",
            }
            writes = new_files | destructive | {"create_workout"}
            hints = definition["annotations"]
            self.assertEqual(hints["readOnlyHint"], name not in writes, name)
            self.assertEqual(hints["openWorldHint"], name not in {"calculate_strain", "solve_segment_duration"}, name)
            if name in writes:
                self.assertEqual(hints["destructiveHint"], name in destructive, name)
                self.assertEqual(hints["idempotentHint"], name in {"set_note", "delete_workout", "delete_planner_event"}, name)

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

    def test_list_activities_is_compact_by_default(self) -> None:
        activities = self.tools.call_tool(
            "list_activities",
            {"start_date": "2026-08-01", "end_date": "2026-08-02"},
        )
        self.assertEqual(activities["includeFields"], [])
        self.assertEqual(activities["activities"][0], {
            "path": "a1", "name": "Ride", "start_local": "2026-08-01T10:00:00",
        })
        self.assertEqual(
            self.fake.calls[0],
            ("list_activities", "2026-08-01", "2026-08-02", False),
        )

    def test_list_activities_reads_all_summary_fields_from_one_v2_page(self) -> None:
        session = {
            "avg_power": 218.5, "max_power": 390, "avg_heart_rate": 140.5,
            "max_heart_rate": 167, "avg_cadence": 85.25, "max_cadence": 104,
        }
        xss = {"total": 51, "low": 48, "high": 3, "peak": 0}
        fields = [
            "duration_s", "signature", "xss", "xep_watts", "focus", "specificity",
            "difficulty", "difficulty_rating", *session,
        ]
        start = datetime.fromisoformat("2026-08-01T10:00:00").astimezone().isoformat()
        payload = {"activities": [
            {"path": "ride", "name": "Ride", "start_date": start, "summary": {
                "duration": 1800, "sig": {"ftp": 280, "ltp": 230, "pp": 900, "hie": 20.75},
                "xss": xss, "xep": 237, "focus": "Endurance", "specificity": "Pure",
                "difficulty": 60, "difficulty_rating": "Moderate", "session": session,
            }},
            {"path": "no-data", "name": "No data", "start_date": start, "summary": None},
        ], "next_cursor": None}
        service = SERVICE.XertService(SERVICE.XertCredentials)
        with (
            patch.object(service._auth, "bearer_token", return_value="token"),
            patch.object(ACTIVITIES, "_request_json", return_value=payload) as request,
        ):
            tools = MCP.XertToolService(lambda: service)
            args = {"start_date": "2026-08-01", "end_date": "2026-08-02"}
            result = tools.call_tool("list_activities", {**args, "includeFields": fields})
            request.assert_called_once()
            self.assertEqual(request.call_args.args, ("/oauth/v2/activity", "token"))
            self.assertEqual(request.call_args.kwargs["params"]["include_details"], 1)
            selected = tools.call_tool("list_activities", {
                **args,
                "filters": [{"field": "xss.peak", "op": "eq", "value": 0}],
                "sort": [{"field": "signature.atc", "direction": "desc"}],
            })
        self.assertEqual(result["activities"][0], {
            "path": "ride", "name": "Ride", "start_local": "2026-08-01T10:00:00",
            "duration_s": 1800, "signature": {"ftp": 280, "ltp": 230, "pp": 900, "atc": 20750},
            "xss": xss, "xep_watts": 237, "focus": "Endurance", "specificity": "Pure",
            "difficulty": 60, "difficulty_rating": "Moderate", **session,
        })
        self.assertTrue(all(result["activities"][1][field] is None for field in fields))
        self.assertEqual([row["path"] for row in selected["activities"]], ["ride"])
        self.assertEqual(selected["activities"][0]["signature"]["atc"], 20750)
        self.assertEqual(request.call_args.kwargs["params"]["include_details"], 1)

    def test_list_activities_cheap_include_field_uses_summary_read(self) -> None:
        activities = self.tools.call_tool("list_activities", {
            "start_date": "2026-08-01", "end_date": "2026-08-02",
            "includeFields": ["map_url"],
        })
        self.assertFalse(activities["activities"][0]["map_url"])
        self.assertFalse(self.fake.calls[0][-1])

    def test_list_activities_adds_old_default_fields_only_when_requested(self) -> None:
        activities = self.tools.call_tool("list_activities", {
            "start_date": "2026-08-01", "end_date": "2026-08-02",
            "includeFields": ["duration_s", "distance_m", "source"],
        })
        self.assertEqual(activities["activities"][0], {
            "path": "a1", "name": "Ride", "start_local": "2026-08-01T10:00:00",
            "duration_s": 3630, "distance_m": 30250, "source": "xert_plugin",
        })
        self.assertTrue(self.fake.calls[0][-1])

    def test_list_activities_requests_duration_for_filters_and_sort(self) -> None:
        for query in (
            {"filters": [{"field": "duration_s", "op": "gte", "value": 3600}]},
            {"sort": [{"field": "duration_s", "direction": "desc"}]},
        ):
            with self.subTest(query=query):
                result = self.tools.call_tool("list_activities", {
                    "start_date": "2026-08-01", "end_date": "2026-08-02", **query,
                })
                self.assertEqual(result["activities"][0]["duration_s"], 3630)
                self.assertTrue(self.fake.calls[-1][-1])

    def test_list_activities_rejects_invalid_include_fields(self) -> None:
        for include_fields, message in (
            (["unknown"], "Unsupported includeFields value"),
            (["xss", "xss"], "unique"),
            ("xss", "array of strings"),
        ):
            with self.subTest(include_fields=include_fields), self.assertRaisesRegex(
                MCP.ToolFailure, message
            ):
                self.tools.call_tool("list_activities", {
                    "start_date": "2026-08-01", "end_date": "2026-08-02",
                    "includeFields": include_fields,
                })

    def test_editable_workout(self) -> None:
        workout = self.tools.call_tool(
            "get_workout", {"workout_path": "w1", "view": "editable"}
        )
        self.assertEqual(workout["rows"], [{"name": "Warm-up"}])

    def test_list_workouts_is_compact_by_default(self) -> None:
        result = self.tools.call_tool("list_workouts", {"name_keywords": "VT1"})
        self.assertEqual(result["includeFields"], [])
        self.assertEqual(result["workouts"], [{
            "path": "w1", "name": "XMB VT1",
        }])
        self.assertEqual(self.fake.calls[0], ("list_workouts", "VT1", "summary"))

    def test_list_workouts_adds_only_requested_fields(self) -> None:
        result = self.tools.call_tool("list_workouts", {
            "includeFields": ["work_watts", "xss"],
        })
        self.assertEqual(result["includeFields"], ["work_watts", "xss"])
        self.assertEqual(result["workouts"][0], {
            "path": "w1", "name": "XMB VT1",
            "work_watts": 210, "xss": 100.0,
        })

        with_duration = self.tools.call_tool("list_workouts", {
            "includeFields": ["duration_s"],
        })
        self.assertEqual(with_duration["workouts"][0]["duration_s"], 7200)

    def test_list_workouts_rejects_invalid_include_fields(self) -> None:
        for include_fields, message in (
            (["unknown"], "Unsupported includeFields value"),
            (["xss", "xss"], "unique"),
            ("xss", "array of strings"),
        ):
            with self.subTest(include_fields=include_fields), self.assertRaisesRegex(
                MCP.ToolFailure, message
            ):
                self.tools.call_tool("list_workouts", {"includeFields": include_fields})

    def test_get_activity_always_returns_summary(self) -> None:
        result = self.tools.call_tool("get_activity", {"activity_path": "a1"})
        self.assertEqual(result["activity"], {"path": "a1", "xss": {"total": 12}})
        self.assertEqual(self.fake.calls, [("get_activity", "a1", "summary")])
        self.assertNotIn("full_activity_file", result)
        self.assertNotIn("session_file", result)

    def test_get_activity_can_save_full_and_session_private_files(self) -> None:
        result = self.tools.call_tool(
            "get_activity", {
                "activity_path": "folder/a1", "save_session": True, "save_full": True,
            }
        )
        full_path = Path(result["full_activity_file"])
        session_path = Path(result["session_file"])
        try:
            self.assertEqual(result["full_activity_format"], "xert-activity-v1")
            self.assertEqual(result["session_format"], "xert-activity-session-v1")
            self.assertEqual(result["activity"]["xss"]["total"], 12)
            for path, size_key in (
                (full_path, "full_activity_byte_size"),
                (session_path, "session_byte_size"),
            ):
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(result[size_key], path.stat().st_size)
                envelope = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(envelope["activity_path"], "folder/a1")
                self.assertEqual(envelope["activity"]["path"], "folder/a1")
                self.assertEqual(envelope["activity"]["summary"]["xss"], 12)
                self.assertEqual(envelope["activity"]["activity_summary"], result["activity"])
                self.assertNotIn("/", path.name)
            self.assertNotIn("session_data", json.loads(full_path.read_text())["activity"])
            self.assertEqual(json.loads(session_path.read_text())["activity"]["session_data"],
                             [{"time": 0, "xds": 0.2}])
            self.assertEqual(
                self.fake.calls,
                [("get_activity", "folder/a1", "session")],
            )
        finally:
            full_path.unlink(missing_ok=True)
            session_path.unlink(missing_ok=True)

    def test_get_activity_rejects_non_boolean_save_flags(self) -> None:
        for field in ("save_full", "save_session"):
            with self.subTest(field=field), self.assertRaisesRegex(
                MCP.ToolFailure, f"{field} must be a boolean"
            ):
                self.tools.call_tool(
                    "get_activity", {"activity_path": "a1", field: "yes"}
                )

    @patch.object(MCP, "analyze_activity_xert_2")
    def test_xert_2_activity_analysis_is_read_only(self, preview) -> None:
        preview.return_value = {
            "activity_path": "a1", "source": "xert_2_local_wasm", "experimental": True,
            "standard_xert_comparable": False, "caveats": [], "metrics": {}, "xss": {},
        }
        result = self.tools.call_tool(
            "analyze_activity_xert_2", {"activity_path": "a1", "save_series": True}
        )
        self.assertTrue(result["experimental"])
        preview.assert_called_once_with("a1", save_series=True)
        with self.assertRaisesRegex(MCP.ToolFailure, "save_series must be a boolean"):
            self.tools.call_tool(
                "analyze_activity_xert_2", {"activity_path": "a1", "save_series": "yes"}
            )

    @patch.object(MCP, "calculate_workout_xert_2")
    def test_xert_2_workout_calculation_is_read_only(self, preview) -> None:
        preview.return_value = {
            "model_source_activity_path": "a1", "workout_duration_s": 600,
            "source": "xert_2_local_wasm", "experimental": True,
            "standard_xert_comparable": False, "caveats": [], "metrics": {}, "xss": {},
        }
        result = self.tools.call_tool("calculate_workout_xert_2", {
            "model_source_activity_path": "a1",
            "rows": [{"duration_seconds": 600, "power": 200}],
            "initial_muscle_glycogen_balance_g": -100,
            "muscle_glucose_uptake_g_per_hour": 0,
            "save_series": True,
        })
        self.assertTrue(result["experimental"])
        preview.assert_called_once_with(
            [{"duration_seconds": 600, "power": 200}],
            model_source_activity_path="a1",
            initial_muscle_glycogen_balance_g=-100, muscle_glucose_uptake_g_per_hour=0,
            save_series=True,
        )
        with self.assertRaisesRegex(MCP.ToolFailure, "save_series must be a boolean"):
            self.tools.call_tool("calculate_workout_xert_2", {
                "model_source_activity_path": "a1",
                "rows": [{"duration_seconds": 600, "power": 200}],
                "save_series": "yes",
            })

    def test_rejects_unknown_and_missing_arguments(self) -> None:
        with self.assertRaisesRegex(MCP.ToolFailure, "unknown argument"):
            self.tools.call_tool(
                "list_workouts", {"view": "summary"}
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

    def test_planner_event_tools_dispatch_verified_contracts(self) -> None:
        listed = self.tools.call_tool("list_planner_events", {
            "start_date": "2026-08-17", "end_date": "2026-08-18",
        })
        created = self.tools.call_tool("create_planner_event", {
            "event": {"title": "Ride", "start_date": "2026-08-17T10:00:00+02:00"},
        })
        updated = self.tools.call_tool("update_planner_event", {
            "date": "2026-08-17", "event_path": "event-1", "patch": {"title": "Long ride"},
        })
        deleted = self.tools.call_tool("delete_planner_event", {
            "date": "2026-08-17", "event_path": "event-1",
        })

        self.assertEqual(listed["count"], 1)
        self.assertTrue(created["success"])
        self.assertEqual(updated["event"]["title"], "Long ride")
        self.assertTrue(deleted["success"])

    def test_training_state_dispatches_requested_view(self) -> None:
        result = self.tools.call_tool("get_training_state", {"view": "full"})
        self.assertEqual(result["view"], "full")
        self.assertEqual(result["state"], {"training_info": {}})

    def test_training_state_dispatches_capacity_horizon(self) -> None:
        horizon = {"as_of": "2026-08-17T10:00:00+02:00", "fresh_at": "2026-08-18T09:00:00+02:00"}
        self.tools.call_tool("get_training_state", {"capacity_for": horizon})
        self.assertEqual(self.fake.calls[-1], ("get_training_state", "summary", horizon))

    def test_training_advice_dispatches_optional_time_and_view(self) -> None:
        result = self.tools.call_tool(
            "get_training_advice",
            {
                "at": "2026-08-18T09:00:00+02:00",
                "view": "full",
            },
        )
        self.assertEqual(result["view"], "full")
        self.assertEqual(result["advice"]["source_scope"], "planned_time")

    def test_recommended_workouts_dispatches_optional_time(self) -> None:
        result = self.tools.call_tool(
            "list_recommended_workouts",
            {"at": "2026-08-18T09:00:00+02:00", "limit": 5},
        )
        self.assertEqual(result["at"], "2026-08-18T09:00:00+02:00")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["workouts"][0]["path"], "w1")

    def test_training_forecast_dispatches_range_and_view(self) -> None:
        result = self.tools.call_tool(
            "get_training_forecast",
            {"start_date": "2026-08-17", "end_date": "2026-08-24"},
        )
        self.assertEqual(result["forecast"], {"days": []})

    def test_all_xert_list_tools_support_general_queries(self) -> None:
        self.fake.list_activities = lambda *args, **kwargs: [
            {"path": "a1", "name": "Easy", "elapsed_minutes": 60, "distance_km": 30},
            {"path": "a2", "name": "Hard", "elapsed_minutes": 90, "distance_km": 45},
        ]
        activities = self.tools.call_tool("list_activities", {
            "start_date": "2026-08-01", "end_date": "2026-08-17",
            "filters": [{"field": "duration_s", "op": "gte", "value": 5000}],
        })
        self.assertEqual([row["path"] for row in activities["activities"]], ["a2"])

        self.fake.list_workouts = lambda **kwargs: [
            {"path": "w1", "name": "Easy", "duration_min": 60, "difficulty": 20},
            {"path": "w2", "name": "Hard", "duration_min": 45, "difficulty": 80},
        ]
        workouts = self.tools.call_tool("list_workouts", {
            "filters": [{"field": "difficulty", "op": "gt", "value": 50}],
        })
        self.assertEqual([row["path"] for row in workouts["workouts"]], ["w2"])

        self.fake.list_notes = lambda *args: [
            {"date": "2026-08-16", "text": "Easy"},
            {"date": "2026-08-17", "text": "Sick today"},
        ]
        notes = self.tools.call_tool("list_notes", {
            "start_date": "2026-08-16", "end_date": "2026-08-17",
            "filters": [{"field": "text", "op": "contains", "value": "sick"}],
        })
        self.assertEqual([row["date"] for row in notes["notes"]], ["2026-08-17"])

        self.fake.list_recommended_workouts = lambda **kwargs: [
            {"path": "w1", "name": "Low", "xss": {"total": 40}},
            {"path": "w2", "name": "High", "xss": {"total": 90}},
        ]
        recommended = self.tools.call_tool("list_recommended_workouts", {
            "limit": 1,
            "sort": [{"field": "xss.total", "direction": "desc"}],
        })
        self.assertEqual([row["path"] for row in recommended["workouts"]], ["w2"])

        self.fake.get_training_forecast = lambda *args, **kwargs: {"days": [
            {"date": "2026-08-18", "xss": {"total": 40}},
            {"date": "2026-08-19", "xss": {"total": 80}},
        ]}
        forecast = self.tools.call_tool("get_training_forecast", {
            "start_date": "2026-08-18", "end_date": "2026-08-19",
            "filters": [{"field": "xss.total", "op": "gte", "value": 60}],
        })
        self.assertEqual(
            [row["date"] for row in forecast["forecast"]["days"]], ["2026-08-19"]
        )

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

    def test_update_workout_dispatches_metadata_and_row_operations(self) -> None:
        result = self.tools.call_tool(
            "update_workout",
            {
                "workout_path": "workout",
                "name": "Updated",
                "rows": [{"method": "update", "row_number": 2, "power": 200}],
            },
        )
        self.assertEqual(result["workout"]["submit"], "save")

    def test_model_and_calculation_tools_dispatch(self) -> None:
        self.assertEqual(
            self.tools.call_tool("calculate_workout_capacity", {
                "as_of": "2026-08-18T09:00:00+02:00",
                "fresh_at": "2026-08-19T09:00:00+02:00",
            })["workout_capacity_xss"]["low"],
            100,
        )
        self.assertEqual(self.tools.call_tool("calculate_strain", {
            "signature": {"tp": 300, "hie": 14000, "pp": 800},
            "segments": [{"duration_seconds": 600, "power": 200}],
        })["xss"]["low"], 50)
        self.assertEqual(self.tools.call_tool("solve_segment_duration", {
            "signature": {"tp": 300, "hie": 14000, "pp": 800},
            "segments": [{"duration_seconds": 600, "power": 200}],
            "adjustable_segment_index": 0, "target_metric": "low_xss", "target_value": 50,
        })["adjustable_duration_seconds"], 3600)
        self.assertEqual(self.tools.call_tool("project_load_model", {
            "workout_at": "2026-08-18T09:00:00+02:00",
            "target_at": "2026-08-19T09:00:00+02:00",
        })["target_at"], "2026-08-19T09:00:00+02:00")
        self.assertFalse(self.tools.call_tool("calculate_workout", {
            "rows": [{"duration_seconds": 600, "power": 200}],
        })["saved"])

    def test_calculate_strain_projects_fields_without_changing_calculation_inputs(self):
        arguments = {
            "signature": {"tp": 300, "hie": 14000, "pp": 800},
            "segments": [{"duration_seconds": 600, "power": 200}],
        }
        full = self.tools.call_tool("calculate_strain", arguments)
        self.assertEqual(full["feasibility"]["first_point_of_failure"], {"time_seconds": 300})
        metadata = {"source": "local_xert_strain_model", "network_used": False}
        cases = (
            ([], metadata),
            (["xss"], {**metadata, "xss": full["xss"]}),
            (["xss.total", "feasibility.valid"], {
                **metadata, "xss": {"total": 50}, "feasibility": {"valid": False},
            }),
            (["segments.duration_seconds", "absent"], {
                **metadata, "segments": [{"duration_seconds": 600}],
            }),
        )
        for fields, expected in cases:
            with self.subTest(fields=fields):
                result = self.tools.call_tool("calculate_strain", {**arguments, "includeFields": fields})
                self.assertEqual(result, expected)
        self.assertEqual(self.fake.calls, [("calculate_strain", arguments)] * (1 + len(cases)))

    def test_calculate_strain_rejects_invalid_field_selections(self):
        for fields in (None, "xss", [1], ["xss", "xss"], ["feasibility..valid"], [" xss"]):
            with self.subTest(fields=fields), self.assertRaisesRegex(MCP.ToolFailure, "includeFields"):
                self.tools.call_tool("calculate_strain", {
                    "signature": {"tp": 300, "hie": 14000, "pp": 800},
                    "segments": [{"duration_seconds": 600, "power": 200}],
                    "includeFields": fields,
                })
        self.assertEqual(self.fake.calls, [])

    def test_projection_requires_absolute_workout_time(self):
        for arguments in [
            {"target_at": "2026-10-19T08:00:00+02:00"},
            {"target_at": "2026-10-19T08:00:00+02:00", "workout_after_hours": 33},
        ]:
            with self.subTest(arguments=arguments), self.assertRaises(MCP.ToolFailure):
                self.tools.call_tool("project_load_model", arguments)
        self.assertEqual(self.fake.calls, [])


class XertServiceTests(unittest.TestCase):
    def test_projection_compares_dose_and_baseline_without_refetching(self):
        model = {
            "at_state": {"start_date": "2026-10-17T08:00:00Z",
                         "tl": {"ftp": 100, "hie": 1, "pp": 0.2},
                         "rl": {"ftp": 90, "hie": 0.8, "pp": 0.15}},
            "ir_params": {
                "ftp": {"tau1": 60, "tau2": 5, "k1": 0.4},
                "hie": {"tau1": 22, "tau2": 12, "k1": 0.75},
                "pp": {"tau1": 22, "tau2": 12, "k1": 50},
            },
            "recovery_offset": 0.2,
        }
        for dose in [0, 100]:
            with self.subTest(dose=dose):
                service = self._service(SERVICE.XertCredentials(username="user", password="secret"))
                with (
                    patch.object(SERVICE, "_request_json", return_value={
                        "signature": {"ftp": 296, "hie": 14, "pp": 775},
                    }) as fetch_signature,
                    patch.object(SERVICE, "fetch_recovery_model_with_opener", return_value=model) as fetch_model,
                ):
                    result = service.project_load_model(
                        workout_at="2026-10-18T17:00:00+02:00",
                        target_at="2026-10-19T08:00:00+02:00", low_xss=dose,
                    )
                fetch_signature.assert_called_once_with("/oauth/v2/training_info", "token")
                fetch_model.assert_called_once()
                baseline = result["no_training_projection"]
                self.assertEqual(result["state_sync"], baseline["state_sync"])
                self.assertEqual(result["horizon_days"], baseline["horizon_days"])
                self.assertEqual(result["systems"]["high"], baseline["systems"]["high"])
                if dose:
                    self.assertGreater(result["totals"]["training_load"], baseline["totals"]["training_load"])
                    self.assertGreater(result["signature_projection"]["ftp"], baseline["signature_projection"]["ftp"])
                else:
                    self.assertEqual(result["systems"], baseline["systems"])
                    self.assertEqual(result["signature_projection"], baseline["signature_projection"])
                json.dumps(result)

    def test_projection_anchors_absolute_workout_to_fetched_source_state(self):
        service = self._service(SERVICE.XertCredentials(username="user", password="secret"))
        with (
            patch.object(SERVICE, "_request_json", return_value={"signature": {}}),
            patch.object(SERVICE, "fetch_recovery_model_with_opener", return_value={
                "at_state": {"start_date": "2026-10-17T08:00:00Z"},
                "ir_params": {}, "recovery_offset": 0,
            }),
            patch.object(SERVICE, "calculate_load_projection", return_value={}) as calculate,
        ):
            result = service.project_load_model(
                workout_at="2026-10-18T17:00:00+02:00",
                target_at="2026-10-19T08:00:00+02:00", low_xss=100,
            )
        # The source is 10:00 local, not the scenario's wall-clock 08:00.
        self.assertAlmostEqual(calculate.call_args.kwargs["workout_after_days"], 31 / 24)
        self.assertAlmostEqual(calculate.call_args.kwargs["horizon_days"], 46 / 24)
        self.assertEqual(result["source_state_as_of"], "2026-10-17T08:00:00+00:00")
        self.assertEqual(result["workout_at"], "2026-10-18T17:00:00+02:00")

    def test_projection_rejects_workout_outside_source_target_interval(self):
        service = self._service(SERVICE.XertCredentials(username="user", password="secret"))
        with (
            patch.object(SERVICE, "_request_json", return_value={"signature": {}}),
            patch.object(SERVICE, "fetch_recovery_model_with_opener", return_value={
                "at_state": {"start_date": "2026-10-17T08:00:00Z"},
                "ir_params": {}, "recovery_offset": 0,
            }),
            patch.object(SERVICE, "calculate_load_projection", return_value={}) as calculate,
        ):
            for workout_at in ["2026-10-17T07:59:59Z", "2026-10-17T09:00:01Z"]:
                with self.subTest(workout_at=workout_at), self.assertRaises(ValueError):
                    service.project_load_model(workout_at=workout_at, target_at="2026-10-17T09:00:00Z")
            calculate.assert_not_called()
            for workout_at in ["2026-10-17T08:00:00Z", "2026-10-17T09:00:00Z"]:
                service.project_load_model(workout_at=workout_at, target_at="2026-10-17T09:00:00Z")
            self.assertEqual(calculate.call_count, 4)

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
            patch.object(SERVICE, "list_activities_v2", return_value=[{
                "path": "a1", "name": "Ride", "start_local": "2026-08-01T10:00:00",
                "elapsed_minutes": 60.5, "distance_km": 30.25, "source": "xert_plugin",
            }]) as oauth,
            patch.object(SERVICE, "fetch_activity_summary_v2", return_value={"xss": {"total": 4}}) as activity,
            patch.object(SERVICE, "fetch_activity_web") as web_activity,
            patch.object(SERVICE, "fetch_workouts", return_value=[{"name": "XMB VT1", "path": "w1"}]),
            patch.object(SERVICE, "fetch_workout", return_value={"path": "w1"}),
        ):
            listed = service.list_activities("2026-08-01", "2026-08-01")
            self.assertEqual(listed[0]["path"], "a1")
            self.assertEqual(listed[0]["source"], "xert_plugin")
            self.assertEqual(listed[0]["elapsed_minutes"], 60.5)
            self.assertEqual(listed[0]["distance_km"], 30.25)
            self.assertEqual(listed[0]["start_local"], "2026-08-01T10:00:00")
            oauth.assert_called_once_with(
                date(2026, 8, 1), date(2026, 8, 1), "token", include_details=True,
            )
            self.assertEqual(service.get_activity("a1")["xss"]["total"], 4)
            activity.assert_called_once_with("a1", "token")
            web_activity.assert_not_called()
            self.assertEqual(service.list_workouts(name_keywords="vt1", view="full")[0]["path"], "w1")
            self.assertEqual(service.get_workout("w1"), {"path": "w1"})

    def test_activity_exports_combine_v2_summary_and_web_analytics(self):
        service = self._service(SERVICE.XertCredentials(username="user", password="secret"))
        summary = {"path": "a1", "xss": {"total": 7}}
        with (
            patch.object(SERVICE, "fetch_activity_summary_v2", return_value=summary) as api,
            patch.object(SERVICE, "fetch_activity_web", return_value={
                "path": "a1", "summary": {"xss": 7}, "session_data": [{"time": 0, "xds": 2}],
            }) as web,
        ):
            exported = service.get_activity("a1", view="session")
        api.assert_called_once_with("a1", "token")
        web.assert_called_once_with(service._auth._opener, "a1", include_session_data=True)
        self.assertEqual(exported["activity_summary"], summary)
        self.assertEqual(exported["summary"], {"xss": 7})
        self.assertEqual(exported["session_data"], [{"time": 0, "xds": 2}])

    def test_credentials_support_mcp_config_with_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "xert.json"
            config.write_text(
                json.dumps({"username": "config-user", "password": "config-password",
                            "oauthClientId": "xk_config", "oauthClientSecret": "xs_config"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "XERT_MCP_CONFIG": str(config),
                    "XERT_USERNAME": "environment-user",
                    "XERT_PASSWORD": "environment-password",
                },
                clear=True,
            ):
                credentials = SERVICE.discover_xert_credentials()
                self.assertEqual(credentials.oauth_client_id, "xk_config")
                self.assertEqual(credentials.oauth_client_secret, "xs_config")
                with patch.dict(os.environ, {"XERT_OAUTH_CLIENT_ID": "xk_env",
                                             "XERT_OAUTH_CLIENT_SECRET": "xs_env"}):
                    overridden = SERVICE.discover_xert_credentials()
                    self.assertEqual(overridden.oauth_client_id, "xk_env")
                    self.assertEqual(overridden.oauth_client_secret, "xs_env")
        self.assertEqual(credentials.username, "environment-user")
        self.assertEqual(credentials.password, "environment-password")

    def test_api_only_workout_reads_do_not_require_web_credentials(self) -> None:
        service = self._service(SERVICE.XertCredentials(
            oauth_client_id="xk_test", oauth_client_secret="xs_test"))
        with (
            patch.object(SERVICE, "fetch_workouts", return_value=[]) as listing,
            patch.object(SERVICE, "fetch_workout", return_value={"name": "Personal"}),
            patch.object(SERVICE, "xert_web_login") as login,
        ):
            self.assertEqual(service.list_workouts(), [])
            self.assertEqual(service.get_workout("w1"), {"name": "Personal"})
            self.assertEqual(listing.call_args.kwargs["access_token"], "token")
            login.assert_not_called()

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

    def test_planner_event_service_reuses_session_and_verified_helpers(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        first_day = {"date": "2026-08-01", "events": [{"path": "e1"}]}
        second_day = {"date": "2026-08-02", "events": [{"path": "e2"}]}
        with (
            patch.object(SERVICE, "fetch_calendar_events_with_opener", side_effect=[first_day, second_day]) as list_events,
            patch.object(SERVICE, "create_calendar_event_with_opener", return_value={"success": True, "response": "ok", "event": {"path": "e3"}}) as create_event,
            patch.object(SERVICE, "update_calendar_event_with_opener", return_value={"success": True, "event": {"path": "e3"}, "payload": {"title": "Updated"}}) as update_event,
            patch.object(SERVICE, "delete_calendar_event_with_opener", return_value={"success": True, "response": "ok", "deleted": {"path": "e3"}}) as delete_event,
        ):
            self.assertEqual(
                [event["path"] for event in service.list_planner_events("2026-08-01", "2026-08-02")],
                ["e1", "e2"],
            )
            self.assertTrue(service.create_planner_event({"title": "Ride"})["success"])
            self.assertTrue(service.update_planner_event("2026-08-02", " e3 ", {"title": "Updated"})["success"])
            self.assertTrue(service.delete_planner_event("2026-08-02", " e3 ")["success"])

        self.assertEqual(list_events.call_count, 2)
        create_event.assert_called_once_with(ANY, {"title": "Ride"})
        update_event.assert_called_once_with(
            ANY, SERVICE.date(2026, 8, 2), "e3", {"title": "Updated"}
        )
        delete_event.assert_called_once_with(ANY, SERVICE.date(2026, 8, 2), "e3")

    def test_training_state_combines_oauth_and_recovery_sources(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        training_info = {
            "signature": {"ftp": 300, "ltp": 265, "hie": 14.2, "pp": 800},
            "status": "Fresh",
            "sport": "Cycling",
            "target_xss": {"low": 70, "high": 0, "peak": 0, "total": 70},
            "wotd": None,
        }
        recovery_model = {
            "at_state": {
                "start_date": "2026-08-17T09:00:00+02:00",
                "tl": {"ftp": 70, "hie": 8, "pp": 2},
                "rl": {"ftp": 65, "hie": 7, "pp": 1},
                "form": {"ftp": 5, "hie": 1, "pp": 1},
            },
            "training_status": "Fresh",
            "recovery_days": {"lo": 0, "hi": 4 / 24, "pk": -2 / 24},
            "recovery_hours": {"lo": 0, "hi": 4, "pk": 0},
            "targetXSS": {"xlss": 50, "xhss": 0, "xpss": 0},
        }
        with (
            patch.object(SERVICE, "_request_json", return_value=training_info) as fetch_training_info,
            patch.object(SERVICE, "fetch_recovery_model_with_opener", return_value=recovery_model),
        ):
            summary = service.get_training_state()["state"]
            full = service.get_training_state(view="full")["state"]
        self.assertEqual(summary["signature"]["tp_watts"], 300)
        self.assertEqual(summary["signature"]["hie_kj"], 14.2)
        self.assertEqual(summary["target_xss"], {"low": 50, "high": 0, "peak": 0})
        self.assertEqual(summary["training_load"], {"low": 70, "high": 8, "peak": 2})
        self.assertEqual(summary["recovery_hours"]["high"], 4)
        self.assertEqual(summary["fresh_at"], {
            "low": "2026-08-17T09:00:00+02:00",
            "all": "2026-08-17T13:00:00+02:00",
        })
        self.assertEqual(full["training_info"], training_info)
        self.assertEqual([call.args for call in fetch_training_info.call_args_list],
                         [("/oauth/v2/training_info", "token")] * 2)

        horizon = {"as_of": "2026-08-17T10:00:00+02:00", "fresh_at": "2026-08-18T09:00:00+02:00"}
        recovery_model["ir_params"] = {
            "ftp": {"tau1": 60, "tau2": 5},
            "hie": {"tau1": 22, "tau2": 12},
            "pp": {"tau1": 22, "tau2": 12},
        }
        recovery_model["recovery_offset"] = 0
        with (
            patch.object(SERVICE, "_request_json", return_value=training_info),
            patch.object(SERVICE, "fetch_recovery_model_with_opener", return_value=recovery_model) as fetch,
        ):
            combined = service.get_training_state(capacity_for=horizon)
            fetch.assert_called_once()
            self.assertEqual(combined["workout_capacity"], service.calculate_workout_capacity(**horizon))
        self.assertEqual(combined["state"], summary)
        self.assertEqual(combined["workout_capacity"]["source_state_as_of"], recovery_model["at_state"]["start_date"])
        self.assertEqual(combined["workout_capacity"]["state_as_of"], horizon["as_of"])

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

    def test_planned_advice_preserves_planning_context(self) -> None:
        source = {
            "xss_deficit": 273.3,
            "xss_goal": 223.3,
            "availability": 3.25,
            "is_availability_restricted": True,
            "ir": 3,
            "weekly_hours": 16.8,
            "training_gradient": 3,
            "phase": "Continuous",
            "recommended_athlete": "Endurance",
        }
        for zero_values in (False, True):
            with self.subTest(zero_values=zero_values):
                advice = dict(source)
                if zero_values:
                    advice.update({
                        key: False if isinstance(value, bool) else 0
                        for key, value in source.items()
                        if isinstance(value, (int, float))
                    })
                summary = SERVICE.compact_planned_training_advice(
                    {"training_advice": advice}, at="2026-08-18T09:00:00+02:00"
                )
                for key, value in advice.items():
                    output_key = "improvement_rate" if key == "ir" else key
                    self.assertEqual(summary[output_key], value)
                    self.assertIs(type(summary[output_key]), type(value))

    def test_current_advice_preserves_source_context_in_summary_and_full(self) -> None:
        service = self._service(SERVICE.XertCredentials(username="user", password="secret"))
        advice = {
            "at_state": {"start_date": "2026-08-17T09:00:00+02:00"},
            "targetXSS": {"xlss": 40, "xhss": 2, "xpss": 0},
            "xss_deficit": 0,
            "xss_goal": 42,
            "availability": 0,
            "is_availability_restricted": False,
            "ir": 0,
            "weekly_hours": 0,
            "training_gradient": 0,
            "phase": "Continuous",
            "recommended_athlete": "Endurance",
            "additional_source_field": "preserved in full",
        }
        with (
            patch.object(RECOVERY, "fetch_my_fitness_model", return_value=(
                advice, {"settings": {"recovery": 0.2}}
            )),
            patch.object(RECOVERY, "fetch_ir_params", return_value={}),
            patch.object(RECOVERY, "fetch_training_forecast_with_opener", return_value={}),
            patch.object(RECOVERY, "calculate_recovery_days", return_value={}),
            patch.object(RECOVERY, "infer_next_workout_days", return_value=1),
            patch.object(RECOVERY, "calculate_workout_capacity", return_value={}),
        ):
            summary = service.get_training_advice()
            full = service.get_training_advice(view="full")
        self.assertEqual(full["payload"]["training_advice"], advice)
        self.assertEqual(summary["target_xss"], {"low": 40, "high": 2, "peak": 0})
        for key in (
            "xss_deficit", "xss_goal", "availability", "is_availability_restricted",
            "ir", "weekly_hours", "training_gradient", "phase", "recommended_athlete",
        ):
            output_key = "improvement_rate" if key == "ir" else key
            self.assertEqual(summary[output_key], advice[key])
            self.assertIs(type(summary[output_key]), type(advice[key]))

    def test_list_recommended_workouts_filters_to_workouts(self) -> None:
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
            result = service.list_recommended_workouts(
                at="2026-08-18T09:00:00+02:00", limit=1
            )
        self.assertEqual([row["path"] for row in result], ["w1"])

    def test_list_recommended_workouts_applies_limit_after_workout_filter(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        payload = {
            "exercises": [
                {"exerciseType": "Activity", "path": "a1"},
                {"exerciseType": "Workout", "path": "w1"},
                {"exerciseType": "Workout", "path": "w2"},
            ]
        }
        with patch.object(
            SERVICE, "fetch_recommended_training_with_opener", return_value=payload
        ):
            result = service.list_recommended_workouts(limit=1)
        self.assertEqual([row["path"] for row in result], ["w1"])

    def test_list_recommended_workouts_rejects_invalid_limit(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        for limit in (0, 101, True, "10"):
            with self.subTest(limit=limit), self.assertRaisesRegex(
                ValueError, "limit must be an integer from 1 to 100"
            ):
                service.list_recommended_workouts(limit=limit)

    def test_full_planned_advice_excludes_workout_candidates(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        payload = {
            "training_advice": {"training_status": "Fresh"},
            "exercises": [{"exerciseType": "Workout", "path": "w1"}],
        }
        with patch.object(
            SERVICE, "fetch_recommended_training_with_opener", return_value=payload
        ):
            result = service.get_training_advice(
                at="2026-08-18T09:00:00+02:00", view="full"
            )

        self.assertIn("training_advice", result["payload"])
        self.assertNotIn("exercises", result["payload"])

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

    def test_create_workout_preserves_disabled_zero_repeat_row(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        with patch.object(
            SERVICE,
            "create_saved_workout",
            return_value={"path": "created", "saved": True},
        ) as create:
            service.create_workout(
                name="Template",
                rows=[{
                    "name": "Endurance",
                    "duration_seconds": 1800,
                    "power": 210,
                    "interval_count": 0,
                }],
            )
        self.assertEqual(create.call_args.kwargs["rows"][0]["interval_count"], "0")

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

    def test_update_workout_applies_operations_and_saves_once(self) -> None:
        credentials = SERVICE.XertCredentials(username="user", password="secret")
        service = self._service(credentials)
        original = [
            SERVICE._designer_row_from_input(
                {"name": name, "duration_seconds": 600, "power": power}, sequence=index
            )
            for index, (name, power) in enumerate(
                (("Warmup", 150), ("Work", 200), ("Cooldown", 120))
            )
        ]
        with (
            patch.object(SERVICE, "fetch_workout_designer_rows", return_value=original),
            patch.object(
                SERVICE,
                "replace_saved_workout",
                return_value={
                    "path": "workout", "submit": "save", "replaced_rows": 3
                },
            ) as replace,
        ):
            result = service.update_workout("workout", name="Updated", rows=[
                {"method": "update", "row_number": 2, "duration_seconds": 900},
                {
                    "method": "insert", "after_row_number": 2, "name": "Extra",
                    "duration_seconds": 300, "power": 180,
                },
                {"method": "remove", "row_number": 3},
            ])
        self.assertEqual(result["submit"], "save")
        self.assertNotIn("replaced_rows", result)
        saved_rows = replace.call_args.kwargs["rows"]
        self.assertEqual([row["name"] for row in saved_rows], ["Warmup", "Work", "Extra"])
        self.assertEqual(saved_rows[1]["duration"]["value"], "15:00")
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

    def test_row_operations_bind_to_original_rows_and_preserve_insert_order(self) -> None:
        rows = [
            SERVICE._designer_row_from_input(
                {"name": name, "duration_seconds": 60, "power": 100}, sequence=index
            )
            for index, name in enumerate(("A", "B", "C"))
        ]
        result = SERVICE._apply_workout_row_operations(rows, [
            {
                "method": "insert", "after_row_number": 2, "name": "X",
                "duration_seconds": 60, "power": 100,
            },
            {
                "method": "insert", "after_row_number": 2, "name": "Y",
                "duration_seconds": 60, "power": 100,
            },
            {"method": "remove", "row_number": 2},
        ])
        self.assertEqual([row["name"] for row in result], ["A", "X", "Y", "C"])

    def test_row_operations_reject_conflicting_changes(self) -> None:
        rows = [SERVICE._designer_row_from_input(
            {"name": "A", "duration_seconds": 60, "power": 100}, sequence=0
        )]
        with self.assertRaisesRegex(ValueError, "Conflicting updates"):
            SERVICE._apply_workout_row_operations(rows, [
                {"method": "update", "row_number": 1, "power": 200},
                {"method": "update", "row_number": 1, "power": 210},
            ])

    def test_row_operations_merge_distinct_updates_for_one_original_step(self) -> None:
        rows = [SERVICE._designer_row_from_input(
            {"name": "A", "duration_seconds": 60, "power": 100}, sequence=0
        )]
        result = SERVICE._apply_workout_row_operations(rows, [
            {"method": "update", "row_number": 1, "power": 200},
            {"method": "update", "row_number": 1, "interval_count": 0},
        ])
        self.assertEqual(result[0]["power"]["value"], 200)
        self.assertEqual(result[0]["interval_count"], "0")

    def test_row_operations_reject_update_and_remove_of_same_original_step(self) -> None:
        rows = [SERVICE._designer_row_from_input(
            {"name": "A", "duration_seconds": 60, "power": 100}, sequence=0
        )]
        with self.assertRaisesRegex(ValueError, "Conflicting operations"):
            SERVICE._apply_workout_row_operations(rows, [
                {"method": "update", "row_number": 1, "power": 200},
                {"method": "remove", "row_number": 1},
            ])


if __name__ == "__main__":
    unittest.main()
