import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "intervals-icu"
SPEC = importlib.util.spec_from_file_location(
    "intervals_icu_mcp_under_test", PLUGIN_DIR / "intervals_icu_mcp.py"
)
assert SPEC is not None and SPEC.loader is not None
MCP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MCP)


class IntervalsIcuMcpTests(unittest.TestCase):
    def service(self, **overrides):
        defaults = {
            "credential_factory": lambda: MCP.IntervalsIcuCredentials(api_key="secret"),
            "activity_lister": lambda **kwargs: [{"id": "i1"}, {"id": "i2"}],
            "activity_searcher": lambda **kwargs: [{"id": "i1"}, {"id": "i1"}],
            "activity_getter": lambda **kwargs: {"id": kwargs["activity_id"]},
            "streams_downloader": self._write_streams,
            "activity_file_downloader": self._write_activity_file,
            "activity_updater": lambda **kwargs: kwargs["updates"],
            "activity_deleter": lambda **kwargs: {"id": kwargs["activity_id"]},
            "activity_uploader": lambda **kwargs: {"id": "i-uploaded"},
            "wellness_lister": lambda **kwargs: [{"id": "2026-08-17", "soreness": 2}],
            "wellness_getter": lambda **kwargs: {},
            "wellness_updater": lambda **kwargs: kwargs["updates"],
            "event_lister": lambda **kwargs: [],
            "event_creator": lambda **kwargs: kwargs["event"] | {"id": 10},
            "event_updater": lambda **kwargs: kwargs["updates"] | {"id": kwargs["event_id"]},
            "event_deleter": lambda **kwargs: {"id": kwargs["event_id"]},
        }
        defaults.update(overrides)
        return MCP.IntervalsIcuToolService(**defaults)

    @staticmethod
    def _write_streams(**kwargs):
        path = Path(kwargs["output_path"])
        path.write_text("secs,watts\n0,200\n", encoding="utf-8")
        return path

    @staticmethod
    def _write_activity_file(**kwargs):
        directory = Path(kwargs["output_path"])
        path = directory / f"{kwargs['activity_id']}.{('fit' if kwargs['kind'] == 'fit' else 'bin')}"
        path.write_bytes(b"activity-file")
        return path

    def test_advertises_exactly_fourteen_tools(self):
        self.assertEqual(
            [tool["name"] for tool in self.service().list_tools()],
            [
                "list_activities", "search_activities", "get_activity",
                "get_activity_streams", "get_activity_file", "update_activity",
                "delete_activity", "upload_activity", "list_wellness", "update_wellness",
                "list_events", "create_event", "update_event", "delete_event",
            ],
        )

    def test_list_activities_uses_inclusive_date_bounds(self):
        calls = []
        service = self.service(activity_lister=lambda **kwargs: calls.append(kwargs) or [{"id": "i1"}])
        result = service.call_tool(
            "list_activities", {"since": "2026-08-17", "until": "2026-08-17"}
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(calls[0]["oldest"].isoformat(), "2026-08-17")
        self.assertEqual(calls[0]["newest"].isoformat(), "2026-08-17")

    def test_authentication_is_discovered_once_and_reused(self):
        discoveries = []
        calls = []

        def discover():
            discoveries.append(True)
            return MCP.IntervalsIcuCredentials(api_key="cached-key")

        service = self.service(
            credential_factory=discover,
            activity_lister=lambda **kwargs: calls.append(kwargs) or [],
        )
        service.call_tool("list_activities", {"since": "2026-08-17", "until": "2026-08-17"})
        service.call_tool("list_activities", {"since": "2026-08-17", "until": "2026-08-17"})

        self.assertEqual(len(discoveries), 1)
        self.assertEqual([call["api_key"] for call in calls], ["cached-key", "cached-key"])

    def test_get_activity_defaults_to_intervals(self):
        calls = []
        service = self.service(activity_getter=lambda **kwargs: calls.append(kwargs) or {"id": "i1"})
        result = service.call_tool("get_activity", {"activity_id": "i1"})
        self.assertTrue(result["include_intervals"])
        self.assertTrue(calls[0]["include_intervals"])

    def test_search_activities_is_one_source_call_and_preserves_duplicates(self):
        calls = []
        source_rows = [{"id": "i1"}, {"id": "i1"}, {"id": "i2"}]
        service = self.service(
            activity_searcher=lambda **kwargs: calls.append(kwargs) or source_rows
        )
        result = service.call_tool("search_activities", {"query": "#VT2", "limit": 20})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["query"], "#VT2")
        self.assertEqual(calls[0]["limit"], 20)
        self.assertEqual(result["activities"], source_rows)
        self.assertEqual(result["count"], 3)

    def test_search_activities_defaults_limit_and_rejects_invalid_limit(self):
        calls = []
        service = self.service(activity_searcher=lambda **kwargs: calls.append(kwargs) or [])
        result = service.call_tool("search_activities", {"query": "VT2"})
        self.assertEqual(result["limit"], 10)
        self.assertEqual(calls[0]["limit"], 10)
        for value in (0, -1, True, "10"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(MCP.ToolFailure, "positive integer"):
                    service.call_tool("search_activities", {"query": "VT2", "limit": value})

    def test_streams_are_private_file_and_not_inline(self):
        result = self.service().call_tool("get_activity_streams", {"activity_id": "i1"})
        path = Path(result["streams_file"])
        try:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["byte_size"], path.stat().st_size)
            self.assertNotIn("streams", result)
        finally:
            path.unlink(missing_ok=True)

    def test_activity_file_is_private_and_excludes_web_original(self):
        result = self.service().call_tool(
            "get_activity_file", {"activity_id": "i1", "kind": "fit"}
        )
        path = Path(result["file_path"])
        try:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["byte_size"], len(b"activity-file"))
        finally:
            path.unlink(missing_ok=True)
            path.parent.rmdir()
        with self.assertRaisesRegex(MCP.ToolFailure, "original.*fit"):
            self.service().call_tool(
                "get_activity_file", {"activity_id": "i1", "kind": "web-original"}
            )

    def test_update_activity_is_patch_based_and_verified(self):
        reads = [
            {"id": "i1", "name": "Old", "feel": None},
            {"id": "i1", "name": "New", "feel": None},
        ]
        writes = []
        service = self.service(
            activity_getter=lambda **kwargs: reads.pop(0),
            activity_updater=lambda **kwargs: writes.append(kwargs) or {},
        )
        result = service.call_tool(
            "update_activity",
            {"activity_id": "i1", "updates": {"name": "New"}, "confirm_overwrite": True},
        )
        self.assertEqual(writes[0]["updates"], {"name": "New"})
        self.assertEqual(result["overwritten_fields"], ["name"])
        self.assertTrue(result["verified"])

    def test_update_activity_requires_confirmation_and_rejects_unknown_fields(self):
        service = self.service(activity_getter=lambda **kwargs: {"name": "Old"})
        with self.assertRaisesRegex(MCP.ToolFailure, "without confirmation"):
            service.call_tool(
                "update_activity", {"activity_id": "i1", "updates": {"name": "New"}}
            )
        with self.assertRaisesRegex(MCP.ToolFailure, "Unsupported activity field"):
            service.call_tool(
                "update_activity", {"activity_id": "i1", "updates": {"description": "x"}}
            )

    def test_update_activity_accepts_numeric_feel_scale_only(self):
        reads = [
            {"id": "i1", "feel": None},
            {"id": "i1", "feel": 1},
        ]
        service = self.service(
            activity_getter=lambda **kwargs: reads.pop(0),
            activity_updater=lambda **kwargs: {},
        )
        result = service.call_tool(
            "update_activity", {"activity_id": "i1", "updates": {"feel": 1}}
        )
        self.assertEqual(result["after"]["feel"], 1)
        for invalid in (0, 6, "strong", True):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                MCP.ToolFailure, "integer from 1 to 5"
            ):
                self.service().call_tool(
                    "update_activity", {"activity_id": "i1", "updates": {"feel": invalid}}
                )

    def test_delete_activity_confirms_and_verifies_direct_and_list_absence(self):
        reads = [
            {"id": "i1", "start_date_local": "2026-08-17T10:00:00"},
            RuntimeError("Intervals.icu request failed: HTTP 404 Not Found"),
        ]

        def getter(**kwargs):
            value = reads.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        service = self.service(
            activity_getter=getter,
            activity_lister=lambda **kwargs: [],
        )
        result = service.call_tool(
            "delete_activity", {"activity_id": "i1", "confirm": "i1"}
        )
        self.assertTrue(result["verified_deleted"])

    def test_upload_activity_verifies_returned_id_and_date_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            file_path = Path(temporary) / "ride.fit"
            file_path.write_bytes(b"fit")
            service = self.service(
                activity_getter=lambda **kwargs: {
                    "id": "i-uploaded", "start_date_local": "2026-08-17T10:00:00"
                },
                activity_lister=lambda **kwargs: [{"id": "i-uploaded"}],
            )
            result = service.call_tool("upload_activity", {"file_path": str(file_path)})
        self.assertEqual(result["activity_id"], "i-uploaded")
        self.assertTrue(result["verified"])

    def test_list_wellness_uses_inclusive_date_bounds(self):
        calls = []
        service = self.service(
            wellness_lister=lambda **kwargs: calls.append(kwargs) or [{"id": "2026-08-17"}]
        )
        result = service.call_tool(
            "list_wellness", {"since": "2026-08-10", "until": "2026-08-17"}
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(calls[0]["oldest"].isoformat(), "2026-08-10")
        self.assertEqual(calls[0]["newest"].isoformat(), "2026-08-17")

    def test_update_wellness_applies_only_explicit_updates_and_verifies(self):
        reads = [
            {"id": "2026-08-17", "soreness": None, "fatigue": 2, "motivation": 3},
            {"id": "2026-08-17", "soreness": 1, "fatigue": 2, "motivation": 3},
        ]
        writes = []
        service = self.service(
            wellness_getter=lambda **kwargs: reads.pop(0),
            wellness_updater=lambda **kwargs: writes.append(kwargs) or {},
        )
        result = service.call_tool(
            "update_wellness",
            {"date": "2026-08-17", "updates": {"soreness": 1}},
        )
        self.assertEqual(writes[0]["updates"], {"soreness": 1})
        self.assertEqual(result["updates"], {"soreness": 1})
        self.assertEqual(result["overwritten_fields"], [])
        self.assertTrue(result["verified"])

    def test_update_wellness_requires_confirmation_for_conflicts(self):
        writes = []
        service = self.service(
            wellness_getter=lambda **kwargs: {"soreness": 2},
            wellness_updater=lambda **kwargs: writes.append(kwargs) or {},
        )
        with self.assertRaisesRegex(MCP.ToolFailure, "without confirmation") as raised:
            service.call_tool(
                "update_wellness",
                {"date": "2026-08-17", "updates": {"soreness": 3}},
            )
        self.assertEqual(raised.exception.code, "overwrite_confirmation_required")
        self.assertEqual(writes, [])

    def test_update_wellness_supports_all_current_fields(self):
        requested = {
            "soreness": 2, "fatigue": 1, "motivation": 3,
            "comments": "Heavy legs",
        }
        reads = [{}, dict(requested)]
        service = self.service(wellness_getter=lambda **kwargs: reads.pop(0))
        result = service.call_tool(
            "update_wellness", {"date": "2026-08-17", "updates": requested}
        )
        self.assertEqual(result["after"], requested)

    def test_update_wellness_rejects_unknown_and_invalid_fields(self):
        service = self.service()
        invalid_updates = (
            {}, {"stress": 2}, {"soreness": 5}, {"fatigue": True},
            {"motivation": 0}, {"comments": 3},
        )
        for updates in invalid_updates:
            with self.subTest(updates=updates):
                with self.assertRaises(MCP.ToolFailure):
                    service.call_tool(
                        "update_wellness",
                        {"date": "2026-08-17", "updates": updates},
                    )

    def test_list_events_lists_all_categories(self):
        calls = []
        service = self.service(
            event_lister=lambda **kwargs: calls.append(kwargs) or [{"id": 10, "category": "SICK"}]
        )
        result = service.call_tool(
            "list_events", {"since": "2026-08-17", "until": "2026-08-18"}
        )
        self.assertEqual(result["count"], 1)
        self.assertIsNone(calls[0]["categories"])

    def test_create_sick_event_uses_exclusive_end_and_verifies(self):
        writes = []
        expected = {
            "id": 10, "category": "SICK", "name": "Syk",
            "start_date_local": "2026-08-17T00:00:00",
            "end_date_local": "2026-08-19T00:00:00",
        }
        reads = [[], [expected]]
        service = self.service(
            event_lister=lambda **kwargs: reads.pop(0),
            event_creator=lambda **kwargs: writes.append(kwargs) or expected,
        )
        result = service.call_tool(
            "create_event",
            {"category": "SICK", "name": "Syk", "since": "2026-08-17", "until": "2026-08-18"},
        )
        self.assertEqual(writes[0]["event"]["end_date_local"], "2026-08-19T00:00:00")
        self.assertEqual(result["stored_end_exclusive"], "2026-08-19")
        self.assertTrue(result["verified"])

    def test_create_event_returns_unchanged_for_exact_existing_event(self):
        existing = {
            "id": 10, "category": "SICK", "name": "Syk",
            "start_date_local": "2026-08-17T00:00:00",
            "end_date_local": "2026-08-18T00:00:00",
        }
        writes = []
        service = self.service(
            event_lister=lambda **kwargs: [existing],
            event_creator=lambda **kwargs: writes.append(kwargs) or {},
        )
        result = service.call_tool(
            "create_event",
            {"category": "SICK", "name": "Syk", "since": "2026-08-17", "until": "2026-08-17"},
        )
        self.assertEqual(result["action"], "unchanged")
        self.assertEqual(writes, [])

    def test_update_event_replaces_all_day_state_and_verifies_by_id(self):
        writes = []
        expected = {
            "id": 10, "category": "SICK", "name": "Syk",
            "start_date_local": "2026-08-17T00:00:00",
            "end_date_local": "2026-08-20T00:00:00",
        }
        service = self.service(
            event_lister=lambda **kwargs: [expected],
            event_updater=lambda **kwargs: writes.append(kwargs) or expected,
        )
        result = service.call_tool(
            "update_event",
            {"event_id": 10, "category": "SICK", "name": "Syk", "since": "2026-08-17", "until": "2026-08-19"},
        )
        self.assertEqual(writes[0]["updates"]["end_date_local"], "2026-08-20T00:00:00")
        self.assertEqual(result["verified_event"]["id"], 10)

    def test_delete_event_reads_confirms_and_verifies_absence(self):
        existing = {"id": 10, "category": "SICK"}
        reads = [[existing], []]
        deletes = []
        service = self.service(
            event_lister=lambda **kwargs: reads.pop(0),
            event_deleter=lambda **kwargs: deletes.append(kwargs) or {"id": 10},
        )
        result = service.call_tool(
            "delete_event",
            {"event_id": 10, "since": "2026-08-17", "until": "2026-08-18", "confirm": 10},
        )
        self.assertEqual(deletes[0]["event_id"], 10)
        self.assertTrue(result["verified_deleted"])

    def test_delete_event_rejects_wrong_confirmation(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "confirm"):
            self.service().call_tool(
                "delete_event",
                {"event_id": 10, "since": "2026-08-17", "until": "2026-08-18", "confirm": 11},
            )

    def test_rejects_bad_dates_and_unknown_arguments(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "YYYY-MM-DD"):
            self.service().call_tool("list_activities", {"since": "bad", "until": "2026-08-17"})
        with self.assertRaisesRegex(MCP.ToolFailure, "Unsupported argument"):
            self.service().call_tool("get_activity", {"activity_id": "i1", "extra": True})


class IntervalsIcuMcpHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_initialize_and_list_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "./intervals_icu_mcp.py"],
            cwd=str(PLUGIN_DIR),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()

        self.assertEqual(
            [tool.name for tool in result.tools],
            [
                "list_activities", "search_activities", "get_activity",
                "get_activity_streams", "get_activity_file", "update_activity",
                "delete_activity", "upload_activity", "list_wellness", "update_wellness",
                "list_events", "create_event", "update_event", "delete_event",
            ],
        )


class IntervalsIcuConfigTests(unittest.TestCase):
    def setUp(self):
        self.original_environment = {
            name: os.environ.pop(name, None)
            for name in ("INTERVALS_ICU_API_KEY",)
        }

    def tearDown(self):
        for name, value in self.original_environment.items():
            if value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)

    def test_reads_user_owned_json_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps({"apiKey": "from-file"}), encoding="utf-8")
            credentials = MCP.discover_intervals_icu_credentials(path)
            self.assertEqual(credentials.api_key, "from-file")

    def test_environment_overrides_config(self):
        os.environ["INTERVALS_ICU_API_KEY"] = "from-environment"
        credentials = MCP.discover_intervals_icu_credentials("/missing/config.json")
        self.assertEqual(credentials.api_key, "from-environment")

    def test_rejects_non_api_key_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(
                json.dumps({"bearerToken": "token", "cookie": "session-cookie"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Unknown setting"):
                MCP.discover_intervals_icu_credentials(path)

    def test_delete_event_uses_documented_delete_endpoint(self):
        globals_dict = MCP.delete_event.__globals__
        original = globals_dict["_request_bytes"]
        calls = []
        globals_dict["_request_bytes"] = lambda path, credentials, **kwargs: calls.append(
            (path, kwargs)
        ) or b""
        try:
            result = MCP.delete_event(event_id=123, api_key="secret")
        finally:
            globals_dict["_request_bytes"] = original
        self.assertEqual(calls, [("/athlete/0/events/123", {"method": "DELETE"})])
        self.assertEqual(result, {"id": 123})


if __name__ == "__main__":
    unittest.main()
