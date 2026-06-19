"""Xert activity access."""

from __future__ import annotations

from datetime import date
from typing import Any

from xert_common import XertCredentials, _date_to_unix, _request_json


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
