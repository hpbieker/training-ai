#!/usr/bin/env python3
"""Transport-independent Python service for Xert activities and workouts."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
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
from xert_calendar import (  # noqa: E402
    create_calendar_event_with_opener,
    delete_calendar_event_with_opener,
    fetch_calendar_events_with_opener,
    fetch_calendar_notes_with_opener,
    fetch_recommended_training_with_opener,
    fetch_training_forecast_with_opener,
    set_calendar_note,
    update_calendar_event_with_opener,
)
from xert_common import (  # noqa: E402
    LOCAL_TIMEZONE,
    DEFAULT_XERT_OAUTH_CLIENT_ID,
    DEFAULT_XERT_OAUTH_CLIENT_SECRET,
    XertCredentials,
    _request_json,
    request_xert_token,
    xert_web_login,
)
from xert_recovery import calculate_workout_capacity, fetch_recovery_model_with_opener  # noqa: E402
from xert_load_model import calculate_load_projection  # noqa: E402
from xert_strain_model import calculate_workout as calculate_strain_workout, solve_segment_duration  # noqa: E402
from xert_workouts import (  # noqa: E402
    create_workout as create_saved_workout,
    calculate_new_workout,
    delete_workout as delete_saved_workout,
    fetch_workout,
    fetch_workout_designer_rows,
    list_workouts as fetch_workouts,
    replace_workout as replace_saved_workout,
    summarize_workout_library,
    update_workout as update_saved_workout,
    update_workout_rows,
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

    return XertCredentials(
        username=os.environ.get("XERT_USERNAME") or _config_string(config, "username"),
        password=os.environ.get("XERT_PASSWORD") or _config_string(config, "password"),
        oauth_client_id=(
            os.environ.get("XERT_OAUTH_CLIENT_ID")
            or _config_string(config, "oauthClientId")
            or DEFAULT_XERT_OAUTH_CLIENT_ID
        ),
        oauth_client_secret=(
            os.environ.get("XERT_OAUTH_CLIENT_SECRET")
            or _config_string(config, "oauthClientSecret")
            or DEFAULT_XERT_OAUTH_CLIENT_SECRET
        ),
    )


def _config_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value if isinstance(value, str) and value else None


class XertAuthSession:
    """Authentication state owned by one CLI or MCP service instance."""

    def __init__(self, credentials: XertCredentials) -> None:
        self.credentials = credentials
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._opener: Any = None

    def bearer_token(self) -> str:
        with self._lock:
            now = time.monotonic()
            if self._token is not None and now < self._token_expires_at:
                return self._token
            credentials = self.credentials
            payload = request_xert_token(
                _required_credential(credentials.username, "XERT_USERNAME"),
                _required_credential(credentials.password, "XERT_PASSWORD"),
                client_id=credentials.oauth_client_id,
                client_secret=credentials.oauth_client_secret,
            )
            lifetime = payload.get("expires_in", 3600)
            try:
                lifetime_seconds = float(lifetime)
            except (TypeError, ValueError):
                lifetime_seconds = 3600.0
            self._token = str(payload["access_token"])
            self._token_expires_at = now + max(1.0, lifetime_seconds - 60.0)
            return self._token

    def web_opener(self) -> Any:
        with self._lock:
            if self._opener is None:
                credentials = self.credentials
                self._opener = xert_web_login(
                    username=_required_credential(credentials.username, "XERT_USERNAME"),
                    password=_required_credential(credentials.password, "XERT_PASSWORD"),
                )
            return self._opener


class XertService:
    """Stable Python call boundary shared by the CLI and MCP transports."""

    def __init__(self, credential_factory: CredentialFactory = discover_xert_credentials) -> None:
        self._auth = XertAuthSession(credential_factory())

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
            activities = fetch_activities(
                username=credentials.username,
                password=credentials.password,
                oldest=start_date,
                newest=end_date,
                access_token=self._auth.bearer_token(),
            )
            return [
                compact_activity_load({
                    "path": activity.get("path"),
                    "activity_list_row": activity,
                })
                for activity in activities
                if isinstance(activity, dict)
            ]
        details = list_activity_details(
            username=credentials.username,
            password=credentials.password,
            oldest=start_date,
            newest=end_date,
            include_session_data=False,
            access_token=self._auth.bearer_token(),
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
            access_token=self._auth.bearer_token(),
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
            access_token=self._auth.bearer_token(),
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
                access_token=self._auth.bearer_token(),
            )
        return fetch_workout_designer_rows(self._auth.web_opener(), path)

    def create_workout(
        self,
        *,
        name: str,
        rows: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        designer_rows = [
            _designer_row_from_input(row, sequence=index)
            for index, row in enumerate(rows)
        ] if isinstance(rows, list) else []
        if not designer_rows:
            raise ValueError("rows must be a non-empty array")
        credentials = self._credentials()
        return create_saved_workout(
            username=credentials.username,
            password=credentials.password,
            name=name.strip(),
            description=description,
            rows=designer_rows,
            opener=self._auth.web_opener(),
        )

    def delete_workout(self, path: str) -> dict[str, Any]:
        path = _require_identifier(path, "workout path")
        credentials = self._credentials()
        return delete_saved_workout(
            path,
            username=credentials.username,
            password=credentials.password,
            opener=self._auth.web_opener(),
            access_token=self._auth.bearer_token(),
        )

    def update_workout(
        self,
        path: str,
        *,
        name: str | None = None,
        description: str | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        path = _require_identifier(path, "workout path")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValueError("name must be a non-empty string when supplied")
        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string when supplied")
        if name is None and description is None and rows is None:
            raise ValueError("update_workout requires name, description, or rows")
        credentials = self._credentials()
        normalized_name = name.strip() if isinstance(name, str) else None
        if rows is not None:
            if not isinstance(rows, list) or not rows:
                raise ValueError("rows must be a non-empty operation array when supplied")
            opener = self._auth.web_opener()
            current_rows = fetch_workout_designer_rows(opener, path)
            designer_rows = _apply_workout_row_operations(current_rows, rows)
            result = replace_saved_workout(
                path,
                username=credentials.username,
                password=credentials.password,
                rows=designer_rows,
                name=normalized_name,
                description=description,
                submit="save",
                opener=opener,
            )
            result.pop("replaced_rows", None)
            return result
        return update_saved_workout(
            path,
            username=credentials.username,
            password=credentials.password,
            name=normalized_name,
            description=description,
            submit="save",
            opener=self._auth.web_opener(),
        )

    def list_notes(self, start_date: str, end_date: str) -> list[dict[str, str]]:
        start, end = _validate_date_range(start_date, end_date)
        notes = self._calendar_notes()
        result = []
        for raw_date, payload in notes.items():
            try:
                note_date = date.fromisoformat(str(raw_date))
            except ValueError:
                continue
            text = payload.get("notes") if isinstance(payload, dict) else None
            if start <= note_date <= end and isinstance(text, str) and text:
                result.append({"date": note_date.isoformat(), "text": text})
        return sorted(result, key=lambda note: note["date"])

    def list_planner_events(
        self, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """List mixed Planner events over an inclusive local-date range."""

        start, end = _validate_date_range(start_date, end_date)
        opener = self._auth.web_opener()
        events: list[dict[str, Any]] = []
        day = start
        while day <= end:
            events.extend(fetch_calendar_events_with_opener(opener, day)["events"])
            day += timedelta(days=1)
        return events

    def create_planner_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        result = create_calendar_event_with_opener(self._auth.web_opener(), event)
        if not result.get("success") or not isinstance(result.get("event"), dict):
            raise RuntimeError("Xert Planner event create verification failed")
        return result

    def update_planner_event(
        self, event_date: str, event_path: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        day = _validate_date(event_date, "date")
        path = _required_string(event_path, "event_path")
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch must be a non-empty object")
        result = update_calendar_event_with_opener(
            self._auth.web_opener(), day, path, patch
        )
        if not result.get("success") or not isinstance(result.get("event"), dict):
            raise RuntimeError("Xert Planner event update verification failed")
        return result

    def delete_planner_event(
        self, event_date: str, event_path: str
    ) -> dict[str, Any]:
        day = _validate_date(event_date, "date")
        path = _required_string(event_path, "event_path")
        result = delete_calendar_event_with_opener(self._auth.web_opener(), day, path)
        if not result.get("success") or not isinstance(result.get("deleted"), dict):
            raise RuntimeError("Xert Planner event delete verification failed")
        return result

    def get_note(self, note_date: str) -> dict[str, Any]:
        day = _validate_date(note_date, "date")
        payload = self._calendar_notes().get(day.isoformat())
        text = payload.get("notes") if isinstance(payload, dict) else None
        exists = isinstance(text, str) and bool(text)
        return {"date": day.isoformat(), "exists": exists, "text": text if exists else None}

    def set_note(self, note_date: str, text: str) -> dict[str, Any]:
        day = _validate_date(note_date, "date")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        credentials = self._credentials()
        result = set_calendar_note(
            day,
            text,
            username=credentials.username,
            password=credentials.password,
            opener=self._auth.web_opener(),
        )
        return {
            "date": day.isoformat(),
            "exists": bool(text),
            "text": result.get("verified_notes") if text else None,
            "success": bool(result.get("success")),
        }

    def get_training_state(self, *, view: str = "summary") -> dict[str, Any]:
        if view not in {"summary", "full"}:
            raise ValueError("view must be 'summary' or 'full'")
        credentials = self._credentials()
        token = self._auth.bearer_token()
        training_info = _request_json("/oauth/training_info", token)
        if not isinstance(training_info, dict):
            raise TypeError("Expected Xert training_info endpoint to return an object")
        recovery_model = fetch_recovery_model_with_opener(self._auth.web_opener())
        if view == "full":
            return {"training_info": training_info, "recovery_model": recovery_model}
        return compact_training_state(training_info, recovery_model)

    def get_training_advice(
        self,
        *,
        at: str | None = None,
        view: str = "summary",
    ) -> dict[str, Any]:
        if view not in {"summary", "full"}:
            raise ValueError("view must be 'summary' or 'full'")
        credentials = self._credentials()
        if at is None:
            payload = fetch_recovery_model_with_opener(self._auth.web_opener())
            if view == "full":
                return {"source_scope": "current", "at": None, "payload": payload}
            return compact_current_training_advice(payload)

        advice_value = _planned_advice_value(at)
        payload = fetch_recommended_training_with_opener(
            self._auth.web_opener(),
            date_value=advice_value,
            recent=True,
            additional=False,
            sport=None,
        )
        if view == "full":
            advice_payload = dict(payload)
            advice_payload.pop("exercises", None)
            return {"source_scope": "planned_time", "at": at, "payload": advice_payload}
        return compact_planned_training_advice(payload, at=at)

    def list_recommended_workouts(
        self, *, at: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        advice_at = at or datetime.now(LOCAL_TIMEZONE).isoformat()
        payload = fetch_recommended_training_with_opener(
            self._auth.web_opener(),
            date_value=_planned_advice_value(advice_at),
            recent=True,
            additional=False,
            sport=None,
        )
        return compact_workout_recommendations(payload)[:limit]

    def calculate_workout_capacity(self, *, as_of: str, fresh_at: str) -> dict[str, Any]:
        model = fetch_recovery_model_with_opener(self._auth.web_opener())
        at_state = model.get("at_state") or {}
        source_at = _aware_datetime(at_state.get("start_date"), "Xert state time")
        capacity_at = _aware_datetime(as_of, "as_of")
        fresh = _aware_datetime(fresh_at, "fresh_at")
        if capacity_at < source_at or fresh < capacity_at:
            raise ValueError("require Xert state <= as_of <= fresh_at")
        projected = _project_at_state_without_training(
            at_state=at_state,
            ir_params=model["ir_params"],
            days=(capacity_at - source_at).total_seconds() / 86400,
            start_date=capacity_at.isoformat(),
        )
        capacity = calculate_workout_capacity(
            next_workout_days=(fresh - capacity_at).total_seconds() / 86400,
            ir_params=model["ir_params"],
            recovery_offset=float(model["recovery_offset"]),
            at_state=projected,
        )
        return {
            "source": "xert_plugin_explicit_workout_capacity",
            "source_state_as_of": source_at.isoformat(),
            "state_as_of": capacity_at.isoformat(),
            "fresh_at": fresh.isoformat(),
            "workout_capacity_xss": {"low": capacity["lo"], "high": capacity["hi"], "peak": capacity["pk"]},
            "assumption": "no_intervening_training_before_or_after_the_modeled_impulse",
        }

    def calculate_strain(self, *, signature: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
        return calculate_strain_workout(signature=signature, segments=segments, include_series=False)

    def solve_segment_duration(self, **arguments: Any) -> dict[str, Any]:
        return solve_segment_duration(**arguments)

    def project_load_model(
        self, *, target_at: str, workout_after_hours: float = 0.0,
        low_xss: float = 0.0, high_xss: float = 0.0, peak_xss: float = 0.0,
        build_tp: float = 0.0, build_hie: float = 0.0, build_pp: float = 0.0,
    ) -> dict[str, Any]:
        token = self._auth.bearer_token()
        training_info = _request_json("/oauth/training_info", token)
        model = fetch_recovery_model_with_opener(self._auth.web_opener())
        at_state = dict(model["at_state"])
        at_state["recovery_offset"] = model["recovery_offset"]
        source_at = _aware_datetime(at_state.get("start_date"), "Xert state time")
        target = _aware_datetime(target_at, "target_at")
        horizon_days = (target - source_at).total_seconds() / 86400
        if horizon_days < 0:
            raise ValueError("target_at must not precede the current Xert state")
        payload = calculate_load_projection(
            at_state=at_state,
            ir_params=model["ir_params"],
            current_signature=training_info["signature"],
            planned_xss={"low": low_xss, "high": high_xss, "peak": peak_xss},
            horizon_days=horizon_days,
            workout_after_days=workout_after_hours / 24,
            desired_signature_gain={"ftp": build_tp, "hie": build_hie, "pp": build_pp},
        )
        payload["target_at"] = target.isoformat()
        return payload

    def calculate_workout(self, *, name: str, description: str, rows: list[dict[str, Any]],
                          include_series: bool = False, signature_tp: float | None = None,
                          signature_hie: float | None = None, signature_pp: float | None = None) -> dict[str, Any]:
        credentials = self._credentials()
        return calculate_new_workout(
            username=credentials.username, password=credentials.password,
            name=name, description=description, rows=[_designer_row_from_input(row, sequence=i) for i, row in enumerate(rows)],
            include_series=include_series, signature_tp=signature_tp,
            signature_hie=signature_hie, signature_pp=signature_pp,
        )

    def get_training_forecast(
        self, start_date: str, end_date: str, *, view: str = "summary"
    ) -> dict[str, Any]:
        start, end = _validate_date_range(start_date, end_date)
        if view not in {"summary", "full"}:
            raise ValueError("view must be 'summary' or 'full'")
        credentials = self._credentials()
        payload = fetch_training_forecast_with_opener(self._auth.web_opener())
        days = _forecast_days_in_range(payload, start, end)
        if view == "full":
            full = dict(payload) if isinstance(payload, dict) else {}
            full["days"] = days
            return full
        return {"days": [compact_forecast_day(day) for day in days]}

    def _calendar_notes(self) -> dict[str, Any]:
        return fetch_calendar_notes_with_opener(self._auth.web_opener())

    def _credentials(self) -> XertCredentials:
        credentials = self._auth.credentials
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
        "start_local": _activity_start_local(summary) or _activity_start_local(list_row),
        "distance_km": summary.get("distance") or list_row.get("distance"),
        "elapsed_minutes": _minutes(_number(
            summary.get("duration")
            or session.get("total_elapsed_time")
            or list_row.get("duration")
        )),
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


def _designer_row_from_input(row: Any, *, sequence: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError(f"rows[{sequence}] must be an object")
    duration = _nonnegative_int(row.get("duration_seconds"), f"rows[{sequence}].duration_seconds")
    if duration == 0:
        raise ValueError(f"rows[{sequence}].duration_seconds must be positive")
    power = _number_field(row.get("power"), f"rows[{sequence}].power")
    interval_count = _nonnegative_int(row.get("interval_count", 1), f"rows[{sequence}].interval_count")
    rib_duration = _nonnegative_int(
        row.get("rib_duration_seconds", 0), f"rows[{sequence}].rib_duration_seconds"
    )
    power_type = str(row.get("power_type") or "absolute")
    if power_type not in {"absolute", "relative_ftp", "ramp_ftp", "ramp_ltp", "ramp_absolute"}:
        raise ValueError(f"rows[{sequence}].power_type is unsupported")
    rib_power_type = str(row.get("rib_power_type") or "absolute")
    if rib_power_type not in {"absolute", "relative_ftp"}:
        raise ValueError(f"rows[{sequence}].rib_power_type is unsupported")
    power_object: dict[str, Any] = {
        "type": power_type,
        "value": power,
    }
    if row.get("power_second_value") is not None:
        power_object["second_value"] = _number_field(
            row["power_second_value"], f"rows[{sequence}].power_second_value"
        )
    if power_type.startswith("ramp_") and "second_value" not in power_object:
        raise ValueError(f"rows[{sequence}].power_second_value is required for a ramp")
    return {
        "sequence": sequence,
        "DT_RowId": "",
        "name": str(row.get("name") or f"Row {sequence + 1}"),
        "duration": {"type": "absolute", "value": _duration_text(duration)},
        "power": power_object,
        "interval_count": str(interval_count),
        "rib_duration": {"type": "absolute", "value": _duration_text(rib_duration)},
        "rib_power": {
            "type": rib_power_type,
            "value": _number_field(row.get("rib_power", 0), f"rows[{sequence}].rib_power"),
        },
    }


_ROW_FIELDS = {
    "name", "duration_seconds", "power", "power_type", "power_second_value",
    "interval_count", "rib_duration_seconds", "rib_power", "rib_power_type",
}


def _apply_workout_row_operations(
    rows: list[dict[str, Any]], operations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply validated operations against one original row snapshot."""

    original = deepcopy(rows)
    updates: dict[int, dict[str, Any]] = {}
    removed: set[int] = set()
    before: dict[int, list[dict[str, Any]]] = {}
    after: dict[int, list[dict[str, Any]]] = {}

    def row_number(operation: dict[str, Any], field: str) -> int:
        value = operation.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= len(original):
            raise ValueError(f"{field} must identify an original row from 1 to {len(original)}")
        return value

    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"rows[{index}] must be an operation object")
        method = operation.get("method")
        if method not in {"update", "insert", "remove"}:
            raise ValueError(f"rows[{index}].method must be update, insert, or remove")
        fields = set(operation) - {"method", "row_number", "before_row_number", "after_row_number"}
        unknown = fields - _ROW_FIELDS
        if unknown:
            raise ValueError(f"rows[{index}] has unsupported fields: {', '.join(sorted(unknown))}")

        if method == "insert":
            if "row_number" in operation:
                raise ValueError(f"rows[{index}] insert must not use row_number")
            anchors = [key for key in ("before_row_number", "after_row_number") if key in operation]
            if len(anchors) != 1:
                raise ValueError(
                    f"rows[{index}] insert requires exactly one of before_row_number or after_row_number"
                )
            inserted = _designer_row_from_input(
                {key: operation[key] for key in fields}, sequence=index
            )
            anchor = row_number(operation, anchors[0])
            (before if anchors[0] == "before_row_number" else after).setdefault(
                anchor, []
            ).append(inserted)
            continue

        if "before_row_number" in operation or "after_row_number" in operation:
            raise ValueError(f"rows[{index}] {method} must not use an insertion anchor")
        target = row_number(operation, "row_number")
        if method == "remove":
            if fields:
                raise ValueError(f"rows[{index}] remove must not include row fields")
            if target in removed or target in updates:
                raise ValueError(f"Conflicting operations for original row {target}")
            removed.add(target)
            continue
        if not fields:
            raise ValueError(f"rows[{index}] update requires at least one row field")
        if target in removed:
            raise ValueError(f"Conflicting operations for original row {target}")
        existing = updates.setdefault(target, {})
        overlap = set(existing) & fields
        if overlap:
            raise ValueError(
                f"Conflicting updates for original row {target}: {', '.join(sorted(overlap))}"
            )
        existing.update({key: operation[key] for key in fields})

    result: list[dict[str, Any]] = []
    for number, original_row in enumerate(original, start=1):
        result.extend(before.get(number, []))
        if number not in removed:
            row = deepcopy(original_row)
            patch = updates.get(number)
            if patch:
                update_workout_rows(
                    [row],
                    set_duration=(
                        _duration_text(_positive_int(patch["duration_seconds"], "duration_seconds"))
                        if "duration_seconds" in patch else None
                    ),
                    set_power=(
                        _number_field(patch["power"], "power") if "power" in patch else None
                    ),
                    set_power_type=patch.get("power_type"),
                    set_power_second_value=(
                        _number_field(patch["power_second_value"], "power_second_value")
                        if "power_second_value" in patch else None
                    ),
                    set_row_name=patch.get("name") if "name" in patch else None,
                    set_interval_count=(
                        str(_nonnegative_int(patch["interval_count"], "interval_count"))
                        if "interval_count" in patch else None
                    ),
                    set_rib_duration=(
                        _duration_text(_nonnegative_int(patch["rib_duration_seconds"], "rib_duration_seconds"))
                        if "rib_duration_seconds" in patch else None
                    ),
                    set_rib_power=(
                        _number_field(patch["rib_power"], "rib_power")
                        if "rib_power" in patch else None
                    ),
                    set_rib_power_type=patch.get("rib_power_type"),
                )
            result.append(row)
        result.extend(after.get(number, []))
    if not result:
        raise ValueError("Workout must retain at least one row")
    return result


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise ValueError(f"{label} must be positive")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _number_field(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return value


def _duration_text(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def compact_training_state(
    training_info: dict[str, Any], recovery_model: dict[str, Any]
) -> dict[str, Any]:
    signature = training_info.get("signature") if isinstance(training_info.get("signature"), dict) else {}
    at_state = recovery_model.get("at_state") if isinstance(recovery_model.get("at_state"), dict) else {}
    return {
        "source": "xert_plugin_training_state",
        "as_of": at_state.get("start_date"),
        "signature": {
            "tp_watts": signature.get("ftp"),
            "ltp_watts": signature.get("ltp"),
            "hie_kj": signature.get("hie"),
            "pp_watts": signature.get("pp"),
        },
        "training_status": recovery_model.get("training_status") or training_info.get("status"),
        "training_load": _system_triplet(at_state.get("tl"), "ftp", "hie", "pp"),
        "recovery_load": _system_triplet(at_state.get("rl"), "ftp", "hie", "pp"),
        "form": at_state.get("form"),
        "recovery_hours": _system_triplet(recovery_model.get("recovery_hours"), "lo", "hi", "pk"),
        "target_xss": _system_triplet(recovery_model.get("targetXSS"), "xlss", "xhss", "xpss"),
    }


def compact_current_training_advice(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": model.get("source"),
        "source_endpoint": "/my-fitness",
        "source_scope": "current",
        "at": None,
        "training_status": model.get("training_status"),
        "target_xss": _system_triplet(model.get("targetXSS"), "xlss", "xhss", "xpss"),
        "remaining_xss": None,
        "completed_xss": None,
        "original_target_xss": None,
        "daily_goal_complete": None,
        "recovery_needed": None,
        "training_advice_as_of": (model.get("at_state") or {}).get("start_date"),
        "targets_source": None,
        "based_on_day": None,
    }


def _aware_datetime(value: Any, label: str) -> datetime:
    if not value:
        raise ValueError(f"{label} must be an ISO date-time")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date-time") from exc
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def _project_at_state_without_training(
    *, at_state: dict[str, Any], ir_params: dict[str, Any], days: float, start_date: str
) -> dict[str, Any]:
    if days < 0:
        raise ValueError("projection days must not be negative")
    training_load, recovery_load = at_state.get("tl"), at_state.get("rl")
    if not isinstance(training_load, dict) or not isinstance(recovery_load, dict):
        raise TypeError("Expected at_state with tl and rl objects")
    projected_tl, projected_rl = dict(training_load), dict(recovery_load)
    for key in ("ftp", "hie", "pp"):
        params = ir_params.get(key)
        if not isinstance(params, dict):
            raise TypeError(f"Expected ir_params.{key}")
        tau1, tau2 = float(params["tau1"]), float(params["tau2"])
        tl = float(training_load[key]) * math.exp(-days / tau1)
        classic_rl = float(recovery_load[key]) * math.exp(-days / tau2)
        rl_cap = tl * math.exp(-1.0 / tau2)
        projected_tl[key] = tl
        projected_rl[key] = max(classic_rl, rl_cap)
        projected_rl[f"{key}-cap"] = rl_cap
    return {**at_state, "start_date": start_date, "tl": projected_tl, "rl": projected_rl}


def compact_planned_training_advice(payload: dict[str, Any], *, at: str) -> dict[str, Any]:
    advice = payload.get("training_advice") if isinstance(payload, dict) else {}
    if not isinstance(advice, dict):
        advice = {}
    return {
        "source": "xert_recommended_training",
        "source_endpoint": "/recommended-training",
        "source_scope": "planned_time",
        "at": at,
        "training_status": advice.get("training_status"),
        "target_xss": _system_triplet(advice.get("targetXSS"), "xlss", "xhss", "xpss"),
        "remaining_xss": _system_triplet(advice.get("remainingXSS"), "xlss", "xhss", "xpss"),
        "completed_xss": _system_triplet(advice.get("completedXSS"), "xlss", "xhss", "xpss"),
        "original_target_xss": _system_triplet(
            advice.get("originalTargetXSS"), "xlss", "xhss", "xpss"
        ),
        "daily_goal_complete": advice.get("daily_goal_complete"),
        "recovery_needed": advice.get("recovery_needed"),
        "training_advice_as_of": advice.get("training_advice_as_of"),
        "targets_source": advice.get("targets_source"),
        "based_on_day": advice.get("based_on_day"),
    }


def compact_workout_recommendations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    exercises = payload.get("exercises") if isinstance(payload, dict) else []
    if not isinstance(exercises, list):
        return []
    return [
        {
            "path": exercise.get("path"),
            "name": exercise.get("name"),
            "duration_seconds": exercise.get("duration"),
            "xss": {
                "total": exercise.get("xss"),
                "low": exercise.get("xlss"),
                "high": exercise.get("xhss"),
                "peak": exercise.get("xpss"),
            },
            "focus": exercise.get("focus"),
            "specificity": exercise.get("specificity"),
            "difficulty": exercise.get("difficulty"),
            "rating": exercise.get("rating"),
            "suitability": exercise.get("suitability"),
        }
        for exercise in exercises
        if isinstance(exercise, dict) and exercise.get("exerciseType") == "Workout"
    ]


def _forecast_days_in_range(
    payload: Any, start: date, end: date
) -> list[dict[str, Any]]:
    source_days = payload.get("days") if isinstance(payload, dict) else []
    if not isinstance(source_days, list):
        return []
    result = []
    for day in source_days:
        if not isinstance(day, dict):
            continue
        timestamp = day.get("t")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
            continue
        local_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).astimezone(
            LOCAL_TIMEZONE
        )
        if start <= local_at.date() <= end:
            normalized = dict(day)
            normalized["date"] = local_at.date().isoformat()
            normalized["at"] = local_at.isoformat(timespec="seconds")
            result.append(normalized)
    return result


def compact_forecast_day(day: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": day.get("date"),
        "at": day.get("at"),
        "name": day.get("name") or day.get("title"),
        "focus": day.get("focus"),
        "high_intensity": day.get("high_intensity"),
        "xss": {
            "total": day.get("xss"),
            "low": day.get("xlss"),
            "high": day.get("xhss"),
            "peak": day.get("xpss"),
        },
    }


def _planned_advice_value(at: str) -> str:
    try:
        planned_at = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("at must be an ISO date-time") from exc
    if planned_at.tzinfo is None:
        planned_at = planned_at.replace(tzinfo=LOCAL_TIMEZONE)
    return (planned_at - timedelta(seconds=1)).astimezone(timezone.utc).isoformat(
        timespec="seconds"
    )


def _system_triplet(source: Any, low_key: str, high_key: str, peak_key: str) -> dict[str, Any]:
    if not isinstance(source, dict):
        source = {}
    return {
        "low": source.get(low_key),
        "high": source.get(high_key),
        "peak": source.get(peak_key),
    }


def _validate_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    start = _validate_date(start_date, "start_date")
    end = _validate_date(end_date, "end_date")
    if end < start:
        raise ValueError("end_date must not precede start_date")
    return start, end


def _validate_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc


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


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _activity_start_local(summary: dict[str, Any]) -> str | None:
    start = summary.get("start_date")
    if isinstance(start, dict):
        raw = start.get("date")
        if raw:
            parsed = datetime.fromisoformat(str(raw))
            if start.get("timezone") == "UTC":
                parsed = parsed.replace(tzinfo=timezone.utc).astimezone(LOCAL_TIMEZONE)
            return parsed.replace(tzinfo=None).isoformat()
    if isinstance(start, str) and start:
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)
        return parsed.isoformat()
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
