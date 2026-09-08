from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/strava"
sys.path.insert(0, str(PLUGIN))
sys.path.insert(0, str(PLUGIN / "scripts"))

import strava_mcp as mcp_server

api = sys.modules[mcp_server.activities.StravaSession.__module__]


class Response:
    status = 200

    def __init__(self, url, body=b"[]"):
        self.url, self.body = url, body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return self.body

    def geturl(self):
        return self.url


class StravaMcpTests(unittest.TestCase):
    def setUp(self):
        self.service = mcp_server.StravaToolService()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cookie = Path(self.tmp.name) / "session.headers"
        self.cookie.write_text("Cookie: session=first\n")
        self.cookie.chmod(0o600)
        self.env = mock.patch.dict(os.environ, {"STRAVA_COOKIE_FILE": str(self.cookie)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_rejects_invalid_writes_before_network(self):
        for args in [
            {"activity_id": "12", "patch": {"mute": True}, "confirm": False},
            {"activity_id": "12", "patch": {}, "confirm": True},
            {"activity_id": "12", "patch": {"mute": "false"}, "confirm": True},
            {"activity_id": "12", "patch": {"bike_id": "1", "bike_name": "Bike"}, "confirm": True},
            {"activity_id": "12/other", "patch": {"mute": True}, "confirm": True},
        ]:
            with self.subTest(args=args), mock.patch.object(mcp_server.activities, "update_activity") as write:
                with self.assertRaises(mcp_server.ToolFailure) as error:
                    self.service.call_tool("update_activity", args)
                self.assertEqual(error.exception.code, "invalid_arguments")
                write.assert_not_called()

    def test_all_six_dispatch_without_cookie_arguments(self):
        samples = {
            "list_activities": {"since": "2026-09-01"},
            "get_activity": {"activity_id": "12"},
            "list_gear": {}, "get_gear": {"gear_id": "3"},
            "update_activity": {"activity_id": "12", "patch": {"mute": True}, "confirm": True},
            "update_activities": {"activity_ids": ["12"], "patch": {"tag": None}, "confirm": True},
        }
        self.assertEqual(set(samples), set(mcp_server.TOOL_DEFINITIONS))
        for name, args in samples.items():
            with self.subTest(name=name), mock.patch.object(mcp_server.activities, name, return_value={"complete": True}) as handler:
                self.service.call_tool(name, args)
                handler.assert_called_once_with(**args)

    def test_missing_cookie_and_login_redirect_are_auth_required(self):
        self.cookie.unlink()
        with self.assertRaises(mcp_server.ToolFailure) as error:
            self.service.call_tool("get_activity", {"activity_id": "12"})
        self.assertEqual(error.exception.code, "auth_required")
        self.cookie.write_text("Cookie: session=expired\n")
        self.cookie.chmod(0o600)
        with mock.patch.object(api.urllib.request, "urlopen", return_value=Response("https://www.strava.com/login")):
            with self.assertRaises(mcp_server.ToolFailure) as error:
                self.service.call_tool("get_activity", {"activity_id": "12"})
        self.assertEqual(error.exception.code, "auth_required")

    def test_401_is_auth_but_403_and_500_are_not_and_body_is_private(self):
        for status, code in [(401, "auth_required"), (403, "tool_error"), (500, "tool_error")]:
            response = urllib.error.HTTPError("https://www.strava.com/test", status, "error", {}, io.BytesIO(b"secret-response"))
            with self.subTest(status=status), mock.patch.object(api.urllib.request, "urlopen", side_effect=response):
                with self.assertRaises(mcp_server.ToolFailure) as error:
                    self.service.call_tool("get_activity", {"activity_id": "12"})
                self.assertEqual(error.exception.code, code)
                self.assertNotIn("secret-response", str(error.exception))

    def test_session_file_is_reread_without_server_restart(self):
        seen = []

        def read(request, **kwargs):
            seen.append(request.get_header("Cookie"))
            return Response(request.full_url, b'{}')

        with mock.patch.object(api.urllib.request, "urlopen", side_effect=read):
            self.service.call_tool("get_activity", {"activity_id": "12"})
            self.cookie.write_text("Cookie: session=second\n")
            self.service.call_tool("get_activity", {"activity_id": "12"})
        self.assertEqual(seen, ["session=first", "session=first", "session=second", "session=second"])

    def test_batch_auth_failure_retains_progress_and_stops(self):
        with mock.patch.object(mcp_server.activities, "update_with_session", side_effect=[{"id": 1}, api.StravaAuthRequired("Expired")]) as update:
            with self.assertRaises(mcp_server.ToolFailure) as error:
                self.service.call_tool("update_activities", {
                    "activity_ids": ["1", "2", "3"], "patch": {"mute": True}, "confirm": True,
                })
        self.assertEqual(error.exception.code, "auth_required")
        self.assertEqual(error.exception.details["updated"], [{"id": 1}])
        self.assertEqual(error.exception.details["failed"][0]["activity_id"], "2")
        self.assertEqual(error.exception.details["not_attempted"], ["3"])
        self.assertEqual(update.call_count, 2)

    def test_real_stdio_catalog_and_structured_auth_error(self):
        # A separate interpreter also checks plugin packaging/imports and SDK
        # initialization without requiring a browser session or network.
        script = '''
import asyncio, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def run():
    params = StdioServerParameters(command="python3", args=["-B", "strava_mcp.py"], cwd=os.getcwd(), env={**os.environ, "STRAVA_COOKIE_FILE": os.environ["MISSING_COOKIE"]})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            catalog = await client.list_tools()
            assert len(catalog.tools) == 6
            assert all(tool.outputSchema for tool in catalog.tools)
            result = await client.call_tool("get_activity", {"activity_id": "12"})
            assert result.isError
            assert result.structuredContent["errorCode"] == "auth_required", result
asyncio.run(run())
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=PLUGIN,
                                env={**os.environ, "MISSING_COOKIE": str(Path(self.tmp.name) / "missing")},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
