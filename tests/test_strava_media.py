from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins/strava"
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


api = load_module("strava_route_api", SCRIPTS / "strava_route_api.py")
service = load_module("strava_activity_service", PLUGIN_ROOT / "strava_activity_service.py")


EDIT_HTML = """
<meta name="csrf" content="csrf-token">
<div data-react-class='MediaUploader' data-react-props='{&quot;athleteId&quot;:7,&quot;media&quot;:[{&quot;id&quot;:44,&quot;media_type&quot;:1,&quot;caption&quot;:&quot;Topp&quot;,&quot;original_filename&quot;:&quot;ride.jpg&quot;,&quot;urls&quot;:{&quot;100&quot;:&quot;https://images.example/100.jpg&quot;,&quot;1800&quot;:&quot;https://images.example/1800.jpg&quot;}}],&quot;activityId&quot;:12}'></div>
"""


class FakeResponse:
    status = 200

    def __init__(self, body: bytes, url: str):
        self.body = body
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body

    def geturl(self) -> str:
        return self.url


class StravaMediaTests(unittest.TestCase):
    def test_media_state_and_largest_url_are_normalized(self) -> None:
        props = service._media_props(EDIT_HTML)
        row = props["media"][0]
        self.assertEqual(service._media_url(row), "https://images.example/1800.jpg")
        self.assertEqual(
            service._normalize_media(row),
            {"media_id": "44", "type": "photo", "caption": "Topp", "filename": "ride.jpg", "is_highlight": False},
        )

    def test_media_state_rejects_missing_or_invalid_payload(self) -> None:
        with self.assertRaisesRegex(service.StravaError, "media state"):
            service._media_props("<div></div>")
        with self.assertRaisesRegex(service.StravaError, "invalid media state"):
            service._media_props("<div data-react-class='MediaUploader' data-react-props='{not-json}'></div>")

    def test_presigned_upload_request_never_receives_strava_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookie.headers"
            cookie_file.write_text("Cookie: session=secret\n")
            cookie_file.chmod(0o600)
            captured = []

            def urlopen(request, timeout=0):
                captured.append(request)
                return FakeResponse(b"ok", request.full_url)

            with mock.patch.object(api.urllib.request, "urlopen", side_effect=urlopen):
                with api.StravaSession(cookie_file) as session:
                    session.request("https://storage.example/upload", method="PUT", data=b"file", include_cookie=False)

        self.assertEqual(captured[0].get_header("Cookie"), None)
        self.assertEqual(captured[0].data, b"file")

    def test_upload_requires_explicit_confirmation_and_supported_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirm=true"):
            service.upload_activity_media(activity_id=12, file_path="missing.jpg", confirm=False)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ride.txt"
            source.write_text("not media")
            with self.assertRaisesRegex(ValueError, "JPG"):
                service.upload_activity_media(activity_id=12, file_path=str(source), confirm=True)


if __name__ == "__main__":
    unittest.main()
