import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MCP_PATH = ROOT / "plugins" / "garmin-connect" / "garmin_connect_mcp.py"
SPEC = importlib.util.spec_from_file_location("garmin_connect_mcp", MCP_PATH)
assert SPEC and SPEC.loader
MCP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MCP
SPEC.loader.exec_module(MCP)


class GarminConnectMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MCP.GarminConnectToolService(lambda: "/mock/gccli")

    def test_lists_exactly_four_read_only_tools_with_closed_inputs(self) -> None:
        tools = self.service.list_tools()

        self.assertEqual([tool["name"] for tool in tools], list(MCP.ALL_TOOL_NAMES))
        for tool in tools:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertFalse(tool["annotations"]["destructiveHint"])

    @patch.object(MCP, "compact_day_payload")
    @patch.object(MCP, "fetch_day")
    def test_get_health_day_uses_readiness_profile_and_compacts(
        self, fetch_day, compact_day
    ) -> None:
        fetch_day.return_value = {"date": "2026-08-17"}
        compact_day.return_value = {"date": "2026-08-17", "compact": True}

        result = self.service.call_tool("get_health_day", {"date": "2026-08-17"})

        fetch_day.assert_called_once_with(
            "2026-08-17",
            gccli="/mock/gccli",
            only=None,
            profile="readiness",
            tolerate_errors=True,
        )
        self.assertTrue(result["compact"])

    @patch.object(MCP, "compact_recent_payload")
    @patch.object(MCP, "fetch_recent_days")
    def test_list_health_days_supports_narrow_sources(
        self, fetch_recent, compact_recent
    ) -> None:
        fetch_recent.return_value = {"days": [], "body_battery_range": [{"value": 50}]}
        compact_recent.return_value = {"days": []}

        result = self.service.call_tool(
            "list_health_days",
            {
                "until": "2026-08-17",
                "days": 7,
                "sources": ["hrv", "body-battery"],
            },
        )

        fetch_recent.assert_called_once_with(
            days=7,
            until="2026-08-17",
            gccli="/mock/gccli",
            only=["hrv", "body-battery"],
            profile="full",
            tolerate_errors=True,
        )
        self.assertEqual(result["body_battery_range"], [{"value": 50}])

    @patch.object(MCP, "local_now", return_value="2026-08-17T12:00:00+02:00")
    @patch.object(MCP, "garmin_activity_search")
    def test_list_activities_returns_count(self, search, _local_now) -> None:
        search.return_value = [{"activityId": 123}]

        result = self.service.call_tool(
            "list_activities",
            {"since": "2026-08-17", "until": "2026-08-17"},
        )

        search.assert_called_once_with(
            "/mock/gccli", "2026-08-17", "2026-08-17", limit=100
        )
        self.assertEqual(result["count"], 1)

    @patch.object(MCP, "fetch_activity")
    def test_get_activity_returns_only_normalized_summary(self, fetch_activity) -> None:
        fetch_activity.return_value = {
            "source": "garmin_connect_gccli",
            "metrics_summary": {"training_effect": {}},
            "summary": {"large": True},
            "details": {"chart": []},
        }

        result = self.service.call_tool("get_activity", {"activity_id": "123"})

        fetch_activity.assert_called_once_with(
            "123", gccli="/mock/gccli", include_details=True
        )
        self.assertNotIn("summary", result)
        self.assertNotIn("details", result)
        self.assertIn("metrics_summary", result)

    def test_invalid_date_becomes_structured_tool_failure(self) -> None:
        with self.assertRaises(MCP.ToolFailure) as caught:
            self.service.call_tool("get_health_day", {"date": "17-08-2026"})

        self.assertEqual(caught.exception.code, "invalid_arguments")


if __name__ == "__main__":
    unittest.main()
