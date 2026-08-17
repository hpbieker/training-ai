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

    def test_date_bounded_tools_use_start_and_end_date_only(self):
        tools = {tool["name"]: tool for tool in self.service().list_tools()}
        for name in (
            "list_activities", "list_wellness", "list_events",
            "create_event", "update_event", "delete_event",
        ):
            properties = tools[name]["inputSchema"]["properties"]
            self.assertIn("start_date", properties)
            self.assertIn("end_date", properties)
            self.assertNotIn("since", properties)
            self.assertNotIn("until", properties)

        with self.assertRaisesRegex(MCP.ToolFailure, "Unsupported argument: since"):
            self.service().call_tool(
                "list_activities", {"since": "2026-08-17", "until": "2026-08-17"}
            )

    def test_list_activities_uses_inclusive_date_bounds(self):
        calls = []
        source = {
            "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
            "type": "Ride", "elapsed_time": 3600, "moving_time": 3590,
            "distance": 30000, "source": "GARMIN_CONNECT", "external_id": "g1",
            "icu_training_load": 55, "source_noise": "excluded",
        }
        service = self.service(activity_lister=lambda **kwargs: calls.append(kwargs) or [source])
        result = service.call_tool(
            "list_activities", {"start_date": "2026-08-17", "end_date": "2026-08-17"}
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["includeFields"], [])
        self.assertEqual(result["activities"][0], {
            "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
            "type": "Ride", "duration_s": 3600, "distance_m": 30000,
            "source": "GARMIN_CONNECT", "external_id": "g1",
        })
        self.assertEqual(calls[0]["oldest"].isoformat(), "2026-08-17")
        self.assertEqual(calls[0]["newest"].isoformat(), "2026-08-17")

    def test_list_activities_filters_sorts_and_limits_with_query_fields(self):
        rows = [
            {"id": "i1", "name": "Low", "max_heartrate": 160},
            {"id": "i2", "name": "High", "max_heartrate": 172},
            {"id": "i3", "name": "Middle", "max_heartrate": 168},
        ]
        result = self.service(activity_lister=lambda **kwargs: rows).call_tool(
            "list_activities",
            {
                "start_date": "2026-01-01", "end_date": "2026-08-17",
                "filters": [{"field": "max_heartrate", "op": "gt", "value": 165}],
                "sort": [{"field": "max_heartrate", "direction": "desc"}],
                "limit": 1,
            },
        )
        self.assertEqual([row["id"] for row in result["activities"]], ["i2"])
        self.assertEqual(result["source_count"], 3)
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["activities"][0]["max_heartrate"], 172)

    def test_search_wellness_and_events_support_general_queries(self):
        search = self.service(activity_searcher=lambda **kwargs: [
            {"id": "i1", "name": "VT1"}, {"id": "i2", "name": "VO2Max"},
        ]).call_tool("search_activities", {
            "query": "ride", "limit": 10,
            "filters": [{"field": "name", "op": "contains", "value": "vo2"}],
        })
        self.assertEqual([row["id"] for row in search["activities"]], ["i2"])
        self.assertTrue(search["source_limited"])

        wellness = self.service(wellness_lister=lambda **kwargs: [
            {"id": "2026-08-16", "fatigue": 1},
            {"id": "2026-08-17", "fatigue": 3},
        ]).call_tool("list_wellness", {
            "start_date": "2026-08-16", "end_date": "2026-08-17",
            "filters": [{"field": "fatigue", "op": "gte", "value": 2}],
        })
        self.assertEqual([row["id"] for row in wellness["wellness"]], ["2026-08-17"])

        events = self.service(event_lister=lambda **kwargs: [
            {"id": 1, "category": "NOTE"}, {"id": 2, "category": "SICK"},
        ]).call_tool("list_events", {
            "start_date": "2026-08-16", "end_date": "2026-08-17",
            "filters": [{"field": "category", "op": "eq", "value": "SICK"}],
        })
        self.assertEqual([row["id"] for row in events["events"]], [2])

    def test_list_activities_adds_only_requested_fields(self):
        service = self.service(activity_lister=lambda **kwargs: [{
            "id": "i1", "elapsed_time": 3600, "moving_time": 3590,
            "icu_training_load": 55, "stream_types": ["watts"],
        }])
        result = service.call_tool("list_activities", {
            "start_date": "2026-08-17", "end_date": "2026-08-17",
            "includeFields": ["icu_training_load", "stream_types"],
        })
        self.assertEqual(result["includeFields"], ["icu_training_load", "stream_types"])
        self.assertEqual(result["activities"][0]["icu_training_load"], 55)
        self.assertEqual(result["activities"][0]["stream_types"], ["watts"])
        self.assertNotIn("moving_time", result["activities"][0])

    def test_list_activities_rejects_invalid_include_fields(self):
        for include_fields, message in (
            (["unknown"], "Unsupported includeFields value"),
            (["moving_time", "moving_time"], "unique"),
            ("moving_time", "array of strings"),
        ):
            with self.subTest(include_fields=include_fields), self.assertRaisesRegex(
                MCP.ToolFailure, message
            ):
                self.service().call_tool("list_activities", {
                    "start_date": "2026-08-17", "end_date": "2026-08-17",
                    "includeFields": include_fields,
                })

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
        service.call_tool("list_activities", {"start_date": "2026-08-17", "end_date": "2026-08-17"})
        service.call_tool("list_activities", {"start_date": "2026-08-17", "end_date": "2026-08-17"})

        self.assertEqual(len(discoveries), 1)
        self.assertEqual([call["api_key"] for call in calls], ["cached-key", "cached-key"])

    def test_get_activity_returns_compact_summary_and_fetches_intervals(self):
        calls = []
        service = self.service(activity_getter=lambda **kwargs: calls.append(kwargs) or {
            "id": "i1", "name": "Ride", "icu_training_load": 99,
            "icu_intervals": [{"id": 1}], "source_private_field": "secret-noise",
        })
        result = service.call_tool("get_activity", {"activity_id": "i1"})
        self.assertEqual(
            result["activity"], {"id": "i1", "name": "Ride", "icu_training_load": 99}
        )
        self.assertNotIn("full_activity_file", result)
        self.assertTrue(calls[0]["include_intervals"])

    def test_get_activity_can_save_full_private_standard_envelope(self):
        source = {
            "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
            "icu_intervals": [{"id": 1}], "source_private_field": "retained-in-file",
        }
        result = self.service(activity_getter=lambda **kwargs: source).call_tool(
            "get_activity", {"activity_id": "i1", "save_full": True}
        )
        path = Path(result["full_activity_file"])
        try:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["full_activity_format"], "intervals-icu-activity-v1")
            self.assertEqual(result["full_activity_byte_size"], path.stat().st_size)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"activity_id": "i1", "activity": source},
            )
            self.assertNotIn("icu_intervals", result["activity"])
        finally:
            path.unlink(missing_ok=True)

    def test_get_activity_rejects_non_boolean_save_full(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "save_full must be a boolean"):
            self.service().call_tool(
                "get_activity", {"activity_id": "i1", "save_full": "yes"}
            )

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
        self.assertEqual([row["id"] for row in result["activities"]], ["i1", "i1", "i2"])
        self.assertEqual(result["includeFields"], [])
        self.assertEqual(result["count"], 3)

    def test_search_activities_supports_same_include_fields_as_list(self):
        service = self.service(
            activity_searcher=lambda **kwargs: [{"id": "i1", "icu_training_load": 42}]
        )
        result = service.call_tool(
            "search_activities", {"query": "tempo", "includeFields": ["icu_training_load"]}
        )
        self.assertEqual(result["activities"][0]["icu_training_load"], 42)

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
                "update_activity", {"activity_id": "i1", "updates": {"max_heartrate": 180}}
            )

    def test_update_activity_accepts_supported_metadata_and_ignore_fields(self):
        updates = {
            "description": "Corrected metadata",
            "tags": ["quality", "indoor"],
            "sub_type": "RACE",
            "icu_color": "#dd0447",
            "carbs_ingested": 90,
            "kg_lifted": 1250.5,
            "icu_ignore_time": False,
            "icu_ignore_hr": True,
            "icu_ignore_power": False,
            "ignore_velocity": True,
            "ignore_pace": False,
        }
        reads = [{"id": "i1"}, {"id": "i1", **updates}]
        writes = []
        service = self.service(
            activity_getter=lambda **kwargs: reads.pop(0),
            activity_updater=lambda **kwargs: writes.append(kwargs) or {},
        )
        result = service.call_tool(
            "update_activity", {"activity_id": "i1", "updates": updates}
        )
        self.assertEqual(writes[0]["updates"], updates)
        self.assertTrue(result["verified"])

    def test_update_activity_validates_new_field_types(self):
        invalid_updates = (
            ({"description": 3}, "description"),
            ({"tags": ["same", "same"]}, "tags"),
            ({"tags": [""]}, "tags"),
            ({"sub_type": "TRAINING"}, "sub_type"),
            ({"icu_color": ""}, "icu_color"),
            ({"carbs_ingested": 1.5}, "carbs_ingested"),
            ({"carbs_ingested": -1}, "carbs_ingested"),
            ({"kg_lifted": -0.1}, "kg_lifted"),
            ({"icu_ignore_hr": 1}, "icu_ignore_hr"),
        )
        for updates, field in invalid_updates:
            with self.subTest(updates=updates), self.assertRaisesRegex(
                MCP.ToolFailure, field
            ):
                self.service().call_tool(
                    "update_activity", {"activity_id": "i1", "updates": updates}
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
            "list_wellness", {"start_date": "2026-08-10", "end_date": "2026-08-17"}
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
            "list_events", {"start_date": "2026-08-17", "end_date": "2026-08-18"}
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
            {"category": "SICK", "name": "Syk", "start_date": "2026-08-17", "end_date": "2026-08-18"},
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
            {"category": "SICK", "name": "Syk", "start_date": "2026-08-17", "end_date": "2026-08-17"},
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
            {"event_id": 10, "category": "SICK", "name": "Syk", "start_date": "2026-08-17", "end_date": "2026-08-19"},
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
            {"event_id": 10, "start_date": "2026-08-17", "end_date": "2026-08-18", "confirm": 10},
        )
        self.assertEqual(deletes[0]["event_id"], 10)
        self.assertTrue(result["verified_deleted"])

    def test_delete_event_rejects_wrong_confirmation(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "confirm"):
            self.service().call_tool(
                "delete_event",
                {"event_id": 10, "start_date": "2026-08-17", "end_date": "2026-08-18", "confirm": 11},
            )

    def test_rejects_bad_dates_and_unknown_arguments(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "YYYY-MM-DD"):
            self.service().call_tool("list_activities", {"start_date": "bad", "end_date": "2026-08-17"})
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
