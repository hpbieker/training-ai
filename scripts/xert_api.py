"""Utilities for downloading Xert training summaries.

Xert uses OAuth password credentials with the public ``xert_public`` client for
personal scripts. Keep credentials in ``.env`` and cache only the returned
training/activity metadata under ``data/xert``.
"""

from __future__ import annotations

import csv
import base64
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


XERT_API_BASE_URL = "https://www.xertonline.com"
XERT_ADVICE_URL = (
    "https://mystic-treat-429407-f2.uc.r.appspot.com/"
    "training-advice-with-forecast-activities"
)
DEFAULT_DATA_DIR = Path("data")


@dataclass(frozen=True)
class XertCredentials:
    """Credentials for Xert API calls."""

    access_token: str | None = None
    username: str | None = None
    password: str | None = None

    def bearer_token(self) -> str:
        if self.access_token:
            return self.access_token
        if self.username and self.password:
            token = request_xert_token(self.username, self.password)
            return token["access_token"]
        raise ValueError("Set XERT_ACCESS_TOKEN or XERT_USERNAME and XERT_PASSWORD")


def request_xert_token(username: str, password: str) -> dict[str, Any]:
    """Request an OAuth token from Xert."""

    body = urlencode(
        {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
    ).encode("utf-8")
    request = Request(
        f"{XERT_API_BASE_URL}/oauth/token",
        data=body,
        headers={
            "Authorization": "Basic eGVydF9wdWJsaWM6eGVydF9wdWJsaWM=",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "training-ai/0.1 (+https://www.xertonline.com/API.html)",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert token request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise TypeError("Expected Xert token endpoint to return an access_token")
    return payload


def cache_training_info(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache Xert training, fitness and status information."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    training_info = _request_json("/oauth/training_info", credentials.bearer_token())
    if not isinstance(training_info, dict):
        raise TypeError("Expected Xert training_info endpoint to return an object")

    xert_dir = Path(output_dir) / "xert"
    xert_dir.mkdir(parents=True, exist_ok=True)
    path = xert_dir / f"training_info_{date.today().isoformat()}.json"
    _write_json(path, training_info)
    return {"training_info_json": path}


def cache_training_advice(
    *,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache Xert training advice including recovery load/days.

    This endpoint uses HTTP Basic Auth with the user's Xert credentials.
    """

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for training advice")
    advice = fetch_training_advice(username=username, password=password)
    xert_dir = Path(output_dir) / "xert"
    xert_dir.mkdir(parents=True, exist_ok=True)
    path = xert_dir / f"training_advice_{date.today().isoformat()}.json"
    _write_json(path, advice)
    return {"training_advice_json": path}


def fetch_training_advice(*, username: str, password: str) -> dict[str, Any]:
    """Fetch Xert training advice and forecast data."""

    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = Request(
        XERT_ADVICE_URL,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "User-Agent": "training-ai/0.1 (+Xert advice cache)",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert advice request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert advice endpoint to return an object")
    return payload


def list_activities(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    oldest: str | date,
    newest: str | date,
) -> list[dict[str, Any]]:
    """List Xert activities for a date range."""

    credentials = XertCredentials(
        access_token=access_token,
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


def cache_activity_summaries(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    oldest: str | date,
    newest: str | date,
    output_dir: str | Path = DEFAULT_DATA_DIR,
    include_details: bool = True,
    include_session_data: bool = False,
) -> dict[str, Path]:
    """Cache Xert activity list and per-activity summary details."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    token = credentials.bearer_token()
    oldest_value = _date_to_string(oldest)
    newest_value = _date_to_string(newest)
    xert_dir = Path(output_dir) / "xert"
    summary_dir = xert_dir / "activity_summaries"
    activities_dir = xert_dir / "activities"
    summary_dir.mkdir(parents=True, exist_ok=True)
    activities_dir.mkdir(parents=True, exist_ok=True)

    activity_list = _request_json(
        "/oauth/activity",
        token,
        params={
            "from": _date_to_unix(oldest),
            "to": _date_to_unix(newest, end_of_day=True),
        },
    )
    if not isinstance(activity_list, dict) or not isinstance(activity_list.get("activities"), list):
        raise TypeError("Expected Xert activity endpoint to return an activities list")
    activities = activity_list["activities"]

    list_json = summary_dir / f"{oldest_value}_{newest_value}.json"
    list_csv = summary_dir / f"{oldest_value}_{newest_value}.csv"
    _write_json(list_json, activities)
    _write_csv(list_csv, activities)

    artifacts = {
        "activities_json": list_json,
        "activities_csv": list_csv,
    }
    if include_details:
        for activity in activities:
            path = _activity_path(activity)
            detail = fetch_activity_detail(
                path,
                access_token=token,
                include_session_data=include_session_data,
            )
            activity_dir = _activity_cache_dir(activities_dir, activity)
            activity_dir.mkdir(parents=True, exist_ok=True)
            _write_json(activity_dir / "activity.json", detail)
        artifacts["activities_dir"] = activities_dir
    return artifacts


def fetch_activity_detail(
    path: str,
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    include_session_data: bool = False,
) -> dict[str, Any]:
    """Fetch one Xert activity detail document."""

    credentials = XertCredentials(
        access_token=access_token,
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


def load_xert_credentials(env_path: str | Path = ".env") -> XertCredentials:
    """Load Xert credentials from a local dotenv-style file."""

    values = _load_env_values(env_path)
    return XertCredentials(
        access_token=values.get("XERT_ACCESS_TOKEN"),
        username=values.get("XERT_USERNAME"),
        password=values.get("XERT_PASSWORD"),
    )


def _request_json(
    path: str,
    access_token: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{XERT_API_BASE_URL}{path}{query}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "training-ai/0.1 (+https://www.xertonline.com/API.html)",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc


def _activity_path(activity: dict[str, Any]) -> str:
    path = activity.get("path") or activity.get("id")
    if not path:
        raise KeyError(f"Xert activity is missing path/id: {activity}")
    return str(path)


def _activity_cache_dir(root: Path, activity: dict[str, Any]) -> Path:
    activity_date = _activity_date(activity)
    return root / f"{activity_date}_{_activity_path(activity)}"


def _activity_date(activity: dict[str, Any]) -> str:
    start = activity.get("start_date")
    if isinstance(start, dict):
        raw = str(start.get("date") or "")
        if raw:
            return raw[:10]
    return str(activity.get("date") or "unknown")[:10]


def _date_to_unix(value: str | date, *, end_of_day: bool = False) -> int:
    from datetime import datetime, time, timezone

    value_date = date.fromisoformat(value) if isinstance(value, str) else value
    value_time = time.max if end_of_day else time.min
    return int(datetime.combine(value_date, value_time, tzinfo=timezone.utc).timestamp())


def _date_to_string(value: str | date) -> str:
    return value.isoformat() if isinstance(value, date) else value


def _load_env_values(env_path: str | Path) -> dict[str, str]:
    path = Path(env_path)
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
