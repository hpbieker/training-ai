from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/strava/scripts"
sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = load_module("strava_route_api", SCRIPTS / "strava_route_api.py")
routes = load_module("strava_create_route", SCRIPTS / "strava_create_route.py")


class FakeResponse:
    def __init__(self, body: str, url: str, status: int = 200):
        self.body = body.encode()
        self.url = url
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body

    def geturl(self) -> str:
        return self.url


class StravaRouteTests(unittest.TestCase):
    def cookie_file(self, directory: Path) -> Path:
        path = directory / "strava-cookie.headers"
        path.write_text("Cookie: session=secret\n")
        path.chmod(0o600)
        return path

    def test_auth_uses_python_http_and_private_cookie(self) -> None:
        requests = []

        def urlopen(request, timeout=0):
            requests.append(request)
            if "/athlete/training" in request.full_url:
                return FakeResponse('<a href="/athletes/23820495">Athlete</a>', request.full_url)
            return FakeResponse('<meta name="csrf" content="csrf-token">', request.full_url)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(api.urllib.request, "urlopen", side_effect=urlopen):
            with api.StravaSession(self.cookie_file(Path(tmp))) as session:
                result = session.authenticate()

        self.assertEqual(result["athlete_id"], 23820495)
        self.assertEqual(result["transport"], "python-cookie-file")
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.get_header("Cookie") == "session=secret" for request in requests))

    def test_route_api_posts_json_without_subprocess(self) -> None:
        responses = [
            FakeResponse('<a href="/athletes/23820495">Athlete</a>', api.AUTH_CHECK_URL),
            FakeResponse('<meta name="csrf" content="csrf-token">', api.CREATE_URL),
            FakeResponse(json.dumps({"buildRoute": []}), api.ENDPOINTS["build"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            body = directory / "body.json"
            output = directory / "output.json"
            body.write_text('{"requests": []}')
            with mock.patch.object(api.urllib.request, "urlopen", side_effect=responses) as urlopen:
                with api.StravaSession(self.cookie_file(directory)) as session:
                    payload = session.api("build", body, output)

        self.assertEqual(payload, {"buildRoute": []})
        posted = urlopen.call_args_list[-1].args[0]
        self.assertEqual(posted.method, "POST")
        self.assertEqual(posted.data, b'{"requests": []}')
        self.assertEqual(posted.get_header("X-csrf-token"), "csrf-token")

    def test_route_candidate_logic_is_unchanged(self) -> None:
        result = {
            "ok": True,
            "leg_count": 3,
            "total_length_m": 30000,
            "skeptical_surface_m": 0,
        }
        routes.validate_candidate(
            result,
            target_km=30,
            tolerance_pct=15,
            surface="Paved",
            allow_distance_deviation=False,
        )

    def test_rejects_cookie_file_visible_to_other_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = self.cookie_file(Path(tmp))
            cookie_file.chmod(0o644)
            with self.assertRaisesRegex(api.StravaError, "must not be accessible by group or others"):
                api.StravaSession(cookie_file)


if __name__ == "__main__":
    unittest.main()
