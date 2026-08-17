from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/strava/scripts"
COOKIE_SCRIPT = SCRIPTS / "strava_cookie_from_curl.py"
SAFARI_SESSION_SCRIPT = SCRIPTS / "strava_session_from_safari.py"


def load_module(name: str, path: Path):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


activities = load_module("strava_activities", SCRIPTS / "strava_activities.py")
metadata = load_module("strava_activity_tags", SCRIPTS / "strava_activity_tags.py")


EDIT_HTML = """
<form>
  <input name="authenticity_token" value="token">
  <input type="checkbox" name="activity[stats_visibility][start_time]" value="only_me" checked>
  <select name="activity[bike_id]">
    <option value="">None</option>
    <option value="15590716" selected>Kickr Bike v2 (hjeme)</option>
  </select>
</form>
<div data-react-class='ActivityTagInput' data-react-props='{&quot;trainerOption&quot;:{&quot;selected&quot;:true}}'></div>
"""


class StravaActivityTests(unittest.TestCase):
    def test_safari_bootstrap_exports_private_strava_cookie_header(self) -> None:
        fake = """#!/bin/sh
jar=''
while test "$#" -gt 0; do
  if test "$1" = '--cookie-jar'; then jar="$2"; shift 2; else shift; fi
done
printf '# Netscape HTTP Cookie File\n#HttpOnly_.strava.com\tTRUE\t/\tTRUE\t0\t_strava4_session\tsecret\n.strava.com\tTRUE\t/\tTRUE\t0\tother\tvalue\n' > "$jar"
printf '200\nhttps://www.strava.com/athlete/training'
"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = directory / "curl-safari"
            executable.write_text(fake)
            executable.chmod(0o755)
            output = directory / "strava-cookie.headers"
            result = subprocess.run(
                [
                    sys.executable, "-B", str(SAFARI_SESSION_SCRIPT),
                    "--curl-safari", str(executable), "--output", str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), "Cookie: _strava4_session=secret; other=value\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertNotIn("secret", result.stdout)
            self.assertEqual(json.loads(result.stdout)["source"], "curl-safari")

    def test_safari_bootstrap_rejects_missing_session_cookie(self) -> None:
        fake = """#!/bin/sh
jar=''
while test "$#" -gt 0; do
  if test "$1" = '--cookie-jar'; then jar="$2"; shift 2; else shift; fi
done
printf '# Netscape HTTP Cookie File\n.strava.com\tTRUE\t/\tTRUE\t0\tother\tvalue\n' > "$jar"
printf '200\nhttps://www.strava.com/athlete/training'
"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = directory / "curl-safari"
            executable.write_text(fake)
            executable.chmod(0o755)
            result = subprocess.run(
                [sys.executable, "-B", str(SAFARI_SESSION_SCRIPT), "--curl-safari", str(executable)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("required _strava4_session", result.stderr)

    def test_cookie_extractor_writes_only_private_cookie_header(self) -> None:
        copied = "curl 'https://www.strava.com/athlete/training' -H 'accept: text/html' -H 'Cookie: session=secret; x=1'"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "cookie.headers"
            result = subprocess.run(
                [sys.executable, "-B", str(COOKIE_SCRIPT), "--output", str(output)],
                input=copied,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), "Cookie: session=secret; x=1\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertNotIn("secret", result.stdout)

    def test_payload_rows_supports_training_api_models(self) -> None:
        rows = activities.payload_rows({"models": [{"id": 1}, {"id": 2}]})
        self.assertEqual([row["id"] for row in rows], [1, 2])

    def test_cookie_extractor_accepts_browser_cookie_argument(self) -> None:
        copied = "curl 'https://www.strava.com/athlete/training' --cookie 'session=secret; x=1'"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "cookie.headers"
            result = subprocess.run(
                [sys.executable, "-B", str(COOKIE_SCRIPT), "--output", str(output)],
                input=copied,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), "Cookie: session=secret; x=1\n")
            self.assertNotIn("secret", result.stdout)

    def test_cookie_extractor_accepts_safari_multiline_flags(self) -> None:
        copied = "curl 'https://www.strava.com/athlete/training' \\\n-H 'Cookie: session=secret; x=1'"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "cookie.headers"
            result = subprocess.run(
                [sys.executable, "-B", str(COOKIE_SCRIPT), "--output", str(output)],
                input=copied,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), "Cookie: session=secret; x=1\n")

    def test_bike_name_and_edit_readback(self) -> None:
        self.assertEqual(metadata.resolve_bike_id(EDIT_HTML, None, "kickr bike v2 (HJEME)"), "15590716")
        self.assertEqual(
            metadata.edit_state(EDIT_HTML),
            {"start_time_hidden": True, "bike_id": "15590716", "bike_name": "Kickr Bike v2 (hjeme)"},
        )

    def test_form_preserves_tag_and_sends_react_visibility(self) -> None:
        body = metadata.build_form_body(
            EDIT_HTML,
            activity_name=None,
            tag=None,
            tag_supplied=False,
            current_tag="Workout",
            trainer=None,
            visibility="everyone",
            start_time_hidden=None,
            bike_id=None,
        )
        pairs = urllib.parse.parse_qs(body, keep_blank_values=True)
        self.assertEqual(pairs["activity[tags][]"], ["", "Workout"])
        self.assertEqual(pairs["activity[visibility]"], ["everyone"])
        self.assertEqual(pairs["activity[bike_id]"], ["15590716"])

    def test_explicit_clear_removes_existing_tag(self) -> None:
        body = metadata.build_form_body(
            EDIT_HTML,
            activity_name=None,
            tag=None,
            tag_supplied=True,
            current_tag="Workout",
            trainer=None,
            visibility=None,
            start_time_hidden=None,
            bike_id=None,
        )
        pairs = urllib.parse.parse_qs(body, keep_blank_values=True)
        self.assertEqual(pairs["activity[tags][]"], [""])

    def test_form_updates_name_without_changing_other_fields(self) -> None:
        edit_html = EDIT_HTML.replace(
            '<input name="authenticity_token" value="token">',
            '<input name="authenticity_token" value="token"><input name="activity[name]" value="Old name">',
        )
        body = metadata.build_form_body(
            edit_html,
            activity_name="Fjällbacka diverse",
            tag=None,
            tag_supplied=False,
            current_tag=None,
            trainer=None,
            visibility=None,
            start_time_hidden=None,
            bike_id=None,
        )
        pairs = urllib.parse.parse_qs(body, keep_blank_values=True)
        self.assertEqual(pairs["activity[name]"], ["Fjällbacka diverse"])
        self.assertEqual(pairs["activity[bike_id]"], ["15590716"])


if __name__ == "__main__":
    unittest.main()
