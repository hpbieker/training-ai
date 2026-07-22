"""Xert workout library and Workout Designer access."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request

from xert_common import (
    XERT_API_BASE_URL,
    XertCredentials,
    _extract_html_input_value,
    _extract_html_textarea_value,
    _numbers_equal,
    _numeric_or_none,
    _open_text,
    _parse_float,
    _request_json,
    _round_optional,
    xert_web_login,
)


def list_workouts(
    *,
    username: str | None = None,
    password: str | None = None,
) -> list[dict[str, Any]]:
    """List the user's Xert workout library."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    payload = _request_json("/oauth/workouts", credentials.bearer_token())
    if not isinstance(payload, dict) or not isinstance(payload.get("workouts"), list):
        raise TypeError("Expected Xert workouts endpoint to return a workouts list")
    return payload["workouts"]

def summarize_workout_library(
    workouts: Iterable[dict[str, Any]],
    *,
    name_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return compact workout-library rows for chat/table output."""

    rows = []
    for workout in workouts:
        name = str(workout.get("name") or "")
        if name_filter and name_filter.lower() not in name.lower():
            continue
        rows.append(
            {
                "name": name,
                "path": workout.get("path"),
                "duration_min": _round_optional(_numeric_or_none(workout.get("duration")), 1, scale=60),
                "work_watts": parse_work_watts_from_name(name),
                "xss": _round_optional(_numeric_or_none(workout.get("xss")), 1),
                "xlss": _round_optional(_numeric_or_none(workout.get("xlss")), 1),
                "xhss": _round_optional(_numeric_or_none(workout.get("xhss")), 1),
                "xpss": _round_optional(_numeric_or_none(workout.get("xpss")), 1),
                "difficulty": _round_optional(_numeric_or_none(workout.get("difficulty")), 1),
                "rating": workout.get("rating"),
            }
        )
    return rows

def fetch_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Fetch one resolved Xert workout using the user's fitness signature."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    payload = _request_json(f"/oauth/workout/{path}", credentials.bearer_token())
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert workout endpoint to return an object")
    return payload

def fetch_workout_designer_rows(opener, path: str) -> list[dict[str, Any]]:
    """Fetch editable Xert Workout Designer rows for a workout."""

    request = Request(
        f"{XERT_API_BASE_URL}/workout/{path}/intervals",
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "xert-plugin/0.1 (+Xert workout designer rows)",
        },
    )
    body = _open_text(opener, request, "Xert workout intervals")
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise TypeError("Expected Xert workout intervals endpoint to return data rows")
    return payload["data"]

def update_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    name: str | None = None,
    description: str | None = None,
    match_name: str | None = None,
    match_power: float | None = None,
    set_duration: str | None = None,
    set_power: float | None = None,
    set_row_name: str | None = None,
    set_interval_count: str | None = None,
    set_rib_duration: str | None = None,
    set_rib_power: float | None = None,
    set_rib_power_type: str | None = None,
    submit: str = "save",
) -> dict[str, Any]:
    """Update a Xert workout through the authenticated Workout Designer flow."""

    if submit not in {"calculate", "save", "copy"}:
        raise ValueError("submit must be 'calculate', 'save', or 'copy'")
    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if not any(
        [
            name,
            description is not None,
            set_duration,
            set_power is not None,
            set_row_name is not None,
            set_interval_count,
            set_rib_duration,
            set_rib_power is not None,
            set_rib_power_type,
        ]
    ):
        raise ValueError("No workout update requested")

    opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, path)
    rows = fetch_workout_designer_rows(opener, path)
    changed_rows = update_workout_rows(
        rows,
        match_name=match_name,
        match_power=match_power,
        set_duration=set_duration,
        set_power=set_power,
        set_row_name=set_row_name,
        set_interval_count=set_interval_count,
        set_rib_duration=set_rib_duration,
        set_rib_power=set_rib_power,
        set_rib_power_type=set_rib_power_type,
    )
    if (
        set_duration
        or set_power is not None
        or set_row_name is not None
        or set_interval_count
        or set_rib_duration
        or set_rib_power is not None
        or set_rib_power_type
    ) and changed_rows == 0:
        raise ValueError("No workout rows matched the requested update")

    form = workout_designer_form_payload(
        page,
        rows=rows,
        name=name,
        description=description,
        submit=submit,
    )
    result = post_workout_designer_form(opener, path, form)
    verification = None
    verification_path = path
    redirect_path = workout_path_from_redirect(result.get("redirect"))
    if submit == "copy" and redirect_path:
        verification_path = redirect_path
    if submit in {"save", "copy"}:
        verification = verify_workout_page(opener, verification_path)
    return {
        "path": path,
        "created_path": redirect_path if submit == "copy" else None,
        "submit": submit,
        "changed_rows": changed_rows,
        "result": summarize_workout_update_result(result),
        "verification": verification,
    }


def calculate_new_workout(
    *,
    username: str | None = None,
    password: str | None = None,
    name: str = "Xert calculate probe",
    description: str = "Calculated by training-ai; not saved.",
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate a new unsaved Xert workout through Workout Designer."""

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if not rows:
        raise ValueError("At least one workout row is required")

    opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, "")
    form = workout_designer_form_payload(
        page,
        rows=rows,
        name=name,
        description=description,
        submit="calculate",
    )
    form["exclude_from_recommendations"] = "1"
    result = post_workout_designer_form(opener, "", form)
    return {
        "submit": "calculate",
        "saved": False,
        "result": summarize_workout_update_result(result),
    }


def delete_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Delete a Xert workout through the authenticated web flow."""

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    opener = xert_web_login(username=username, password=password)
    request = Request(
        f"{XERT_API_BASE_URL}/workout/{path}",
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "xert-plugin/0.1 (+Xert workout delete)",
        },
        method="DELETE",
    )
    body = _open_text(opener, request, "Xert workout delete")
    payload = json.loads(body) if body else {}
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert workout delete endpoint to return an object")
    return payload

def fetch_workout_designer_page(opener, path: str) -> dict[str, Any]:
    """Fetch Workout Designer page values needed for update POSTs."""

    workout_url = (
        f"{XERT_API_BASE_URL}/workout" if not path else f"{XERT_API_BASE_URL}/workout/{path}"
    )
    html_text = _open_text(
        opener,
        Request(
            workout_url,
            headers={"User-Agent": "xert-plugin/0.1 (+Xert workout designer page)"},
        ),
        "Xert workout designer",
    )
    token = _extract_html_input_value(html_text, "_token")
    if not token:
        raise RuntimeError("Could not find Xert workout CSRF token")
    atc_kj = _parse_float(_extract_html_input_value(html_text, "atc"))
    return {
        "token": token,
        "name": _extract_html_input_value(html_text, "name") or "",
        "description": _extract_html_textarea_value(html_text, "description") or "",
        "pp": _extract_html_input_value(html_text, "pp") or "",
        "atc": "" if atc_kj is None else str(atc_kj * 1000),
        "ftp": _extract_html_input_value(html_text, "ftp") or "",
    }

def verify_workout_page(opener, path: str | None) -> dict[str, Any] | None:
    """Read back the saved Workout Designer page for compact verification."""

    if not path:
        return None
    page = fetch_workout_designer_page(opener, path)
    return {
        "path": path,
        "name": page.get("name"),
        "description": page.get("description"),
    }

def update_workout_rows(
    rows: list[dict[str, Any]],
    *,
    match_name: str | None = None,
    match_power: float | None = None,
    set_duration: str | None = None,
    set_power: float | None = None,
    set_row_name: str | None = None,
    set_interval_count: str | None = None,
    set_rib_duration: str | None = None,
    set_rib_power: float | None = None,
    set_rib_power_type: str | None = None,
) -> int:
    """Modify editable Workout Designer rows in place."""

    if not any(
        [
            set_duration,
            set_power is not None,
            set_row_name is not None,
            set_interval_count,
            set_rib_duration,
            set_rib_power is not None,
            set_rib_power_type,
        ]
    ):
        return 0
    changed = 0
    for row in rows:
        if match_name and str(row.get("name", "")).lower() != match_name.lower():
            continue
        if match_power is not None:
            power = row.get("power")
            if not isinstance(power, dict) or not _numbers_equal(power.get("value"), match_power):
                continue
        if set_duration:
            duration = row.setdefault("duration", {})
            if not isinstance(duration, dict):
                raise TypeError(f"Workout row has invalid duration object: {row}")
            duration["value"] = set_duration
            duration.setdefault("type", "absolute")
        if set_power is not None:
            power = row.setdefault("power", {})
            if not isinstance(power, dict):
                raise TypeError(f"Workout row has invalid power object: {row}")
            power["value"] = set_power
            power.setdefault("type", "absolute")
        if set_row_name is not None:
            row["name"] = set_row_name
        if set_interval_count is not None:
            row["interval_count"] = set_interval_count
        if set_rib_duration is not None:
            rib_duration = row.setdefault("rib_duration", {})
            if not isinstance(rib_duration, dict):
                raise TypeError(f"Workout row has invalid rib_duration object: {row}")
            rib_duration["value"] = set_rib_duration
            rib_duration.setdefault("type", "absolute")
        if set_rib_power is not None or set_rib_power_type is not None:
            rib_power = row.setdefault("rib_power", {})
            if not isinstance(rib_power, dict):
                raise TypeError(f"Workout row has invalid rib_power object: {row}")
            if set_rib_power is not None:
                rib_power["value"] = set_rib_power
            if set_rib_power_type is not None:
                rib_power["type"] = set_rib_power_type
            else:
                rib_power.setdefault("type", "absolute")
        changed += 1
    return changed

def workout_designer_form_payload(
    page: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    name: str | None = None,
    description: str | None = None,
    submit: str,
) -> dict[str, str]:
    """Build Xert Workout Designer form payload."""

    return {
        "_token": str(page["token"]),
        "name": name if name is not None else str(page.get("name") or ""),
        "focus": "",
        "specRating": "",
        "rating": "",
        "description": (
            description if description is not None else str(page.get("description") or "")
        ),
        "pp": str(page.get("pp") or ""),
        "atc": str(page.get("atc") or ""),
        "ftp": str(page.get("ftp") or ""),
        "submit": submit,
        "rows": json.dumps(rows, separators=(",", ":")),
    }

def post_workout_designer_form(opener, path: str, form: dict[str, str]) -> dict[str, Any]:
    """Post a calculate/save request to Xert Workout Designer."""

    workout_url = (
        f"{XERT_API_BASE_URL}/workout" if not path else f"{XERT_API_BASE_URL}/workout/{path}"
    )
    request = Request(
        workout_url,
        data=urlencode(form).encode("utf-8"),
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": form["_token"],
            "Referer": workout_url,
            "User-Agent": "xert-plugin/0.1 (+Xert workout designer update)",
        },
        method="POST",
    )
    body = _open_text(opener, request, "Xert workout designer update")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert workout update endpoint to return an object")
    return payload

def summarize_workout_update_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary of Xert's verbose workout update response."""

    stats = payload.get("stats")
    compact: dict[str, Any] = {
        "result": payload.get("result"),
        "redirect": payload.get("redirect"),
        "error": payload.get("error"),
        "info": payload.get("info"),
    }
    if isinstance(stats, dict):
        compact["stats"] = {
            key: stats.get(key)
            for key in (
                "duration",
                "xss",
                "xlss",
                "xhss",
                "xpss",
                "difficulty",
                "rating",
                "focus",
                "specRating",
                "specificity",
                "xep",
                "avg_power",
                "max_power",
            )
        }
    if isinstance(payload.get("data"), list):
        compact["data_points"] = len(payload["data"])
    return compact

def workout_path_from_redirect(redirect: Any) -> str | None:
    """Extract the workout path from a Xert workout redirect URL/path."""

    if not redirect:
        return None
    text = str(redirect)
    match = re.search(r"/workout/([^/?#]+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]+", text):
        return text
    return None

def parse_work_watts_from_name(name: str) -> float | None:
    """Extract a trailing work target such as '(205W)' from a workout name."""

    match = re.search(r"\((\d+(?:\.\d+)?)\s*W\)", name, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))
