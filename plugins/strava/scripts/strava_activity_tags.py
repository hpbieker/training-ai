#!/usr/bin/env python3
"""Read or update Strava activity metadata using Python HTTP.

The persistent private session cache contains exactly one ``Cookie:`` header.
The parsed cookie value exists only in the Python process memory.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from strava_route_api import StravaError, StravaSession, default_cookie_file


SESSION: StravaSession | None = None

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
        self._option: dict[str, Any] | None = None
        self._textarea: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k: (v or "") for k, v in attrs}
        if tag == "input":
            self.inputs.append(data)
        elif tag == "select":
            self._select = {"attrs": data, "options": []}
        elif tag == "option" and self._select is not None:
            self._option = {"attrs": data, "text": ""}
        elif tag == "textarea":
            self._textarea = {"attrs": data, "text": ""}

    def handle_data(self, data: str) -> None:
        if self._option is not None:
            self._option["text"] += data
        if self._textarea is not None:
            self._textarea["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._option is not None and self._select is not None:
            self._select["options"].append(self._option)
            self._option = None
        elif tag == "select" and self._select is not None:
            self.selects.append(self._select)
            self._select = None
        elif tag == "textarea" and self._textarea is not None:
            self.textareas.append(self._textarea)
            self._textarea = None


def session() -> StravaSession:
    if SESSION is None:
        raise RuntimeError("Strava session was not configured.")
    return SESSION


def normalize_tag(value: str | None) -> str | None:
    if value is None or value.lower() in {"", "none", "clear"}:
        return None
    key = value.strip().lower().replace(" ", "-")
    return TAG_ALIASES.get(key, value)


def fetch_activity(activity_id: str) -> dict[str, Any]:
    try:
        body, _, _ = session().request(
            f"https://www.strava.com/athlete/training_activities/{activity_id}",
            headers=[
                "Accept: application/json, text/javascript, */*; q=0.01",
                "X-Requested-With: XMLHttpRequest",
                "Referer: https://www.strava.com/athlete/training",
            ],
        )
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise StravaError("Strava returned non-JSON activity data.") from exc


def fetch_edit(activity_id: str) -> str:
    body, _, _ = session().request(f"https://www.strava.com/activities/{activity_id}/edit")
    return body.decode("utf-8", errors="ignore")


def tag_props(edit_html: str) -> dict[str, Any]:
    match = re.search(r"data-react-class='ActivityTagInput' data-react-props='([^']+)'", edit_html)
    if not match:
        return {}
    return json.loads(html.unescape(match.group(1)))


def selected_form_value(select: dict[str, Any]) -> str:
    for option in select["options"]:
        attrs = option["attrs"]
        if "selected" in attrs:
            return attrs.get("value", "")
    return ""


def resolve_bike_id(edit_html: str, bike_id: str | None, bike_name: str | None) -> str | None:
    if bike_id is not None:
        return bike_id
    if bike_name is None:
        return None
    parser = EditFormParser()
    parser.feed(edit_html)
    matches = [
        option["attrs"].get("value", "")
        for select in parser.selects
        if select["attrs"].get("name") == "activity[bike_id]"
        for option in select["options"]
        if html.unescape(option["text"]).strip().casefold() == bike_name.strip().casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one bike named {bike_name!r}, found {len(matches)}.")
    return matches[0]


def build_form_body(
    edit_html: str,
    *,
    activity_name: str | None,
    tag: str | None,
    tag_supplied: bool,
    current_tag: str | None,
    trainer: bool | None,
    visibility: str | None,
    start_time_hidden: bool | None,
    bike_id: str | None,
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
        value = html.unescape(item.get("value", ""))
        if name == "activity[name]" and activity_name is not None:
            value = activity_name
        pairs.append((name, value))

    for select in parser.selects:
        name = select["attrs"].get("name")
        if not name:
            continue
        value = selected_form_value(select)
        if name == "activity[bike_id]" and bike_id is not None:
            value = bike_id
        pairs.append((name, value))

    for textarea in parser.textareas:
        name = textarea["attrs"].get("name")
        if name:
            pairs.append((name, html.unescape(textarea["text"])))

    effective_tag = tag if tag_supplied else current_tag
    pairs.append(("activity[tags][]", ""))
    if effective_tag:
        pairs.append(("activity[tags][]", effective_tag))

    # Visibility is rendered by React rather than as a normal select.
    if visibility is not None:
        pairs = [(key, value) for key, value in pairs if key != "activity[visibility]"]
        pairs.append(("activity[visibility]", visibility))

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
    activity_name: str | None,
    tag: str | None,
    tag_supplied: bool,
    trainer: bool | None,
    visibility: str | None,
    start_time_hidden: bool | None,
    bike_id: str | None,
    bike_name: str | None,
) -> dict[str, Any]:
    edit_html = fetch_edit(activity_id)
    before = fetch_activity(activity_id)
    resolved_bike_id = resolve_bike_id(edit_html, bike_id, bike_name)
    body = build_form_body(
        edit_html,
        activity_name=activity_name,
        tag=tag,
        tag_supplied=tag_supplied,
        current_tag=before.get("selected_tag_type"),
        trainer=trainer,
        visibility=visibility,
        start_time_hidden=start_time_hidden,
        bike_id=resolved_bike_id,
    ).encode("utf-8")
    session().request(
        f"https://www.strava.com/activities/{activity_id}",
        method="POST",
        headers=[
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type: application/x-www-form-urlencoded",
            "Origin: https://www.strava.com",
            f"Referer: https://www.strava.com/activities/{activity_id}/edit",
        ],
        data=body,
    )

    expected: dict[str, Any] = {}
    if activity_name is not None:
        expected["name"] = activity_name
    if tag_supplied:
        expected["tag"] = tag
    if trainer is not None:
        expected["trainer"] = trainer
    if visibility is not None:
        expected["visibility"] = visibility
    if start_time_hidden is not None:
        expected["start_time_hidden"] = start_time_hidden
    if resolved_bike_id is not None:
        expected["bike_id"] = str(resolved_bike_id)

    deadline = time.monotonic() + 5.0
    last_unverified: list[str] = sorted(expected)
    while True:
        activity = fetch_activity(activity_id)
        edit_html = fetch_edit(activity_id)
        edit = edit_state(edit_html)
        props = tag_props(edit_html)
        selected_tags = [
            option.get("gqlString")
            for option in props.get("tagOptions", [])
            if option.get("selected")
        ]
        actual = {
            "name": activity.get("name"),
            "tag": selected_tags[0] if selected_tags else None,
            "trainer": bool(activity.get("trainer")),
            "visibility": activity.get("visibility"),
            "start_time_hidden": bool(edit.get("start_time_hidden")),
            "bike_id": str(edit.get("bike_id")) if edit.get("bike_id") is not None else None,
        }
        last_unverified = [field for field, value in expected.items() if actual.get(field) != value]
        if not last_unverified:
            activity["_edit_html"] = edit_html
            activity["_verified_fields"] = sorted(expected)
            return activity
        if time.monotonic() >= deadline:
            fields = ", ".join(last_unverified)
            raise StravaError(
                f"Strava accepted the update request, but readback did not confirm: {fields}. "
                "The activity may be partially updated."
            )
        time.sleep(0.4)


def edit_state(edit_html: str) -> dict[str, Any]:
    parser = EditFormParser()
    parser.feed(edit_html)
    state: dict[str, Any] = {}
    for item in parser.inputs:
        if item.get("name") == "activity[stats_visibility][start_time]" and item.get("value") == "only_me":
            state["start_time_hidden"] = "checked" in item
    for select in parser.selects:
        if select["attrs"].get("name") == "activity[bike_id]":
            for option in select["options"]:
                if "selected" in option["attrs"]:
                    state["bike_id"] = option["attrs"].get("value") or None
                    state["bike_name"] = html.unescape(option["text"]).strip() or None
    return state


def summarize(activity: dict[str, Any]) -> dict[str, Any]:
    tags = activity.get("tags") or {}
    result = {
        "id": activity.get("id"),
        "name": activity.get("name"),
        "start_date_local": activity.get("start_date_local") or activity.get("start_date_local_raw"),
        "visibility": activity.get("visibility"),
        "private": activity.get("private"),
        "trainer": activity.get("trainer"),
        "bike_id": activity.get("bike_id"),
        "selected_tag_type": activity.get("selected_tag_type"),
        "true_tag_ids": sorted([str(k) for k, v in tags.items() if v is True], key=lambda v: int(v) if v.isdigit() else v),
        "tags": tags,
    }
    if activity.get("_edit_html"):
        result.update(edit_state(activity["_edit_html"]))
    if "_verified_fields" in activity:
        result["verified_fields"] = list(activity["_verified_fields"])
    return result


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
    global SESSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("activity_id", nargs="+")
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=default_cookie_file(),
        help="Private Cookie header file (default: STRAVA_COOKIE_FILE or ~/.strava/session.headers)",
    )
    parser.add_argument(
        "--header-file",
        type=Path,
        help="Optional private header file for non-cookie browser headers",
    )
    parser.add_argument("--read", action="store_true", help="Read activity tag state only")
    parser.add_argument("--name", help="Set the activity name")
    parser.add_argument("--tag", help="Set primary tag, e.g. Workout, Recovery, WithKid, none")
    parser.add_argument("--trainer", type=parse_bool, default=None, help="Set indoor trainer flag: true, false, or keep")
    parser.add_argument("--visibility", choices=["everyone", "followers_only", "only_me"])
    parser.add_argument("--start-time-hidden", type=parse_bool, default=None, help="Set start time hidden: true, false, or keep")
    bike_group = parser.add_mutually_exclusive_group()
    bike_group.add_argument("--bike-id", help="Set the exact Strava bike ID")
    bike_group.add_argument("--bike-name", help="Set a bike by exact edit-form name")
    args = parser.parse_args()
    read_only = args.read or (
        args.name is None and args.tag is None and args.trainer is None and args.visibility is None
        and args.start_time_hidden is None and args.bike_id is None and args.bike_name is None
    )
    results = []
    try:
        with StravaSession(args.cookie_file, args.header_file) as SESSION:
            for activity_id in args.activity_id:
                if read_only:
                    activity = fetch_activity(activity_id)
                    activity["_edit_html"] = fetch_edit(activity_id)
                else:
                    activity = update_activity(
                        activity_id,
                        activity_name=args.name,
                        tag=normalize_tag(args.tag),
                        tag_supplied=args.tag is not None,
                        trainer=args.trainer,
                        visibility=args.visibility,
                        start_time_hidden=args.start_time_hidden,
                        bike_id=args.bike_id,
                        bike_name=args.bike_name,
                    )
                results.append(summarize(activity))
    except (OSError, StravaError, ValueError) as exc:
        parser.error(str(exc))
    payload: Any = results[0] if len(results) == 1 else results
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
