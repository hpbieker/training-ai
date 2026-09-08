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

    def test_all_tools_dispatch_without_cookie_arguments(self):
        samples = {
            "list_routes": {},
            "get_route": {"route_id": "3517267791863546324"},
            "create_route": {"props": {"name": "Test", "elements": [
                {"elementType": "Waypoint", "waypoint": {"point": {"lat": 0, "lng": 0}}},
                {"elementType": "Waypoint", "waypoint": {"point": {"lat": 1, "lng": 1}}},
            ], "legs": [{"startElement": 0, "paths": [{"polyline": {"encoding": "Google", "data": "abcd"}}]}],
                "routePrefs": {"routeType": "Ride", "surfaceType": "Paved", "popularity": 0, "elevation": 0, "straightLine": False}}, "confirm": True},
            "update_route": {"route_id": "12", "patch": {"name": "Test"}, "confirm": True},
            "delete_route": {"route_id": "12", "confirm": True},
            "list_activities": {"since": "2026-09-01"},
            "get_activity": {"activity_id": "12"},
            "list_gear": {}, "get_gear": {"gear_id": "3"},
            "list_activity_media": {"activity_id": "12"},
            "download_activity_media": {"activity_id": "12", "media_id": "media-uuid", "destination_dir": "/private/tmp/media"},
            "upload_activity_media": {"activity_id": "12", "file_path": "/private/tmp/ride.jpg", "caption": "Ride", "confirm": True},
            "update_activity": {"activity_id": "12", "patch": {"mute": True}, "confirm": True},
            "update_activities": {"activity_ids": ["12"], "patch": {"tag": None}, "confirm": True},
        }
        self.assertEqual(set(samples), set(mcp_server.TOOL_DEFINITIONS))
        for name, args in samples.items():
            service = mcp_server.routes if name in {"list_routes", "get_route", "create_route", "update_route", "delete_route"} else mcp_server.activities
            with self.subTest(name=name), mock.patch.object(service, name, return_value={"complete": True}) as handler:
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

    def test_media_write_arguments_are_validated_before_dispatch(self):
        cases = [
            ("upload_activity_media", {"activity_id": "12", "file_path": "/tmp/a.png"}),
            ("upload_activity_media", {"activity_id": "12", "file_path": "/tmp/a.png", "confirm": False}),
            ("download_activity_media", {"activity_id": "12", "media_id": "id", "destination_dir": "relative"}),
            ("download_activity_media", {"activity_id": "12", "media_id": "id", "destination_dir": "/tmp", "overwrite": "true"}),
        ]
        for name, args in cases:
            with self.subTest(name=name, args=args), mock.patch.object(mcp_server.activities, name) as handler:
                with self.assertRaises(mcp_server.ToolFailure) as error:
                    self.service.call_tool(name, args)
                self.assertEqual(error.exception.code, "invalid_arguments")
                handler.assert_not_called()

    def test_download_preserves_existing_file_until_overwrite_is_explicit(self):
        props = {"media": [{"uuid": "media-uuid", "filename": "ride.jpg", "url": "https://media.example/ride.jpg"}]}
        target = Path(self.tmp.name) / "ride.jpg"
        target.write_bytes(b"original")
        args = {"activity_id": "12", "media_id": "media-uuid", "destination_dir": self.tmp.name}
        with mock.patch.object(mcp_server.activities, "_fetch_edit_media", return_value=("", props)), mock.patch.object(api.urllib.request, "urlopen", return_value=Response("https://media.example/ride.jpg", b"download")) as network:
            with self.assertRaises(mcp_server.ToolFailure):
                self.service.call_tool("download_activity_media", args)
            network.assert_not_called()
            self.assertEqual(target.read_bytes(), b"original")
            result = self.service.call_tool("download_activity_media", {**args, "overwrite": True})
            self.assertEqual(Path(result["path"]).read_bytes(), b"download")
            self.assertIsNone(network.call_args.args[0].get_header("Cookie"))

    def test_upload_returns_verified_media_after_readback(self):
        source = Path(self.tmp.name) / "ride.png"
        source.write_bytes(b"test-image")
        before = {"athleteId": 7, "media": []}
        after = {"athleteId": 7, "media": [{"uuid": "uploaded-uuid", "media_type": 1, "caption": "Ride"}]}
        with mock.patch.object(mcp_server.activities, "_fetch_edit_media", side_effect=[('<meta name="csrf" content="token">', before), ("", after)]), mock.patch.object(mcp_server.activities, "_upload_media_blob", return_value="uploaded-uuid"), mock.patch.object(api.StravaSession, "request", return_value=(b"", 200, "https://www.strava.com/activities/12")):
            result = self.service.call_tool("upload_activity_media", {"activity_id": "12", "file_path": str(source), "caption": "Ride", "confirm": True})
        self.assertTrue(result["verified"])
        self.assertEqual(result["uploaded"]["media_id"], "uploaded-uuid")

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
            assert len(catalog.tools) == 14
            assert all(tool.outputSchema for tool in catalog.tools)
            result = await client.call_tool("get_activity", {"activity_id": "12"})
            assert result.isError
            assert result.structuredContent["errorCode"] == "auth_required", result
            media = await client.call_tool("list_activity_media", {"activity_id": "12"})
            assert media.isError and media.structuredContent["errorCode"] == "auth_required"
            routes = await client.call_tool("list_routes", {})
            assert routes.isError and routes.structuredContent["errorCode"] == "auth_required"
            route = await client.call_tool("get_route", {"route_id": "3517267791863546324"})
            assert route.isError and route.structuredContent["errorCode"] == "auth_required"
asyncio.run(run())
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=PLUGIN,
                                env={**os.environ, "MISSING_COOKIE": str(Path(self.tmp.name) / "missing")},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
