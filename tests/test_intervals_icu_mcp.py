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
            "credential_factory": lambda: "secret",
            "activity_lister": lambda **kwargs: [{"id": "i1"}, {"id": "i2"}],
            "activity_getter": lambda **kwargs: {"id": kwargs["activity_id"]},
            "streams_downloader": self._write_streams,
        }
        defaults.update(overrides)
        return MCP.IntervalsIcuToolService(**defaults)

    @staticmethod
    def _write_streams(**kwargs):
        path = Path(kwargs["output_path"])
        path.write_text("secs,watts\n0,200\n", encoding="utf-8")
        return path

    def test_advertises_exactly_three_tools(self):
        self.assertEqual(
            [tool["name"] for tool in self.service().list_tools()],
            ["list_activities", "get_activity", "get_activity_streams"],
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

    def test_get_activity_defaults_to_intervals(self):
        calls = []
        service = self.service(activity_getter=lambda **kwargs: calls.append(kwargs) or {"id": "i1"})
        result = service.call_tool("get_activity", {"activity_id": "i1"})
        self.assertTrue(result["include_intervals"])
        self.assertTrue(calls[0]["include_intervals"])

    def test_streams_are_private_file_and_not_inline(self):
        result = self.service().call_tool("get_activity_streams", {"activity_id": "i1"})
        path = Path(result["streams_file"])
        try:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["byte_size"], path.stat().st_size)
            self.assertNotIn("streams", result)
        finally:
            path.unlink(missing_ok=True)

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
            ["list_activities", "get_activity", "get_activity_streams"],
        )


class IntervalsIcuConfigTests(unittest.TestCase):
    def setUp(self):
        self.api = MCP.load_intervals_icu_api_key.__globals__
        self.original_api_key = os.environ.pop("INTERVALS_ICU_API_KEY", None)

    def tearDown(self):
        if self.original_api_key is not None:
            os.environ["INTERVALS_ICU_API_KEY"] = self.original_api_key
        else:
            os.environ.pop("INTERVALS_ICU_API_KEY", None)

    def test_reads_user_owned_json_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps({"apiKey": "from-file"}), encoding="utf-8")
            self.assertEqual(MCP.load_intervals_icu_api_key(path), "from-file")

    def test_environment_overrides_config(self):
        os.environ["INTERVALS_ICU_API_KEY"] = "from-environment"
        self.assertEqual(MCP.load_intervals_icu_api_key("/missing/config.json"), "from-environment")


if __name__ == "__main__":
    unittest.main()
