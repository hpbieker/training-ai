"""Xert workout library and Workout Designer access."""

from __future__ import annotations

import json
import re
from copy import deepcopy
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
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    """List the user's Xert workout library."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    payload = _request_json("/oauth/workouts", access_token or credentials.bearer_token())
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
        keywords = name_filter.casefold().split() if name_filter else []
        if not all(keyword in name.casefold() for keyword in keywords):
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
    access_token: str | None = None,
) -> dict[str, Any]:
    """Fetch one resolved Xert workout using the user's fitness signature."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    payload = _request_json(
        f"/oauth/workout/{path}", access_token or credentials.bearer_token()
    )
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
    expected_matches: int = 1,
    set_duration: str | None = None,
    set_power: float | None = None,
    set_power_type: str | None = None,
    set_power_second_value: float | None = None,
    set_row_name: str | None = None,
    set_interval_count: str | None = None,
    set_rib_duration: str | None = None,
    set_rib_power: float | None = None,
    set_rib_power_type: str | None = None,
    submit: str = "save",
    opener=None,
) -> dict[str, Any]:
    """Update a Xert workout through the authenticated Workout Designer flow."""

    if submit not in {"calculate", "save", "copy"}:
        raise ValueError("submit must be 'calculate', 'save', or 'copy'")
    if opener is None and (not username or not password):
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if not any(
        [
            name,
            description is not None,
            set_duration,
            set_power is not None,
            set_power_type,
            set_power_second_value is not None,
            set_row_name is not None,
            set_interval_count,
            set_rib_duration,
            set_rib_power is not None,
            set_rib_power_type,
        ]
    ):
        raise ValueError("No workout update requested")

    row_change_requested = any(
        [
            set_duration,
            set_power is not None,
            set_power_type,
            set_power_second_value is not None,
            set_row_name is not None,
            set_interval_count,
            set_rib_duration,
            set_rib_power is not None,
            set_rib_power_type,
        ]
    )
    if row_change_requested and not (match_name or match_power is not None):
        raise ValueError("Workout row updates require --match-name or --match-power")
    if expected_matches < 1:
        raise ValueError("expected_matches must be positive")
    if opener is None:
        opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, path)
    rows = fetch_workout_designer_rows(opener, path)
    changed_rows = update_workout_rows(
        rows,
        match_name=match_name,
        match_power=match_power,
        set_duration=set_duration,
        set_power=set_power,
        set_power_type=set_power_type,
        set_power_second_value=set_power_second_value,
        set_row_name=set_row_name,
        set_interval_count=set_interval_count,
        set_rib_duration=set_rib_duration,
        set_rib_power=set_rib_power,
        set_rib_power_type=set_rib_power_type,
    )
    if row_change_requested and changed_rows != expected_matches:
        raise ValueError(
            f"Expected {expected_matches} matching workout row(s), found {changed_rows}"
        )

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
        verification = verify_saved_workout(opener, verification_path, expected_rows=rows)
        if verification is None or not verification["rows_match"]:
            raise RuntimeError("Saved Xert workout rows did not match the requested update")
    timeline_rows = (
        verification["rows"]
        if isinstance(verification, dict) and isinstance(verification.get("rows"), list)
        else rows
    )
    output = {
        "path": path,
        "submit": submit,
        "changed_rows": changed_rows,
        "result": summarize_workout_update_result(result),
        "timeline_summary": workout_timeline_summary(timeline_rows),
    }
    if submit == "copy" and redirect_path:
        output["created_path"] = redirect_path
    if verification is not None:
        output["verification"] = compact_workout_verification(verification)
    return output


def replace_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    rows: list[dict[str, Any]],
    name: str | None = None,
    description: str | None = None,
    submit: str = "calculate",
    opener=None,
) -> dict[str, Any]:
    """Atomically calculate or replace every Workout Designer row."""

    if submit not in {"calculate", "save"}:
        raise ValueError("submit must be 'calculate' or 'save'")
    if opener is None and (not username or not password):
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    normalized_rows = normalize_workout_rows(rows)
    if opener is None:
        opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, path)
    form = workout_designer_form_payload(
        page,
        rows=normalized_rows,
        name=name,
        description=description,
        submit=submit,
    )
    result = post_workout_designer_form(opener, path, form)
    verification = None
    if submit == "save":
        verification = verify_saved_workout(
            opener,
            path,
            expected_rows=normalized_rows,
        )
        if not verification["rows_match"]:
            raise RuntimeError("Saved Xert workout rows did not match the requested replacement")
        if name is not None and verification.get("name") != name:
            raise RuntimeError("Saved Xert workout name did not match the requested replacement")
        if description is not None and verification.get("description") != description:
            raise RuntimeError(
                "Saved Xert workout description did not match the requested replacement"
            )
    timeline_rows = (
        verification["rows"]
        if isinstance(verification, dict) and isinstance(verification.get("rows"), list)
        else normalized_rows
    )
    output = {
        "path": path,
        "submit": submit,
        "replaced_rows": len(normalized_rows),
        "result": summarize_workout_update_result(result),
        "timeline_summary": workout_timeline_summary(timeline_rows),
    }
    if verification is not None:
        output["verification"] = compact_workout_verification(verification)
    return output


def mutate_workout_row(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    operation: str,
    row_number: int,
    row: dict[str, Any] | None = None,
    set_duration: str | None = None,
    set_power: float | None = None,
    set_power_type: str | None = None,
    set_power_second_value: float | None = None,
    set_row_name: str | None = None,
    set_interval_count: str | None = None,
    set_rib_duration: str | None = None,
    set_rib_power: float | None = None,
    set_rib_power_type: str | None = None,
    submit: str = "calculate",
) -> dict[str, Any]:
    """Add, patch, or remove one one-based Workout Designer row."""

    if operation not in {"add", "update", "remove"}:
        raise ValueError("operation must be 'add', 'update', or 'remove'")
    if submit not in {"calculate", "save"}:
        raise ValueError("submit must be 'calculate' or 'save'")
    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if row_number < 1:
        raise ValueError("row_number must be one-based and positive")

    opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, path)
    rows = fetch_workout_designer_rows(opener, path)
    before = None
    after = None

    if operation == "add":
        if row is None:
            raise ValueError("Adding a workout row requires a row object")
        if row_number > len(rows) + 1:
            raise IndexError(
                f"Cannot insert workout row {row_number}; valid positions are 1-{len(rows) + 1}"
            )
        added_row = deepcopy(row)
        if set_power_second_value is not None:
            power = added_row.get("power")
            if not isinstance(power, dict):
                raise TypeError("Added workout row has invalid power object")
            power["second_value"] = set_power_second_value
        rows.insert(row_number - 1, added_row)
        after = rows[row_number - 1]
    else:
        if row_number > len(rows):
            raise IndexError(
                f"Workout row {row_number} does not exist; workout has {len(rows)} rows"
            )
        before = deepcopy(rows[row_number - 1])
        if operation == "remove":
            if len(rows) == 1:
                raise ValueError("Cannot remove the only workout row")
            del rows[row_number - 1]
        else:
            changed = update_workout_rows(
                [rows[row_number - 1]],
                set_duration=set_duration,
                set_power=set_power,
                set_power_type=set_power_type,
                set_power_second_value=set_power_second_value,
                set_row_name=set_row_name,
                set_interval_count=set_interval_count,
                set_rib_duration=set_rib_duration,
                set_rib_power=set_rib_power,
                set_rib_power_type=set_rib_power_type,
            )
            if changed != 1:
                raise ValueError("No workout row update requested")
            after = rows[row_number - 1]

    normalized_rows = normalize_workout_rows(rows)
    if operation == "add":
        after = normalized_rows[row_number - 1]
    elif operation == "update":
        after = normalized_rows[row_number - 1]
    form = workout_designer_form_payload(page, rows=normalized_rows, submit=submit)
    result = post_workout_designer_form(opener, path, form)
    verification = None
    if submit == "save":
        verification = verify_saved_workout(opener, path, expected_rows=normalized_rows)
        if not verification or not verification["rows_match"]:
            raise RuntimeError("Saved Xert workout rows did not match the requested row operation")
    timeline_rows = (
        verification["rows"]
        if isinstance(verification, dict) and isinstance(verification.get("rows"), list)
        else normalized_rows
    )
    output = {
        "path": path,
        "operation": operation,
        "row_number": row_number,
        "submit": submit,
        "before": before,
        "after": after,
        "row_count": len(normalized_rows),
        "result": summarize_workout_update_result(result),
        "timeline_summary": workout_timeline_summary(timeline_rows),
    }
    if verification is not None:
        output["verification"] = compact_workout_verification(verification)
    return output


def calculate_new_workout(
    *,
    username: str | None = None,
    password: str | None = None,
    name: str = "Xert calculate probe",
    description: str = "Calculated by training-ai; not saved.",
    rows: list[dict[str, Any]],
    include_series: bool = False,
    signature_tp: float | None = None,
    signature_hie: float | None = None,
    signature_pp: float | None = None,
) -> dict[str, Any]:
    """Calculate a new unsaved Xert workout through Workout Designer."""

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if not rows:
        raise ValueError("At least one workout row is required")
    signature_override = (signature_tp, signature_hie, signature_pp)
    if any(value is not None for value in signature_override) and not all(
        value is not None for value in signature_override
    ):
        raise ValueError("Set signature_tp, signature_hie, and signature_pp together")
    if all(value is not None for value in signature_override):
        if signature_tp <= 0 or signature_hie <= 0 or signature_pp <= signature_tp:
            raise ValueError("Require TP > 0, HIE > 0, and PP > TP")

    opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, "")
    form = workout_designer_form_payload(
        page,
        rows=rows,
        name=name,
        description=description,
        submit="calculate",
    )
    if signature_tp is not None:
        form["ftp"] = str(signature_tp)
    if signature_hie is not None:
        form["atc"] = str(signature_hie)
    if signature_pp is not None:
        form["pp"] = str(signature_pp)
    form["exclude_from_recommendations"] = "1"
    result = post_workout_designer_form(opener, "", form)
    normalized_rows = normalize_workout_rows(rows)
    output = {
        "submit": "calculate",
        "saved": False,
        "result": summarize_workout_update_result(result),
        "timeline_summary": workout_timeline_summary(normalized_rows),
    }
    if include_series:
        output["signature"] = result.get("sig")
        output["series"] = result.get("data")
        output["calculation_stats"] = result.get("stats")
    return output


def create_workout(
    *,
    username: str | None = None,
    password: str | None = None,
    name: str,
    description: str = "",
    rows: list[dict[str, Any]],
    opener=None,
) -> dict[str, Any]:
    """Create a new workout through the blank Workout Designer and verify it."""

    if opener is None and (not username or not password):
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Workout name must be a non-empty string")
    normalized_rows = normalize_workout_rows(rows)
    if opener is None:
        opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, "")
    form = workout_designer_form_payload(
        page,
        rows=normalized_rows,
        name=name.strip(),
        description=description,
        submit="save",
    )
    result = post_workout_designer_form(opener, "", form)
    created_path = workout_path_from_redirect(result.get("redirect"))
    if not created_path:
        raise RuntimeError("Xert did not return a path for the created workout")
    verification = verify_saved_workout(
        opener,
        created_path,
        expected_rows=normalized_rows,
    )
    if verification is None or not verification.get("rows_match"):
        raise RuntimeError("Created Xert workout rows did not match the requested structure")
    if verification.get("name") != name.strip():
        raise RuntimeError("Created Xert workout name did not match the requested name")
    if verification.get("description") != description:
        raise RuntimeError("Created Xert workout description did not match the requested description")
    verified_rows = verification.get("rows")
    return {
        "path": created_path,
        "saved": True,
        "result": summarize_workout_update_result(result),
        "verification": compact_workout_verification(verification),
        "timeline_summary": workout_timeline_summary(
            verified_rows if isinstance(verified_rows, list) else normalized_rows
        ),
    }


def delete_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    opener=None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Delete a Xert workout through the authenticated web flow."""

    if opener is None and (not username or not password):
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if opener is None:
        opener = xert_web_login(username=username, password=password)
    target = verify_workout_page(opener, path)
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
    remaining = list_workouts(
        username=username,
        password=password,
        access_token=access_token,
    )
    verified_absent = all(str(row.get("path")) != path for row in remaining)
    if not verified_absent:
        raise RuntimeError(f"Xert workout {path} still exists after delete")
    return {
        "path": path,
        "target": target,
        "delete_response": payload,
        "verified_absent": True,
    }

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


def verify_saved_workout(
    opener,
    path: str | None,
    *,
    expected_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Read back workout metadata and rows and compare the saved structure."""

    page = verify_workout_page(opener, path)
    if not path or page is None:
        return page
    actual_rows = normalize_workout_rows(fetch_workout_designer_rows(opener, path))
    expected = normalize_workout_rows(expected_rows)
    return {
        **page,
        "row_count": len(actual_rows),
        "rows_match": canonical_workout_rows(actual_rows) == canonical_workout_rows(expected),
        "rows": actual_rows,
    }


def compact_workout_verification(
    verification: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Omit verbose readback rows from normal mutation output."""

    if verification is None:
        return None
    return {key: value for key, value in verification.items() if key != "rows"}


def normalize_workout_duration(
    value: Any,
    *,
    field: str = "duration",
    allow_zero: bool = False,
) -> str:
    """Validate MM:SS or HH:MM:SS and return Xert-safe notation."""

    if isinstance(value, bool):
        raise ValueError(f"{field} must use MM:SS or HH:MM:SS")
    if isinstance(value, (int, float)):
        if value == 0 and allow_zero:
            return "00:00"
        raise ValueError(f"{field} must use MM:SS or HH:MM:SS")
    if not isinstance(value, str):
        raise ValueError(f"{field} must use MM:SS or HH:MM:SS")

    text = value.strip()
    parts = text.split(":")
    if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
        raise ValueError(f"{field} must use MM:SS or HH:MM:SS, got {value!r}")

    if len(parts) == 2:
        minutes, seconds = (int(part) for part in parts)
        if seconds >= 60:
            raise ValueError(f"{field} seconds must be between 00 and 59")
        total_seconds = minutes * 60 + seconds
    else:
        hours, minutes, seconds = (int(part) for part in parts)
        if minutes >= 60:
            raise ValueError(f"{field} minutes must be between 00 and 59 in HH:MM:SS")
        if seconds >= 60:
            raise ValueError(f"{field} seconds must be between 00 and 59")
        total_seconds = hours * 3600 + minutes * 60 + seconds

    if total_seconds == 0 and not allow_zero:
        raise ValueError(f"{field} must be greater than zero")

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def normalize_workout_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalize a complete Workout Designer row list."""

    if not isinstance(rows, list) or not rows:
        raise ValueError("Workout replacement requires a non-empty rows array")
    normalized: list[dict[str, Any]] = []
    for sequence, source in enumerate(rows):
        if not isinstance(source, dict):
            raise TypeError(f"Workout row {sequence} must be an object")
        row = deepcopy(source)
        for field in ("duration", "power", "rib_duration", "rib_power"):
            if not isinstance(row.get(field), dict):
                raise TypeError(f"Workout row {sequence} has invalid {field} object")
        row["duration"]["value"] = normalize_workout_duration(
            row["duration"].get("value"),
            field=f"workout row {sequence + 1} duration",
        )
        row["rib_duration"]["value"] = normalize_workout_duration(
            row["rib_duration"].get("value"),
            field=f"workout row {sequence + 1} rib_duration",
            allow_zero=True,
        )
        row["sequence"] = sequence
        row["DT_RowId"] = ""
        row["name"] = str(row.get("name") or f"Row {sequence + 1}")
        interval_count = row.get("interval_count")
        row["interval_count"] = "1" if interval_count is None else str(interval_count)
        normalized.append(row)
    return normalized


def canonical_workout_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep stable row fields for exact post-save verification."""

    def stable_value(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {
            key: value.get(key)
            for key in ("type", "value", "second_value")
            if key in value
        }

    return [
        {
            "sequence": row.get("sequence"),
            "name": row.get("name"),
            "duration": stable_value(row.get("duration")),
            "power": stable_value(row.get("power")),
            "interval_count": (
                "1" if row.get("interval_count") is None else str(row.get("interval_count"))
            ),
            "rib_duration": stable_value(row.get("rib_duration")),
            "rib_power": stable_value(row.get("rib_power")),
        }
        for row in rows
    ]


def workout_timeline_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Expand Designer rows into a compact chronological, human-readable summary."""

    normalized_rows = normalize_workout_rows(rows)
    segments: list[dict[str, Any]] = []
    cursor = 0
    for row in normalized_rows:
        count = int(row["interval_count"])
        if count < 0:
            raise ValueError("workout row interval_count must be non-negative")
        if count == 0:
            continue
        duration = workout_duration_seconds(row["duration"]["value"])
        rib_duration = workout_duration_seconds(row["rib_duration"]["value"])
        base_name = timeline_base_name(str(row["name"]), count=count)
        for repeat_index in range(1, count + 1):
            name = base_name if count == 1 else f"{base_name} {repeat_index}/{count}"
            end = cursor + duration
            segments.append(
                {
                    "start": cursor,
                    "end": end,
                    "duration": duration,
                    "name": name,
                    "power": describe_workout_power(row["power"]),
                }
            )
            cursor = end
            if rib_duration:
                end = cursor + rib_duration
                segments.append(
                    {
                        "start": cursor,
                        "end": end,
                        "duration": rib_duration,
                        "name": f"Rest after {name}",
                        "power": describe_workout_power(row["rib_power"]),
                    }
                )
                cursor = end
    return {"duration": cursor, "segments": segments}


def workout_duration_seconds(value: str) -> int:
    """Convert normalized MM:SS or HH:MM:SS notation to seconds."""

    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds


def timeline_base_name(name: str, *, count: int) -> str:
    """Keep single rows intact and shorten obvious repeated-block labels."""

    if count == 1:
        return name
    match = re.match(r"^(.+?)\s+\d+\s*x\s+.+$", name, flags=re.IGNORECASE)
    return match.group(1).strip() if match else name


def describe_workout_power(power: dict[str, Any]) -> str:
    """Render one Designer power object as compact text for timeline summaries."""

    power_type = str(power.get("type") or "absolute")
    value = format_power_number(power.get("value"))
    second_value = power.get("second_value")
    if power_type == "absolute":
        return f"{value} W"
    if power_type == "relative_ftp":
        return f"{value} % FTP"
    if power_type == "relative_ltp":
        return f"{value} % LTP"
    if power_type in {"ramp_ltp", "ramp_ftp"} and second_value is not None:
        reference = "LTP" if power_type == "ramp_ltp" else "FTP"
        return f"{value}–{format_power_number(second_value)} % {reference}"
    if second_value is not None:
        return f"{power_type}: {value} → {format_power_number(second_value)}"
    return f"{power_type}: {value}"


def format_power_number(value: Any) -> str:
    """Format numeric Designer values without unnecessary decimal zeroes."""

    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def update_workout_rows(
    rows: list[dict[str, Any]],
    *,
    match_name: str | None = None,
    match_power: float | None = None,
    set_duration: str | None = None,
    set_power: float | None = None,
    set_power_type: str | None = None,
    set_power_second_value: float | None = None,
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
            set_power_type,
            set_power_second_value is not None,
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
            duration["value"] = normalize_workout_duration(
                set_duration,
                field="set_duration",
            )
            duration.setdefault("type", "absolute")
        if set_power is not None or set_power_type is not None or set_power_second_value is not None:
            power = row.setdefault("power", {})
            if not isinstance(power, dict):
                raise TypeError(f"Workout row has invalid power object: {row}")
            if set_power is not None:
                power["value"] = set_power
            if set_power_type is not None:
                power["type"] = set_power_type
            else:
                power.setdefault("type", "absolute")
            if set_power_second_value is not None:
                power["second_value"] = set_power_second_value
        if set_row_name is not None:
            row["name"] = set_row_name
        if set_interval_count is not None:
            row["interval_count"] = set_interval_count
        if set_rib_duration is not None:
            rib_duration = row.setdefault("rib_duration", {})
            if not isinstance(rib_duration, dict):
                raise TypeError(f"Workout row has invalid rib_duration object: {row}")
            rib_duration["value"] = normalize_workout_duration(
                set_rib_duration,
                field="set_rib_duration",
                allow_zero=True,
            )
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

    normalized_rows = normalize_workout_rows(rows)
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
        "rows": json.dumps(normalized_rows, separators=(",", ":")),
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
    compact: dict[str, Any] = {}
    for key in ("redirect", "error", "info"):
        if payload.get(key):
            compact[key] = payload[key]
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
