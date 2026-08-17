#!/usr/bin/env python3
"""Transport-independent Python service for Xert activities and workouts."""

from __future__ import annotations

import json
import os
import sys
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
    fetch_calendar_notes_with_opener,
    fetch_recommended_training_with_login,
    set_calendar_note,
)
from xert_common import (  # noqa: E402
    LOCAL_TIMEZONE,
    DEFAULT_XERT_OAUTH_CLIENT_ID,
    DEFAULT_XERT_OAUTH_CLIENT_SECRET,
    XertCredentials,
    _request_json,
    load_xert_credentials,
    xert_web_login,
)
from xert_recovery import fetch_recovery_model_with_login  # noqa: E402
from xert_workouts import (  # noqa: E402
    create_workout as create_saved_workout,
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
        token = credentials.bearer_token()
        training_info = _request_json("/oauth/training_info", token)
        if not isinstance(training_info, dict):
            raise TypeError("Expected Xert training_info endpoint to return an object")
        recovery_model = fetch_recovery_model_with_login(
            username=_required_credential(credentials.username, "XERT_USERNAME"),
            password=_required_credential(credentials.password, "XERT_PASSWORD"),
        )
        if view == "full":
            return {"training_info": training_info, "recovery_model": recovery_model}
        return compact_training_state(training_info, recovery_model)

    def get_training_advice(
        self, *, at: str | None = None, view: str = "summary"
    ) -> dict[str, Any]:
        if view not in {"summary", "full"}:
            raise ValueError("view must be 'summary' or 'full'")
        credentials = self._credentials()
        if at is None:
            payload = fetch_recovery_model_with_login(
                username=_required_credential(credentials.username, "XERT_USERNAME"),
                password=_required_credential(credentials.password, "XERT_PASSWORD"),
            )
            if view == "full":
                return {"source_scope": "current", "at": None, "payload": payload}
            return compact_current_training_advice(payload)

        advice_value = _planned_advice_value(at)
        payload = fetch_recommended_training_with_login(
            username=_required_credential(credentials.username, "XERT_USERNAME"),
            password=_required_credential(credentials.password, "XERT_PASSWORD"),
            date_value=advice_value,
            recent=True,
            additional=False,
            sport=None,
        )
        if view == "full":
            return {"source_scope": "planned_time", "at": at, "payload": payload}
        return compact_planned_training_advice(payload, at=at)

    def _calendar_notes(self) -> dict[str, Any]:
        credentials = self._credentials()
        opener = xert_web_login(
            username=_required_credential(credentials.username, "XERT_USERNAME"),
            password=_required_credential(credentials.password, "XERT_PASSWORD"),
        )
        return fetch_calendar_notes_with_opener(opener)

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


def _designer_row_from_input(row: Any, *, sequence: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError(f"rows[{sequence}] must be an object")
    duration = _nonnegative_int(row.get("duration_seconds"), f"rows[{sequence}].duration_seconds")
    if duration == 0:
        raise ValueError(f"rows[{sequence}].duration_seconds must be positive")
    power = _number_field(row.get("power"), f"rows[{sequence}].power")
    interval_count = _nonnegative_int(row.get("interval_count", 1), f"rows[{sequence}].interval_count")
    if interval_count == 0:
        raise ValueError(f"rows[{sequence}].interval_count must be positive")
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
