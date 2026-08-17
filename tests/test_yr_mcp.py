import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "yr"
sys.path.insert(0, str(PLUGIN_ROOT))

import yr_mcp as MCP  # noqa: E402


class FakeYrService:
    def __init__(self) -> None:
        self.calls = []

    def get_forecast(self, *, latitude, longitude, altitude):
        self.calls.append((latitude, longitude, altitude))
        if latitude == 0:
            raise RuntimeError("MET/Yr request failed: offline")
        return {
            "properties": {
                "meta": {"updated_at": "2026-08-17T08:00:00Z"},
                "timeseries": [
                    {
                        "time": "2026-08-17T07:00:00Z",
                        "data": {
                            "instant": {
                                "details": {
                                    "air_temperature": 17.2,
                                    "wind_speed": 3.1,
                                }
                            },
                            "next_1_hours": {
                                "details": {"precipitation_amount": 0.1},
                                "summary": {"symbol_code": "lightrain"},
                            },
                        },
                    }
                ],
            }
        }


class YrMcpSchemaTests(unittest.TestCase):
    def test_exposes_closed_read_only_tools(self) -> None:
        self.assertEqual(MCP.ALL_TOOL_NAMES, ("get_forecast", "get_forecasts"))
        for name in MCP.ALL_TOOL_NAMES:
            definition = MCP.TOOL_DEFINITIONS[name]
            self.assertFalse(definition["inputSchema"]["additionalProperties"])
            self.assertFalse(definition["outputSchema"]["additionalProperties"])
            self.assertEqual(
                definition["annotations"],
                {
                    "title": MCP.TOOL_ANNOTATIONS[name]["title"],
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": True,
                },
            )

    def test_sdk_accepts_tool_definition(self) -> None:
        self.assertIsNotNone(MCP.create_sdk_server(MCP.YrToolService(FakeYrService)))


class YrMcpDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeYrService()
        self.tools = MCP.YrToolService(lambda: self.fake)

    def test_returns_compact_forecast_in_selected_timezone(self) -> None:
        result = self.tools.call_tool(
            "get_forecast",
            {
                "latitude": 59.946,
                "longitude": 10.689,
                "altitude": 140,
                "timezone": "Europe/Oslo",
                "from_local": "2026-08-17T09:00",
                "to_local": "2026-08-17T11:00",
            },
        )
        self.assertEqual(self.fake.calls, [(59.946, 10.689, 140)])
        self.assertEqual(result["source_updated_at"], "2026-08-17T08:00:00Z")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["hourly"][0]["time_local"], "2026-08-17T09:00:00+02:00")
        self.assertEqual(result["hourly"][0]["precipitation_amount_next_1h"], 0.1)

    def test_omitted_to_local_returns_one_forecast(self) -> None:
        result = self.tools.call_tool(
            "get_forecast",
            {
                "latitude": 59.946,
                "longitude": 10.689,
                "timezone": "Europe/Oslo",
                "from_local": "2026-08-17T08:30",
            },
        )

        self.assertIsNone(result["to_local"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["hourly"][0]["time_local"], "2026-08-17T09:00:00+02:00")

    def test_rejects_unknown_missing_invalid_and_reversed_arguments(self) -> None:
        with self.assertRaisesRegex(MCP.ToolFailure, "unknown argument"):
            self.tools.call_tool("get_forecast", {"surprise": True})
        with self.assertRaisesRegex(MCP.ToolFailure, "missing required"):
            self.tools.call_tool("get_forecast", {})
        arguments = {
            "latitude": 59.9,
            "longitude": 10.7,
            "timezone": "Invalid/Place",
            "from_local": "2026-08-17T09:00",
            "to_local": "2026-08-17T10:00",
        }
        with self.assertRaisesRegex(MCP.ToolFailure, "unknown IANA timezone"):
            self.tools.call_tool("get_forecast", arguments)
        arguments["timezone"] = "Europe/Oslo"
        arguments["from_local"] = "2026-08-17T11:00"
        with self.assertRaisesRegex(MCP.ToolFailure, "before or equal"):
            self.tools.call_tool("get_forecast", arguments)

    def test_batch_returns_ordered_point_and_time_forecasts(self) -> None:
        result = self.tools.call_tool(
            "get_forecasts",
            {
                "timezone": "Europe/Oslo",
                "requests": [
                    {
                        "id": "start",
                        "latitude": 59.946,
                        "longitude": 10.689,
                        "at_local": "2026-08-17T08:30",
                    },
                    {
                        "id": "turnaround",
                        "latitude": 59.6633,
                        "longitude": 10.6298,
                        "altitude": 12,
                        "at_local": "2026-08-17T08:45",
                    },
                ],
            },
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual([row["id"] for row in result["results"]], ["start", "turnaround"])
        self.assertEqual(result["results"][0]["forecast"]["air_temperature"], 17.2)
        self.assertEqual(
            self.fake.calls,
            [(59.946, 10.689, None), (59.6633, 10.6298, 12)],
        )

    def test_batch_validates_all_requests_before_source_calls(self) -> None:
        with self.assertRaisesRegex(MCP.ToolFailure, "duplicate request id"):
            self.tools.call_tool(
                "get_forecasts",
                {
                    "timezone": "Europe/Oslo",
                    "requests": [
                        {
                            "id": "same",
                            "latitude": 59.9,
                            "longitude": 10.7,
                            "at_local": "2026-08-17T09:00",
                        },
                        {
                            "id": "same",
                            "latitude": 59.8,
                            "longitude": 10.6,
                            "at_local": "2026-08-17T10:00",
                        },
                    ],
                },
            )
        self.assertEqual(self.fake.calls, [])

    def test_batch_reports_source_failure_per_point(self) -> None:
        result = self.tools.call_tool(
            "get_forecasts",
            {
                "timezone": "Europe/Oslo",
                "requests": [
                    {
                        "id": "working",
                        "latitude": 59.9,
                        "longitude": 10.7,
                        "at_local": "2026-08-17T08:30",
                    },
                    {
                        "id": "offline",
                        "latitude": 0,
                        "longitude": 10.7,
                        "at_local": "2026-08-17T08:30",
                    },
                ],
            },
        )

        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertIsNone(result["results"][1]["forecast"])
        self.assertIn("offline", result["results"][1]["error"])

    def test_batch_rejects_more_than_25_requests(self) -> None:
        requests = [
            {
                "id": f"point-{index}",
                "latitude": 59.9,
                "longitude": 10.7,
                "at_local": "2026-08-17T08:30",
            }
            for index in range(26)
        ]

        with self.assertRaisesRegex(MCP.ToolFailure, "between 1 and 25"):
            self.tools.call_tool(
                "get_forecasts",
                {"timezone": "Europe/Oslo", "requests": requests},
            )
        self.assertEqual(self.fake.calls, [])


class YrMcpHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_initialize_and_list_tools(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "./yr_mcp.py"],
            cwd=str(PLUGIN_ROOT),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()

        self.assertEqual(
            [tool.name for tool in result.tools],
            ["get_forecast", "get_forecasts"],
        )


if __name__ == "__main__":
    unittest.main()
