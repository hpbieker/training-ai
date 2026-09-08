"""List and filter authenticated Strava activities with Python HTTP."""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import uuid
from typing import Any

from strava_route_api import StravaError, StravaSession


BASE_URL = "https://www.strava.com/athlete/training_activities"


def payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("models", "activities", "results", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise StravaError("Strava returned an unsupported activity-list response.")


def activity_date(row: dict[str, Any]) -> dt.date | None:
    value = row.get("start_time") or row.get("start_date_local") or row.get("start_date_local_raw") or row.get("start_date")
    if not value:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).date()
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def normalized_activity(row: dict[str, Any]) -> dict[str, Any]:
    visibility = row.get("visibility")
    if visibility is None and row.get("private") is not None:
        visibility = "only_me" if row.get("private") else "everyone"
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "start_date_local": row.get("start_time") or row.get("start_date_local"),
        "type": row.get("type") or row.get("sport_type"),
        "visibility": visibility,
        "private": row.get("private"),
        "trainer": row.get("trainer"),
        "bike_id": row.get("bike_id"),
        "selected_tag_type": row.get("selected_tag_type"),
        "elapsed_time_raw": row.get("elapsed_time_raw"),
        "moving_time_raw": row.get("moving_time_raw"),
        "distance_raw": row.get("distance_raw"),
        "elevation_gain_raw": row.get("elevation_gain_raw"),
        "suffer_score": row.get("suffer_score"),
        "commute": row.get("commute"),
        "has_latlng": row.get("has_latlng"),
    }


def fetch_page(session: StravaSession, page: int, per_page: int) -> Any:
    query = urllib.parse.urlencode({
        "keywords": "", "sport_type": "", "tags": "", "commute": "",
        "private_activities": "", "trainer": "", "gear": "",
        "search_session_id": str(uuid.uuid4()), "new_activity_only": "false",
        "page": page, "per_page": per_page,
    })
    try:
        body, _, _ = session.request(
            f"{BASE_URL}?{query}",
            headers=[
                "Accept: application/json, text/javascript, */*; q=0.01",
                "X-Requested-With: XMLHttpRequest",
                "Referer: https://www.strava.com/athlete/training",
            ],
        )
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise StravaError("Strava activity list returned non-JSON content; refresh authentication.") from exc
