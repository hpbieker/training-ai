#!/usr/bin/env python3
"""CLI for Xert operations that are not exposed by the Xert MCP server."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from xert_service import (
    compact_activity_load,
    discover_xert_credentials,
)

from xert_api import (
    LOCAL_TIMEZONE,
    create_calendar_event_with_opener,
    delete_calendar_event_with_opener,
    fetch_activity_detail,
    fetch_calendar_event_with_opener,
    fetch_calendar_events_with_opener,
    fetch_recommended_training_with_login,
    fetch_recovery_model_with_login,
    update_calendar_event_with_opener,
    xert_web_login,
)


def main() -> None:
    """Expose only Xert operations that do not have an MCP equivalent."""

    parser = argparse.ArgumentParser(description="Xert readiness adapter and Planner utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    readiness = subparsers.add_parser(
        "readiness-input", help="Compact selected Xert fields for training-analysis"
    )
    readiness.add_argument("--activity", action="append", default=[])
    readiness.add_argument(
        "--advice-source",
        choices=("current", "recommended-training", "auto"),
        default="current",
    )
    readiness.add_argument("--advice-date")
    readiness.add_argument("--advice-at")
    readiness.add_argument("--advice-now")
    calendar_events = subparsers.add_parser("calendar-events")
    calendar_events.add_argument("date")
    calendar_event = subparsers.add_parser("calendar-event")
    calendar_event.add_argument("path")
    calendar_event.add_argument("--date", required=True)
    create = subparsers.add_parser("calendar-event-create")
    create.add_argument("--event-json", required=True)
    create.add_argument("--yes", action="store_true")
    update = subparsers.add_parser("calendar-event-update")
    update.add_argument("path")
    update.add_argument("--date", required=True)
    update.add_argument("--patch-json", required=True)
    update.add_argument("--yes", action="store_true")
    delete = subparsers.add_parser("calendar-event-delete")
    delete.add_argument("path")
    delete.add_argument("--date", required=True)
    delete.add_argument("--yes", action="store_true")

    args = parser.parse_args()
    credentials = discover_xert_credentials()
    username = _require(credentials.username, "XERT_USERNAME")
    password = _require(credentials.password, "XERT_PASSWORD")
    if args.command == "readiness-input":
        payload = build_readiness_input(
            username=username,
            password=password,
            activity_paths=args.activity,
            advice_source=args.advice_source,
            advice_date=args.advice_date,
            advice_at=args.advice_at,
            advice_now=args.advice_now,
        )
    else:
        opener = xert_web_login(username=username, password=password)
        if args.command == "calendar-events":
            payload = fetch_calendar_events_with_opener(opener, args.date)
        elif args.command == "calendar-event":
            payload = fetch_calendar_event_with_opener(opener, args.date, args.path)
            if payload is None:
                raise SystemExit(f"Xert calendar event not found: {args.path}")
        elif args.command == "calendar-event-create":
            event = _json_object(args.event_json, "--event-json")
            payload = ({"dry_run": True, "event": event} if not args.yes
                       else create_calendar_event_with_opener(opener, event))
        elif args.command == "calendar-event-update":
            patch = _json_object(args.patch_json, "--patch-json")
            current = fetch_calendar_event_with_opener(opener, args.date, args.path)
            if current is None:
                raise SystemExit(f"Xert calendar event not found: {args.path}")
            payload = ({"dry_run": True, "current": current, "patch": patch} if not args.yes
                       else update_calendar_event_with_opener(opener, args.date, args.path, patch))
        else:
            if not args.yes:
                raise SystemExit("Refusing to delete Xert calendar event without --yes")
            payload = delete_calendar_event_with_opener(opener, args.date, args.path)
    print(json.dumps(payload, indent=2, sort_keys=True))


def _json_object(raw: str, option: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{option} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{option} must contain a JSON object")
    return value


def build_readiness_input(
    *,
    username: str,
    password: str,
    activity_paths: list[str],
    advice_source: str = "current",
    advice_date: str | None = None,
    advice_at: str | None = None,
    advice_now: str | None = None,
) -> dict[str, Any]:
    model = fetch_recovery_model_with_login(username=username, password=password)
    source_time = datetime.now(LOCAL_TIMEZONE)
    current_advice = compact_current_training_advice(model)
    decision = training_advice_source_decision(
        requested_source=advice_source,
        current_advice=current_advice,
        advice_at=advice_at,
        advice_date=advice_date,
        advice_now=advice_now,
    )
    resolved_source = decision["resolved_source"]
    planned_advice = None
    if resolved_source == "recommended-training":
        advice_value = recommended_training_advice_value(
            advice_at=advice_at,
            advice_date=advice_date,
        )
        recommended_training = fetch_recommended_training_with_login(
            username=username,
            password=password,
            date_value=advice_value,
            recent=True,
            additional=False,
            sport=None,
        )
        planned_advice = compact_recommended_training_advice(
            recommended_training,
            advice_value=advice_value,
        )
        training_advice = planned_advice
    elif resolved_source == "current":
        training_advice = current_advice
    else:
        raise ValueError(f"Unknown resolved Xert advice source: {resolved_source}")
    recovery = compact_recovery_model(model)
    if advice_at:
        recovery["recovery_hours_at_advice_time"] = project_recovery_hours(
            recovery.get("recovery_hours"),
            source_time=source_time,
            advice_at=parse_optional_local_datetime(advice_at),
        )
    return {
        "source": "xert_plugin",
        "source_time_local": source_time.isoformat(timespec="seconds"),
        "training_advice": training_advice,
        "training_advice_debug": training_advice_debug(
            decision=decision,
            current_advice=current_advice,
            planned_advice=planned_advice,
        ),
        "recovery": recovery,
        "activity_loads": [
            compact_activity_load(
                fetch_activity_detail(
                    activity_path,
                    username=username,
                    password=password,
                    include_session_data=False,
                )
            )
            for activity_path in activity_paths
        ],
    }


def training_advice_source_decision(
    *,
    requested_source: str,
    current_advice: dict[str, Any],
    advice_at: str | None,
    advice_date: str | None,
    advice_now: str | None,
) -> dict[str, Any]:
    now = parse_optional_local_datetime(advice_now) or datetime.now(LOCAL_TIMEZONE)
    planned_at = parse_optional_local_datetime(advice_at)
    current_fresh = xert_training_status_is_fresh(current_advice.get("training_status"))
    planned_is_other_day = False
    planned_later_than_now = False
    if planned_at is not None:
        planned_is_other_day = planned_at.astimezone(LOCAL_TIMEZONE).date() != now.date()
        planned_later_than_now = planned_at > now + timedelta(minutes=5)
    elif advice_date:
        advice_date_value = parse_optional_local_datetime(advice_date)
        if advice_date_value is not None:
            planned_is_other_day = advice_date_value.date() != now.date()
        else:
            planned_is_other_day = date.fromisoformat(advice_date).isoformat() != now.date().isoformat()

    if requested_source == "auto":
        if planned_is_other_day:
            resolved = "recommended-training"
            reason = "planned_time_is_other_day"
        elif planned_later_than_now and not current_fresh:
            resolved = "recommended-training"
            reason = "planned_time_later_and_current_xert_not_fresh"
        else:
            resolved = "current"
            reason = "current_advice_sufficient"
    else:
        resolved = requested_source
        reason = f"explicit_{requested_source}"

    return {
        "requested_source": requested_source,
        "resolved_source": resolved,
        "reason": reason,
        "advice_at": advice_at,
        "advice_date": advice_date,
        "advice_now": now.isoformat(timespec="seconds"),
        "planned_is_other_day": planned_is_other_day,
        "planned_later_than_now": planned_later_than_now,
        "current_xert_is_fresh": current_fresh,
    }


def parse_optional_local_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def project_recovery_hours(
    recovery_hours: Any,
    *,
    source_time: datetime,
    advice_at: datetime | None,
) -> dict[str, Any]:
    if advice_at is None:
        raise ValueError("advice_at is required for recovery projection")
    values = recovery_hours if isinstance(recovery_hours, dict) else {}
    hours_from_source = (advice_at - source_time).total_seconds() / 3600

    def projected(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value) - hours_from_source, 1)
        except (TypeError, ValueError):
            return None

    return {
        "meaning": (
            "Deterministic projection from source_time_local to advice_time_local; "
            "assumes no intervening training."
        ),
        "advice_time_local": advice_at.isoformat(timespec="seconds"),
        "hours_from_source_time": round(hours_from_source, 1),
        "low": projected(values.get("low")),
        "high": projected(values.get("high")),
        "peak": projected(values.get("peak")),
    }


def xert_training_status_is_fresh(training_status: Any) -> bool:
    if not isinstance(training_status, dict):
        return False
    form_cat = str(training_status.get("form_cat") or "").strip().lower()
    if form_cat:
        return form_cat in {"fresh", "very fresh"}
    cat = str(training_status.get("cat") or "").strip().lower()
    if cat:
        return cat in {"fresh", "very fresh", "elite"}
    return False


def training_advice_debug(
    *,
    decision: dict[str, Any],
    current_advice: dict[str, Any],
    planned_advice: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "meaning": (
            "Debug context for choosing Xert training advice source. If planned "
            "and current targets diverge unexpectedly, inspect the source decision "
            "before changing recommendation logic."
        ),
        "decision": decision,
        "current": {
            "source_endpoint": current_advice.get("source_endpoint"),
            "target_xss": current_advice.get("target_xss"),
            "training_status": compact_debug_training_status(
                current_advice.get("training_status")
            ),
        },
        "planned": (
            {
                "source_endpoint": planned_advice.get("source_endpoint"),
                "date": planned_advice.get("date"),
                "target_xss": planned_advice.get("target_xss"),
                "remaining_xss": planned_advice.get("remaining_xss"),
                "completed_xss": planned_advice.get("completed_xss"),
                "training_status": compact_debug_training_status(
                    planned_advice.get("training_status")
                ),
            }
            if planned_advice
            else None
        ),
    }


def compact_debug_training_status(training_status: Any) -> dict[str, Any] | None:
    if not isinstance(training_status, dict):
        return None
    return {
        "cat": training_status.get("cat"),
        "form_cat": training_status.get("form_cat"),
        "form_ratio": training_status.get("form_ratio"),
        "tl_total": training_status.get("tl_total"),
        "rl_total": training_status.get("rl_total"),
    }


def recommended_training_advice_value(
    *,
    advice_at: str | None,
    advice_date: str | None,
) -> str:
    if advice_at:
        planned_at = datetime.fromisoformat(advice_at.replace("Z", "+00:00"))
        if planned_at.tzinfo is None:
            planned_at = planned_at.replace(tzinfo=LOCAL_TIMEZONE)
        return (planned_at - timedelta(seconds=1)).astimezone(timezone.utc).isoformat(
            timespec="seconds"
        )
    return advice_date or date.today().isoformat()


def compact_current_training_advice(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": model.get("source"),
        "source_endpoint": "/my-fitness",
        "source_scope": "current",
        "training_status": model.get("training_status"),
        "target_xss": _system_triplet(model.get("targetXSS"), "xlss", "xhss", "xpss"),
        "meaning": (
            "Current Xert trainingAdvice from /my-fitness. This is the fastest "
            "source for advice now."
        ),
    }


def compact_recommended_training_advice(
    payload: dict[str, Any],
    *,
    advice_value: str,
) -> dict[str, Any]:
    advice = payload.get("training_advice") if isinstance(payload, dict) else {}
    if not isinstance(advice, dict):
        advice = {}
    return {
        "source": "xert_recommended_training",
        "source_endpoint": "/recommended-training",
        "source_scope": "planned_time",
        "date": advice_value,
        "training_status": advice.get("training_status"),
        "target_xss": _system_triplet(advice.get("targetXSS"), "xlss", "xhss", "xpss"),
        "remaining_xss": _system_triplet(advice.get("remainingXSS"), "xlss", "xhss", "xpss"),
        "completed_xss": _system_triplet(advice.get("completedXSS"), "xlss", "xhss", "xpss"),
        "original_target_xss": _system_triplet(
            advice.get("originalTargetXSS"),
            "xlss",
            "xhss",
            "xpss",
        ),
        "training_advice_as_of": advice.get("training_advice_as_of"),
        "training_advice_as_of_val": advice.get("training_advice_as_of_val"),
        "daily_goal_complete": advice.get("daily_goal_complete"),
        "recovery_needed": advice.get("recovery_needed"),
        "availability": advice.get("availability"),
        "is_availability_restricted": advice.get("is_availability_restricted"),
        "xss_deficit": advice.get("xss_deficit"),
        "xss_goal": advice.get("xss_goal"),
        "hours_deficit": advice.get("hours_deficit"),
        "activity_deficit": advice.get("activity_deficit"),
        "targets_source": advice.get("targets_source"),
        "based_on_day": advice.get("based_on_day"),
        "improvement_rate": advice.get("ir"),
        "weekly_hours": advice.get("weekly_hours"),
        "training_gradient": advice.get("training_gradient"),
        "phase": advice.get("phase"),
        "recommended_athlete": advice.get("recommended_athlete"),
        "meaning": (
            "Planned-time Xert training advice from /recommended-training. Prefer "
            "this source when advice is needed for a planned time rather than now."
        ),
    }


def compact_recovery_model(model: dict[str, Any]) -> dict[str, Any]:
    at_state = model.get("at_state") if isinstance(model.get("at_state"), dict) else {}
    training_load = at_state.get("tl") if isinstance(at_state, dict) else {}
    recovery_load = at_state.get("rl") if isinstance(at_state, dict) else {}
    return {
        "source": model.get("source"),
        "time_scope": "source_time_local",
        "meaning": (
            "recovery_hours is evaluated at the top-level source_time_local. "
            "When --advice-at is supplied, recovery_hours_at_advice_time provides "
            "the projected value for that time, assuming no intervening training; "
            "recovery_hours remains the raw source-time value for auditability."
        ),
        "recovery_offset": model.get("recovery_offset"),
        "next_workout_days": model.get("next_workout_days"),
        "recovery_hours": _system_triplet(model.get("recovery_hours"), "lo", "hi", "pk"),
        "training_load": _system_triplet(training_load, "ftp", "hie", "pp"),
        "recovery_load": _system_triplet(recovery_load, "ftp", "hie", "pp"),
        "workout_capacity": _system_triplet(model.get("workout_capacity"), "lo", "hi", "pk"),
    }


def _system_triplet(source: Any, low_key: str, high_key: str, peak_key: str) -> dict[str, Any]:
    if not isinstance(source, dict):
        source = {}
    return {
        "low": source.get(low_key),
        "high": source.get(high_key),
        "peak": source.get(peak_key),
    }


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"Set {name} in .env")
    return value


if __name__ == "__main__":
    main()
