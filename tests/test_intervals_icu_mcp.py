import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "intervals-icu"
SPEC = importlib.util.spec_from_file_location(
    "intervals_icu_mcp_under_test", PLUGIN_DIR / "intervals_icu_mcp.py"
)
assert SPEC is not None and SPEC.loader is not None
MCP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MCP)
API = sys.modules["intervals_icu_api"]


class IntervalsIcuMcpTests(unittest.TestCase):
    def service(self, **overrides):
        defaults = {
            "credential_factory": lambda: MCP.IntervalsIcuCredentials(api_key="secret"),
            "athlete_lister": lambda **kwargs: [
                {"id": "i-me", "name": "Me"},
                {"id": "i-other", "name": "Other", "icu_tags": ["Coaching"]},
            ],
            "activity_lister": lambda **kwargs: [{"id": "i1"}, {"id": "i2"}],
            "activity_power_curve_lister": lambda **kwargs: {
                "secs": list(kwargs["secs"]),
                "curves": [{"id": "i1", "watts": [900]}],
            },
            "activity_hr_curve_lister": lambda **kwargs: {"secs": list(kwargs["secs"]), "curves": []},
            "activity_pace_curve_lister": lambda **kwargs: {"distances": list(kwargs["distances"]), "curves": []},
            "activity_searcher": lambda **kwargs: [{"id": "i1"}, {"id": "i1"}],
            "activity_interval_searcher": lambda **kwargs: [],
            "sport_settings_lister": lambda **kwargs: [],
            "activity_getter": lambda **kwargs: {"id": kwargs["activity_id"]},
            "activities_getter": lambda **kwargs: [
                {"id": activity_id} for activity_id in kwargs["activity_ids"]
            ],
            "streams_downloader": self._write_streams,
            "activity_file_downloader": self._write_activity_file,
            "activity_updater": lambda **kwargs: kwargs["updates"],
            "activity_deleter": lambda **kwargs: {"id": kwargs["activity_id"]},
            "activity_uploader": lambda **kwargs: {"id": "i-uploaded"},
            "activity_message_lister": lambda **kwargs: [],
            "training_plan_getter": lambda **kwargs: {},
            "athlete_summary_getter": lambda **kwargs: [],
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

    def test_advertises_exactly_twenty_five_tools(self):
        self.assertEqual(
            [tool["name"] for tool in self.service().list_tools()],
            [
                "list_athletes",
                "list_activities", "list_activity_power_curves", "list_activity_hr_curves",
                "list_activity_pace_curves", "search_activity_intervals", "list_sport_settings",
                "search_activities", "get_activity",
                "get_activities",
                "get_activity_streams", "get_activity_file", "update_activity",
                "delete_activity", "delete_activities", "upload_activity",
                "list_activity_messages", "get_training_plan", "get_athlete_summary",
                "list_wellness", "update_wellness",
                "list_events", "create_event", "update_event", "delete_event",
            ],
        )

    def test_list_athletes_returns_compact_accessible_rows(self):
        result = self.service().call_tool("list_athletes", {})
        self.assertEqual(result, {
            "count": 2,
            "athletes": [
                {"id": "i-me", "name": "Me"},
                {"id": "i-other", "name": "Other", "tags": ["Coaching"]},
            ],
        })

    def test_activity_tools_default_to_me_without_athlete_in_response(self):
        list_calls = []
        get_calls = []
        stream_calls = []
        service = self.service(
            activity_lister=lambda **kwargs: list_calls.append(kwargs) or [],
            activity_getter=lambda **kwargs: get_calls.append(kwargs) or {"id": kwargs["activity_id"]},
            streams_downloader=lambda **kwargs: stream_calls.append(kwargs) or self._write_streams(**kwargs),
        )
        listed = service.call_tool("list_activities", {
            "start_date": "2026-08-28", "end_date": "2026-08-28",
        })
        fetched = service.call_tool("get_activity", {"activity_id": "i1"})
        streamed = service.call_tool("get_activity_streams", {"activity_id": "i1"})
        self.assertEqual(list_calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", listed)
        self.assertNotIn("athlete", fetched)
        self.assertNotIn("athlete", streamed)
        self.assertNotIn("athlete_id", get_calls[0])
        self.assertNotIn("athlete_id", stream_calls[0])

    def test_activity_tools_include_explicit_non_default_athlete(self):
        calls = []
        service = self.service(activity_lister=lambda **kwargs: calls.append(kwargs) or [])
        listed = service.call_tool("list_activities", {
            "athlete": "i-other",
            "start_date": "2026-08-28", "end_date": "2026-08-28",
        })
        fetched = service.call_tool("get_activity", {
            "athlete": "i-other", "activity_id": "i1",
        })
        streamed = service.call_tool("get_activity_streams", {
            "athlete": "i-other", "activity_id": "i1",
        })
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        for result in (listed, fetched, streamed):
            self.assertEqual(result["athlete"], {
                "id": "i-other", "name": "Other", "tags": ["Coaching"],
            })

    def test_explicit_me_and_zero_remain_implicit(self):
        for athlete in ("me", 0, "0"):
            with self.subTest(athlete=athlete):
                result = self.service().call_tool("list_activities", {
                    "athlete": athlete,
                    "start_date": "2026-08-28", "end_date": "2026-08-28",
                })
                self.assertNotIn("athlete", result)

    def test_rejects_inaccessible_athlete(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "not accessible"):
            self.service().call_tool("get_activity", {
                "athlete": "i-unknown", "activity_id": "i1",
            })

    def test_rejects_boolean_athlete(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "athlete must"):
            self.service().call_tool("get_activity", {
                "athlete": False, "activity_id": "i1",
            })

    def test_list_activity_power_curves_defaults_to_me(self):
        calls = []
        service = self.service(
            activity_power_curve_lister=lambda **kwargs: calls.append(kwargs) or {
                "secs": [1, 5],
                "curves": [{"id": "i1", "watts": [1000, 900]}],
            }
        )
        result = service.call_tool("list_activity_power_curves", {
            "start_date": "2026-08-01", "end_date": "2026-08-17", "secs": [1, 5],
        })
        self.assertEqual(calls[0]["oldest"].isoformat(), "2026-08-01")
        self.assertEqual(calls[0]["newest"].isoformat(), "2026-08-17")
        self.assertEqual(calls[0]["secs"], (1, 5))
        self.assertEqual(calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", result)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["curves"][0]["watts"], [1000, 900])

    def test_list_activity_power_curves_validates_secs(self):
        service = self.service()
        for secs in ([], [0], [1, 1], [True], "1"):
            with self.subTest(secs=secs), self.assertRaises(MCP.ToolFailure):
                service.call_tool("list_activity_power_curves", {
                    "start_date": "2026-08-01", "end_date": "2026-08-17", "secs": secs,
                })

    def test_power_curves_include_explicit_non_default_athlete(self):
        calls = []
        result = self.service(
            activity_power_curve_lister=lambda **kwargs: calls.append(kwargs) or {
                "secs": [60], "curves": [],
            }
        ).call_tool("list_activity_power_curves", {
            "athlete": "i-other", "start_date": "2026-08-01",
            "end_date": "2026-08-17", "secs": [60],
        })
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        self.assertEqual(result["athlete"]["id"], "i-other")

    def test_list_activity_hr_and_pace_curves_pass_explicit_values(self):
        hr_calls = []
        pace_calls = []
        service = self.service(
            activity_hr_curve_lister=lambda **kwargs: hr_calls.append(kwargs) or {
                "secs": [30, 60], "curves": [{"id": "i1", "bpm": [170, 165]}],
            },
            activity_pace_curve_lister=lambda **kwargs: pace_calls.append(kwargs) or {
                "distances": [1000, 5000], "curves": [{"id": "i2", "times": [220, 1200]}],
            },
        )
        hr = service.call_tool("list_activity_hr_curves", {
            "start_date": "2026-08-01", "end_date": "2026-08-17", "secs": [30, 60],
        })
        pace = service.call_tool("list_activity_pace_curves", {
            "start_date": "2026-08-01", "end_date": "2026-08-17",
            "distances": [1000, 5000],
        })
        self.assertEqual(hr_calls[0]["secs"], (30, 60))
        self.assertEqual(pace_calls[0]["distances"], (1000, 5000))
        self.assertEqual(hr_calls[0]["athlete_id"], 0)
        self.assertEqual(pace_calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", hr)
        self.assertNotIn("athlete", pace)
        self.assertEqual(hr["count"], 1)
        self.assertEqual(pace["count"], 1)

    def test_hr_and_pace_curves_include_explicit_non_default_athlete(self):
        hr_calls = []
        pace_calls = []
        service = self.service(
            activity_hr_curve_lister=lambda **kwargs: hr_calls.append(kwargs) or {
                "secs": [60], "curves": [],
            },
            activity_pace_curve_lister=lambda **kwargs: pace_calls.append(kwargs) or {
                "distances": [1000], "curves": [],
            },
        )
        hr = service.call_tool("list_activity_hr_curves", {
            "athlete": "i-other", "start_date": "2026-08-01",
            "end_date": "2026-08-17", "secs": [60],
        })
        pace = service.call_tool("list_activity_pace_curves", {
            "athlete": "i-other", "start_date": "2026-08-01",
            "end_date": "2026-08-17", "distances": [1000],
        })
        self.assertEqual(hr_calls[0]["athlete_id"], "i-other")
        self.assertEqual(pace_calls[0]["athlete_id"], "i-other")
        self.assertEqual(hr["athlete"]["id"], "i-other")
        self.assertEqual(pace["athlete"]["id"], "i-other")

    def test_activity_curve_tools_validate_values(self):
        for tool, key, value in (
            ("list_activity_hr_curves", "secs", []),
            ("list_activity_hr_curves", "secs", [True]),
            ("list_activity_pace_curves", "distances", [0]),
            ("list_activity_pace_curves", "distances", [1000, 1000]),
        ):
            with self.subTest(tool=tool, value=value), self.assertRaises(MCP.ToolFailure):
                self.service().call_tool(tool, {
                    "start_date": "2026-08-01", "end_date": "2026-08-17", key: value,
                })

    def test_search_activity_intervals_passes_bounds_and_returns_compact_rows(self):
        calls = []
        source = [{
            "id": "i1", "name": "5x5", "start_date_local": "2026-08-10T10:00:00",
            "icu_training_load": 90, "source_noise": "excluded",
        }]
        result = self.service(
            activity_interval_searcher=lambda **kwargs: calls.append(kwargs) or source
        ).call_tool("search_activity_intervals", {
            "min_secs": 280, "max_secs": 320,
            "min_intensity": 105, "max_intensity": 120,
            "interval_type": "POWER", "min_reps": 4, "max_reps": 6,
            "limit": 20, "includeFields": ["icu_training_load"],
        })
        self.assertEqual(calls[0]["interval_type"], "POWER")
        self.assertEqual(calls[0]["min_reps"], 4)
        self.assertEqual(calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", result)
        self.assertEqual(result["activities"], [{
            "id": "i1", "name": "5x5", "start_date_local": "2026-08-10T10:00:00",
            "icu_training_load": 90,
        }])

    def test_search_activity_intervals_validates_bounds(self):
        base = {"min_secs": 300, "max_secs": 300, "min_intensity": 100, "max_intensity": 110}
        for updates, message in (
            ({"min_secs": 0}, "positive"),
            ({"max_secs": 299}, "max_secs"),
            ({"min_intensity": -1}, "non-negative"),
            ({"max_intensity": 99}, "max_intensity"),
            ({"min_reps": 3, "max_reps": 2}, "max_reps"),
            ({"interval_type": "CADENCE"}, "interval_type"),
        ):
            with self.subTest(updates=updates), self.assertRaisesRegex(MCP.ToolFailure, message):
                self.service().call_tool("search_activity_intervals", base | updates)

    def test_list_sport_settings_defaults_to_me_without_athlete_in_response(self):
        calls = []
        source = [{
            "id": 1, "types": ["Ride", "VirtualRide"], "ftp": 300,
            "lthr": 170, "power_zones": [55, 75, 90, 105, 120],
        }]
        result = self.service(
            sport_settings_lister=lambda **kwargs: calls.append(kwargs) or source
        ).call_tool("list_sport_settings", {})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["athlete_id"], 0)
        self.assertEqual(result, {"count": 1, "settings": source})

    def test_interval_search_and_sport_settings_include_explicit_athlete(self):
        interval_calls = []
        setting_calls = []
        service = self.service(
            activity_interval_searcher=lambda **kwargs: interval_calls.append(kwargs) or [],
            sport_settings_lister=lambda **kwargs: setting_calls.append(kwargs) or [],
        )
        searched = service.call_tool("search_activity_intervals", {
            "athlete": "i-other", "min_secs": 300, "max_secs": 300,
            "min_intensity": 100, "max_intensity": 110,
        })
        settings = service.call_tool("list_sport_settings", {"athlete": "i-other"})
        self.assertEqual(interval_calls[0]["athlete_id"], "i-other")
        self.assertEqual(setting_calls[0]["athlete_id"], "i-other")
        self.assertEqual(searched["athlete"]["id"], "i-other")
        self.assertEqual(settings["athlete"]["id"], "i-other")

    def test_date_bounded_tools_use_start_and_end_date_only(self):
        tools = {tool["name"]: tool for tool in self.service().list_tools()}
        for name in (
            "list_activities", "get_athlete_summary", "list_wellness", "list_events",
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
            "created": "2026-08-17T12:00:00Z",
        }])
        result = service.call_tool("list_activities", {
            "start_date": "2026-08-17", "end_date": "2026-08-17",
            "includeFields": ["icu_training_load", "stream_types", "created"],
        })
        self.assertEqual(
            result["includeFields"], ["icu_training_load", "stream_types", "created"]
        )
        self.assertEqual(result["activities"][0]["icu_training_load"], 55)
        self.assertEqual(result["activities"][0]["stream_types"], ["watts"])
        self.assertEqual(result["activities"][0]["created"], "2026-08-17T12:00:00Z")
        self.assertNotIn("moving_time", result["activities"][0])

    def test_list_activities_filters_and_sorts_by_created(self):
        rows = [
            {"id": "i1", "name": "Older", "created": "2026-08-17T12:00:00Z"},
            {"id": "i2", "name": "Newest", "created": "2026-08-18T08:00:00Z"},
            {"id": "i3", "name": "Oldest", "created": "2026-08-16T09:00:00Z"},
        ]
        result = self.service(activity_lister=lambda **kwargs: rows).call_tool(
            "list_activities",
            {
                "start_date": "2026-08-16", "end_date": "2026-08-18",
                "filters": [{
                    "field": "created", "op": "gte", "value": "2026-08-17T00:00:00Z",
                }],
                "sort": [{"field": "created", "direction": "desc"}],
            },
        )
        self.assertEqual([row["id"] for row in result["activities"]], ["i2", "i1"])
        self.assertEqual(
            [row["created"] for row in result["activities"]],
            ["2026-08-18T08:00:00Z", "2026-08-17T12:00:00Z"],
        )

    def test_list_activities_adds_old_default_fields_only_when_requested(self):
        service = self.service(activity_lister=lambda **kwargs: [{
            "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
            "type": "Ride", "elapsed_time": 3600, "distance": 30000,
            "source": "GARMIN_CONNECT", "external_id": "g1",
        }])
        result = service.call_tool("list_activities", {
            "start_date": "2026-08-17", "end_date": "2026-08-17",
            "includeFields": ["type", "duration_s", "distance_m", "source", "external_id"],
        })
        self.assertEqual(result["activities"][0], {
            "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
            "type": "Ride", "duration_s": 3600, "distance_m": 30000,
            "source": "GARMIN_CONNECT", "external_id": "g1",
        })

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
            result["activity"], {"id": "i1", "name": "Ride", "start_date_local": None}
        )
        self.assertEqual(result["includeFields"], [])
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

    def test_get_activities_returns_compact_summaries_in_one_source_call(self):
        calls = []
        source = [
            {"id": "i2", "name": "Run", "icu_training_load": 40, "source_noise": "excluded"},
            {"id": "i1", "name": "Ride", "icu_training_load": 50, "icu_intervals": [{"id": 1}]},
        ]
        result = self.service(
            activities_getter=lambda **kwargs: calls.append(kwargs) or source
        ).call_tool("get_activities", {
            "activity_ids": ["i1", "i2"], "includeFields": ["icu_training_load"],
        })
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["activity_ids"], ["i1", "i2"])
        self.assertTrue(calls[0]["include_intervals"])
        self.assertEqual(calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", result)
        self.assertEqual(result["activity_ids"], ["i1", "i2"])
        self.assertEqual(result["includeFields"], ["icu_training_load"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["activities"], [
            {"id": "i1", "name": "Ride", "start_date_local": None, "icu_training_load": 50},
            {"id": "i2", "name": "Run", "start_date_local": None, "icu_training_load": 40},
        ])

    def test_get_activities_includes_explicit_non_default_athlete(self):
        calls = []
        result = self.service(
            activities_getter=lambda **kwargs: calls.append(kwargs) or [{"id": "i1"}]
        ).call_tool("get_activities", {
            "athlete": "i-other", "activity_ids": ["i1"],
        })
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        self.assertEqual(result["athlete"], {
            "id": "i-other", "name": "Other", "tags": ["Coaching"],
        })

    def test_get_activity_include_fields_only_changes_inline_summary(self):
        source = {
            "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
            "icu_training_load": 99, "created": "2026-08-17T12:00:00Z",
            "source_private_field": "retained-in-file",
        }
        result = self.service(activity_getter=lambda **kwargs: source).call_tool(
            "get_activity", {
                "activity_id": "i1", "includeFields": ["created"], "save_full": True,
            }
        )
        path = Path(result["full_activity_file"])
        try:
            self.assertEqual(result["includeFields"], ["created"])
            self.assertEqual(result["activity"], {
                "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
                "created": "2026-08-17T12:00:00Z",
            })
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["activity"], source
            )
        finally:
            path.unlink(missing_ok=True)

    def test_get_activities_can_save_full_private_batch_envelope(self):
        source = [{"id": "i2"}, {"id": "i1", "icu_intervals": [{"id": 1}]}]
        ordered = [source[1], source[0]]
        result = self.service(activities_getter=lambda **kwargs: source).call_tool(
            "get_activities", {"activity_ids": ["i1", "i2"], "save_full": True}
        )
        path = Path(result["full_activities_file"])
        try:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["full_activities_format"], "intervals-icu-activities-v1")
            self.assertEqual(result["full_activities_byte_size"], path.stat().st_size)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "activity_ids": ["i1", "i2"], "activities": ordered,
            })
        finally:
            path.unlink(missing_ok=True)

    def test_get_activities_validates_ids_and_save_full(self):
        for arguments, message in (
            ({"activity_ids": []}, "non-empty array"),
            ({"activity_ids": ["i1", ""]}, "non-empty array"),
            ({"activity_ids": ["i1", "i1"]}, "unique"),
            ({"activity_ids": ["i1"], "save_full": "yes"}, "save_full must be a boolean"),
            ({"activity_ids": ["i1"], "includeFields": ["unknown"]}, "Unsupported includeFields"),
        ):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(MCP.ToolFailure, message):
                self.service().call_tool("get_activities", arguments)

    def test_get_activities_rejects_batch_response_with_wrong_ids(self):
        for source, message in (
            ([{"id": "i1"}], "missing ids: i2"),
            ([{"id": "i1"}, {"id": "i3"}], "missing ids: i2; unexpected ids: i3"),
            ([{"id": "i1"}, {"id": "i1"}], "duplicate activity id: i1"),
            ([{"name": "No id"}, {"id": "i2"}], "missing a valid id"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(MCP.ToolFailure, message):
                self.service(activities_getter=lambda **kwargs: source).call_tool(
                    "get_activities", {"activity_ids": ["i1", "i2"]}
                )

    def test_search_activities_is_one_source_call_and_preserves_duplicates(self):
        calls = []
        source_rows = [
            {"id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
             "type": "Ride", "elapsed_time": 3600, "distance": 30000,
             "source": "GARMIN_CONNECT", "external_id": "g1"},
            {"id": "i1"}, {"id": "i2"},
        ]
        service = self.service(
            activity_searcher=lambda **kwargs: calls.append(kwargs) or source_rows
        )
        result = service.call_tool("search_activities", {"query": "#VT2", "limit": 20})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["query"], "#VT2")
        self.assertEqual(calls[0]["limit"], 20)
        self.assertEqual(calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", result)
        self.assertEqual([row["id"] for row in result["activities"]], ["i1", "i1", "i2"])
        self.assertEqual(result["includeFields"], [])
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["activities"][0], {
            "id": "i1", "name": "Ride", "start_date_local": "2026-08-17T10:00:00",
        })

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

    def test_search_activities_includes_explicit_non_default_athlete(self):
        calls = []
        result = self.service(
            activity_searcher=lambda **kwargs: calls.append(kwargs) or []
        ).call_tool("search_activities", {
            "athlete": "i-other", "query": "ski",
        })
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        self.assertEqual(result["athlete"]["id"], "i-other")

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

    def test_activity_file_includes_explicit_non_default_athlete(self):
        result = self.service().call_tool("get_activity_file", {
            "athlete": "i-other", "activity_id": "i1", "kind": "fit",
        })
        path = Path(result["file_path"])
        try:
            self.assertEqual(result["athlete"]["id"], "i-other")
        finally:
            path.unlink(missing_ok=True)
            path.parent.rmdir()

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
        self.assertEqual(result["before"], {"name": "Old"})
        self.assertEqual(result["after"], {"name": "New"})
        self.assertNotIn("id", result["before"])
        self.assertNotIn("feel", result["after"])
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
        self.assertEqual(result["before"], {field: None for field in updates})
        self.assertEqual(result["after"], updates)
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

    def test_delete_activities_reads_once_deletes_each_and_verifies_once(self):
        reads = [
            [{"id": "i2"}, {"id": "i1"}],
            [],
        ]
        read_calls = []
        delete_calls = []

        def get_many(**kwargs):
            read_calls.append(kwargs)
            return reads.pop(0)

        service = self.service(
            activities_getter=get_many,
            activity_deleter=lambda **kwargs: delete_calls.append(kwargs) or {
                "id": kwargs["activity_id"]
            },
        )
        result = service.call_tool("delete_activities", {
            "activity_ids": ["i1", "i2"],
            "confirm_activity_ids": ["i1", "i2"],
        })

        self.assertEqual(len(read_calls), 2)
        self.assertEqual(read_calls[0]["activity_ids"], ["i1", "i2"])
        self.assertEqual(read_calls[1]["activity_ids"], ["i1", "i2"])
        self.assertFalse(read_calls[0]["include_intervals"])
        self.assertEqual(
            [call["activity_id"] for call in delete_calls], ["i1", "i2"]
        )
        self.assertEqual(result, {
            "activity_ids": ["i1", "i2"],
            "deleted_count": 2,
            "verified_deleted": True,
        })

    def test_delete_activities_requires_exact_ordered_confirmation(self):
        service = self.service()
        for confirmation in (["i2", "i1"], ["i1"], ["i1", "i3"]):
            with self.subTest(confirmation=confirmation), self.assertRaisesRegex(
                MCP.ToolFailure, "exactly match"
            ):
                service.call_tool("delete_activities", {
                    "activity_ids": ["i1", "i2"],
                    "confirm_activity_ids": confirmation,
                })

    def test_delete_activities_fails_when_batch_verification_returns_activity(self):
        reads = [[{"id": "i1"}], [{"id": "i1"}]]
        with self.assertRaisesRegex(MCP.ToolFailure, "did not verify as deleted: i1"):
            self.service(activities_getter=lambda **kwargs: reads.pop(0)).call_tool(
                "delete_activities", {
                    "activity_ids": ["i1"], "confirm_activity_ids": ["i1"],
                }
            )

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

    def test_list_activity_messages_defaults_to_me_and_passes_pagination(self):
        calls = []
        result = self.service(
            activity_message_lister=lambda **kwargs: calls.append(kwargs) or [
                {"id": 7, "content": "Heavy legs"}
            ]
        ).call_tool("list_activity_messages", {
            "activity_id": "i1", "since_id": 5, "limit": 20,
        })
        self.assertEqual(calls[0]["activity_id"], "i1")
        self.assertEqual(calls[0]["since_id"], 5)
        self.assertEqual(calls[0]["limit"], 20)
        self.assertNotIn("athlete", result)
        self.assertEqual(result["messages"][0]["content"], "Heavy legs")

    def test_list_activity_messages_validates_explicit_athlete(self):
        result = self.service().call_tool("list_activity_messages", {
            "athlete": "i-other", "activity_id": "i1",
        })
        self.assertEqual(result["athlete"]["id"], "i-other")
        for since_id in (-1, True, "7"):
            with self.subTest(since_id=since_id), self.assertRaises(MCP.ToolFailure):
                self.service().call_tool("list_activity_messages", {
                    "activity_id": "i1", "since_id": since_id,
                })

    def test_get_training_plan_uses_selected_athlete(self):
        calls = []
        result = self.service(
            training_plan_getter=lambda **kwargs: calls.append(kwargs) or {
                "training_plan_alias": "Ski"
            }
        ).call_tool("get_training_plan", {"athlete": "i-other"})
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        self.assertEqual(result["plan"]["training_plan_alias"], "Ski")
        self.assertEqual(result["athlete"]["id"], "i-other")

    def test_plan_and_summary_default_to_me(self):
        plan_calls = []
        summary_calls = []
        service = self.service(
            training_plan_getter=lambda **kwargs: plan_calls.append(kwargs) or {},
            athlete_summary_getter=lambda **kwargs: summary_calls.append(kwargs) or [],
        )
        plan = service.call_tool("get_training_plan", {})
        summary = service.call_tool("get_athlete_summary", {
            "start_date": "2026-08-17", "end_date": "2026-08-28",
        })
        self.assertEqual(plan_calls[0]["athlete_id"], 0)
        self.assertEqual(summary_calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", plan)
        self.assertNotIn("athlete", summary)

    def test_get_athlete_summary_uses_inclusive_dates_and_selected_athlete(self):
        calls = []
        result = self.service(
            athlete_summary_getter=lambda **kwargs: calls.append(kwargs) or [
                {"athlete_id": "i-other", "training_load": 400}
            ]
        ).call_tool("get_athlete_summary", {
            "athlete": "i-other", "start_date": "2026-08-17", "end_date": "2026-08-28",
        })
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        self.assertEqual(calls[0]["start"].isoformat(), "2026-08-17")
        self.assertEqual(calls[0]["end"].isoformat(), "2026-08-28")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["athlete"]["id"], "i-other")

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
        self.assertEqual(calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", result)

    def test_list_wellness_includes_explicit_athlete_and_readiness_fields(self):
        calls = []
        source = [{
            "id": "2026-08-17", "sleepSecs": 28800, "restingHR": 48,
            "hrv": 72, "fatigue": 2, "soreness": 1, "stress": 2,
            "motivation": 3, "injury": 0, "ctl": 64.2, "atl": 71.5,
        }]
        result = self.service(
            wellness_lister=lambda **kwargs: calls.append(kwargs) or source
        ).call_tool("list_wellness", {
            "athlete": "i-other", "start_date": "2026-08-17",
            "end_date": "2026-08-17",
        })
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        self.assertEqual(result["athlete"]["id"], "i-other")
        self.assertEqual(result["wellness"], source)

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
        self.assertEqual(calls[0]["athlete_id"], 0)
        self.assertNotIn("athlete", result)

    def test_list_events_includes_explicit_non_default_athlete(self):
        calls = []
        result = self.service(
            event_lister=lambda **kwargs: calls.append(kwargs) or []
        ).call_tool("list_events", {
            "athlete": "i-other", "start_date": "2026-08-17",
            "end_date": "2026-08-18",
        })
        self.assertEqual(calls[0]["athlete_id"], "i-other")
        self.assertEqual(result["athlete"]["id"], "i-other")

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


class IntervalsIcuAthleteTransportTests(unittest.TestCase):
    def test_new_analysis_endpoints_use_expected_paths_and_parameters(self):
        calls = []

        def request(path, credentials, **kwargs):
            calls.append((path, kwargs.get("params")))
            if path.endswith("/messages"):
                return []
            if path.endswith("/training-plan"):
                return {"training_plan_alias": "Ski"}
            if path.endswith("/athlete-summary.json"):
                return []
            raise AssertionError(path)

        with mock.patch.object(API, "_request_json", side_effect=request):
            API.list_activity_messages(
                activity_id="i1", since_id=4, limit=25, api_key="secret"
            )
            API.get_training_plan(athlete_id="i-other", api_key="secret")
            API.get_athlete_summary(
                athlete_id="i-other", start="2026-08-17", end="2026-08-28",
                api_key="secret",
            )

        self.assertEqual(calls, [
            ("/activity/i1/messages", {"limit": 25, "sinceId": 4}),
            ("/athlete/i-other/training-plan", None),
            ("/athlete/i-other/athlete-summary.json", {
                "start": "2026-08-17", "end": "2026-08-28",
            }),
        ])

    def test_default_athlete_is_resolved_for_curve_and_settings_endpoints(self):
        paths = []

        def request(path, credentials, **kwargs):
            paths.append(path)
            if path == "/athlete/0":
                return {"id": "i-me"}
            if path.endswith("activity-hr-curves"):
                return {"secs": [60], "curves": []}
            if path.endswith("activity-power-curves"):
                return {"secs": [60], "curves": []}
            if path.endswith("activity-pace-curves"):
                return {"distances": [1000], "curves": []}
            if path.endswith("sport-settings"):
                return []
            raise AssertionError(path)

        with mock.patch.object(API, "_request_json", side_effect=request):
            API.list_activity_power_curves(
                secs=[60], oldest="2026-08-01", newest="2026-08-28", api_key="secret"
            )
            API.list_activity_hr_curves(
                secs=[60], oldest="2026-08-01", newest="2026-08-28", api_key="secret"
            )
            API.list_activity_pace_curves(
                distances=[1000], oldest="2026-08-01", newest="2026-08-28",
                api_key="secret",
            )
            API.list_sport_settings(api_key="secret")

        self.assertEqual(paths, [
            "/athlete/0", "/athlete/i-me/activity-power-curves",
            "/athlete/0", "/athlete/i-me/activity-hr-curves",
            "/athlete/0", "/athlete/i-me/activity-pace-curves",
            "/athlete/0", "/athlete/i-me/sport-settings",
        ])

    def test_explicit_athlete_skips_authenticated_profile_resolution(self):
        paths = []

        def request(path, credentials, **kwargs):
            paths.append(path)
            if path.endswith("activity-hr-curves"):
                return {"secs": [60], "curves": []}
            if path.endswith("activity-power-curves"):
                return {"secs": [60], "curves": []}
            if path.endswith("activity-pace-curves"):
                return {"distances": [1000], "curves": []}
            if path.endswith("sport-settings"):
                return []
            raise AssertionError(path)

        with mock.patch.object(API, "_request_json", side_effect=request):
            API.list_activity_power_curves(
                athlete_id="i-other", secs=[60], oldest="2026-08-01",
                newest="2026-08-28", api_key="secret",
            )
            API.list_activity_hr_curves(
                athlete_id="i-other", secs=[60], oldest="2026-08-01",
                newest="2026-08-28", api_key="secret",
            )
            API.list_activity_pace_curves(
                athlete_id="i-other", distances=[1000], oldest="2026-08-01",
                newest="2026-08-28", api_key="secret",
            )
            API.list_sport_settings(athlete_id="i-other", api_key="secret")

        self.assertEqual(paths, [
            "/athlete/i-other/activity-power-curves",
            "/athlete/i-other/activity-hr-curves",
            "/athlete/i-other/activity-pace-curves",
            "/athlete/i-other/sport-settings",
        ])


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
                "list_athletes",
                "list_activities", "list_activity_power_curves", "list_activity_hr_curves",
                "list_activity_pace_curves", "search_activity_intervals", "list_sport_settings",
                "search_activities", "get_activity",
                "get_activities",
                "get_activity_streams", "get_activity_file", "update_activity",
                "delete_activity", "delete_activities", "upload_activity",
                "list_activity_messages", "get_training_plan", "get_athlete_summary",
                "list_wellness", "update_wellness",
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
