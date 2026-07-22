#!/usr/bin/env python3
"""Read or update Strava activity tags using Safari-authenticated curl.

This script intentionally does not print or persist Strava cookies. It uses a
temporary cookie jar so the CSRF token fetched from the edit page is posted with
the matching session cookie.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


CURL_SAFARI = "/Users/hanspetterbieker/sources/curl-safari/bin/curl-safari"

TAG_ALIASES = {
    "race": "Race",
    "lop": "Race",
    "løp": "Race",
    "workout": "Workout",
    "treningsokt": "Workout",
    "treningsøkt": "Workout",
    "commute": "Commute",
    "pendling": "Commute",
    "foracause": "ForACause",
    "for_a_cause": "ForACause",
    "for-en-god-sak": "ForACause",
    "recovery": "Recovery",
    "restitusjon": "Recovery",
    "withkid": "WithKid",
    "with_kid": "WithKid",
    "med-barn": "WithKid",
    "withpet": "WithPet",
    "with_pet": "WithPet",
    "med-kjaeledyr": "WithPet",
    "med-kjæledyr": "WithPet",
}


class EditFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str]] = []
        self.selects: list[dict[str, Any]] = []
        self.textareas: list[dict[str, Any]] = []
        self._select: dict[str, Any] | None = None
        self._textarea: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k: (v or "") for k, v in attrs}
        if tag == "input":
            self.inputs.append(data)
        elif tag == "select":
            self._select = {"attrs": data, "options": []}
        elif tag == "option" and self._select is not None:
            self._select["options"].append(data)
        elif tag == "textarea":
            self._textarea = {"attrs": data, "text": ""}

    def handle_data(self, data: str) -> None:
        if self._textarea is not None:
            self._textarea["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._select is not None:
            self.selects.append(self._select)
            self._select = None
        elif tag == "textarea" and self._textarea is not None:
            self.textareas.append(self._textarea)
            self._textarea = None


def run_curl(args: list[str]) -> None:
    result = subprocess.run(
        [CURL_SAFARI, *args],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def normalize_tag(value: str | None) -> str | None:
    if value is None or value.lower() in {"", "none", "clear"}:
        return None
    key = value.strip().lower().replace(" ", "-")
    return TAG_ALIASES.get(key, value)


def fetch_activity(activity_id: str, jar: str | None = None) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out = tmp.name
    args = [
        "-L",
        "-H",
        "Accept: application/json, text/javascript, */*; q=0.01",
        "-H",
        "X-Requested-With: XMLHttpRequest",
        "-H",
        "Referer: https://www.strava.com/athlete/training",
    ]
    if jar:
        args.extend(["-b", jar])
    args.extend([f"https://www.strava.com/athlete/training_activities/{activity_id}", "-o", out])
    try:
        run_curl(args)
        return json.loads(Path(out).read_text())
    finally:
        Path(out).unlink(missing_ok=True)


def fetch_edit(activity_id: str, jar: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        out = tmp.name
    try:
        run_curl([
            "-L",
            "-b",
            jar,
            "-c",
            jar,
            f"https://www.strava.com/activities/{activity_id}/edit",
            "-o",
            out,
        ])
        return Path(out).read_text(encoding="utf-8", errors="ignore")
    finally:
        Path(out).unlink(missing_ok=True)


def tag_props(edit_html: str) -> dict[str, Any]:
    match = re.search(r"data-react-class='ActivityTagInput' data-react-props='([^']+)'", edit_html)
    if not match:
        return {}
    return json.loads(html.unescape(match.group(1)))


def selected_form_value(select: dict[str, Any]) -> str:
    for option in select["options"]:
        if "selected" in option:
            return option.get("value", "")
    return ""


def build_form_body(
    edit_html: str,
    *,
    tag: str | None,
    trainer: bool | None,
    visibility: str | None,
    start_time_hidden: bool | None,
) -> str:
    parser = EditFormParser()
    parser.feed(edit_html)
    pairs: list[tuple[str, str]] = []

    for item in parser.inputs:
        name = item.get("name")
        if not name:
            continue
        if name.startswith("activity[tags]") or name == "activity[trainer]":
            continue
        input_type = item.get("type", "text").lower()
        if input_type in {"checkbox", "radio"} and "checked" not in item:
            continue
        if name == "activity[stats_visibility][start_time]" and item.get("value") == "only_me":
            if start_time_hidden is False:
                continue
        pairs.append((name, html.unescape(item.get("value", ""))))

    for select in parser.selects:
        name = select["attrs"].get("name")
        if not name:
            continue
        value = selected_form_value(select)
        if name == "activity[visibility]" and visibility is not None:
            value = visibility
        pairs.append((name, value))

    for textarea in parser.textareas:
        name = textarea["attrs"].get("name")
        if name:
            pairs.append((name, html.unescape(textarea["text"])))

    pairs.append(("activity[tags][]", ""))
    if tag:
        pairs.append(("activity[tags][]", tag))

    props = tag_props(edit_html)
    current_trainer = bool((props.get("trainerOption") or {}).get("selected"))
    trainer_value = current_trainer if trainer is None else trainer
    pairs.append(("activity[trainer]", "0"))
    if trainer_value:
        pairs.append(("activity[trainer]", "1"))

    if start_time_hidden is True and not any(
        key == "activity[stats_visibility][start_time]" and value == "only_me"
        for key, value in pairs
    ):
        pairs.append(("activity[stats_visibility][start_time]", "only_me"))

    pairs.append(("commit", "Save"))
    return urllib.parse.urlencode(pairs, doseq=True)


def update_activity(
    activity_id: str,
    *,
    tag: str | None,
    trainer: bool | None,
    visibility: str | None,
    start_time_hidden: bool | None,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(prefix="strava-activity-", suffix=".cookies", delete=False) as cookie_file:
        jar = cookie_file.name
    body_path = None
    out_path = None
    try:
        edit_html = fetch_edit(activity_id, jar)
        body = build_form_body(
            edit_html,
            tag=tag,
            trainer=trainer,
            visibility=visibility,
            start_time_hidden=start_time_hidden,
        )
        with tempfile.NamedTemporaryFile(prefix="strava-activity-", suffix=".body", delete=False, mode="w") as body_file:
            body_file.write(body)
            body_path = body_file.name
        with tempfile.NamedTemporaryFile(prefix="strava-activity-", suffix=".html", delete=False) as out_file:
            out_path = out_file.name
        run_curl([
            "-sS",
            "-L",
            "-b",
            jar,
            "-c",
            jar,
            f"https://www.strava.com/activities/{activity_id}",
            "-H",
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H",
            "Content-Type: application/x-www-form-urlencoded",
            "-H",
            "Origin: https://www.strava.com",
            "-H",
            f"Referer: https://www.strava.com/activities/{activity_id}/edit",
            "--data-binary",
            f"@{body_path}",
            "-o",
            out_path,
        ])
        time.sleep(1.0)
        return fetch_activity(activity_id, jar)
    finally:
        for path in (jar, body_path, out_path):
            if path:
                Path(path).unlink(missing_ok=True)


def summarize(activity: dict[str, Any]) -> dict[str, Any]:
    tags = activity.get("tags") or {}
    return {
        "id": activity.get("id"),
        "name": activity.get("name"),
        "visibility": activity.get("visibility"),
        "private": activity.get("private"),
        "trainer": activity.get("trainer"),
        "selected_tag_type": activity.get("selected_tag_type"),
        "true_tag_ids": sorted([str(k) for k, v in tags.items() if v is True], key=lambda v: int(v) if v.isdigit() else v),
        "tags": tags,
    }


def parse_bool(value: str) -> bool | None:
    value = value.lower()
    if value == "keep":
        return None
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true, false, or keep")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("activity_id")
    parser.add_argument("--read", action="store_true", help="Read activity tag state only")
    parser.add_argument("--tag", help="Set primary tag, e.g. Workout, Recovery, WithKid, none")
    parser.add_argument("--trainer", type=parse_bool, default=None, help="Set indoor trainer flag: true, false, or keep")
    parser.add_argument("--visibility", choices=["everyone", "followers_only", "only_me"])
    parser.add_argument("--start-time-hidden", type=parse_bool, default=None, help="Set start time hidden: true, false, or keep")
    args = parser.parse_args()

    if args.read or (args.tag is None and args.trainer is None and args.visibility is None and args.start_time_hidden is None):
        activity = fetch_activity(args.activity_id)
    else:
        activity = update_activity(
            args.activity_id,
            tag=normalize_tag(args.tag),
            trainer=args.trainer,
            visibility=args.visibility,
            start_time_hidden=args.start_time_hidden,
        )
    print(json.dumps(summarize(activity), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
