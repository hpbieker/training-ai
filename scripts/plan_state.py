#!/usr/bin/env python3
"""Persist and advance the active training plan's session queue."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "training-ai-plan-state-v2"
DEFAULT_STATE_PATH = Path("config/plan-state.json")
DEFAULT_ARTIFACTS_DIR = Path("outputs/intervals/activities")
QUALITY_ROLES = {"vt2", "vo2max", "sprint", "mixed"}
AEROBIC_ROLES = {"easy_aerobic", "medium_aerobic", "long_aerobic", "vt1"}
COMPLETED_ROLES = QUALITY_ROLES | AEROBIC_ROLES | {
    "recovery",
    "rest",
    "cross_training",
    "unclassified",
}
PROGRESSION_EFFECTS = {"advance", "hold", "consolidate", "none"}


class PlanStateError(ValueError):
    """Raised when plan-state data or a transition is invalid."""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read or update the persistent training plan state. Activity "
            "classification is explicit; this helper does not infer session intent."
        )
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("show")

    pending_parser = subparsers.add_parser(
        "pending",
        help="List saved activities newer than or absent from the state.",
    )
    pending_parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply one explicit, already-reviewed activity classification.",
    )
    apply_parser.add_argument(
        "--classification-json",
        type=parse_classification_json,
        required=True,
        help=(
            "One normalized JSON activity classification containing identity, "
            "roles, quality/progression outcome, reason, evidence, and optional "
            "progression_update."
        ),
    )

    args = parser.parse_args()
    state = load_plan_state(args.state)
    if args.command == "show":
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "pending":
        print(
            json.dumps(
                pending_activities(state, args.artifacts_dir),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    event = args.classification_json
    updated = apply_activity_classification(state, event)
    write_plan_state(args.state, updated)
    print(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True))


def parse_classification_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--classification-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--classification-json must contain one JSON object"
        )
    allowed = {
        "activity_id",
        "activity_name",
        "started_at",
        "planned_role",
        "completed_role",
        "quality_completed",
        "quality_stimulus",
        "progression_effect",
        "reason",
        "evidence",
        "progression_update",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise argparse.ArgumentTypeError(
            "unsupported classification field(s): " + ", ".join(unknown)
        )
    event = dict(payload)
    event.setdefault("evidence", [])
    event.setdefault("progression_update", {})
    try:
        validate_event(event)
    except PlanStateError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return event


def load_plan_state(path: Path | str) -> dict[str, Any]:
    state_path = Path(path)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanStateError(f"Plan state does not exist: {state_path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanStateError(f"Plan state is not valid JSON: {state_path}: {exc}") from exc
    validate_plan_state(payload)
    return payload


def validate_plan_state(state: dict[str, Any]) -> None:
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise PlanStateError(f"Expected schema {SCHEMA!r}.")
    active_plan = state.get("active_plan")
    if not isinstance(active_plan, dict) or not active_plan.get("id") or not active_plan.get("path"):
        raise PlanStateError("active_plan.id and active_plan.path are required.")
    queue = state.get("quality_queue")
    if not isinstance(queue, dict):
        raise PlanStateError("quality_queue is required.")
    steps = queue.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        raise PlanStateError("quality_queue.steps must contain at least two queue steps.")
    step_ids = []
    for step in steps:
        if (
            not isinstance(step, dict)
            or set(step) != {"id", "intensity_goal"}
            or not isinstance(step.get("id"), str)
            or not step["id"].strip()
            or step.get("intensity_goal") not in QUALITY_ROLES
        ):
            raise PlanStateError(
                "Each quality_queue step must contain a non-empty id and a supported intensity_goal."
            )
        step_ids.append(step["id"])
    if len(set(step_ids)) != len(step_ids):
        raise PlanStateError("quality_queue step ids must be unique.")
    next_quality_step = queue.get("next_quality_step")
    if next_quality_step not in step_ids:
        raise PlanStateError("quality_queue.next_quality_step must identify one queue step.")
    minimum_aerobic_days = queue.get("minimum_aerobic_days_after_quality")
    if not isinstance(minimum_aerobic_days, int) or minimum_aerobic_days < 0:
        raise PlanStateError("minimum_aerobic_days_after_quality must be a non-negative integer.")
    aerobic_dates = queue.get("aerobic_dates_since_quality")
    if not isinstance(aerobic_dates, list) or any(not is_iso_date(day) for day in aerobic_dates):
        raise PlanStateError("aerobic_dates_since_quality must contain ISO dates.")
    if len(set(aerobic_dates)) != len(aerobic_dates):
        raise PlanStateError("aerobic_dates_since_quality must not contain duplicates.")
    expected_next_role = (
        quality_step_goal(steps, next_quality_step)
        if len(aerobic_dates) >= minimum_aerobic_days
        else "easy_aerobic"
    )
    if state.get("next_role") != expected_next_role:
        raise PlanStateError(
            f"next_role must be {expected_next_role!r} for the current queue state."
        )
    events = state.get("activity_events")
    if not isinstance(events, list):
        raise PlanStateError("activity_events must be a list.")
    ids = []
    previous_started_at = None
    for event in events:
        validate_event(event)
        ids.append(event["activity_id"])
        started_at = parse_datetime(event["started_at"])
        if previous_started_at is not None and started_at < previous_started_at:
            raise PlanStateError("activity_events must be chronological.")
        previous_started_at = started_at
    if len(ids) != len(set(ids)):
        raise PlanStateError("activity_events must not contain duplicate activity IDs.")
    cursor = state.get("activity_cursor")
    if not isinstance(cursor, dict):
        raise PlanStateError("activity_cursor is required.")
    if events:
        latest = events[-1]
        if cursor.get("activity_id") != latest["activity_id"]:
            raise PlanStateError("activity_cursor.activity_id must match the latest event.")
        if cursor.get("started_at") != latest["started_at"]:
            raise PlanStateError("activity_cursor.started_at must match the latest event.")


def validate_event(event: dict[str, Any]) -> None:
    required_strings = (
        "activity_id",
        "activity_name",
        "started_at",
        "planned_role",
        "completed_role",
        "progression_effect",
        "reason",
    )
    if not isinstance(event, dict) or any(not event.get(key) for key in required_strings):
        raise PlanStateError("Activity event is missing required string fields.")
    parse_datetime(event["started_at"])
    completed_role = event["completed_role"]
    if completed_role not in COMPLETED_ROLES:
        raise PlanStateError(f"Unsupported completed_role: {completed_role!r}.")
    effect = event["progression_effect"]
    if effect not in PROGRESSION_EFFECTS:
        raise PlanStateError(f"Unsupported progression_effect: {effect!r}.")
    quality_completed = event.get("quality_completed")
    if not isinstance(quality_completed, bool):
        raise PlanStateError("quality_completed must be boolean.")
    if quality_completed and completed_role not in QUALITY_ROLES:
        raise PlanStateError("quality_completed requires a quality completed_role.")
    if effect == "advance" and not quality_completed:
        raise PlanStateError("progression_effect=advance requires quality_completed=true.")
    quality_stimulus = event.get("quality_stimulus", quality_completed)
    if not isinstance(quality_stimulus, bool):
        raise PlanStateError("quality_stimulus must be boolean.")
    if quality_stimulus and completed_role not in QUALITY_ROLES:
        raise PlanStateError("quality_stimulus requires a quality completed_role.")
    evidence = event.get("evidence")
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
        raise PlanStateError("evidence must be a list of paths or references.")
    progression_update = event.get("progression_update", {})
    if not isinstance(progression_update, dict) or any(
        key not in {"status", "next_step", "anchor"}
        or not isinstance(value, str)
        or not value.strip()
        for key, value in progression_update.items()
    ):
        raise PlanStateError(
            "progression_update may contain non-empty status, next_step, and anchor strings."
        )


def apply_activity_classification(
    state: dict[str, Any],
    event: dict[str, Any],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    validate_plan_state(state)
    validate_event(event)
    existing = {
        item["activity_id"]: item
        for item in state["activity_events"]
    }
    if event["activity_id"] in existing:
        if existing[event["activity_id"]] == event:
            return deepcopy(state)
        raise PlanStateError(
            f"Activity {event['activity_id']} was already applied with different data."
        )
    event_started_at = parse_datetime(event["started_at"])
    cursor_started_at = parse_datetime(state["activity_cursor"]["started_at"])
    if event_started_at < cursor_started_at:
        raise PlanStateError(
            "Activity is older than the state cursor; rebuild deliberately instead of "
            "silently applying events out of order."
        )

    updated = deepcopy(state)
    queue = updated["quality_queue"]
    completed_role = event["completed_role"]
    if event.get("quality_stimulus", event["quality_completed"]):
        queue["last_quality_session"] = {
            "activity_id": event["activity_id"],
            "date": event_started_at.date().isoformat(),
            "role": completed_role,
            "completed": event["quality_completed"],
        }
        # Keep the historical field for consumers that only understand the
        # older schema; it denotes the last quality session, not only a
        # progression-advancing session.
        queue["last_completed_quality"] = {
            "activity_id": event["activity_id"],
            "date": event_started_at.date().isoformat(),
            "role": completed_role,
        }
        current_step_goal = quality_step_goal(
            queue["steps"], queue["next_quality_step"]
        )
        if completed_role == current_step_goal:
            queue["next_quality_step"] = next_step_id(
                queue["steps"], queue["next_quality_step"]
            )
        queue["aerobic_dates_since_quality"] = []
    elif completed_role in AEROBIC_ROLES:
        aerobic_day = event_started_at.date().isoformat()
        if aerobic_day not in queue["aerobic_dates_since_quality"]:
            queue["aerobic_dates_since_quality"].append(aerobic_day)
            queue["aerobic_dates_since_quality"].sort()

    progression_update = event.get("progression_update") or {}
    if progression_update:
        if completed_role not in QUALITY_ROLES:
            raise PlanStateError(
                "progression_update requires a VT2, VO2Max, sprint, or mixed completed role."
            )
        updated["progression"].setdefault(completed_role, {}).update(
            deepcopy(progression_update)
        )

    queue["aerobic_days_since_quality"] = len(queue["aerobic_dates_since_quality"])
    updated["next_role"] = (
        quality_step_goal(queue["steps"], queue["next_quality_step"])
        if queue["aerobic_days_since_quality"]
        >= queue["minimum_aerobic_days_after_quality"]
        else "easy_aerobic"
    )
    updated["activity_events"].append(deepcopy(event))
    updated["activity_cursor"] = {
        "activity_id": event["activity_id"],
        "started_at": event["started_at"],
    }
    updated["updated_at"] = updated_at or utc_now()
    validate_plan_state(updated)
    return updated


def pending_activities(
    state: dict[str, Any],
    artifacts_dir: Path | str,
) -> list[dict[str, Any]]:
    validate_plan_state(state)
    known_ids = {event["activity_id"] for event in state["activity_events"]}
    cursor = parse_datetime(state["activity_cursor"]["started_at"])
    pending = []
    for activity_json in sorted(Path(artifacts_dir).glob("*/activity.json")):
        try:
            activity = json.loads(activity_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        activity_id = str(activity.get("id") or "")
        started_at_raw = activity.get("start_date_local") or activity.get("start_date")
        if not activity_id or not started_at_raw:
            continue
        started_at = parse_datetime(str(started_at_raw))
        if activity_id in known_ids or started_at <= cursor:
            continue
        pending.append(
            {
                "activity_id": activity_id,
                "activity_name": activity.get("name"),
                "activity_type": activity.get("type"),
                "started_at": str(started_at_raw),
                "activity_dir": str(activity_json.parent),
            }
        )
    return sorted(pending, key=lambda item: parse_datetime(item["started_at"]))


def plan_role_to_intensity_goal(role: str) -> str:
    mapping = {
        "easy_aerobic": "vt1",
        "medium_aerobic": "vt1",
        "long_aerobic": "vt1",
        "vt1": "vt1",
        "recovery": "recovery",
        "rest": "recovery",
        "vt2": "vt2",
        "vo2max": "vo2max",
        "sprint": "sprint",
        "mixed": "mixed",
    }
    try:
        return mapping[role]
    except KeyError as exc:
        raise PlanStateError(f"Cannot map plan role {role!r} to an intensity goal.") from exc


def recommendation_plan_context(
    state: dict[str, Any],
    *,
    intensity_goal: str,
    mismatch_reason: str | None = None,
) -> dict[str, Any]:
    validate_plan_state(state)
    expected_goal = plan_role_to_intensity_goal(state["next_role"])
    matches = intensity_goal == expected_goal
    if not matches and not (mismatch_reason or "").strip():
        raise PlanStateError(
            f"intensity_goal {intensity_goal!r} conflicts with plan-state next role "
            f"{state['next_role']!r} ({expected_goal!r}). Pass "
            "role_mismatch_reason in --plan-selection-json with the deliberate plan-level reason."
        )
    return {
        "schema": SCHEMA,
        "active_plan": deepcopy(state["active_plan"]),
        "state_updated_at": state["updated_at"],
        "activity_cursor": deepcopy(state["activity_cursor"]),
        "next_role": state["next_role"],
        "next_quality_step": state["quality_queue"]["next_quality_step"],
        "next_quality_role": quality_step_goal(
            state["quality_queue"]["steps"],
            state["quality_queue"]["next_quality_step"],
        ),
        "last_completed_quality": deepcopy(
            state["quality_queue"]["last_completed_quality"]
        ),
        "aerobic_days_since_quality": state["quality_queue"][
            "aerobic_days_since_quality"
        ],
        "progression": deepcopy(state["progression"]),
        "expected_intensity_goal": expected_goal,
        "requested_intensity_goal": intensity_goal,
        "goal_matches_state": matches,
        "mismatch_reason": None if matches else mismatch_reason.strip(),
    }


def write_plan_state(path: Path | str, state: dict[str, Any]) -> None:
    validate_plan_state(state)
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.",
        suffix=".tmp",
        dir=state_path.parent,
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, state_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def quality_step_goal(steps: list[dict[str, str]], step_id: str) -> str:
    for step in steps:
        if step["id"] == step_id:
            return step["intensity_goal"]
    raise PlanStateError(f"Quality step {step_id!r} is not in the queue.")


def next_step_id(steps: list[dict[str, str]], step_id: str) -> str:
    step_ids = [step["id"] for step in steps]
    try:
        index = step_ids.index(step_id)
    except ValueError as exc:
        raise PlanStateError(f"Quality step {step_id!r} is not in the queue.") from exc
    return step_ids[(index + 1) % len(step_ids)]


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanStateError(f"Invalid ISO datetime: {value!r}.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_iso_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    main()
