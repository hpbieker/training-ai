"""Xert activity access."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import re
from urllib.parse import urljoin, urlsplit
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

SUMMARY_FIELDS = (
    "duration_s", "distance_m", "source", "map_url", "signature", "xss",
    "xep_watts", "focus", "specificity", "difficulty", "difficulty_rating",
    "avg_power", "max_power", "avg_heart_rate", "max_heart_rate",
    "avg_cadence", "max_cadence",
)


def _activity_request(path, access_token, *, params=None):
    """Reject API-level failures even when HTTP transport succeeds."""
    payload = _request_json(path, access_token, params=params)
    if isinstance(payload, dict) and (
        payload.get("error") or payload.get("success") is False
        or str(payload.get("success", "")).lower() == "false"
    ):
        code = payload.get("error") or "unsuccessful_response"
        hint = (
            " Third-party API access can exclude Garmin activities; personal "
            "API 1.7 client credentials include them. "
            "use list_activities for activity discovery. "
            "This response does not prove the activity is absent from Xert."
            if code == "activity_not_found" else ""
        )
        raise RuntimeError(f"Xert activity API failed: {code}.{hint}")
    return payload

def list_activities(
    *,
    username: str | None = None,
    password: str | None = None,
    oldest: str | date,
    newest: str | date,
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    """List Xert activities for a date range."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    activities = _activity_request(
        "/oauth/activity",
        access_token or credentials.bearer_token(),
        params={
            "from": _date_to_unix(oldest),
            "to": _date_to_unix(newest, end_of_day=True),
        },
    )
    if not isinstance(activities, dict) or not isinstance(activities.get("activities"), list):
        raise TypeError("Expected Xert activity endpoint to return an activities list")
    return activities["activities"]


def list_activities_v2(
    start: date, end: date, access_token: str, *, include_details: bool
) -> list[dict[str, Any]]:
    """Read completed activities newest first across an inclusive local date range."""
    activities = []
    seen_paths = set()
    previous_start = None
    while end >= start:
        # Xert caps detailed requests at 31 elapsed days. Thirty local days
        # also fit when the clocks go back.
        first_day = end - timedelta(days=min(29, (end - start).days)) if include_details else start
        window_start = datetime.combine(first_day, time.min).astimezone()
        window_end = datetime.combine(end, time.max).astimezone()
        params = {"from": window_start.isoformat(), "to": window_end.isoformat()}
        if include_details:
            params["include_details"] = 1

        cursors = set()
        while True:
            page = _activity_request("/oauth/v2/activity", access_token, params=params)
            if not isinstance(page, dict) or not isinstance(page.get("activities"), list):
                raise RuntimeError("Invalid Xert v2 activity page")
            if page.get("data_use_notice"):
                raise RuntimeError("Xert v2 activity list was filtered; period coverage is unknown")

            for row in page["activities"]:
                if not isinstance(row, dict) or not row.get("path"):
                    raise RuntimeError("Xert v2 activity is missing its identity")
                started = _v2_activity_start(row)
                if not window_start <= started <= window_end or row["path"] in seen_paths:
                    continue
                if previous_start is not None and started > previous_start:
                    raise RuntimeError("Xert v2 activities are not newest-first")
                previous_start = started
                seen_paths.add(row["path"])

                summary = row.get("summary") or {}
                activity = _normalize_v2_activity_identity(row, started, summary.get("duration"))
                if include_details:
                    activity.update(_normalize_v2_activity_details(summary))
                activities.append(activity)

            cursor = page.get("next_cursor")
            if cursor is None and "next_cursor" in page:
                break
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise RuntimeError("Invalid Xert v2 activity pagination cursor")
            cursors.add(cursor)
            params = {**params, "cursor": cursor}
        if first_day == start:
            break
        end = first_day - timedelta(days=1)
    return activities


def fetch_activity_summary_v2(path: str, access_token: str) -> dict[str, Any]:
    """Read the compact activity summary without downloading session streams."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", path):
        raise ValueError("Invalid Xert activity path")
    payload = _activity_request(f"/oauth/v2/activity/{path}", access_token)
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        raise TypeError("Expected Xert v2 activity detail to contain a summary")
    summary = payload["summary"]
    identity = {
        "path": path,
        "name": payload.get("name"),
        "distance": summary.get("distance"),
        "map_url": summary.get("activity_map"),
    }
    duration = summary.get("duration")
    return {
        **_normalize_v2_activity_identity(identity, _v2_activity_start(summary), duration),
        **_normalize_v2_activity_details(summary),
        "elapsed_minutes": round(duration / 60, 1) if duration is not None else None,
        "freshness": summary.get("freshness"),
    }


def _v2_activity_start(row: dict[str, Any]) -> datetime:
    started = datetime.fromisoformat(row["start_date"])
    if started.utcoffset() is None:
        raise RuntimeError("Xert v2 activity start_date has no UTC offset")
    return started


def _normalize_v2_activity_identity(
    row: dict[str, Any], started: datetime, duration: float | None
) -> dict[str, Any]:
    distance = row.get("distance")
    map_url = row.get("map_url")
    return {
        "path": row["path"],
        "name": row.get("name"),
        "start_local": started.astimezone().replace(tzinfo=None).isoformat(),
        "duration_s": duration,
        "elapsed_minutes": duration / 60 if duration is not None else None,
        "distance_m": distance * 1000 if distance is not None else None,
        "distance_km": distance,
        "source": "xert_plugin",
        "map_url": urljoin(XERT_API_BASE_URL, map_url) if isinstance(map_url, str) and map_url else None,
    }


def _normalize_v2_activity_details(summary: dict[str, Any]) -> dict[str, Any]:
    signature = summary.get("sig")
    session = summary.get("session") or {}
    if signature is not None:
        signature = {
            "ftp": signature.get("ftp"),
            "ltp": signature.get("ltp"),
            "pp": signature.get("pp"),
            "hie": signature.get("hie"),
        }
    return {
        "signature": signature,
        "xss": summary.get("xss"),
        "xep_watts": summary.get("xep"),
        "focus": summary.get("focus"),
        "specificity": summary.get("specificity"),
        "difficulty": summary.get("difficulty"),
        "difficulty_rating": summary.get("difficulty_rating"),
        "avg_power": session.get("avg_power"),
        "max_power": session.get("max_power"),
        "avg_heart_rate": session.get("avg_heart_rate"),
        "max_heart_rate": session.get("max_heart_rate"),
        "avg_cadence": session.get("avg_cadence"),
        "max_cadence": session.get("max_cadence"),
    }


def fetch_activity_detail(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    include_session_data: bool = False,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Fetch one Xert activity detail document."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    detail = _activity_request(
        f"/oauth/activity/{path}",
        access_token or credentials.bearer_token(),
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
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    """List activities and fetch compact detail documents using one token."""

    credentials = XertCredentials(
        username=username,
        password=password,
    )
    token = access_token or credentials.bearer_token()
    activities = _activity_request(
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
        detail = _activity_request(
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
    activities = _activity_request(
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
        detail = _activity_request(
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


def fetch_activity_web(opener, path: str, *, include_session_data=False):
    """Read standard activity-page analytics, including Garmin-synced rides.

    Preserve web chart field names rather than pretending they are OAuth data.
    Only follow the page's same-origin, same-activity standard MPA endpoint.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", path):
        raise ValueError("Invalid Xert activity path")
    page_url = f"{XERT_API_BASE_URL}/activities/{path}"
    html = _open_text(opener, Request(page_url), "Xert activity page")
    match = re.search(r"(?:const|let|var)\s+activity\s*=\s*", html)
    chart = re.search(r'Xert\.Activity\.Analytics\.MPA\._chartURL\s*=\s*"([^"<>]+)"', html)
    if not match or not chart:
        raise RuntimeError("Xert activity page lacks standard activity analytics")
    activity, _ = json.JSONDecoder().raw_decode(html[match.end():])
    url = chart.group(1)
    parsed, base = urlsplit(url), urlsplit(XERT_API_BASE_URL)
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        base.scheme, base.netloc, f"/activities/{path}/mpa/default"
    ):
        raise RuntimeError("Xert chart URL does not match the requested activity")
    if not isinstance(activity, dict) or not activity.get("start_date_local"):
        raise RuntimeError("Xert activity page has invalid metadata")
    data = json.loads(_open_text(opener, Request(url, headers={
        "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
    }), "Xert activity analytics"))
    if (not isinstance(data, dict) or data.get("result") is not True
            or not isinstance(data.get("summary"), dict)
            or not isinstance(data.get("data"), list) or not data["data"]
            or any(not isinstance(row, dict) for row in data["data"])):
        raise RuntimeError("Xert activity analytics returned invalid or empty data")
    summary = {**activity, **data["summary"], "sig": data.get("sig"),
               "focus": data["summary"].get("fa"),
               "specificity": data["summary"].get("spr")}
    result = {"path": path, "source": "xert_authenticated_web",
              "summary": summary, "events": data.get("events", []),
              "series_format": "xert-standard-mpa-chart-v1"}
    if include_session_data:
        result["session_data"] = data["data"]
    return result
