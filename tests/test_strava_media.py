from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlencode


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
    def test_csrf_metadata_variants(self) -> None:
        for markup in (
            '<meta name="csrf" content="a&amp;b">',
            "<meta content='a&amp;b' name='csrf-token' />",
            '<META NAME="csrf-token" CONTENT="a&amp;b">',
        ):
            with self.subTest(markup=markup):
                self.assertEqual(service._csrf_from_edit_html(markup), "a&b")
        with self.assertRaisesRegex(service.StravaError, "CSRF"):
            service._csrf_from_edit_html('<meta name="other" content="unrelated">')

    def test_storage_upload_preserves_signed_headers_without_cookies(self) -> None:
        for headers in ({"Content-Type": "image/jpeg"}, {"content-type": "image/png"}, {}):
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "card.png"
                source.write_bytes(b"image data")
                session = mock.Mock()
                session.request.return_value = (json.dumps({
                    "uri": "https://storage.example/upload", "header": headers,
                }).encode(), 200, "")
                service._upload_media_blob(session, athlete_id=7, file_path=source, csrf="token")
                call = session.request.call_args
                types = [h.split(":", 1)[1].strip() for h in call.kwargs["headers"]
                         if h.lower().startswith("content-type:")]
                self.assertEqual(types, [next(iter(headers.values()), "application/octet-stream")])
                self.assertFalse(call.kwargs["include_cookie"])
                self.assertEqual(call.kwargs["data"], b"image data")

    def test_upload_readback_matches_uuid_after_numeric_id_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "card.png"
            source.write_bytes(b"image data")
            attached = {"id": 99, "unique_id": "upload-uuid", "media_type": 1}
            unrelated = {"id": 98, "unique_id": "someone-else", "media_type": 1}
            with (
                mock.patch.object(service, "StravaSession"),
                mock.patch.object(service.activity_metadata, "fetch_activity", return_value={"selected_tag_type": "Workout"}),
                mock.patch.object(service, "_upload_media_blob", return_value="upload-uuid") as upload,
                mock.patch.object(service.activity_metadata, "build_form_body", return_value="_method=put"),
                mock.patch.object(service, "_fetch_edit_media", side_effect=[
                    (EDIT_HTML, {"athleteId": 7, "media": []}),
                    (EDIT_HTML, {"media": [unrelated]}),
                    (EDIT_HTML, {"media": [unrelated, attached]}),
                ]),
                mock.patch.object(service.time, "sleep"),
            ):
                result = service.upload_activity_media(activity_id=12, file_path=str(source), confirm=True)
            self.assertTrue(result["verified"])
            self.assertEqual(result["uploaded"]["media_id"], "99")
            upload.assert_called_once()

    def test_delete_omits_only_target_uuid_and_preserves_other_form_fields(self) -> None:
        target = {"id": 44, "unique_id": "photo-uuid", "media_type": 1}
        retained = {"id": 45, "unique_id": "photo-uuid-extra", "media_type": 1}
        fields = [
            ("_method", "put"),
            ("activity[name]", "Ride & coffee"),
            ("photos[photo-uuid][id]", "44"),
            ("photos[photo-uuid][caption]", "Remove"),
            ("photos[photo-uuid-extra][id]", "45"),
            ("photos[photo-uuid-extra][caption]", "Keep"),
            ("photos[photo-uuid-extra][caption]", "Repeated field"),
        ]
        with (
            mock.patch.object(service, "StravaSession") as session_factory,
            mock.patch.object(service.activity_metadata, "fetch_activity", return_value={}),
            mock.patch.object(service.activity_metadata, "build_form_body", return_value=urlencode(fields)),
            mock.patch.object(service, "_fetch_edit_media", side_effect=[
                (EDIT_HTML, {"media": [target, retained]}),
                (EDIT_HTML, {"media": [retained]}),
            ]) as readback,
        ):
            result = service.delete_activity_media(activity_id=12, media_id=44, confirm=True)
        request = session_factory.return_value.__enter__.return_value.request
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["method"], "POST")
        sent = parse_qsl(request.call_args.kwargs["data"].decode(), keep_blank_values=True)
        self.assertEqual(sent, [fields[0], fields[1], *fields[4:]])
        self.assertEqual(readback.call_count, 2)
        self.assertEqual(result, {"activity_id": 12, "deleted_media_id": "44", "verified": True})

    def test_upload_readback_rejects_unrelated_media(self) -> None:
        self.assertFalse(service._matches_upload({"id": 99, "unique_id": "other"}, "upload-uuid"))
        self.assertFalse(service._matches_upload({}, "upload-uuid"))
        self.assertTrue(service._matches_upload({"id": "upload-uuid"}, "upload-uuid"))

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
