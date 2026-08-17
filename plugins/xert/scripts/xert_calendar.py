"""Xert calendar, forecast, and recommendation access."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

from xert_common import (
    CsrfTokenParser,
    LOCAL_TIMEZONE,
    XERT_API_BASE_URL,
    XERT_FORECAST_PATH,
    _coerce_date,
    _open_text,
    _xert_calendar_date_iso,
    xert_web_login,
)


def fetch_calendar_notes_with_opener(opener) -> dict[str, Any]:
    """Fetch Xert calendar notes for the authenticated user."""

    body = _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}/calendar/get-notes",
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "xert-plugin/0.1 (+Xert calendar notes)",
            },
        ),
        "Xert calendar notes",
    )
    notes = json.loads(body)
    if not isinstance(notes, dict):
        raise TypeError("Expected Xert calendar notes endpoint to return an object")
    return notes


def fetch_calendar_events_with_opener(opener, event_date: str | date) -> dict[str, Any]:
    """Fetch and flatten the Xert Planner events for one calendar date."""

    day = _coerce_date(event_date)
    body = _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}/calendar/forecast-activities-close/{day.isoformat()}",
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "xert-plugin/0.1 (+Xert calendar events)",
            },
        ),
        "Xert calendar events",
    )
    source = json.loads(body)
    groups = source.get("activities", []) if isinstance(source, dict) else []
    events = [
        event
        for group in groups
        if isinstance(group, list)
        for event in group
        if isinstance(event, dict)
        and _event_calendar_date(event) == day
    ]
    return {"date": day.isoformat(), "events": events}


def _event_calendar_date(event: dict[str, Any]) -> date | None:
    local_start = event.get("start_date_local")
    if local_start:
        try:
            return datetime.fromisoformat(str(local_start).replace("Z", "+00:00")).date()
        except ValueError:
            pass
    start = event.get("start_date")
    if not start:
        return None
    try:
        parsed = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE).date()


def fetch_calendar_event_with_opener(opener, event_date: str | date, path: str) -> dict[str, Any] | None:
    payload = fetch_calendar_events_with_opener(opener, event_date)
    return next(
        (event for event in payload["events"] if str(event.get("path") or event.get("id")) == path),
        None,
    )


def _post_calendar_json(opener, endpoint: str, payload: dict[str, Any]) -> str:
    csrf_token = getattr(opener, "_xert_csrf_token", None)
    if not csrf_token:
        csrf_token = fetch_my_fitness_csrf_token(opener)
        setattr(opener, "_xert_csrf_token", csrf_token)
    return _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "xert-plugin/0.1 (+Xert calendar event write)",
            },
            method="POST",
        ),
        f"Xert {endpoint}",
    )


def create_calendar_event_with_opener(opener, event: dict[str, Any]) -> dict[str, Any]:
    """Create a Planner event and read it back from its calendar day."""

    start = datetime.fromisoformat(str(event["start_date"]).replace("Z", "+00:00"))
    title = str(event.get("title") or "").strip()
    if not title:
        raise ValueError("calendar event requires title")
    response = _post_calendar_json(opener, "/createCalendarEvent", event)
    candidates = fetch_calendar_events_with_opener(opener, start.date())["events"]
    matches = [
        candidate
        for candidate in candidates
        if candidate.get("name") == title
        and _same_instant(candidate.get("start_date"), start)
    ]
    if not matches:
        raise RuntimeError("Xert calendar event was not found after create")
    created = matches[-1]
    return {"success": True, "response": response, "event": created}


def _same_instant(raw: Any, expected: datetime) -> bool:
    if not raw:
        return False
    try:
        actual = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if actual.tzinfo is None or expected.tzinfo is None:
        return actual.replace(tzinfo=None) == expected.replace(tzinfo=None)
    return actual.astimezone(timezone.utc) == expected.astimezone(timezone.utc)


def update_calendar_event_with_opener(
    opener,
    event_date: str | date,
    path: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Update a manual Planner event through Xert's create-or-edit endpoint."""

    current = fetch_calendar_event_with_opener(opener, event_date, path)
    if current is None:
        raise ValueError(f"Xert calendar event not found: {path}")
    allowed = {
        "start_date", "end_date", "duration", "sport", "description", "focus",
        "sfd", "specificity_rating", "sp", "xss", "xlss", "xhss", "xpss",
        "distance",
    }
    event = {key: current[key] for key in allowed if key in current}
    event.update({key: value for key, value in patch.items() if key != "options"})
    event["title"] = patch.get("title", current.get("name") or current.get("title"))
    event["manualExercise"] = patch.get("manualExercise", True)
    options = {
        "planned": True,
        "state": list(current.get("state") or ["scheduled", "recommended"]),
        "edit_id": path,
    }
    options.update(patch.get("options") or {})
    event["options"] = options
    _post_calendar_json(opener, "/createCalendarEvent", event)
    new_start = datetime.fromisoformat(str(event["start_date"]).replace("Z", "+00:00"))
    verified = fetch_calendar_event_with_opener(opener, new_start.date(), path)
    return {"success": verified is not None, "event": verified, "payload": event}


def delete_calendar_event_with_opener(opener, event_date: str | date, path: str) -> dict[str, Any]:
    """Delete one Planner event and verify that it is absent."""

    current = fetch_calendar_event_with_opener(opener, event_date, path)
    if current is None:
        raise ValueError(f"Xert calendar event not found: {path}")
    response = _post_calendar_json(opener, "/deleteCalendarEvent", {"id": path})
    verified = fetch_calendar_event_with_opener(opener, event_date, path)
    return {"success": verified is None, "response": response, "deleted": current}

def set_calendar_note(
    note_date: str | date,
    notes: str,
    *,
    username: str | None = None,
    password: str | None = None,
    update_weight: bool = False,
    weight: float | None = None,
    weight_units: str = "kg",
) -> dict[str, Any]:
    """Set one Xert calendar note and verify it through get-notes."""

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    day = _coerce_date(note_date)
    opener = xert_web_login(username=username, password=password)
    csrf_token = fetch_my_fitness_csrf_token(opener)
    payload = {
        "notes": notes,
        "weight": "" if weight is None else weight,
        "weight_units": weight_units,
        "date": _xert_calendar_date_iso(day),
        "forUser": username,
        "updateWeight": "true" if update_weight else "false",
    }
    request = Request(
        f"{XERT_API_BASE_URL}/calendar/save-notes",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-CSRF-TOKEN": csrf_token,
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "xert-plugin/0.1 (+Xert calendar save-notes)",
        },
        method="POST",
    )
    response_body = _open_text(opener, request, "Xert calendar save-notes")
    verified_notes = fetch_calendar_notes_with_opener(opener)
    date_key = day.isoformat()
    verified = verified_notes.get(date_key)
    return {
        "date": date_key,
        "payload": payload,
        "response": response_body,
        "verified": verified,
        "verified_notes": (verified or {}).get("notes") if isinstance(verified, dict) else None,
        "success": isinstance(verified, dict) and verified.get("notes") == notes,
    }

def fetch_my_fitness_csrf_token(opener) -> str:
    """Fetch the CSRF token embedded in Xert's my-fitness page."""

    html_text = _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}/my-fitness",
            headers={"User-Agent": "xert-plugin/0.1 (+Xert my-fitness csrf)"},
        ),
        "Xert my-fitness",
    )
    token = CsrfTokenParser.from_html(html_text)
    if not token:
        token_match = re.search(r"Xert\._csrfToken\s*=\s*\"([^\"]+)\"", html_text)
        token = token_match.group(1) if token_match else None
    if not token:
        raise TypeError("Expected Xert my-fitness page to include a CSRF token")
    return token

def fetch_recommended_training_with_login(
    *,
    date_value: str | date,
    recent: bool,
    additional: bool,
    sport: str | None,
    username: str,
    password: str,
) -> dict[str, Any]:
    """Fetch Xert recommendations by creating a web login session."""

    opener = xert_web_login(username=username, password=password)
    return fetch_recommended_training_with_opener(
        opener,
        date_value=date_value,
        recent=recent,
        additional=additional,
        sport=sport,
    )


def fetch_recommended_training_with_opener(
    opener,
    *,
    date_value: str | date,
    recent: bool,
    additional: bool,
    sport: str | None,
) -> dict[str, Any]:
    """Fetch Xert recommendations using an existing authenticated session."""

    request = Request(
        recommended_training_url(
            date_value=date_value,
            recent=recent,
            additional=additional,
            sport=sport,
        ),
        headers={
            "Accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "xert-plugin/0.1 (+Xert recommended training)",
        },
    )
    try:
        with opener.open(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert recommended training request failed: "
            f"HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return json.loads(body)

def recommended_training_url(
    *,
    date_value: str | date,
    recent: bool,
    additional: bool,
    sport: str | None,
) -> str:
    params = {
        "recent": str(recent).lower(),
        "date": recommended_training_timestamp(date_value),
        "additional": str(additional).lower(),
        "sport": sport if sport else "null",
    }
    return f"{XERT_API_BASE_URL}/recommended-training?{urlencode(params)}"


def recommended_training_timestamp(date_value: str | date | datetime) -> str:
    if isinstance(date_value, datetime):
        value = date_value
    elif isinstance(date_value, date):
        value = datetime.combine(date_value, time.min, tzinfo=timezone.utc)
    else:
        raw = str(date_value)
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            value = datetime.combine(date.fromisoformat(raw), time.min, tzinfo=timezone.utc)
    return value.isoformat()


def fetch_training_forecast_with_login(*, username: str, password: str) -> dict[str, Any]:
    """Fetch Xert calendar training forecast by creating a web login session."""

    opener = xert_web_login(username=username, password=password)
    return fetch_training_forecast_with_opener(opener)

def fetch_training_forecast_with_opener(opener) -> dict[str, Any]:
    """Fetch Xert calendar training forecast with an authenticated opener."""

    request = Request(
        f"{XERT_API_BASE_URL}{XERT_FORECAST_PATH}?duration=-1&includePlaceholders=true",
        headers={
            "Accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "xert-plugin/0.1 (+Xert calendar forecast)",
        },
    )
    try:
        with opener.open(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert forecast request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return json.loads(body)
