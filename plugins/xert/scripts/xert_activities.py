"""Xert activity access."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Any
from urllib.request import Request

from xert_common import (
    XERT_API_BASE_URL,
    XertCredentials,
    _date_to_unix,
    _open_text,
    _request_json,
    xert_web_login,
)


def list_activities(
    *,
    username: str | None = None,
    password: str | None = None,
    oldest: str | date,
    newest: str | date,
) -> list[dict[str, Any]]:
    """List Xert activities for a date range."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    activities = _request_json(
        "/oauth/activity",
        credentials.bearer_token(),
        params={
            "from": _date_to_unix(oldest),
            "to": _date_to_unix(newest, end_of_day=True),
        },
    )
    if not isinstance(activities, dict) or not isinstance(activities.get("activities"), list):
        raise TypeError("Expected Xert activity endpoint to return an activities list")
    return activities["activities"]

def fetch_activity_detail(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    include_session_data: bool = False,
) -> dict[str, Any]:
    """Fetch one Xert activity detail document."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    detail = _request_json(
        f"/oauth/activity/{path}",
        credentials.bearer_token(),
        params={"include_session_data": 1 if include_session_data else 0},
    )
    if not isinstance(detail, dict):
        raise TypeError("Expected Xert activity detail endpoint to return an object")
    return detail


def list_activity_details(
    *,
    username: str | None = None,
    password: str | None = None,
    oldest: str | date,
    newest: str | date,
    include_session_data: bool = False,
) -> list[dict[str, Any]]:
    """List activities and fetch compact detail documents using one token."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    token = credentials.bearer_token()
    activities = _request_json(
        "/oauth/activity",
        token,
        params={
            "from": _date_to_unix(oldest),
            "to": _date_to_unix(newest, end_of_day=True),
        },
    )
    if not isinstance(activities, dict) or not isinstance(activities.get("activities"), list):
        raise TypeError("Expected Xert activity endpoint to return an activities list")

    details: list[dict[str, Any]] = []
    for activity in activities["activities"]:
        if not isinstance(activity, dict) or not activity.get("path"):
            continue
        detail = _request_json(
            f"/oauth/activity/{activity['path']}",
            token,
            params={"include_session_data": 1 if include_session_data else 0},
        )
        if not isinstance(detail, dict):
            raise TypeError("Expected Xert activity detail endpoint to return an object")
        detail["path"] = activity.get("path")
        detail["activity_list_row"] = activity
        details.append(detail)
    return details


def fetch_activity_event_metadata_for_starts(
    start_dates: list[str], *, username: str | None = None, password: str | None = None
) -> dict[str, dict[str, Any]]:
    """Fetch breakthrough/manual metadata for selected activity start times."""

    if not start_dates:
        return {}
    credentials = XertCredentials(username=username, password=password)
    token = credentials.bearer_token()

    def key(value: Any) -> str | None:
        if isinstance(value, dict):
            value = value.get("date")
        if not isinstance(value, str):
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    targets = {key(value) for value in start_dates}
    targets.discard(None)
    parsed_targets = [datetime.fromisoformat(value) for value in targets]
    activities = _request_json(
        "/oauth/activity",
        token,
        params={
            "from": _date_to_unix(min(parsed_targets).date()),
            "to": _date_to_unix(max(parsed_targets).date(), end_of_day=True),
        },
    )
    if not isinstance(activities, dict) or not isinstance(activities.get("activities"), list):
        raise TypeError("Expected Xert activity endpoint to return an activities list")
    result: dict[str, dict[str, Any]] = {}
    for activity in activities["activities"]:
        if not isinstance(activity, dict) or not activity.get("path"):
            continue
        start_key = key(activity.get("start_date"))
        if start_key not in targets:
            continue
        detail = _request_json(
            f"/oauth/activity/{activity['path']}", token, params={"include_session_data": 0}
        )
        summary = detail.get("summary") if isinstance(detail, dict) else None
        if not isinstance(summary, dict):
            continue
        signature = summary.get("sig") if isinstance(summary.get("sig"), dict) else {}
        result[start_key] = {
            "path": activity["path"],
            "breakthrough": summary.get("breakthrough"),
            "medal": summary.get("medal"),
            "manual": signature.get("manual") is True,
        }
    return result


def fetch_flagged_activity_starts_with_login(
    *, username: str, password: str, per_page: int = 1000
) -> dict[str, dict[str, Any]]:
    """Fetch every activity flagged as an invalid breakthrough."""

    opener = xert_web_login(username=username, password=password)
    page = 1
    result: dict[str, dict[str, Any]] = {}
    while True:
        body = _open_text(
            opener,
            Request(
                f"{XERT_API_BASE_URL}/activities/dashboard?searchFavourites=false&page={page}&perPage={per_page}",
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            ),
            "Xert activities dashboard",
        )
        payload = json.loads(body)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise TypeError("Expected Xert activities dashboard data list")
        for row in rows:
            if not isinstance(row, dict) or row.get("flag") is not True:
                continue
            raw_start = row.get("start_date")
            if not isinstance(raw_start, str):
                continue
            parsed = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            start_key = parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            result[start_key] = {"path": row.get("path"), "flag": True}
        last_page = int(payload.get("last_page") or page)
        if page >= last_page:
            break
        page += 1
    return result
