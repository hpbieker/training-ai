#!/usr/bin/env python3
"""Read Olympiatoppen diary records using a private local browser session."""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://dagbok.olympiatoppen.no"
USER_AGENT = "training-ai/1.0 (read-only personal diary export)"
DEFAULT_COOKIE_FILE = Path.home() / ".olympiatoppen" / "session.headers"


class ToolFailure(RuntimeError):
    def __init__(self, message: str, code: str = "tool_error"):
        super().__init__(message)
        self.code = code


def cookie_file_path() -> Path:
    override = os.environ.get("OLYMPIATTOPPEN_COOKIE_FILE")
    return Path(override).expanduser() if override else DEFAULT_COOKIE_FILE


def normalize_cookie_header(raw: str) -> str:
    value = raw.strip()
    if "\r" in value or "\n" in value:
        raise ValueError("cookie must be a single line")
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    if not re.fullmatch(r"\S[^\r\n]*", value) or "=" not in value:
        raise ValueError("expected a non-empty Cookie header")
    return f"Cookie: {value}"


def read_cookie_header(path: Path | None = None) -> str:
    path = path or cookie_file_path()
    if not path.is_file():
        raise ToolFailure("no saved session; import a cookie from the authenticated browser session", "auth_required")
    if stat.S_IMODE(path.parent.stat().st_mode) != 0o700 or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ToolFailure("saved session must be private (directory 0700, file 0600)", "session_permissions")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ToolFailure("saved session file has an invalid format", "invalid_session_file")
    return normalize_cookie_header(lines[0])


def save_cookie_header(path: Path, cookie_header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(cookie_header + "\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def get_json(path: str, cookie_header: str) -> Any:
    request = Request(
        f"{BASE_URL}{path}",
        headers={
            "Accept": "application/json",
            "Cookie": cookie_header.removeprefix("Cookie: "),
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ToolFailure("saved session is invalid or expired; renew it using the skill", "auth_required") from None
        raise ToolFailure(f"source returned HTTP {exc.code}", "source_error") from None
    except URLError as exc:
        raise ToolFailure(f"could not reach the diary: {exc.reason}", "source_unavailable") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ToolFailure("source did not return JSON; the session may have expired", "invalid_source_response") from None


def _session_for_user(cookie: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    if date.fromisoformat(from_date) > date.fromisoformat(to_date):
        raise ToolFailure("from_date must be on or before to_date", "invalid_arguments")
    user_id = get_json("/api/Auth/Session", cookie)
    if not isinstance(user_id, str) or not user_id:
        raise ToolFailure("could not verify the logged-in diary session", "auth_required")
    query = urlencode({"fromDate": from_date, "toDate": to_date})
    payload = get_json(f"/api/WorkoutSessions/{user_id}?{query}", cookie)
    sessions = payload.get("workoutSessions") if isinstance(payload, dict) else None
    if not isinstance(sessions, list):
        raise ToolFailure("source response did not contain workout sessions", "invalid_source_response")
    return [row for row in sessions if isinstance(row, dict)]


def session_row(session: dict[str, Any]) -> dict[str, Any]:
    activities: list[str] = []
    for activity in session.get("activities") or []:
        activity_type = activity.get("activityType") or ""
        metrics = [
            f"{metric.get('name')} {metric.get('value')}"
            for metric in activity.get("activityMetrics") or []
            if metric.get("name") and metric.get("value") is not None
        ]
        activities.append("; ".join(part for part in (activity_type, ", ".join(metrics)) if part))
    return {
        "id": session.get("id"),
        "date": session.get("date", ""),
        "name": session.get("name", ""),
        "duration_min": session.get("duration", ""),
        "description": session.get("description") or "",
        "activities": " | ".join(activities),
        "sessionMetrics": session.get("sessionMetrics") or [],
    }


class OlympiatoppenToolService:
    TOOL_DEFINITIONS = [
        {"name": "import_session", "description": "Verify a Cookie header obtained from the authenticated Olympiatoppen browser tab, store it in a private local file, and return only verification status. Do not pass cookies from other sites or include them in any other tool call.", "inputSchema": {"type": "object", "properties": {"cookie_header": {"type": "string", "minLength": 1, "description": "Cookie header read from the authenticated Olympiatoppen site in Nettleser. Sensitive session credential; do not include unrelated headers or cURL text."}}, "required": ["cookie_header"], "additionalProperties": False}, "outputSchema": {"type": "object", "properties": {"stored": {"type": "boolean"}, "verified": {"type": "boolean"}}, "required": ["stored", "verified"], "additionalProperties": False}, "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}},
        {"name": "get_session_status", "description": "Check whether the saved diary session exists, has private file permissions, and is currently valid.", "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, "outputSchema": {"type": "object", "properties": {"stored": {"type": "boolean"}, "verified": {"type": "boolean"}}, "required": ["stored", "verified"], "additionalProperties": False}, "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}},
        {"name": "list_workouts", "description": "List logged diary sessions in an inclusive date range. Returns dates, names, descriptions, recorded activity metrics, and sessionMetrics such as perceived load and daily form.", "inputSchema": {"type": "object", "properties": {"from_date": {"type": "string", "format": "date"}, "to_date": {"type": "string", "format": "date"}}, "required": ["from_date", "to_date"], "additionalProperties": False}, "outputSchema": {"type": "object", "additionalProperties": True}, "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}},
        {"name": "get_activity", "description": "Retrieve one exact session by its session ID within a required inclusive date range. Use the logged local date as both bounds when known.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string", "minLength": 1}, "from_date": {"type": "string", "format": "date"}, "to_date": {"type": "string", "format": "date"}}, "required": ["session_id", "from_date", "to_date"], "additionalProperties": False}, "outputSchema": {"type": "object", "additionalProperties": True}, "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}},
        {"name": "clear_session", "description": "Remove the locally saved diary session cookie.", "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, "outputSchema": {"type": "object", "properties": {"cleared": {"type": "boolean"}}, "required": ["cleared"], "additionalProperties": False}, "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}},
    ]

    def list_tools(self) -> list[dict[str, Any]]:
        return self.TOOL_DEFINITIONS

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ToolFailure("arguments must be an object", "invalid_arguments")
        if name == "import_session":
            try:
                cookie = normalize_cookie_header(arguments.get("cookie_header", ""))
            except (AttributeError, TypeError, ValueError):
                raise ToolFailure("cookie_header must contain one non-empty Cookie header", "invalid_arguments") from None
            user_id = get_json("/api/Auth/Session", cookie)
            if not isinstance(user_id, str) or not user_id:
                raise ToolFailure("could not verify the logged-in diary session", "auth_required")
            save_cookie_header(cookie_file_path(), cookie)
            return {"stored": True, "verified": True}
        if name == "get_session_status":
            cookie = read_cookie_header()
            user_id = get_json("/api/Auth/Session", cookie)
            if not isinstance(user_id, str) or not user_id:
                raise ToolFailure("could not verify the logged-in diary session", "auth_required")
            return {"stored": True, "verified": True}
        if name == "list_workouts":
            sessions = _session_for_user(read_cookie_header(), arguments.get("from_date", ""), arguments.get("to_date", ""))
            rows = [session_row(session) for session in sessions]
            rows.sort(key=lambda row: (row["date"], row["name"]))
            return {"count": len(rows), "workouts": rows}
        if name == "get_activity":
            sessions = _session_for_user(read_cookie_header(), arguments.get("from_date", ""), arguments.get("to_date", ""))
            session = next((row for row in sessions if str(row.get("id")) == str(arguments.get("session_id"))), None)
            if session is None:
                raise ToolFailure("session was not found in the requested date range", "not_found")
            return session
        if name == "clear_session":
            path = cookie_file_path()
            existed = path.exists()
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
            return {"cleared": existed}
        raise ToolFailure(f"unknown tool: {name}", "unknown_tool")
