"""Utilities for downloading training data from Intervals.icu.

The personal API key flow uses HTTP Basic Auth with username ``API_KEY`` and
the API key as the password. OAuth bearer tokens are also supported.
"""

from __future__ import annotations

import base64
import csv
import gzip
import json
import mimetypes
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


INTERVALS_API_BASE_URL = "https://intervals.icu/api/v1"
DEFAULT_ARTIFACTS_DIR = Path("outputs/intervals")

ActivityFileKind = Literal["original", "fit", "web-original"]


@dataclass(frozen=True)
class IntervalsIcuCredentials:
    """Credentials for Intervals.icu API calls."""

    api_key: str | None = None
    bearer_token: str | None = None

    def auth_header(self) -> str:
        if self.bearer_token:
            return f"Bearer {self.bearer_token}"
        if self.api_key:
            token = base64.b64encode(f"API_KEY:{self.api_key}".encode()).decode()
            return f"Basic {token}"
        raise ValueError("Set either api_key or bearer_token")


def download_intervals_icu_data(
    *,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
    oldest: str | date,
    newest: str | date,
    output_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
    include_activity_details: bool = True,
    include_intervals: bool = True,
    download_activity_files: bool = False,
    activity_file_kind: ActivityFileKind = "fit",
) -> dict[str, Path]:
    """Download Intervals.icu activity data for a date range.

    Args:
        api_key: Personal Intervals.icu API key. Use this for private scripts.
        bearer_token: OAuth access token. Use this for multi-user apps.
        athlete_id: Intervals.icu athlete id. ``0`` means "current athlete".
        oldest: First local date to include, formatted ``YYYY-MM-DD``.
        newest: Last local date to include, formatted ``YYYY-MM-DD``.
        output_dir: Directory where downloaded data should be written.
        include_activity_details: Fetch one JSON document per activity.
        include_intervals: Include Intervals.icu interval data in details.
        download_activity_files: Download FIT files for each activity.
        activity_file_kind: ``"fit"`` for Intervals.icu generated FIT files,
            ``"original"`` for the original uploaded file.

    Returns:
        A mapping of artifact names to paths.
    """

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    summaries_dir = output_path / "activity_summaries"
    summaries_dir.mkdir(exist_ok=True)

    oldest_value = _date_to_string(oldest)
    newest_value = _date_to_string(newest)
    params = {"oldest": oldest_value, "newest": newest_value}

    activities = _request_json(
        f"/athlete/{athlete_id}/activities",
        credentials,
        params=params,
    )
    if not isinstance(activities, list):
        raise TypeError("Expected Intervals.icu activities endpoint to return a list")

    artifacts: dict[str, Path] = {}
    summary_json_path = summaries_dir / f"{oldest_value}_{newest_value}.json"
    summary_csv_path = summaries_dir / f"{oldest_value}_{newest_value}.csv"
    _write_json(summary_json_path, activities)
    _write_csv(summary_csv_path, activities)
    artifacts["activities_json"] = summary_json_path
    artifacts["activities_csv"] = summary_csv_path

    if include_activity_details:
        for activity in activities:
            activity_id = _activity_id(activity)
            activity_dir = _activity_artifact_dir(output_path, activity)
            detail = _request_json(
                f"/activity/{activity_id}",
                credentials,
                params={"intervals": str(include_intervals).lower()},
            )
            activity_dir.mkdir(parents=True, exist_ok=True)
            detail_path = activity_dir / "activity.json"
            _write_json(detail_path, detail)
        artifacts["activities_dir"] = output_path / "activities"

    if download_activity_files:
        for activity in activities:
            activity_id = _activity_id(activity)
            activity_dir = _activity_artifact_dir(output_path, activity)
            files_dir = activity_dir / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            download_path = _download_activity_file(
                activity_id=activity_id,
                credentials=credentials,
                output_dir=files_dir,
                kind=activity_file_kind,
                original_file_type=str(activity.get("file_type") or "fit"),
            )
            artifacts[f"activity_file_{activity_id}"] = download_path
        artifacts["activities_dir"] = output_path / "activities"

    return artifacts


def save_latest_activity_streams(
    *,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
    output_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
    lookback_days: int = 365,
    stream_types: list[str] | None = None,
) -> dict[str, Path]:
    """Save streams for the newest Intervals.icu activity not older than lookback.

    The activity list endpoint is queried over ``lookback_days`` ending today.
    CSV stream exports and activity metadata are saved under
    ``outputs/intervals/activities/<date>_<activity_id>/`` by default.
    """

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    today = date.today()
    activities = list_activities(
        api_key=api_key,
        bearer_token=bearer_token,
        athlete_id=athlete_id,
        oldest=today - timedelta(days=lookback_days),
        newest=today,
    )
    if not activities:
        raise RuntimeError(f"No Intervals.icu activities found in last {lookback_days} days")

    latest_activity = max(
        activities,
        key=lambda activity: str(activity.get("start_date_local") or ""),
    )
    return save_activity_streams(
        activity_id=_activity_id(latest_activity),
        activity_summary=latest_activity,
        api_key=api_key,
        bearer_token=bearer_token,
        output_dir=output_dir,
        stream_types=stream_types,
    )


def save_activity_streams(
    *,
    activity_id: str,
    activity_summary: dict[str, Any] | None = None,
    api_key: str | None = None,
    bearer_token: str | None = None,
    output_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
    stream_types: list[str] | None = None,
) -> dict[str, Path]:
    """Save activity metadata and stream CSV for one Intervals.icu activity."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    detail = _request_json(
        f"/activity/{activity_id}",
        credentials,
        params={"intervals": "true"},
    )

    stream_params = None
    if stream_types:
        stream_params = {"types": ",".join(stream_types)}

    streams_csv = _request_bytes(
        f"/activity/{activity_id}/streams.csv",
        credentials,
        params=stream_params,
    )

    activity_dir = _activity_artifact_dir(output_path, activity_summary or detail)
    activity_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = activity_dir / "activity.json"
    streams_csv_path = activity_dir / "streams.csv"

    _write_json(metadata_path, detail)
    streams_csv_path.write_bytes(streams_csv)

    return {
        "activity_dir": activity_dir,
        "activity_metadata": metadata_path,
        "streams_csv": streams_csv_path,
    }


def save_activity_file(
    *,
    activity_id: str,
    activity_summary: dict[str, Any] | None = None,
    api_key: str | None = None,
    bearer_token: str | None = None,
    cookie: str | None = None,
    output_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
    kind: ActivityFileKind = "original",
) -> dict[str, Path]:
    """Save the original or generated FIT file for one Intervals.icu activity."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    detail = _request_json(
        f"/activity/{activity_id}",
        credentials,
        params={"intervals": "true"},
    )
    activity = activity_summary or detail
    activity_dir = _activity_artifact_dir(output_path, activity)
    files_dir = activity_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = activity_dir / "activity.json"
    _write_json(metadata_path, detail)

    if kind == "web-original":
        download_path = _download_activity_web_file(
            activity_id=activity_id,
            cookie=cookie or load_intervals_icu_cookie(),
            output_dir=files_dir,
            original_file_type=str((activity_summary or detail).get("file_type") or "fit"),
        )
    else:
        download_path = _download_activity_file(
            activity_id=activity_id,
            credentials=credentials,
            output_dir=files_dir,
            kind=kind,
            original_file_type=str((activity_summary or detail).get("file_type") or "fit"),
        )
    return {
        "activity_dir": activity_dir,
        "activity_metadata": metadata_path,
        "activity_file": download_path,
    }


def download_activity_streams_csv(
    *,
    activity_id: str,
    output_path: str | Path,
    api_key: str | None = None,
    bearer_token: str | None = None,
    stream_types: list[str] | None = None,
) -> Path:
    """Download activity streams CSV to an explicit path without saving metadata."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    stream_params = None
    if stream_types:
        stream_params = {"types": ",".join(stream_types)}
    streams_csv = _request_bytes(
        f"/activity/{activity_id}/streams.csv",
        credentials,
        params=stream_params,
    )
    output_file = _resolve_output_file(
        output_path=Path(output_path),
        filename=f"{activity_id}_streams.csv",
    )
    output_file.write_bytes(streams_csv)
    return output_file


def download_activity_file(
    *,
    activity_id: str,
    output_path: str | Path,
    api_key: str | None = None,
    bearer_token: str | None = None,
    cookie: str | None = None,
    kind: ActivityFileKind = "original",
) -> Path:
    """Download an activity file to an explicit path without saving metadata."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    detail = get_activity(
        activity_id=activity_id,
        api_key=api_key,
        bearer_token=bearer_token,
        include_intervals=False,
    )
    original_file_type = str(detail.get("file_type") or "fit").lower()
    output_file = _resolve_output_file(
        output_path=Path(output_path),
        filename=_activity_file_name(
            activity_id=activity_id,
            kind=kind,
            original_file_type=original_file_type,
        ),
    )

    if kind == "web-original":
        body = _request_activity_web_file_bytes(
            activity_id=activity_id,
            cookie=cookie or load_intervals_icu_cookie(),
        )
    else:
        if kind == "fit":
            path = f"/activity/{activity_id}/fit-file"
        elif kind == "original":
            path = f"/activity/{activity_id}/file"
        else:
            raise ValueError("kind must be 'original', 'fit', or 'web-original'")
        body = _request_bytes(path, credentials)

    _write_maybe_gzip(output_file, body)
    return output_file


def download_latest_activity_streams(**kwargs: Any) -> dict[str, Path]:
    """Download and save streams for the newest Intervals.icu activity."""

    return save_latest_activity_streams(**kwargs)


def save_wellness(
    *,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
    oldest: str | date,
    newest: str | date,
    output_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
) -> dict[str, Path]:
    """Save Intervals.icu wellness data for a date range.

    Wellness includes daily values such as HRV, resting HR, sleep, weight,
    fatigue, stress and related readiness fields when available.
    """

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    oldest_value = _date_to_string(oldest)
    newest_value = _date_to_string(newest)
    wellness = _request_json(
        f"/athlete/{athlete_id}/wellness",
        credentials,
        params={"oldest": oldest_value, "newest": newest_value},
    )
    if not isinstance(wellness, list):
        raise TypeError("Expected Intervals.icu wellness endpoint to return a list")

    wellness_dir = Path(output_dir) / "wellness"
    wellness_dir.mkdir(parents=True, exist_ok=True)
    json_path = wellness_dir / f"{oldest_value}_{newest_value}.json"
    csv_path = wellness_dir / f"{oldest_value}_{newest_value}.csv"
    _write_json(json_path, wellness)
    _write_csv(csv_path, wellness)
    return {
        "wellness_json": json_path,
        "wellness_csv": csv_path,
    }


def get_wellness(
    *,
    day: str | date,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
) -> dict[str, Any]:
    """Fetch one Intervals.icu wellness record."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    day_value = _date_to_string(day)
    wellness = _request_json(
        f"/athlete/{athlete_id}/wellness",
        credentials,
        params={"oldest": day_value, "newest": day_value},
    )
    if not isinstance(wellness, list):
        raise TypeError("Expected Intervals.icu wellness endpoint to return a list")
    if not wellness:
        return {}
    if not isinstance(wellness[0], dict):
        raise TypeError("Expected Intervals.icu wellness row to be an object")
    return wellness[0]


def list_wellness(
    *,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
    oldest: str | date,
    newest: str | date,
) -> list[dict[str, Any]]:
    """Fetch Intervals.icu wellness rows for a date range without writing files."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    wellness = _request_json(
        f"/athlete/{athlete_id}/wellness",
        credentials,
        params={
            "oldest": _date_to_string(oldest),
            "newest": _date_to_string(newest),
        },
    )
    if not isinstance(wellness, list):
        raise TypeError("Expected Intervals.icu wellness endpoint to return a list")
    return wellness


def update_wellness(
    *,
    day: str | date,
    updates: dict[str, Any],
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
) -> dict[str, Any]:
    """Update one Intervals.icu wellness record and return the updated document."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    updated = _request_json(
        f"/athlete/{athlete_id}/wellness/{_date_to_string(day)}",
        credentials,
        method="PUT",
        json_body=updates,
    )
    if not isinstance(updated, dict):
        raise TypeError("Expected Intervals.icu update wellness endpoint to return an object")
    return updated


def list_activities(
    *,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
    oldest: str | date,
    newest: str | date,
) -> list[dict[str, Any]]:
    """List Intervals.icu activities for a date range."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    activities = _request_json(
        f"/athlete/{athlete_id}/activities",
        credentials,
        params={
            "oldest": _date_to_string(oldest),
            "newest": _date_to_string(newest),
        },
    )
    if not isinstance(activities, list):
        raise TypeError("Expected Intervals.icu activities endpoint to return a list")
    return activities


def search_activities(
    *,
    query: str,
    limit: int = 10,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
) -> list[dict[str, Any]]:
    """Search Intervals.icu activities by query text."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    activities = _request_json(
        f"/athlete/{athlete_id}/activities/search",
        credentials,
        params={"q": query, "limit": limit},
    )
    if not isinstance(activities, list):
        raise TypeError("Expected Intervals.icu activities search endpoint to return a list")
    return activities


def get_activity(
    *,
    activity_id: str,
    api_key: str | None = None,
    bearer_token: str | None = None,
    include_intervals: bool = True,
) -> dict[str, Any]:
    """Fetch one Intervals.icu activity without writing files."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    activity = _request_json(
        f"/activity/{activity_id}",
        credentials,
        params={"intervals": str(include_intervals).lower()},
    )
    if not isinstance(activity, dict):
        raise TypeError("Expected Intervals.icu activity endpoint to return an object")
    return activity


def update_activity(
    *,
    activity_id: str,
    updates: dict[str, Any],
    api_key: str | None = None,
    bearer_token: str | None = None,
) -> dict[str, Any]:
    """Update one Intervals.icu activity and return the updated document."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    updated = _request_json(
        f"/activity/{activity_id}",
        credentials,
        method="PUT",
        json_body=updates,
    )
    if not isinstance(updated, dict):
        raise TypeError("Expected Intervals.icu update activity endpoint to return an object")
    return updated


def delete_activity(
    *,
    activity_id: str,
    api_key: str | None = None,
    bearer_token: str | None = None,
) -> dict[str, Any]:
    """Delete one Intervals.icu activity and return the API response."""

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    body = _request_bytes(
        f"/activity/{activity_id}",
        credentials,
        method="DELETE",
    )
    if not body:
        return {"id": activity_id}
    deleted = json.loads(body.decode("utf-8"))
    if not isinstance(deleted, dict):
        raise TypeError("Expected Intervals.icu delete activity endpoint to return an object")
    return deleted


def upload_activity_file(
    *,
    file_path: str | Path,
    api_key: str | None = None,
    bearer_token: str | None = None,
    athlete_id: str | int = 0,
) -> dict[str, Any]:
    """Upload one activity file to Intervals.icu and return the API response.

    Intervals may deduplicate uploads and return an existing activity id instead
    of creating a new one.
    """

    credentials = IntervalsIcuCredentials(
        api_key=api_key,
        bearer_token=bearer_token,
    )
    path = Path(file_path)
    body, content_type = _multipart_file_body(path, field_name="file")
    uploaded = _request_json(
        f"/athlete/{athlete_id}/activities",
        credentials,
        method="POST",
        body=body,
        content_type=content_type,
    )
    if not isinstance(uploaded, dict):
        raise TypeError("Expected Intervals.icu upload activity endpoint to return an object")
    return uploaded


def load_intervals_icu_api_key(env_path: str | Path = ".env") -> str:
    """Load ``INTERVALS_ICU_API_KEY`` from a local dotenv-style file."""

    path = Path(env_path)
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "INTERVALS_ICU_API_KEY":
            return value.strip().strip('"').strip("'")
    raise KeyError(f"INTERVALS_ICU_API_KEY not found in {path}")


def load_intervals_icu_cookie(env_path: str | Path = ".env") -> str:
    """Load ``INTERVALS_ICU_COOKIE`` from a local dotenv-style file."""

    path = Path(env_path)
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "INTERVALS_ICU_COOKIE":
            return value.strip().strip('"').strip("'")
    raise KeyError(f"INTERVALS_ICU_COOKIE not found in {path}")


def _request_json(
    path: str,
    credentials: IntervalsIcuCredentials,
    *,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
) -> Any:
    body = _request_bytes(
        path,
        credentials,
        params=params,
        method=method,
        json_body=json_body,
        body=body,
        content_type=content_type,
    )
    return json.loads(body.decode("utf-8"))


def _request_bytes(
    path: str,
    credentials: IntervalsIcuCredentials,
    *,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
) -> bytes:
    query = f"?{urlencode(params)}" if params else ""
    if json_body is not None and body is not None:
        raise ValueError("Use either json_body or body, not both")
    request_body = json.dumps(json_body).encode("utf-8") if json_body is not None else body
    headers = {
        "Authorization": credentials.auth_header(),
        "Accept": "application/json, text/csv, */*",
        "User-Agent": "training-ai/0.1 (+https://intervals.icu API client)",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if content_type is not None:
        headers["Content-Type"] = content_type
    request = Request(
        f"{INTERVALS_API_BASE_URL}{path}{query}",
        data=request_body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Intervals.icu request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc


def _multipart_file_body(path: Path, *, field_name: str) -> tuple[bytes, str]:
    boundary = f"----training-ai-intervals-{path.name.replace(' ', '-')}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def _download_activity_file(
    *,
    activity_id: str,
    credentials: IntervalsIcuCredentials,
    output_dir: Path,
    kind: ActivityFileKind,
    original_file_type: str,
) -> Path:
    if kind == "fit":
        path = f"/activity/{activity_id}/fit-file"
        filename = f"{activity_id}_intervals.fit"
    elif kind == "original":
        path = f"/activity/{activity_id}/file"
        filename = f"{activity_id}_original.{original_file_type.lower()}"
    else:
        raise ValueError("activity_file_kind must be 'fit' or 'original'")

    compressed = _request_bytes(path, credentials)
    output_file = output_dir / filename
    _write_maybe_gzip(output_file, compressed)
    return output_file


def _download_activity_web_file(
    *,
    activity_id: str,
    cookie: str,
    output_dir: Path,
    original_file_type: str,
) -> Path:
    body = _request_activity_web_file_bytes(activity_id=activity_id, cookie=cookie)

    output_file = output_dir / f"{activity_id}_web_original.{original_file_type.lower()}"
    _write_maybe_gzip(output_file, body)
    return output_file


def _request_activity_web_file_bytes(*, activity_id: str, cookie: str) -> bytes:
    path = f"https://intervals.icu/api/activity/{activity_id}/file"
    request = Request(
        path,
        headers={
            "Accept": "*/*",
            "Cookie": cookie,
            "User-Agent": "training-ai/0.1 (+https://intervals.icu web file client)",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Intervals.icu web file request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc


def _activity_file_name(
    *,
    activity_id: str,
    kind: ActivityFileKind,
    original_file_type: str,
) -> str:
    if kind == "fit":
        return f"{activity_id}_intervals.fit"
    if kind == "original":
        return f"{activity_id}_original.{original_file_type.lower()}"
    if kind == "web-original":
        return f"{activity_id}_web_original.{original_file_type.lower()}"
    raise ValueError("kind must be 'original', 'fit', or 'web-original'")


def _resolve_output_file(*, output_path: Path, filename: str) -> Path:
    if output_path.suffix:
        output_file = output_path
    else:
        output_file = output_path / filename
    output_file.parent.mkdir(parents=True, exist_ok=True)
    return output_file


def _write_maybe_gzip(output_file: Path, body: bytes) -> None:
    try:
        output_file.write_bytes(gzip.decompress(body))
    except gzip.BadGzipFile:
        output_file.write_bytes(body)


def _activity_id(activity: dict[str, Any]) -> str:
    activity_id = activity.get("id")
    if not activity_id:
        raise KeyError(f"Activity is missing id: {activity}")
    return str(activity_id)


def _activity_artifact_dir(output_path: Path, activity: dict[str, Any]) -> Path:
    activity_id = _activity_id(activity)
    activity_date = str(activity.get("start_date_local") or activity_id)[:10]
    return output_path / "activities" / f"{activity_date}_{activity_id}"


def _date_to_string(value: str | date) -> str:
    return value.isoformat() if isinstance(value, date) else value


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
