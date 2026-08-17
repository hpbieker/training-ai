#!/usr/bin/env python3
"""Transport-independent Python service for Xert activities and workouts."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from xert_activities import (  # noqa: E402
    fetch_activity_detail,
    list_activities as fetch_activities,
    list_activity_details,
)
from xert_common import (  # noqa: E402
    LOCAL_TIMEZONE,
    DEFAULT_XERT_OAUTH_CLIENT_ID,
    DEFAULT_XERT_OAUTH_CLIENT_SECRET,
    XertCredentials,
    load_xert_credentials,
    xert_web_login,
)
from xert_workouts import (  # noqa: E402
    fetch_workout,
    fetch_workout_designer_rows,
    list_workouts as fetch_workouts,
    summarize_workout_library,
)


CredentialFactory = Callable[[], XertCredentials]
CONFIG_ENV = "XERT_MCP_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".xert_mcp.json"


def discover_xert_credentials() -> XertCredentials:
    """Find credentials for an installed MCP server without exposing secrets."""

    config_path = Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH)).expanduser()
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Xert MCP config JSON: {config_path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Xert MCP config must contain one JSON object: {config_path}")
        config = payload

    source_env = _source_env_path()
    dotenv = load_xert_credentials(source_env) if source_env is not None else XertCredentials()
    return XertCredentials(
        username=os.environ.get("XERT_USERNAME") or _config_string(config, "username") or dotenv.username,
        password=os.environ.get("XERT_PASSWORD") or _config_string(config, "password") or dotenv.password,
        oauth_client_id=(
            os.environ.get("XERT_OAUTH_CLIENT_ID")
            or _config_string(config, "oauthClientId")
            or dotenv.oauth_client_id
            or DEFAULT_XERT_OAUTH_CLIENT_ID
        ),
        oauth_client_secret=(
            os.environ.get("XERT_OAUTH_CLIENT_SECRET")
            or _config_string(config, "oauthClientSecret")
            or dotenv.oauth_client_secret
            or DEFAULT_XERT_OAUTH_CLIENT_SECRET
        ),
    )


def _source_env_path() -> Path | None:
    explicit = os.environ.get("XERT_ENV_PATH")
    if explicit:
        return Path(explicit).expanduser()
    candidates = [Path.cwd() / ".env", PLUGIN_ROOT.parent.parent / ".env"]
    return next((path for path in candidates if path.is_file()), None)


def _config_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value if isinstance(value, str) and value else None


class XertService:
    """Stable Python call boundary shared by the CLI and MCP transports."""

    def __init__(self, credential_factory: CredentialFactory = discover_xert_credentials) -> None:
        self._credential_factory = credential_factory

    def list_activities(
        self,
        start_date: str,
        end_date: str,
        *,
        view: str = "summary",
    ) -> list[dict[str, Any]] | dict[str, Any]:
        _validate_date_range(start_date, end_date)
        if view not in {"summary", "loads"}:
            raise ValueError("view must be 'summary' or 'loads'")
        credentials = self._credentials()
        if view == "summary":
            return fetch_activities(
                username=credentials.username,
                password=credentials.password,
                oldest=start_date,
                newest=end_date,
            )
        details = list_activity_details(
            username=credentials.username,
            password=credentials.password,
            oldest=start_date,
            newest=end_date,
            include_session_data=False,
        )
        return {
            "source": "xert_plugin_activity_loads",
            "start_date": start_date,
            "end_date": end_date,
            "activity_count": len(details),
            "activities": [compact_activity_load(detail) for detail in details],
        }

    def get_activity(self, path: str, *, view: str = "summary") -> dict[str, Any]:
        path = _require_identifier(path, "activity path")
        if view not in {"summary", "full", "session"}:
            raise ValueError("view must be 'summary', 'full', or 'session'")
        credentials = self._credentials()
        payload = fetch_activity_detail(
            path,
            username=credentials.username,
            password=credentials.password,
            include_session_data=view == "session",
        )
        if view == "summary":
            result = compact_activity_load(payload)
            result["path"] = path
            return result
        return payload

    def list_workouts(
        self,
        *,
        name_keywords: str | None = None,
        view: str = "summary",
    ) -> list[dict[str, Any]]:
        if view not in {"summary", "full"}:
            raise ValueError("view must be 'summary' or 'full'")
        credentials = self._credentials()
        workouts = fetch_workouts(
            username=credentials.username,
            password=credentials.password,
        )
        if view == "summary":
            return summarize_workout_library(workouts, name_filter=name_keywords)
        return filter_workouts(workouts, name_keywords)

    def get_workout(self, path: str, *, view: str = "resolved") -> dict[str, Any] | list[dict[str, Any]]:
        path = _require_identifier(path, "workout path")
        if view not in {"resolved", "editable"}:
            raise ValueError("view must be 'resolved' or 'editable'")
        credentials = self._credentials()
        if view == "resolved":
            return fetch_workout(
                path,
                username=credentials.username,
                password=credentials.password,
            )
        opener = xert_web_login(
            username=_required_credential(credentials.username, "XERT_USERNAME"),
            password=_required_credential(credentials.password, "XERT_PASSWORD"),
        )
        return fetch_workout_designer_rows(opener, path)

    def _credentials(self) -> XertCredentials:
        credentials = self._credential_factory()
        _required_credential(credentials.username, "XERT_USERNAME")
        _required_credential(credentials.password, "XERT_PASSWORD")
        return credentials


def compact_activity_load(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one activity to the compact source contract used by callers."""

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
    if not isinstance(summary, dict):
        raise TypeError("Expected Xert activity payload to contain an object summary")
    progression = summary.get("progression") if isinstance(summary.get("progression"), dict) else {}
    xss = progression.get("xss") if isinstance(progression.get("xss"), dict) else {}
    session = summary.get("session") if isinstance(summary.get("session"), dict) else {}
    list_row = payload.get("activity_list_row") if isinstance(payload.get("activity_list_row"), dict) else {}
    return {
        "source": "xert_plugin",
        "path": payload.get("path") or summary.get("path"),
        "name": payload.get("name") or summary.get("name") or list_row.get("name"),
        "map_url": payload.get("map_url") or summary.get("map_url") or list_row.get("map_url"),
        "start_local": _activity_start_local(summary),
        "distance_km": summary.get("distance") or list_row.get("distance"),
        "elapsed_minutes": _minutes(_number(summary.get("duration") or session.get("total_elapsed_time"))),
        "xss": {
            "total": summary.get("xss") or xss.get("total"),
            "low": summary.get("xlss") or xss.get("xlss"),
            "high": summary.get("xhss") or xss.get("xhss"),
            "peak": summary.get("xpss") or xss.get("xpss"),
        },
        "xep_watts": summary.get("xep"),
        "focus": summary.get("focus"),
        "specificity": summary.get("specificity"),
        "difficulty": summary.get("difficulty"),
        "difficulty_rating": summary.get("difficulty_rating"),
        "freshness": summary.get("freshness"),
        "signature": summary.get("sig") or progression.get("signature"),
    }


def filter_workouts(
    workouts: list[dict[str, Any]], name_keywords: str | None
) -> list[dict[str, Any]]:
    """Filter workout names by all supplied case-insensitive keywords."""

    if not name_keywords:
        return workouts
    keywords = name_keywords.casefold().split()
    return [
        row
        for row in workouts
        if all(keyword in str(row.get("name") or "").casefold() for keyword in keywords)
    ]


def _validate_date_range(start_date: str, end_date: str) -> None:
    from datetime import date

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date and end_date must use YYYY-MM-DD") from exc
    if end < start:
        raise ValueError("end_date must not precede start_date")


def _require_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _required_credential(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(
            f"Set {name} in the MCP environment, {CONFIG_ENV}, or {DEFAULT_CONFIG_PATH}"
        )
    return value


def _activity_start_local(summary: dict[str, Any]) -> str | None:
    start = summary.get("start_date")
    if isinstance(start, dict):
        raw = start.get("date")
        if raw:
            parsed = datetime.fromisoformat(str(raw))
            if start.get("timezone") == "UTC":
                parsed = parsed.replace(tzinfo=timezone.utc).astimezone(LOCAL_TIMEZONE)
            return parsed.replace(tzinfo=None).isoformat()
    raw_progression_start = (summary.get("progression") or {}).get("start_date")
    if raw_progression_start:
        return (
            datetime.fromisoformat(str(raw_progression_start).replace("Z", "+00:00"))
            .astimezone(LOCAL_TIMEZONE)
            .replace(tzinfo=None)
            .isoformat()
        )
    return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _minutes(seconds: float | None) -> float | None:
    return round(seconds / 60, 1) if seconds is not None else None
