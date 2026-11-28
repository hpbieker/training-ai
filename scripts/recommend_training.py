#!/usr/bin/env python3
"""Collect the standard inputs for a same-day training recommendation."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

XERT_PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "xert"
if str(XERT_PLUGIN) not in sys.path:
    sys.path.insert(0, str(XERT_PLUGIN))

from recommendation_binding import (bind_workout_calculation, canonical_structure, validate_capacity_values,
                                    validate_capacity_horizon, instant)
from illness_return import parse_illness_return_json
import day_constraints
from vt1_dose import dose_comparisons, prior_quality_sequences
from plan_state import (
    AEROBIC_ROLES,
    DEFAULT_STATE_PATH,
    PlanStateError,
    load_plan_state,
    recommendation_plan_context,
)
from readiness_snapshot import (
    ARTIFACTS_DIR,
    build_readiness_snapshot,
    completed_activity_start,
    format_local,
    format_utc,
    load_garmin_input,
    load_xert_input,
    parse_cli_local_datetime,
    parse_timezone,
)
from route_context import parse_route_context_payload
from route_recommendations import parse_date, recommend_routes


DEFAULT_OUTPUT_DIR = Path("outputs/recommendations")
REFRESH_GROUPS = frozenset({"garmin", "xert", "intervals", "weather"})
SOURCE_REFRESH_POLICY = {
    "garmin": ("garmin", 15),
    "garmin_hrv_history": ("garmin", 15),
    "xert": ("xert", 30),
    "intervals_wellness": ("intervals", 30),
    "intervals_events": ("intervals", 30),
    "intervals_activity_volume": ("intervals", 30),
    "xert_activity_loads": ("xert", 30),
    "xert_recommended_training": ("xert", 30),
    "xert_workout_capacity": ("xert", 30),
    "xert_route_maps": ("xert", 24 * 60),
    "weather_home": ("weather", 60),
    "weather_route": ("weather", 60),
}


def parse_training_target_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"--training-target-json must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("--training-target-json must contain one JSON object")
    unknown = set(payload) - {"minutes", "load", "low_xss", "basis", "reason", "evidence", "endurance_extension", "capacity_decision",
                              "vt1_role", "vt1_power_choice", "vt1_comparison", "aerobic_finish"}
    if unknown:
        raise argparse.ArgumentTypeError(f"unsupported training-target field: {sorted(unknown)[0]}")
    for field in ("minutes", "load"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise argparse.ArgumentTypeError(f"training-target {field} must be a finite positive number")
    if "low_xss" in payload:
        value = payload["low_xss"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= payload["load"]:
            raise argparse.ArgumentTypeError("training-target low_xss must be positive and no greater than load")
    if payload.get("basis") not in {"duration", "load"}:
        raise argparse.ArgumentTypeError("training-target basis must be duration or load")
    def justification(obj, name):
        if not isinstance(obj, dict) or not isinstance(obj.get("reason"), str) or not obj["reason"].strip():
            raise argparse.ArgumentTypeError(f"{name} requires a non-empty reason")
        evidence = obj.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(v, str) or not v.strip() for v in evidence):
            raise argparse.ArgumentTypeError(f"{name} requires non-empty evidence strings")
    justification(payload, "training-target")
    if "aerobic_finish" in payload:
        review = payload["aerobic_finish"]
        if not isinstance(review, dict) or review.get("decision") not in ("offer", "finish"):
            raise argparse.ArgumentTypeError("aerobic_finish.decision must be offer or finish")
        fields = {"decision", "reason"}
        if "alternative_extra_minutes" in review:
            fields.add("alternative_extra_minutes")
        if review["decision"] == "finish" and "smaller_extra_minutes" in review:
            fields.add("smaller_extra_minutes")
        if review["decision"] == "offer":
            fields.update(("extra_minutes", "check_at_minute", "intensity", "cue"))
            if "marginal_benefit" in review:
                fields.add("marginal_benefit")
            if "limit_basis" in review:
                fields.add("limit_basis")
                if review["limit_basis"] not in ("observed_response", "practical_limit", "plan_limit", "coaching_judgment"):
                    raise argparse.ArgumentTypeError("Invalid aerobic_finish.limit_basis")
        if "good_response_limit" in review:
            fields.add("good_response_limit")
            if "alternative_extra_minutes" not in review:
                raise argparse.ArgumentTypeError("good_response_limit requires the alternative_extra_minutes reviewed")
        if set(review) != fields:
            raise argparse.ArgumentTypeError(f"aerobic_finish requires exactly {sorted(fields)}")
        numeric_fields = fields & {"extra_minutes", "check_at_minute", "alternative_extra_minutes", "smaller_extra_minutes"}
        for key in fields - numeric_fields - {"decision"}:
            if not isinstance(review[key], str) or not review[key].strip():
                raise argparse.ArgumentTypeError(f"aerobic_finish.{key} requires non-empty text")
        for key in numeric_fields:
            value = review[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise argparse.ArgumentTypeError(f"aerobic_finish.{key} must be finite and positive")
        if "alternative_extra_minutes" in review and review["alternative_extra_minutes"] == review.get("extra_minutes"):
            raise argparse.ArgumentTypeError("Compare a different length of optional aerobic work")
        if "limit_basis" in review and review["extra_minutes"] >= review.get("alternative_extra_minutes", 0):
            raise argparse.ArgumentTypeError("limit_basis applies to an offer shorter than the reviewed alternative")
        if "marginal_benefit" in review and review["extra_minutes"] <= review.get("alternative_extra_minutes", math.inf):
            raise argparse.ArgumentTypeError("marginal_benefit compares a longer offer with a shorter alternative")
        if "smaller_extra_minutes" in review and review["smaller_extra_minutes"] >= review.get("alternative_extra_minutes", 0):
            raise argparse.ArgumentTypeError("smaller_extra_minutes must be below alternative_extra_minutes")
        if review.get("check_at_minute", 0) > payload["minutes"]:
            raise argparse.ArgumentTypeError("aerobic_finish checkpoint falls after the primary ride")
    if "vt1_role" in payload and payload["vt1_role"] not in sorted(AEROBIC_ROLES):
        raise argparse.ArgumentTypeError("vt1_role must be a reviewed aerobic role")
    if "vt1_power_choice" in payload:
        choice = payload["vt1_power_choice"]
        justification(choice, "vt1_power_choice")
        watts = choice.get("watts")
        if type(watts) not in (int, float) or not math.isfinite(watts) or watts <= 0:
            raise argparse.ArgumentTypeError("vt1_power_choice requires finite positive watts")
    if "vt1_comparison" in payload:
        review = payload["vt1_comparison"]
        if not isinstance(review, dict) or not isinstance(review.get("reason"), str) or not review["reason"].strip():
            raise argparse.ArgumentTypeError("vt1_comparison requires a dose comparison reason")
        if "activity_id" in review and not isinstance(review["activity_id"], str):
            raise argparse.ArgumentTypeError("vt1_comparison activity_id must be a string")
    if "endurance_extension" in payload:
        justification(payload["endurance_extension"], "endurance_extension")
    if "capacity_decision" in payload:
        decision = payload["capacity_decision"]
        justification(decision, "capacity_decision")
        if decision.get("action") not in {"reduce_dose", "move_next_workout", "accept_model_conflict"}:
            raise argparse.ArgumentTypeError("capacity_decision action must be reduce_dose, move_next_workout or accept_model_conflict")
    return payload


def expand_quality_workout_rows(
    *,
    rows: list[dict[str, Any]],
    signature: dict[str, Any],
    adjustable_row_index: int,
) -> dict[str, Any]:
    """Expand one canonical Xert row list into local solver segments."""

    tp = number(signature.get("tp"))
    ltp = number(signature.get("ltp"))
    if tp is None:
        raise argparse.ArgumentTypeError("quality-workout signature.tp must be numeric")
    if (
        isinstance(adjustable_row_index, bool)
        or not isinstance(adjustable_row_index, int)
        or not 0 <= adjustable_row_index < len(rows)
    ):
        raise argparse.ArgumentTypeError(
            "quality-workout adjustable_row_index is out of range"
        )

    segments: list[dict[str, Any]] = []
    adjustable_segment_index: int | None = None
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise argparse.ArgumentTypeError(
                f"quality-workout rows[{row_index}] must be an object"
            )
        duration = number(row.get("duration_seconds"))
        repetitions = row.get("interval_count", 1)
        if duration is None or duration < 0 or duration != int(duration):
            raise argparse.ArgumentTypeError(
                f"quality-workout rows[{row_index}].duration_seconds is invalid"
            )
        if (
            isinstance(repetitions, bool)
            or not isinstance(repetitions, int)
            or repetitions < 0
        ):
            raise argparse.ArgumentTypeError(
                f"quality-workout rows[{row_index}].interval_count is invalid"
            )
        if row_index == adjustable_row_index and repetitions != 1:
            raise argparse.ArgumentTypeError(
                "quality-workout adjustable row must have interval_count 1"
            )

        power_type = row.get("power_type", "absolute")
        power = number(row.get("power"))
        second_power = number(row.get("power_second_value"))
        if power is None:
            raise argparse.ArgumentTypeError(
                f"quality-workout rows[{row_index}].power must be numeric"
            )
        if power_type in {"relative_ftp", "ramp_ftp"}:
            power = power * tp / 100.0
            second_power = second_power * tp / 100.0 if second_power is not None else None
        elif power_type == "ramp_ltp":
            if ltp is None:
                raise argparse.ArgumentTypeError(
                    "quality-workout signature.ltp is required for ramp_ltp"
                )
            power = power * ltp / 100.0
            second_power = second_power * ltp / 100.0 if second_power is not None else None
        elif power_type not in {"absolute", "ramp_absolute"}:
            raise argparse.ArgumentTypeError(
                f"quality-workout rows[{row_index}].power_type is unsupported"
            )

        for repetition in range(repetitions):
            segment = {
                "name": row.get("name") or f"row {row_index + 1}",
                "duration_seconds": int(duration),
                "power": power,
            }
            if second_power is not None:
                segment["end_power"] = second_power
            if row_index == adjustable_row_index:
                adjustable_segment_index = len(segments)
            segments.append(segment)

            rib_duration = number(row.get("rib_duration_seconds")) or 0.0
            if rib_duration > 0:
                rib_power = number(row.get("rib_power"))
                if rib_power is None:
                    raise argparse.ArgumentTypeError(
                        f"quality-workout rows[{row_index}].rib_power must be numeric"
                    )
                if row.get("rib_power_type", "absolute") == "relative_ftp":
                    rib_power = rib_power * tp / 100.0
                segments.append({
                    "name": f"Rest after {row.get('name') or f'row {row_index + 1}'} "
                    f"{repetition + 1}/{repetitions}",
                    "duration_seconds": int(rib_duration),
                    "power": rib_power,
                })

    if adjustable_segment_index is None:
        raise argparse.ArgumentTypeError(
            "quality-workout adjustable row produced no solver segment"
        )
    return {
        "signature": signature,
        "segments": segments,
        "adjustable_segment_index": adjustable_segment_index,
    }


def parse_quality_workout_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--quality-workout-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--quality-workout-json must contain one JSON object"
        )
    structure_fields = {
        "signature",
        "rows",
        "adjustable_row_index",
        "minimum_duration_seconds",
        "maximum_duration_seconds",
        "tolerance_xss",
    }
    unknown = sorted(set(payload) - {"status", "calculation", *structure_fields})
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unsupported quality-workout field: {unknown[0]}"
        )
    missing = sorted({"status", "calculation"} - set(payload))
    if missing:
        raise argparse.ArgumentTypeError(
            f"missing required quality-workout field: {missing[0]}"
        )
    if payload["status"] not in {"planned", "completed"}:
        raise argparse.ArgumentTypeError(
            "quality-workout status must be planned or completed"
        )
    if not isinstance(payload["calculation"], dict) or not payload["calculation"]:
        raise argparse.ArgumentTypeError(
            "quality-workout calculation must be a non-empty JSON object"
        )
    supplied_structure_fields = structure_fields.intersection(payload)
    if supplied_structure_fields:
        required = {"signature", "rows", "adjustable_row_index"}
        missing_structure = sorted(required - set(payload))
        if missing_structure:
            raise argparse.ArgumentTypeError(
                f"missing required quality-workout structure field: {missing_structure[0]}"
            )
        if not isinstance(payload["signature"], dict) or not isinstance(payload["rows"], list):
            raise argparse.ArgumentTypeError(
                "quality-workout signature must be an object and rows must be an array"
            )
        structure = expand_quality_workout_rows(
            rows=payload["rows"],
            signature=payload["signature"],
            adjustable_row_index=payload["adjustable_row_index"],
        )
        for field in (
            "minimum_duration_seconds",
            "maximum_duration_seconds",
            "tolerance_xss",
        ):
            if field in payload:
                structure[field] = payload[field]
        payload["solver_structure"] = structure
    return payload


def parse_endurance_workout_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--endurance-workout-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--endurance-workout-json must contain one JSON object"
        )
    unknown = sorted(set(payload) - {"calculation", "structure"})
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unsupported endurance-workout field: {unknown[0]}"
        )
    calculation = payload.get("calculation")
    if "calculation" in payload or "structure" not in payload:
        if not isinstance(calculation, dict) or not calculation:
            raise argparse.ArgumentTypeError("endurance-workout calculation must be a non-empty JSON object")
    if "structure" in payload and not isinstance(payload["structure"], dict):
        raise argparse.ArgumentTypeError("endurance-workout structure must be an object")
    return payload


def parse_plan_selection_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"--plan-selection-json must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("--plan-selection-json must contain one JSON object")
    unknown = sorted(set(payload) - {"intensity_goal", "state", "role_mismatch_reason"})
    if unknown:
        raise argparse.ArgumentTypeError(f"unsupported plan-selection field: {unknown[0]}")
    goal = payload.get("intensity_goal")
    if goal not in {"recovery", "vt1", "vt2", "vo2max", "sprint", "mixed"}:
        raise argparse.ArgumentTypeError("plan-selection intensity_goal is required and unsupported")
    state = payload.get("state", str(DEFAULT_STATE_PATH))
    if not isinstance(state, str) or not state.strip():
        raise argparse.ArgumentTypeError("plan-selection state must be a non-empty path")
    reason = payload.get("role_mismatch_reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise argparse.ArgumentTypeError("plan-selection role_mismatch_reason must be a non-empty string")
    return {"intensity_goal": goal, "state": Path(state), "role_mismatch_reason": reason}


def review_vt1_working_power(structure, reference, choice, *, extension_only=False):
    """Verify the working step in the independent prescription before strain modelling."""
    watts = choice["watts"] if choice else reference
    if watts is None:
        raise ValueError("Missing VT1 working power: supply an evidence-backed vt1_power_choice")
    segments = canonical_structure(structure)["segments"]
    index = structure.get("adjustable_segment_index")
    if index is None and not extension_only:
        steady = [i for i, row in enumerate(segments)
                  if row["duration_seconds"] and row["power"] == row["end_power"] == watts]
        index = max(steady, key=lambda i: segments[i]["duration_seconds"], default=None)
    if type(index) is not int or not 0 <= index < len(segments):
        raise ValueError(f"VT1 prescription requires a steady working segment at the chosen {watts:g} W")
    work = segments[index]
    if work["power"] != watts or work["end_power"] != watts:
        raise ValueError(f"VT1 working segment must use the chosen {watts:g} W; justify a deviation with vt1_power_choice")
    if not extension_only and any(row["duration_seconds"] and max(row["power"], row["end_power"]) > watts
                                  for row in segments):
        raise ValueError("Pure VT1 structure contains work above the chosen working power")
    return {"plan_reference_w": reference, "working_power_w": watts,
            "working_segment_index": index, "choice": choice}


def main(argv: list[str] | None = None, *, require_finish_review: bool = False) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Garmin/Xert/Yr inputs and build one recommendation packet.",
        epilog=(
            "Planning-context calendar.remainder_disposition accepts: "
            "unscheduled, dropped, moved, or conditionally_split."
        ),
    )
    parser.add_argument(
        "--planning-context-json",
        required=True,
        help=(
            "Normalized JSON object containing date, local_timezone, absolute "
            "now and optional planned_at timestamps, availability windows, "
            "cycling modalities and unavailable reasons, next_workout_at for capacity "
            "checks, optional documented capacity_approximation, and route "
            "context."
        ),
    )
    parser.add_argument("--illness-return-json", type=parse_illness_return_json)
    parser.add_argument(
        "--training-target-json",
        type=parse_training_target_json,
        help=(
            "Coach-selected minutes, calculated load, basis (duration/load), reason and "
            "evidence. VT1 uses vt1_role, vt1_comparison and optional vt1_power_choice. "
            "Use aerobic_finish to offer a longer ride or explain finishing at the primary duration. "
            "Optional low_xss, justified endurance_extension and capacity_decision. "
            "Omission requires dose assessment, never an automatic Xert dose."
        ),
    )
    parser.add_argument(
        "--quality-workout-json",
        type=parse_quality_workout_json,
        help=(
            "Optional JSON object with status, the complete native calculate_strain result, "
            "and canonical rows/signature/adjustable_row_index for calculation binding."
        ),
    )
    parser.add_argument(
        "--endurance-workout-json",
        type=parse_endurance_workout_json,
        help=(
            "Optional complete native calculate_strain or solve_segment_duration result from Xert's "
            "offline MCP calculation, plus independent structure (signature, segments, "
            "adjustable_segment_index) for endurance-only work. The flexible segment must match the "
            "applicable low-XSS target."
        ),
    )
    parser.add_argument(
        "--print-endurance-solver-request",
        action="store_true",
        help=(
            "Print the guarded, optionally split MCP solve_segment_duration "
            "request and exit."
        ),
    )
    parser.add_argument(
        "--plan-selection-json",
        type=parse_plan_selection_json,
        required=True,
        help=(
            "Validated JSON with intensity_goal, optional state path, and optional "
            "role_mismatch_reason."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--source-overrides-json",
        type=parse_source_overrides_json,
        default={},
        help=(
            "Optional JSON object mapping normalized source names to JSON file "
            "paths. An overridden source cannot also be forcibly refreshed."
        ),
    )
    parser.add_argument(
        "--refresh-json",
        type=parse_refresh_json,
        default={"mode": "auto", "sources": []},
        help=(
            "Validated JSON source refresh policy with mode auto, all, none, or "
            "selected; selected mode requires a sources array."
        ),
    )
    parser.add_argument(
        "--route-options-json",
        type=parse_route_options_json,
        default={"index": Path("outputs/route-index.json"), "rebuild_index": False, "map_scope": "top"},
        help=(
            "Validated JSON route execution options: index, rebuild_index, and "
            "map_scope (top, all, or none)."
        ),
    )
    output_format = parser.add_mutually_exclusive_group()
    output_format.add_argument(
        "--summary",
        action="store_true",
        help="Print the detailed recommendation report instead of the full JSON packet.",
    )
    output_format.add_argument(
        "--compact-summary",
        action="store_true",
        help="Print the recommendation and key evidence with the full packet path.",
    )
    args = parser.parse_args(argv)
    try:
        planning_context = parse_planning_context_json(args.planning_context_json)
        args.date = planning_context["date"]
        args.local_timezone = planning_context["local_timezone"]
        args.now = planning_context["now"]
        args.planned_at = planning_context.get("planned_at")
        args.available_modalities = frozenset(
            planning_context["cycling"]["available_modalities"]
        )
        preferred_workout_name = planning_context["cycling"].get(
            "preferred_workout_name_contains"
        )
        args.surface_preference = planning_context["route"]["surface_preference"]
        start_anchor = planning_context["route"].get("start_anchor") or {}
        args.start_anchor_displayname = start_anchor.get("display_name")
        args.start_anchor_lat = start_anchor.get("lat")
        args.start_anchor_lng = start_anchor.get("lng")
        args.start_radius_km = start_anchor.get("radius_km", 0.25)
        args.route_target_distance_km = planning_context["route"][
            "target_distance_km"
        ]
        args.route_allow_away = planning_context["route"]["allow_away"]
        local_timezone = parse_timezone(args.local_timezone)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    try:
        plan_state = load_plan_state(args.plan_selection_json["state"])
        plan_context = recommendation_plan_context(
            plan_state,
            intensity_goal=args.plan_selection_json["intensity_goal"],
            mismatch_reason=args.plan_selection_json["role_mismatch_reason"],
        )
    except PlanStateError as exc:
        parser.error(str(exc))
    indoor_available = "indoor_cycling" in args.available_modalities
    indoor_gym_available = "indoor_cycling_gym" in args.available_modalities
    outdoor_available = "outdoor_cycling" in args.available_modalities
    requested_unavailable_reasons = planning_context["cycling"][
        "unavailable_reasons"
    ]
    indoor_unavailable_reason = requested_unavailable_reasons.get(
        "indoor_cycling", "no_indoor_equipment_available"
    )
    outdoor_unavailable_reason = requested_unavailable_reasons.get(
        "outdoor_cycling", "outdoor_riding_not_realistic"
    )
    unavailable_reasons = {}
    if not indoor_available and not indoor_gym_available:
        unavailable_reasons["indoor_cycling"] = indoor_unavailable_reason
    if not outdoor_available:
        unavailable_reasons["outdoor_cycling"] = outdoor_unavailable_reason
    validate_context(parser, args=args, outdoor_available=outdoor_available)

    output_dir = args.output_dir / args.date
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at_utc = datetime.now(timezone.utc)
    generated_at = generated_at_utc.astimezone(local_timezone)
    now = (
        parse_cli_local_datetime(
            args.now,
            default_day=args.date,
            local_timezone=local_timezone,
        )
        if args.now
        else generated_at
    )
    try:
        available_windows = (
            calendar_availability_windows(
                planning_context["calendar"],
                local_timezone=local_timezone,
                day=args.date,
            )
            if planning_context["calendar"].get("events") is not None
            else parse_availability_payload(
                planning_context["availability"],
                expected_timezone=local_timezone,
                argument_name="--planning-context-json availability",
            )
        )
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.planned_at:
        planned_at = parse_cli_local_datetime(
            args.planned_at,
            default_day=args.date,
            local_timezone=local_timezone,
        )
        planned_at_source = "planning_context"
        validate_planned_at_in_available_windows(
            parser,
            planned_at=planned_at,
            available_windows=available_windows,
        )
    elif len(available_windows) == 1:
        planned_at = available_windows[0]["start"]
        planned_at_source = "planning_context_availability"
    elif available_windows:
        parser.error(
            "planning_context planned_at is required when availability contains "
            "multiple windows; evaluate each window with its own planned_at and "
            "candidate-specific Xert advice before selecting the final run"
        )
    else:
        planned_at = default_planned_at(args.date, now=now)
        planned_at_source = "default"
    data_cutoff = min(now, planned_at)
    constraints = day_constraints.for_day(day_constraints.DATABASE, planned_at.date(), data_cutoff.isoformat())
    if constraints:
        try:
            day_constraints.check_candidate(
                constraints, args.plan_selection_json["intensity_goal"],
                (args.quality_workout_json or {}).get("status") == "planned",
            )
        except ValueError as exc:
            parser.error(str(exc))
        plan_context["dated_athlete_constraints"] = constraints
    split_preference = planning_context.get("split_preference")
    if split_preference is not None:
        available_windows = apply_split_preference_to_windows(
            available_windows,
            planned_at=planned_at,
            split_preference=split_preference,
        )
    source_files = source_paths(output_dir, args.date)
    for source_name, override_path in args.source_overrides_json.items():
        source_group = SOURCE_REFRESH_POLICY[source_name][0]
        if refresh_spec_forces(args.refresh_json, source_group):
            parser.error(
                f"source override {source_name} cannot be combined with a refresh "
                f"policy that forces {source_group}"
            )
        override_payload = load_json_if_exists(override_path)
        if not isinstance(override_payload, dict):
            parser.error(
                f"source override {source_name} must contain one JSON object: "
                f"{override_path}"
            )
        override_payload = normalize_source_override_payload(
            source_name,
            override_payload,
        )
        try:
            validate_source_override_payload(source_name, override_payload)
        except ValueError as exc:
            parser.error(str(exc))
        override_payload.setdefault("source_file", str(override_path))
        write_json(source_files[source_name], override_payload)
    compose_garmin_source_overrides(
        source_files, overridden_sources=set(args.source_overrides_json),
    )
    compose_xert_source_overrides(
        source_files,
        overridden_sources=set(args.source_overrides_json),
    )
    required_sources = {
        "garmin", "xert", "intervals_wellness", "intervals_events",
        "xert_activity_loads", "weather_home",
    }
    if args.plan_selection_json["intensity_goal"] == "vt1" or "intervals_activity_volume" in args.source_overrides_json:
        required_sources.add("intervals_activity_volume")
    if "garmin_hrv_history" in args.source_overrides_json:
        required_sources.add("garmin_hrv_history")
    if indoor_available:
        required_sources.add("xert_recommended_training")
    if outdoor_available:
        required_sources.add("weather_route")
        if args.route_options_json["map_scope"] != "none":
            required_sources.add("xert_route_maps")
    source_refresh = build_source_refresh_plan(
        source_files,
        required=required_sources,
        refresh_spec=args.refresh_json,
        checked_at=generated_at,
        overrides=set(args.source_overrides_json),
    )
    sources_requiring_mcp = mcp_sources_requiring_refresh(
        source_refresh,
        indoor_available=indoor_available,
    )
    if sources_requiring_mcp:
        raise SystemExit(
            "Live source access is MCP-only for these inputs. Fetch each normalized "
            "MCP result, persist it as JSON, then pass the files through "
            "--source-overrides-json: "
            + ", ".join(sorted(sources_requiring_mcp))
        )
    ensure_source_files_exist(
        source_files,
        required=tuple(
            sorted(
                required_sources
                - {"xert_route_maps", "weather_home", "weather_route"}
            )
        ),
        policy=args.refresh_json["mode"],
    )

    readiness_packet = build_readiness_snapshot(
        args.date,
        artifacts_dir=ARTIFACTS_DIR,
        now=now,
        planned_at=planned_at,
        local_timezone=local_timezone,
        garmin_input=load_garmin_input(
            str(source_files["garmin"]),
            local_timezone=local_timezone,
        ),
        xert_input=load_xert_input(
            str(source_files["xert"]),
            local_timezone=local_timezone,
        ),
        intervals_wellness_input=load_json_if_exists(source_files["intervals_wellness"]),
        intervals_events_input=load_json_if_exists(source_files["intervals_events"]),
        illness_return_assessment=args.illness_return_json,
    )
    annotate_hrv_decision_context(readiness_packet)
    history_context = training_history_context(
        args.date,
        cutoff=data_cutoff,
        artifacts_dir=ARTIFACTS_DIR,
        xert_activity_loads=load_json_if_exists(source_files["xert_activity_loads"]),
        local_timezone=local_timezone,
    )
    if "intervals_activity_volume" in required_sources:
        try:
            history_context.update(verified_moving_time_history(
                load_json_if_exists(source_files["intervals_activity_volume"]),
                workout_date=planned_at.date(), cutoff=data_cutoff.astimezone(local_timezone),
            ))
        except ValueError as exc:
            parser.error(str(exc))
    history_context["prior_quality_sequences"] = prior_quality_sequences(
        plan_state, data_cutoff, ARTIFACTS_DIR / "activities",
        aerobic_references=args.plan_selection_json["intensity_goal"] in {"recovery", "vt1"},
    )
    if planned_at.date() == data_cutoff.date():
        readiness_packet["recommendation_inputs"]["current_day_athlete_answers"] = (
            history_context["prior_quality_sequences"]["current_day_athlete_answers"]
        )
    target_resolution = resolve_training_targets(
        selection=args.training_target_json,
        readiness_packet=readiness_packet,
        history_context=history_context,
    )
    if "xert_workout_capacity" in args.source_overrides_json:
        target_resolution["capacity_horizon"] = validate_capacity_horizon(
            load_json_if_exists(source_files["xert_workout_capacity"]) or {},
            planned_at=max(planned_at, now).isoformat(),
            next_workout_at=planning_context.get("next_workout_at"),
            approximation=planning_context.get("capacity_approximation"),
        )
    initialize_plan_trace(target_resolution)
    annotate_readiness_dose_review(target_resolution, readiness_packet)
    apply_intervals_illness_target_guardrail(
        target_resolution,
        (readiness_packet.get("recommendation_inputs") or {}).get(
            "intervals_wellness_events"
        )
        or {},
    )
    progression_advice = build_progression_advice(
        day=args.date, cutoff=data_cutoff, local_timezone=local_timezone,
        source_files=source_files,
        plan_progression=plan_context.get("progression") or {},
        plan_state_path=args.plan_selection_json["state"],
    )
    intensity_decision = select_intensity_domain(
        readiness_ceiling=recommendation_bias_from_readiness_packet(
            readiness_packet, intensity_goal=args.plan_selection_json["intensity_goal"],
        ),
        intensity_goal=args.plan_selection_json["intensity_goal"],
        progression_advice=progression_advice,
        plan_progression=plan_context.get("progression"),
    )
    apply_execution_modality_constraint(
        intensity_decision,
        indoor_gym_only=(
            indoor_gym_available and not indoor_available and not outdoor_available
        ),
    )
    try:
        day_constraints.check_candidate(constraints, intensity_decision["selected_domain"])
    except ValueError as exc:
        parser.error(str(exc))
    apply_readiness_domain_target_cap(
        target_resolution,
        intensity_decision=intensity_decision,
    )
    if "xert_workout_capacity" in args.source_overrides_json:
        apply_recovery_protection_capacity(
            target_resolution,
            capacity=load_json_if_exists(source_files["xert_workout_capacity"])
            or {},
            selected_intensity=str(
                intensity_decision.get("selected_domain") or ""
            ),
            quality_low_xss=(
                number(
                    (((args.quality_workout_json or {}).get("calculation") or {}).get("result") or {})
                    .get("stats", {})
                    .get("xlss")
                )
                if args.quality_workout_json is not None
                else None
            ),
        )
    endurance_solver_structure = (
        (args.endurance_workout_json or {}).get("structure")
        or (args.quality_workout_json or {}).get("solver_structure")
    )
    selected_domain = intensity_decision.get("selected_domain")
    completed_quality_only = ((args.quality_workout_json or {}).get("status") == "completed"
                              and not target_resolution.get("endurance_extension"))
    pure_vt1 = selected_domain in {"vt1", "easy_vt1"} and not completed_quality_only
    extension = selected_domain in {"vt2", "vo2max", "sprint", "mixed"} and target_resolution.get("endurance_extension")
    if endurance_solver_structure is not None and (pure_vt1 or extension):
        selection = args.training_target_json
        reference = (plan_context["progression"].get("vt1") or {}).get("target_power_w")
        try:
            power_review = review_vt1_working_power(
                endurance_solver_structure, reference, selection.get("vt1_power_choice"), extension_only=bool(extension)
            )
        except ValueError as exc:
            parser.error(str(exc))
        target_resolution["vt1_power_review"] = power_review
        if pure_vt1:
            role = selection.get("vt1_role") or plan_context["next_role"]
            if role not in AEROBIC_ROLES:
                parser.error("Specify vt1_role for the selected aerobic session purpose")
            review = selection.get("vt1_comparison")
            comparisons = dose_comparisons(
                plan_state, role, power_review["working_power_w"], data_cutoff,
                selected_id=(review or {}).get("activity_id"),
            )
            if comparisons["candidates"] and not review:
                parser.error("Review same-role rides with scripts/vt1_dose.py and supply vt1_comparison")
            if review and review.get("activity_id") is not None and review["activity_id"] not in {
                ride["activity_id"] for ride in comparisons["candidates"]
            }:
                parser.error("vt1_comparison activity_id must identify an eligible same-role ride")
            target_resolution["vt1_dose_comparison"] = {**comparisons, "selection_review": review}
    if endurance_solver_structure is not None:
        if split_preference is not None:
            endurance_solver_structure = split_endurance_structure(
                endurance_solver_structure,
                first_session_minutes=split_preference["first_session_minutes"],
            )
    if args.print_endurance_solver_request:
        if endurance_solver_structure is None:
            raise SystemExit(
                "--print-endurance-solver-request requires "
                "an independent structure in --endurance-workout-json or "
                "--quality-workout-json rows/signature/adjustable_row_index"
            )
        print(json.dumps(
            build_endurance_solver_request(
                target_resolution,
                structure=endurance_solver_structure,
            ),
            indent=2,
            sort_keys=True,
        ))
        return
    if args.quality_workout_json is not None:
        native_quality = args.quality_workout_json["calculation"]
        expected_quality = endurance_solver_structure
        if args.quality_workout_json["status"] == "completed":
            expected_quality = native_quality
        elif expected_quality is not None and target_resolution.get("endurance_extension"):
            expected_quality = {**expected_quality, "segments":[
                segment for index, segment in enumerate(expected_quality["segments"])
                if index != expected_quality["adjustable_segment_index"]]}
        args.quality_workout_json["calculation"] = bind_workout_calculation(
            native_quality, expected_quality or {})
    if args.endurance_workout_json is not None:
        if "calculation" not in args.endurance_workout_json:
            parser.error("Final endurance prescription requires a completed calculation")
        args.endurance_workout_json["calculation"] = bind_workout_calculation(
            args.endurance_workout_json["calculation"], endurance_solver_structure or {})
        apply_xert_endurance_duration_solution(
            target_resolution,
            calculation={**args.endurance_workout_json["calculation"],
                         "canonical_structure": endurance_solver_structure},
            selected_intensity=str(
                intensity_decision.get("selected_domain") or ""
            ),
        )
        if pure_vt1:
            solution = target_resolution["endurance_duration_solution"]
            watts = power_review["working_power_w"]
            rows = canonical_structure(solution)["segments"]
            work_seconds = sum(row["duration_seconds"] for row in rows
                               if row["power"] == watts and row["end_power"] == watts)
            if work_seconds == 0:
                parser.error("Final VT1 prescription contains no work at the chosen power")
            comparison = target_resolution["vt1_dose_comparison"]
            comparison["prescribed_total_minutes"] = solution["duration_seconds"] / 60
            comparison["prescribed_steady_work_minutes"] = work_seconds / 60
            reference_id = (comparison["selection_review"] or {}).get("activity_id")
            reference = next((ride for ride in comparison["candidates"]
                              if ride["activity_id"] == reference_id), None)
            if reference and reference["moving_minutes"] and reference["moving_minutes"] > 0:
                block = history_context["prior_quality_sequences"].get(
                    "measured_indoor_aerobic_references", {}).get(reference_id, {}).get(
                        "longest_detected_steady_power_block")
                comparison["reference_vs_prescription"] = {
                    "reference": {"activity_id": reference_id, "total_minutes": reference["moving_minutes"],
                                  "detected_steady_block": block,
                                  "finish_to_next_quality_minutes": reference["finish_to_next_quality_minutes"]},
                    "prescription": {"total_minutes": comparison["prescribed_total_minutes"],
                                     "work_minutes": work_seconds / 60, "work_watts": watts},
                }
                previous = reference["moving_minutes"]
                delta = comparison["prescribed_total_minutes"] - previous
                comparison["duration_change"] = {
                    "reference_moving_minutes": previous,
                    "delta_minutes": round(delta, 1),
                    "delta_percent": round(100 * delta / previous, 1),
                }
    require_endurance_solution_for_selected_domain(
        intensity_decision=intensity_decision,
        target_resolution=target_resolution,
    )
    finalize_plan_trace(target_resolution)
    if args.quality_workout_json is not None:
        apply_quality_workout_vt1_composition(
            target_resolution,
            quality_calculation=args.quality_workout_json["calculation"],
            selected_intensity=str(
                intensity_decision.get("selected_domain") or ""
            ),
            quality_workout_status=args.quality_workout_json["status"],
        )
    if "xert_workout_capacity" in args.source_overrides_json:
        apply_recovery_protection_capacity(
            target_resolution,
            capacity=load_json_if_exists(source_files["xert_workout_capacity"]) or {},
            selected_intensity=str(intensity_decision.get("selected_domain") or ""),
        )
        require_resolved_capacity_review(target_resolution)
    finalize_plan_trace(target_resolution)
    if indoor_available or outdoor_available or indoor_gym_available:
        require_quality_workout_for_selected_domain(
            intensity_decision=intensity_decision,
            dose_composition=target_resolution.get("dose_composition"),
        )
    target_resolution["split"] = split_session_info(
        target_resolution,
        planned_at=planned_at,
        now=now,
        available_windows=available_windows,
    )
    annotate_dose_composition_window_fit(
        target_resolution,
        planned_at=planned_at,
        now=now,
        available_windows=available_windows,
    )
    annotate_volume_density(target_resolution, history_context=history_context)
    remainder_disposition = planning_context["calendar"]["remainder_disposition"]
    target_resolution["split"]["remainder_disposition"] = remainder_disposition
    target_resolution["split"]["guidance"] = split_session_guidance(
        target_resolution["split"],
        remainder_disposition=remainder_disposition,
    )
    target_resolution["split_note"] = target_resolution["split"]["guidance"]
    if planning_context["calendar"].get("events") is not None:
        target_resolution["split"]["movable_event_placement"] = place_movable_events(
            planning_context["calendar"],
            sessions=target_resolution["split"].get("sessions") or [],
            local_timezone=local_timezone,
            day=args.date,
        )
    target_minutes = float(target_resolution["target_minutes"])
    target_load = float(target_resolution["target_load"])
    route_session_target_minutes = (
        float(split_preference["first_session_minutes"])
        if split_preference is not None
        else target_minutes
    )
    target_distance_km = (
        args.route_target_distance_km
        if args.route_target_distance_km is not None
        else outdoor_target_distance_km(
            target_minutes=route_session_target_minutes,
            surface_preference=args.surface_preference,
        )
    )
    target_resolution["target_distance_km"] = target_distance_km
    target_resolution["target_distance_meaning"] = (
        (
            "Explicit route-context target distance."
            if args.route_target_distance_km is not None
            else "Derived before route ranking from the recommendation duration "
            "target and the selected surface preference."
        )
    )
    target_resolution["route_session_target_minutes"] = round(
        route_session_target_minutes,
        1,
    )
    workout_bias = intensity_decision["readiness_ceiling"]
    recommended_training_raw = (
        None if not indoor_available else load_json_if_exists(source_files["xert_recommended_training"])
    )
    if indoor_gym_available and not indoor_available:
        indoor_workouts_packet = indoor_gym_packet(
            target_minutes=route_session_target_minutes,
        )
        write_json(source_files["xert_workouts"], indoor_workouts_packet)
    elif not indoor_available:
        indoor_workouts_packet = indoor_unavailable_packet(reason=indoor_unavailable_reason)
        write_json(
            source_files["xert_workouts"],
            indoor_workouts_packet,
        )
    elif recommended_training_raw is not None:
        indoor_workouts_packet = compact_xert_workout_recommendations(
            recommended_training_raw,
            target_minutes=target_minutes,
            target_load=target_load,
            readiness_bias=workout_bias,
            preferred_workout_name_contains=preferred_workout_name,
        )
        annotate_indoor_window_fit(
            indoor_workouts_packet,
            planned_at=planned_at,
            now=now,
            available_windows=available_windows,
        )
        write_json(
            source_files["xert_workouts"],
            indoor_workouts_packet,
        )
    elif args.refresh_json["mode"] == "none":
        ensure_source_files_exist(source_files, required=("xert_workouts",))
        indoor_workouts_packet = load_json_if_exists(source_files["xert_workouts"])
    else:
        indoor_workouts_packet = load_json_if_exists(source_files["xert_workouts"])
    if (indoor_available or indoor_gym_available) and isinstance(
        indoor_workouts_packet, dict
    ):
        annotate_indoor_window_fit(
            indoor_workouts_packet,
            planned_at=planned_at,
            now=now,
            available_windows=available_windows,
        )
        write_json(source_files["xert_workouts"], indoor_workouts_packet)

    if "xert_workout_capacity" in args.source_overrides_json:
        effective_start = max(planned_at, now)
        sessions = (target_resolution.get("split") or {}).get("sessions") or []
        if sessions:
            scheduled_start = instant(sessions[0]["start"], "scheduled workout start")
            # Scheduler displays minute precision; retain known seconds in the same minute.
            if scheduled_start.replace(second=0, microsecond=0) != effective_start.astimezone(timezone.utc).replace(second=0, microsecond=0):
                effective_start = scheduled_start
        target_resolution["capacity_horizon"] = validate_capacity_horizon(
            load_json_if_exists(source_files["xert_workout_capacity"]) or {},
            planned_at=effective_start.isoformat(),
            next_workout_at=planning_context.get("next_workout_at"),
            approximation=planning_context.get("capacity_approximation"))
        target_resolution["recovery_protection_capacity"]["horizon"] = target_resolution["capacity_horizon"]

    comparison = (target_resolution.get("vt1_dose_comparison") or {}).get("reference_vs_prescription")
    if comparison:
        sessions = (target_resolution.get("split") or {}).get("sessions") or []
        finish = instant(sessions[-1]["end"], "scheduled workout end") if sessions else None
        next_at = planning_context.get("next_workout_at")
        comparison["prescription"].update(
            finish_at=finish.astimezone(local_timezone).isoformat() if finish else None,
            next_workout_at=next_at,
            finish_to_next_planned_workout_minutes=(
                round((instant(next_at, "next_workout_at") - finish).total_seconds() / 60, 1)
                if finish and next_at else None),
        )

    primary_decision = build_primary_decision(
        readiness_packet=readiness_packet,
        target_resolution=target_resolution,
        intensity_decision=intensity_decision,
        cycling_available=indoor_available or indoor_gym_available or outdoor_available,
        remainder_disposition=planning_context["calendar"]["remainder_disposition"],
    )
    finish_review = resolve_aerobic_finish(
        primary_decision, target_resolution, planned_at=max(planned_at, now),
        available_windows=available_windows, calendar=planning_context["calendar"],
        required=require_finish_review,
        spacing_day=(pure_vt1 and plan_context["next_role"] == "easy_aerobic"
                     and plan_context.get("aerobic_days_since_quality") == 0
                     and bool(plan_context.get("last_quality_session"))),
    )
    if finish_review:
        primary_decision["aerobic_finish"] = finish_review
    selection = primary_decision.get("coaching_selection")
    if selection and "aerobic_finish" in selection:
        # Keep the original proposal in target_resolution. Only the resolved
        # finish belongs in the executable recommendation.
        primary_decision["coaching_selection"] = {
            key: value for key, value in selection.items() if key != "aerobic_finish"
        }

    if not outdoor_available:
        route_packet = outdoor_unavailable_packet(reason=outdoor_unavailable_reason)
    else:
        route_packet = recommend_routes(
            day=parse_date(args.date),
            years=5,
            xert_loads_json=source_files["xert_activity_loads"],
            target_distance_km=target_distance_km,
            target_minutes=target_minutes,
            queries=[],
            max_results=8,
            artifacts_dir=ARTIFACTS_DIR,
            start_anchor_name=args.start_anchor_displayname or "selected start anchor",
            start_anchor_lat=args.start_anchor_lat,
            start_anchor_lng=args.start_anchor_lng,
            start_radius_km=args.start_radius_km,
            allow_away=args.route_allow_away,
            surface_preference=args.surface_preference,
            route_index=args.route_options_json["index"],
            rebuild_index=args.route_options_json["rebuild_index"],
        )
        annotate_route_window_fit(
            route_packet,
            target_minutes=route_session_target_minutes,
            planned_at=planned_at,
            now=now,
            available_windows=available_windows,
        )
    if (
        outdoor_available
        and args.route_options_json["map_scope"] != "none"
        and source_refresh.get("xert_route_maps", {}).get("refresh")
    ):
        route_map_limit = 1 if args.route_options_json["map_scope"] == "top" else None
        route_packet = enrich_route_packet_with_xert_maps(
            route_packet,
            xert_activities=load_json_if_exists(source_files["xert_activity_loads"]),
            local_timezone=local_timezone,
            limit=route_map_limit,
        )
        route_packet = cache_xert_route_map_images(
            route_packet,
            output_dir=output_dir,
            limit=route_map_limit,
        )
        write_json(source_files["xert_route_maps"], route_packet.get("xert_route_maps") or {})
    route_packet = annotate_route_map_status(
        route_packet,
        map_scope=args.route_options_json["map_scope"],
    )
    first_route = first_recommendation(route_packet)

    weather_sources_requiring_mcp = {
        key for key in ("weather_home", "weather_route")
        if source_refresh.get(key, {}).get("refresh")
        and (key != "weather_route" or first_route is not None)
    }
    if weather_sources_requiring_mcp:
        raise SystemExit(
            "Yr live access is MCP-only. Fetch get_forecast for: "
            + ", ".join(sorted(weather_sources_requiring_mcp))
            + "; then pass each normalized JSON file through --source-overrides-json."
        )

    ensure_source_files_exist(
        source_files,
        required=tuple(
            sorted(
                key
                for key in ("weather_home", "weather_route")
                if key in required_sources
                and (key != "weather_route" or first_route is not None)
            )
        ),
        policy=args.refresh_json["mode"],
    )

    weather_home = load_json_if_exists(source_files["weather_home"])
    weather_route = (
        None
        if not outdoor_available
        else weather_home
        if first_route is None
        else load_json_if_exists(source_files["weather_route"])
    )
    indoor_workouts = indoor_workouts_packet
    decision_inputs = compact_decision_inputs(
        readiness_packet,
        routes=route_packet,
        weather_home=weather_home,
        weather_route=weather_route,
        indoor_workouts=indoor_workouts,
        target_resolution=target_resolution,
        history_context=history_context,
        progression_advice=progression_advice,
    )
    fueling_defaults = practical_fueling_defaults()
    llm_context = build_llm_context(
        decision_inputs,
        fueling_defaults=fueling_defaults,
        readiness_notes=readiness_packet.get("notes") or [],
        now=now,
        planned_at=planned_at,
        planned_at_source=planned_at_source,
        available_windows=available_windows,
        calendar_context=planning_context["calendar"],
    )
    llm_context["primary_decision"] = primary_decision
    llm_context["plan_context"] = plan_context
    primary_decision["plan_context"] = plan_context

    packet = {
        "source": "training-ai-recommend-training",
        "date": args.date,
        "generated_at": generated_at_utc.isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "local_timezone": args.local_timezone,
        "planned_at": planned_at.isoformat(timespec="seconds"),
        "planned_at_utc": planned_at.astimezone(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "planned_at_source": planned_at_source,
        "available_windows": serialize_available_windows(available_windows),
        "calendar": planning_context["calendar"],
        "available_modalities": sorted(args.available_modalities),
        "unavailable_reasons": unavailable_reasons,
        "source_files": {
            key: str(path)
            for key, path in source_files.items()
            if not (
                key == "xert_route_maps"
                and args.route_options_json["map_scope"] == "none"
                and not path.exists()
            )
        },
        "source_refresh": source_refresh,
        "readiness": readiness_packet,
        "plan_context": plan_context,
        "primary_decision": primary_decision,
        "target_resolution": target_resolution,
        "training_history_context": history_context,
        "routes": route_packet,
        "weather": {
            "home": weather_home,
            "route": weather_route,
        },
        "indoor_workouts": indoor_workouts,
        "progression_advice": progression_advice,
        "decision_inputs": decision_inputs,
        "llm_context": llm_context,
        "fueling_defaults": fueling_defaults,
    }

    packet_path = output_dir / "recommendation-packet.json"
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.compact_summary:
        print(format_compact_summary(packet, packet_path))
    elif args.summary:
        print(format_summary(packet))
    else:
        print(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))


def source_paths(output_dir: Path, day: str) -> dict[str, Path]:
    return {
        "garmin": output_dir / f"garmin-readiness-{day}.json",
        "garmin_hrv_history": output_dir / f"garmin-hrv-history-{day}.json",
        "xert": output_dir / f"xert-readiness-{day}.json",
        "intervals_wellness": output_dir / f"intervals-wellness-recent-{day}.json",
        "intervals_events": output_dir / f"intervals-events-recent-{day}.json",
        "intervals_activity_volume": output_dir / f"intervals-activity-volume-{day}.json",
        "xert_activity_loads": output_dir / f"xert-activity-loads-recent-{day}.json",
        "xert_recommended_training": output_dir / f"xert-recommended-training-{day}.json",
        "xert_workout_capacity": output_dir / f"xert-workout-capacity-{day}.json",
        "xert_route_maps": output_dir / f"xert-route-maps-{day}.json",
        "xert_workouts": output_dir / f"xert-workouts-{day}.json",
        "progression_vt2": output_dir / f"progression-vt2-{day}.json",
        "progression_vo2max": output_dir / f"progression-vo2max-{day}.json",
        "weather_home": output_dir / f"yr-home-{day}.json",
        "weather_route": output_dir / f"yr-route-{day}.json",
    }


def parse_refresh_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--refresh-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("--refresh-json must contain one JSON object")
    unknown_fields = sorted(set(payload) - {"mode", "sources"})
    if unknown_fields:
        raise argparse.ArgumentTypeError(f"unsupported refresh field: {unknown_fields[0]}")
    mode = payload.get("mode")
    if mode not in {"auto", "all", "none", "selected"}:
        raise argparse.ArgumentTypeError("refresh mode must be auto, all, none, or selected")
    sources = payload.get("sources", [])
    if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
        raise argparse.ArgumentTypeError("refresh sources must be an array of strings")
    sources = sorted(set(sources))
    unknown_sources = sorted(set(sources) - REFRESH_GROUPS)
    if unknown_sources:
        raise argparse.ArgumentTypeError(f"unsupported refresh source: {unknown_sources[0]}")
    if mode == "selected" and not sources:
        raise argparse.ArgumentTypeError("selected refresh mode requires sources")
    if mode != "selected" and sources:
        raise argparse.ArgumentTypeError("refresh sources are only allowed with selected mode")
    return {"mode": mode, "sources": sources}


def parse_source_overrides_json(raw: str) -> dict[str, Path]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--source-overrides-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--source-overrides-json must contain one JSON object"
        )
    unknown = sorted(set(payload) - set(SOURCE_REFRESH_POLICY))
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unsupported source override: {unknown[0]}"
        )
    parsed: dict[str, Path] = {}
    for source_name, raw_path in payload.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise argparse.ArgumentTypeError(
                f"source override {source_name} must be a non-empty file path"
            )
        path = Path(raw_path)
        if not path.is_file():
            raise argparse.ArgumentTypeError(
                f"source override file does not exist: {path}"
            )
        try:
            source_payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise argparse.ArgumentTypeError(
                f"source override {source_name} must contain valid JSON: {exc.msg}"
            ) from exc
        if not isinstance(source_payload, dict):
            raise argparse.ArgumentTypeError(
                f"source override {source_name} must contain one JSON object"
            )
        parsed[source_name] = path
    return parsed


def normalize_source_override_payload(
    source_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Normalize supported MCP structuredContent envelopes at the file boundary."""

    if source_name == "garmin":
        health_day = payload.get("health_day")
        if isinstance(health_day, dict):
            normalized = dict(health_day)
            normalized.setdefault("archive_date", payload.get("date"))
            return normalized
        return dict(payload)

    if source_name == "garmin_hrv_history" and isinstance(payload.get("hrv_history"), dict):
        return dict(payload["hrv_history"])

    if source_name == "xert_recommended_training":
        advice = payload.get("advice")
        if isinstance(advice, dict):
            return dict(advice)
        return dict(payload)

    if source_name == "xert_workout_capacity":
        workout_capacity = payload.get("workout_capacity")
        normalized = dict(workout_capacity if isinstance(workout_capacity, dict) else payload)
        normalized.setdefault("as_of", normalized.get("state_as_of"))
        capacity = normalized.get("capacity")
        if isinstance(capacity, dict) and not isinstance(
            normalized.get("workout_capacity_xss"), dict
        ):
            normalized["workout_capacity_xss"] = capacity
        return normalized

    if source_name != "xert":
        return dict(payload)

    normalized = dict(payload)
    if isinstance(payload.get("state"), dict):
        normalized = {"training_state": {"state": payload["state"]}}
    elif isinstance(payload.get("advice"), dict):
        normalized = {"training_advice": {"advice": payload["advice"]}}

    training_state = normalized.get("training_state")
    if isinstance(training_state, dict) and isinstance(training_state.get("state"), dict):
        normalized["training_state"] = {"state": training_state["state"]}

    training_advice = normalized.get("training_advice")
    if isinstance(training_advice, dict) and isinstance(training_advice.get("advice"), dict):
        normalized["training_advice"] = {"advice": training_advice["advice"]}

    return normalized


def validate_source_override_payload(
    source_name: str,
    payload: dict[str, Any],
) -> None:
    """Fail at ingestion when a supported source lacks its identifying shape."""

    required_list = {
        "garmin_hrv_history": "days",
        "intervals_wellness": "wellness",
        "intervals_events": "events",
        "intervals_activity_volume": "activities",
        "xert_activity_loads": "activities",
    }.get(source_name)
    if required_list is not None and not isinstance(payload.get(required_list), list):
        raise ValueError(
            f"source override {source_name} requires a {required_list} array "
            "after MCP normalization"
        )

    if source_name == "xert_recommended_training":
        remaining = payload.get("remaining_xss")
        target = payload.get("target_xss")
        if not (
            isinstance(remaining, dict) and isinstance(remaining.get("low"), (int, float))
        ) and not (
            isinstance(target, dict) and isinstance(target.get("low"), (int, float))
        ):
            raise ValueError(
                "source override xert_recommended_training requires numeric "
                "remaining_xss.low or target_xss.low after MCP normalization"
            )

    if source_name == "xert_workout_capacity":
        validate_capacity_values(payload)

    if source_name == "xert" and not (
        isinstance(payload.get("training_state"), dict)
        or isinstance(payload.get("training_advice"), dict)
    ):
        raise ValueError(
            "source override xert requires training_state or training_advice "
            "after MCP normalization"
        )


def compose_garmin_source_overrides(
    source_files: dict[str, Path], *, overridden_sources: set[str],
) -> None:
    """Attach unchanged MCP nightly history to the explicitly supplied health day."""
    if "garmin_hrv_history" not in overridden_sources:
        return
    if "garmin" not in overridden_sources:
        raise ValueError("garmin_hrv_history requires a garmin override from this run")
    garmin = load_json_if_exists(source_files["garmin"])
    history = load_json_if_exists(source_files["garmin_hrv_history"])
    if not isinstance(garmin, dict) or not isinstance(history, dict):
        raise ValueError("Garmin day and HRV history must be JSON objects")
    composed = dict(garmin)
    composed["hrv_history"] = history
    composed["hrv_history_source_file"] = str(source_files["garmin_hrv_history"])
    write_json(source_files["garmin"], composed)


def compose_xert_source_overrides(
    source_files: dict[str, Path],
    *,
    overridden_sources: set[str],
) -> None:
    """Combine raw Xert state and planned advice after independent normalization."""

    required = {"xert", "xert_recommended_training"}
    if not required.issubset(overridden_sources):
        return

    xert = load_json_if_exists(source_files["xert"])
    advice = load_json_if_exists(source_files["xert_recommended_training"])
    if not isinstance(xert, dict) or not isinstance(advice, dict):
        raise ValueError(
            "xert and xert_recommended_training overrides must be JSON objects "
            "before composition"
        )

    composed = dict(xert)
    composed["training_advice"] = {"advice": dict(advice)}
    composed["training_advice_source_file"] = str(
        source_files["xert_recommended_training"]
    )
    write_json(source_files["xert"], composed)


def parse_route_options_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--route-options-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("--route-options-json must contain one JSON object")
    unknown = sorted(set(payload) - {"index", "rebuild_index", "map_scope"})
    if unknown:
        raise argparse.ArgumentTypeError(f"unsupported route-option field: {unknown[0]}")
    index = payload.get("index", "outputs/route-index.json")
    if not isinstance(index, str) or not index.strip():
        raise argparse.ArgumentTypeError("route-option index must be a non-empty path")
    rebuild_index = payload.get("rebuild_index", False)
    if not isinstance(rebuild_index, bool):
        raise argparse.ArgumentTypeError("route-option rebuild_index must be boolean")
    map_scope = payload.get("map_scope", "top")
    if map_scope not in {"top", "all", "none"}:
        raise argparse.ArgumentTypeError("route-option map_scope must be top, all, or none")
    return {"index": Path(index), "rebuild_index": rebuild_index, "map_scope": map_scope}


def refresh_spec_forces(refresh_spec: dict[str, Any], group: str) -> bool:
    return refresh_spec["mode"] == "all" or (
        refresh_spec["mode"] == "selected" and group in refresh_spec["sources"]
    )


def build_source_refresh_plan(
    source_files: dict[str, Path],
    *,
    required: set[str],
    refresh_spec: dict[str, Any],
    checked_at: datetime,
    overrides: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    overrides = overrides or set()
    plan: dict[str, dict[str, Any]] = {}
    for key in sorted(required):
        group, ttl_minutes = SOURCE_REFRESH_POLICY[key]
        path = source_files[key]
        age_minutes = source_file_age_minutes(path, checked_at=checked_at)
        exists = age_minutes is not None
        if key in overrides:
            status, refresh, reason = "provided", False, "explicit_input_override"
        elif refresh_spec_forces(refresh_spec, group):
            status, refresh, reason = "forced", True, "forced_by_cli"
        elif refresh_spec["mode"] == "none":
            refresh = False
            status = "reused" if exists and age_minutes <= ttl_minutes else "stale_offline"
            reason = "refresh_disabled"
        elif not exists:
            status, refresh, reason = "fetched", True, "missing"
        elif age_minutes > ttl_minutes:
            status, refresh, reason = "fetched", True, "ttl_expired"
        else:
            status, refresh, reason = "reused", False, "within_ttl"
        plan[key] = {
            "group": group,
            "status": status,
            "refresh": refresh,
            "reason": reason,
            "age_minutes": None if age_minutes is None else round(age_minutes, 1),
            "ttl_minutes": ttl_minutes,
            "path": str(path),
        }
    return plan


def mcp_sources_requiring_refresh(
    source_refresh: dict[str, dict[str, Any]],
    *,
    indoor_available: bool,
) -> set[str]:
    """Return live inputs whose transport is owned by an MCP source plugin."""

    candidates = {
        "intervals_activity_volume",
        "garmin",
        "intervals_wellness",
        "intervals_events",
        "xert",
        "xert_activity_loads",
    }
    if indoor_available:
        candidates.add("xert_recommended_training")
    return {
        key for key in candidates if source_refresh.get(key, {}).get("refresh")
    }


def source_file_age_minutes(path: Path, *, checked_at: datetime) -> float | None:
    if not path.exists():
        return None
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=checked_at.tzinfo)
    return max(0.0, (checked_at - modified_at).total_seconds() / 60)


def parse_planning_context_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--planning-context-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--planning-context-json must contain one JSON object"
        )
    unknown_top_level = sorted(
        set(payload)
        - {
            "date",
            "local_timezone",
            "now",
            "planned_at",
            "availability",
            "cycling",
            "route",
            "calendar",
            "split_preference",
            "next_workout_at",
            "capacity_approximation",
        }
    )
    if unknown_top_level:
        raise argparse.ArgumentTypeError(
            "unsupported planning-context field(s): "
            + ", ".join(unknown_top_level)
        )

    day = payload.get("date")
    if not isinstance(day, str):
        raise argparse.ArgumentTypeError(
            "--planning-context-json date must be an ISO calendar date"
        )
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--planning-context-json date must be an ISO calendar date"
        ) from exc

    timezone_name = payload.get("local_timezone")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise argparse.ArgumentTypeError(
            "--planning-context-json local_timezone must be an IANA timezone"
        )
    local_timezone = parse_timezone(timezone_name)

    now = planning_context_instant(
        payload.get("now"),
        field="--planning-context-json now",
        local_timezone=local_timezone,
        required=True,
    )
    planned_at = planning_context_instant(
        payload.get("planned_at"),
        field="--planning-context-json planned_at",
        local_timezone=local_timezone,
        required=False,
    )
    if planned_at is not None and planned_at.date().isoformat() != day:
        raise argparse.ArgumentTypeError(
            "--planning-context-json planned_at must belong to date"
        )

    if payload.get("next_workout_at") is not None:
        try:
            instant(payload["next_workout_at"], "next_workout_at")
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
    if payload.get("capacity_approximation") is not None and not isinstance(payload["capacity_approximation"], dict):
        raise argparse.ArgumentTypeError("capacity_approximation must be an object with reason and evidence")

    availability = payload.get("availability", {"windows": []})
    windows = parse_availability_payload(
        availability,
        expected_timezone=local_timezone,
        argument_name="--planning-context-json availability",
    )

    cycling = payload.get("cycling")
    if not isinstance(cycling, dict):
        raise argparse.ArgumentTypeError(
            "--planning-context-json requires a cycling object"
        )
    preferred_workout_name_contains = cycling.get("preferred_workout_name_contains")
    if preferred_workout_name_contains is not None and (
        not isinstance(preferred_workout_name_contains, str) or not preferred_workout_name_contains.strip()
    ):
        raise argparse.ArgumentTypeError(
            "--planning-context-json cycling.preferred_workout_name_contains must be a non-empty string"
        )
    modalities_raw = cycling.get("available_modalities")
    if not isinstance(modalities_raw, list) or any(
        not isinstance(value, str) for value in modalities_raw
    ):
        raise argparse.ArgumentTypeError(
            "--planning-context-json cycling.available_modalities must be an array"
        )
    modalities = list(dict.fromkeys(modalities_raw))
    allowed_modalities = {
        "indoor_cycling",
        "indoor_cycling_gym",
        "outdoor_cycling",
    }
    unknown_modalities = sorted(set(modalities) - allowed_modalities)
    if unknown_modalities:
        raise argparse.ArgumentTypeError(
            "unsupported cycling modalit"
            f"{'y' if len(unknown_modalities) == 1 else 'ies'}: "
            + ", ".join(unknown_modalities)
        )

    unavailable_reasons = cycling.get("unavailable_reasons", {})
    if not isinstance(unavailable_reasons, dict):
        raise argparse.ArgumentTypeError(
            "--planning-context-json cycling.unavailable_reasons must be an object"
        )
    unknown_reason_keys = sorted(set(unavailable_reasons) - allowed_modalities)
    if unknown_reason_keys:
        raise argparse.ArgumentTypeError(
            "unsupported unavailable-reason modalit"
            f"{'y' if len(unknown_reason_keys) == 1 else 'ies'}: "
            + ", ".join(unknown_reason_keys)
        )
    if any(
        not isinstance(reason, str) or not reason.strip()
        for reason in unavailable_reasons.values()
    ):
        raise argparse.ArgumentTypeError(
            "--planning-context-json unavailable reasons must be non-empty strings"
        )

    route = parse_route_context_payload(
        payload.get("route", {}),
        argument_name="--planning-context-json route",
    )
    calendar = parse_calendar_context_payload(
        payload.get("calendar", {}),
        local_timezone=local_timezone,
    )
    split_preference = parse_split_preference_payload(
        payload.get("split_preference"),
        local_timezone=local_timezone,
        day=day,
    )
    start_anchor = route["start_anchor"]
    if (
        "outdoor_cycling" in modalities
        and start_anchor is None
        and not route["allow_away"]
    ):
        raise argparse.ArgumentTypeError(
            "--planning-context-json outdoor_cycling requires route.start_anchor "
            "unless route.allow_away is true"
        )

    return {
        "next_workout_at": payload.get("next_workout_at"),
        "capacity_approximation": payload.get("capacity_approximation"),
        "date": day,
        "local_timezone": timezone_name,
        "now": now.isoformat(timespec="seconds"),
        "planned_at": (
            planned_at.isoformat(timespec="seconds") if planned_at else None
        ),
        "availability": {
            "windows": serialize_available_windows(windows),
        },
        "cycling": {
            "available_modalities": modalities,
            "unavailable_reasons": {
                key: value.strip() for key, value in unavailable_reasons.items()
            },
            **(
                {"preferred_workout_name_contains": preferred_workout_name_contains.strip()}
                if preferred_workout_name_contains is not None else {}
            ),
        },
        "route": route,
        "calendar": calendar,
        "split_preference": split_preference,
    }


def build_planning_context(
    *,
    day: str,
    local_timezone: str,
    now: str,
    cycling: dict[str, Any],
    planned_at: str | None = None,
    availability_windows: list[dict[str, Any]] | None = None,
    route: dict[str, Any] | None = None,
    calendar: dict[str, Any] | None = None,
    split_preference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate the internal planning context without hand-written JSON."""

    payload = {
        "date": day,
        "local_timezone": local_timezone,
        "now": now,
        "planned_at": planned_at,
        "availability": {"windows": availability_windows or []},
        "cycling": cycling,
        "route": route or {},
        "calendar": calendar or {},
    }
    if split_preference is not None:
        payload["split_preference"] = split_preference
    return parse_planning_context_json(json.dumps(payload))


def parse_split_preference_payload(
    payload: Any,
    *,
    local_timezone: Any,
    day: str,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "first_session_minutes",
        "second_session_start",
    }:
        raise argparse.ArgumentTypeError(
            "split_preference must contain exactly first_session_minutes and second_session_start"
        )
    first_minutes = payload.get("first_session_minutes")
    if (
        isinstance(first_minutes, bool)
        or not isinstance(first_minutes, (int, float))
        or first_minutes < MIN_SEPARATE_VT1_SESSION_MINUTES
    ):
        raise argparse.ArgumentTypeError(
            f"split_preference.first_session_minutes must be at least {MIN_SEPARATE_VT1_SESSION_MINUTES:g}"
        )
    second_start = planning_context_instant(
        payload.get("second_session_start"),
        field="split_preference.second_session_start",
        local_timezone=local_timezone,
        required=True,
    )
    if second_start.date().isoformat() != day:
        raise argparse.ArgumentTypeError(
            "split_preference.second_session_start must belong to date"
        )
    return {
        "first_session_minutes": round(float(first_minutes), 1),
        "second_session_start": second_start.isoformat(timespec="seconds"),
    }


def parse_calendar_context_payload(
    payload: Any,
    *,
    local_timezone: Any,
) -> dict[str, Any]:
    """Parse only calendar facts needed to explain an already-resolved window."""

    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--planning-context-json calendar must be an object"
        )
    unknown = sorted(
        set(payload)
        - {
            "cleanup_buffer_minutes",
            "assumptions",
            "practical_stop",
            "hard_stop",
            "remainder_disposition",
            "events",
            "open_training_subjects",
            "day_start",
            "day_end",
            "setup_buffer_minutes",
        }
    )
    if unknown:
        raise argparse.ArgumentTypeError(
            "unsupported planning-context calendar field(s): " + ", ".join(unknown)
        )
    cleanup = payload.get("cleanup_buffer_minutes", 0)
    if isinstance(cleanup, bool) or not isinstance(cleanup, (int, float)) or cleanup < 0:
        raise argparse.ArgumentTypeError(
            "calendar.cleanup_buffer_minutes must be a non-negative number"
        )
    assumptions = payload.get("assumptions", [])
    if not isinstance(assumptions, list) or any(
        not isinstance(value, str) or not value.strip() for value in assumptions
    ):
        raise argparse.ArgumentTypeError(
            "calendar.assumptions must be an array of non-empty strings"
        )
    stops = {}
    for field in ("practical_stop", "hard_stop"):
        stop = payload.get(field)
        if stop is None:
            stops[field] = None
            continue
        if not isinstance(stop, dict) or set(stop) != {"subject", "at"}:
            raise argparse.ArgumentTypeError(
                f"calendar.{field} must contain exactly subject and at"
            )
        subject = stop.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            raise argparse.ArgumentTypeError(
                f"calendar.{field}.subject must be a non-empty string"
            )
        at = parse_availability_instant(stop.get("at"), field=f"calendar.{field}.at")
        if at.astimezone(local_timezone).utcoffset() != at.utcoffset():
            raise argparse.ArgumentTypeError(
                f"calendar.{field}.at UTC offset must match local_timezone"
            )
        stops[field] = {
            "subject": subject.strip(),
            "at": at.astimezone(local_timezone).isoformat(timespec="seconds"),
        }
    disposition = payload.get("remainder_disposition", "unscheduled")
    if disposition == "none":
        disposition = "unscheduled"
    if disposition not in {"unscheduled", "dropped", "moved", "conditionally_split"}:
        raise argparse.ArgumentTypeError(
            "calendar.remainder_disposition must be unscheduled, dropped, moved, or conditionally_split"
        )
    setup = payload.get("setup_buffer_minutes", 0)
    if isinstance(setup, bool) or not isinstance(setup, (int, float)) or setup < 0:
        raise argparse.ArgumentTypeError(
            "calendar.setup_buffer_minutes must be a non-negative number"
        )
    day_bounds = {}
    for field in ("day_start", "day_end"):
        value = payload.get(field)
        if value is None:
            day_bounds[field] = None
            continue
        instant = parse_availability_instant(value, field=f"calendar.{field}")
        if instant.astimezone(local_timezone).utcoffset() != instant.utcoffset():
            raise argparse.ArgumentTypeError(
                f"calendar.{field} UTC offset must match local_timezone"
            )
        day_bounds[field] = instant.astimezone(local_timezone).isoformat(timespec="seconds")
    events = payload.get("events")
    if events is not None:
        if not isinstance(events, list):
            raise argparse.ArgumentTypeError("calendar.events must be an array")
        events = [parse_calendar_event(event, index=index, local_timezone=local_timezone)
                  for index, event in enumerate(events)]
        if not day_bounds["day_start"] or not day_bounds["day_end"]:
            raise argparse.ArgumentTypeError(
                "calendar.day_start and calendar.day_end are required with calendar.events"
            )
        if datetime.fromisoformat(day_bounds["day_end"]) <= datetime.fromisoformat(day_bounds["day_start"]):
            raise argparse.ArgumentTypeError("calendar.day_end must be after day_start")
    subjects = payload.get("open_training_subjects", [])
    if not isinstance(subjects, list) or any(not isinstance(s, str) or not s.strip() for s in subjects):
        raise argparse.ArgumentTypeError("calendar.open_training_subjects must be a list of non-empty titles")
    open_titles = {s.strip().casefold() for s in subjects}
    for event in events or []:
        if event["subject"].casefold() in open_titles and event["classification"] != "open_training":
            raise argparse.ArgumentTypeError(
                f"Classify {event['subject']!r} as open_training per the resolved coaching preferences. "
                "Reassess the window, dose and rationale; record any separate commitment as its own event."
            )
    for field, stop in stops.items():
        if stop and stop["subject"].casefold() in open_titles:
            raise argparse.ArgumentTypeError(f"An open training title cannot supply calendar.{field}")
    practical = stops["practical_stop"]
    if practical and any(
        event["classification"] == "movable_event" and event["start"] == practical["at"]
        and event["subject"].casefold() == practical["subject"].casefold()
        for event in events or []
    ):
        stops["practical_stop"] = None
    return {
        "cleanup_buffer_minutes": float(cleanup),
        "setup_buffer_minutes": float(setup),
        **day_bounds,
        "events": events,
        "open_training_subjects": [s.strip() for s in subjects],
        "assumptions": [value.strip() for value in assumptions],
        **stops,
        "remainder_disposition": disposition,
    }


def parse_calendar_event(event: Any, *, index: int, local_timezone: Any) -> dict[str, Any]:
    prefix = f"calendar.events[{index}]"
    if not isinstance(event, dict):
        raise argparse.ArgumentTypeError(f"{prefix} must be an object")
    allowed = {
        "id", "subject", "start", "end", "classification",
        "minimum_duration_minutes", "shorten_if_no_feasible_placement",
    }
    if set(event) - allowed:
        raise argparse.ArgumentTypeError(f"{prefix} has unsupported fields: " + ", ".join(sorted(set(event) - allowed)))
    subject = event.get("subject")
    classification = event.get("classification")
    if not isinstance(subject, str) or not subject.strip():
        raise argparse.ArgumentTypeError(f"{prefix}.subject must be a non-empty string")
    allowed_classes = {
        "fixed_blocker", "open_training", "tentative_nonblocking",
        "movable_event", "flexible_appointment", "indoor_overlap_candidate",
        "unknown",
    }
    if classification not in allowed_classes:
        raise argparse.ArgumentTypeError(f"{prefix}.classification must be one of: " + ", ".join(sorted(allowed_classes)))
    start = parse_availability_instant(event.get("start"), field=f"{prefix}.start")
    end = parse_availability_instant(event.get("end"), field=f"{prefix}.end")
    if start.astimezone(local_timezone).utcoffset() != start.utcoffset() or end.astimezone(local_timezone).utcoffset() != end.utcoffset() or end <= start:
        raise argparse.ArgumentTypeError(f"{prefix} must have valid local offsets and end after start")
    result = {"id": event.get("id"), "subject": subject.strip(), "classification": classification,
              "start": start.astimezone(local_timezone).isoformat(timespec="seconds"),
              "end": end.astimezone(local_timezone).isoformat(timespec="seconds")}
    if classification == "movable_event":
        minimum = event.get("minimum_duration_minutes", (end - start).total_seconds() / 60)
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or minimum <= 0 or minimum > (end - start).total_seconds() / 60:
            raise argparse.ArgumentTypeError(f"{prefix}.minimum_duration_minutes must be positive and no longer than the event")
        shorten = event.get("shorten_if_no_feasible_placement", False)
        if not isinstance(shorten, bool):
            raise argparse.ArgumentTypeError(f"{prefix}.shorten_if_no_feasible_placement must be boolean")
        result["minimum_duration_minutes"] = float(minimum)
        result["shorten_if_no_feasible_placement"] = shorten
    return result


def calendar_availability_windows(calendar: dict[str, Any], *, local_timezone: Any, day: str) -> list[dict[str, Any]]:
    start = datetime.fromisoformat(calendar["day_start"])
    end = datetime.fromisoformat(calendar["day_end"])
    blockers = sorted(
        (datetime.fromisoformat(event["start"]), datetime.fromisoformat(event["end"]))
        for event in calendar["events"]
        if event["classification"]
        in {"fixed_blocker", "flexible_appointment", "unknown", "indoor_overlap_candidate"}
        and datetime.fromisoformat(event["end"]) > start
        and datetime.fromisoformat(event["start"]) < end
    )
    free = []
    cursor = start
    for block_start, block_end in blockers:
        block_start, block_end = max(start, block_start), min(end, block_end)
        if block_start > cursor:
            free.append((cursor, block_start))
        cursor = max(cursor, block_end)
    if cursor < end:
        free.append((cursor, end))
    setup = timedelta(minutes=calendar["setup_buffer_minutes"])
    cleanup = timedelta(minutes=calendar["cleanup_buffer_minutes"])
    return [{"start": a + setup, "end": b - cleanup, "time_zone": str(local_timezone)}
            for a, b in free if b - cleanup > a + setup]


def place_movable_events(calendar: dict[str, Any], *, sessions: list[dict[str, Any]], local_timezone: Any, day: str) -> dict[str, Any]:
    movable_events = [event for event in calendar["events"] if event["classification"] == "movable_event"]
    if not movable_events:
        return {"status": "no_movable_events", "placements": []}
    day_start, day_end = datetime.fromisoformat(calendar["day_start"]), datetime.fromisoformat(calendar["day_end"])
    occupied = [
        (datetime.fromisoformat(event["start"]), datetime.fromisoformat(event["end"]))
        for event in calendar["events"]
        if event["classification"] in {"fixed_blocker", "flexible_appointment", "unknown"}
    ]
    setup = timedelta(minutes=calendar["setup_buffer_minutes"])
    cleanup = timedelta(minutes=calendar["cleanup_buffer_minutes"])
    occupied.extend(
        (datetime.fromisoformat(session["start"]) - setup,
         datetime.fromisoformat(session["end"]) + cleanup)
        for session in sessions if session.get("start") and session.get("end")
    )
    placements = []
    for movable in sorted(movable_events, key=lambda item: item["start"]):
        original, minimum = (datetime.fromisoformat(movable["end"]) - datetime.fromisoformat(movable["start"])), timedelta(minutes=movable["minimum_duration_minutes"])
        candidates = [original.total_seconds() / 60]
        if movable["shorten_if_no_feasible_placement"] and minimum < original:
            candidates.append(minimum.total_seconds() / 60)
        placed = None
        for minutes in candidates:
            duration = timedelta(minutes=minutes)
            starts = [datetime.fromisoformat(movable["start"]), day_start] + [b for _, b in occupied]
            for candidate in sorted(set(starts), key=lambda t: (abs((t - datetime.fromisoformat(movable["start"])).total_seconds()), t)):
                finish = candidate + duration
                if candidate < day_start or finish > day_end or any(candidate < b and finish > a for a, b in occupied):
                    continue
                placed = {"subject": movable["subject"], "start": candidate.isoformat(timespec="seconds"), "end": finish.isoformat(timespec="seconds"), "duration_minutes": minutes, "shortened": minutes < original.total_seconds() / 60}
                break
            if placed:
                break
        if not placed:
            placements.append({"subject": movable["subject"], "status": "unplaced", "reason": "no_feasible_placement"})
        else:
            occupied.append((datetime.fromisoformat(placed["start"]), datetime.fromisoformat(placed["end"])))
            placements.append({"status": "placed", **placed})
    return {"status": "placed" if all(item["status"] == "placed" for item in placements) else "conflict", "placements": placements}


def planning_context_instant(
    value: Any,
    *,
    field: str,
    local_timezone: Any,
    required: bool,
) -> datetime | None:
    if value is None and not required:
        return None
    instant = parse_availability_instant(value, field=field)
    if instant.astimezone(local_timezone).utcoffset() != instant.utcoffset():
        raise argparse.ArgumentTypeError(
            f"{field} UTC offset does not match {local_timezone}"
        )
    return instant.astimezone(local_timezone)


def validate_context(
    parser: argparse.ArgumentParser,
    *,
    args: argparse.Namespace,
    outdoor_available: bool,
) -> None:
    has_start_lat = args.start_anchor_lat is not None
    has_start_lng = args.start_anchor_lng is not None
    if has_start_lat != has_start_lng:
        parser.error(
            "planning_context route.start_anchor requires both lat and lng."
        )
    if outdoor_available and not (has_start_lat and has_start_lng):
        parser.error(
            "planning_context route.start_anchor is required when "
            "cycling.available_modalities includes outdoor_cycling."
        )
def indoor_unavailable_packet(*, reason: str) -> dict[str, Any]:
    return {
        "source": "indoor_unavailable",
        "available": False,
        "reason": reason,
        "policy": (
            "Indoor trainer workouts were not fetched or ranked because indoor "
            "equipment is not available in the current location context."
        ),
        "candidates": [],
        "higher_intensity_candidates": [],
        "recommended": None,
        "relevant_options": [],
    }


def indoor_gym_packet(*, target_minutes: float) -> dict[str, Any]:
    """Describe a basic gym bike without pretending it supports Xert workouts."""
    return {
        "source": "indoor_cycling_gym",
        "available": True,
        "equipment": "gym_bike",
        "policy": (
            "Use continuous aerobic riding controlled by heart rate, breathing, "
            "and RPE. Do not rank watt-based Xert workouts or use the gym bike "
            "for structured threshold or VO2Max by default."
        ),
        "load_estimation": "estimated_without_reliable_power",
        "candidates": [],
        "higher_intensity_candidates": [],
        "recommended": {
            "name": "Continuous aerobic gym-bike ride",
            "duration_minutes": round(target_minutes, 1),
            "control": "heart_rate_breathing_rpe",
            "intensity": "vt1",
            "xss": None,
            "difficulty": None,
            "url": None,
        },
        "relevant_options": [],
    }


def outdoor_unavailable_packet(*, reason: str) -> dict[str, Any]:
    return {
        "source": "outdoor_unavailable",
        "available": False,
        "reason": reason,
        "policy": (
            "Outdoor routes were not ranked because outdoor riding is not "
            "realistic in the current context."
        ),
        "recommendations": [],
    }


def default_planned_at(day: str, *, now: datetime) -> datetime:
    """Pick a practical default while keeping the assumption visible."""

    local_tz = now.tzinfo
    target_day = date.fromisoformat(day)
    candidate = datetime.combine(target_day, datetime.min.time()).replace(
        hour=9,
        minute=30,
        second=0,
        microsecond=0,
        tzinfo=local_tz,
    )
    if target_day == now.date() and now >= candidate - timedelta(minutes=30):
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        latest_reasonable = datetime.combine(target_day, datetime.min.time()).replace(
            hour=20,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=local_tz,
        )
        return (
            min(next_hour, latest_reasonable)
            if next_hour.date() == target_day
            else latest_reasonable
        )
    return candidate


def parse_availability_payload(
    payload: Any,
    *,
    expected_timezone: Any,
    argument_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            f"{argument_name} must contain one JSON object"
        )
    rows = payload.get("windows")
    if not isinstance(rows, list):
        raise argparse.ArgumentTypeError(
            f"{argument_name} requires a windows array"
        )

    expected_timezone_name = str(expected_timezone)
    windows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        label = f"{argument_name}.windows[{index}]"
        if not isinstance(row, dict):
            raise argparse.ArgumentTypeError(f"{label} must be an object")
        time_zone = row.get("time_zone", expected_timezone_name)
        if time_zone != expected_timezone_name:
            raise argparse.ArgumentTypeError(
                f"{label}.time_zone, when provided, must equal --local-timezone "
                f"{expected_timezone_name!r}"
            )
        start = parse_availability_instant(row.get("start"), field=f"{label}.start")
        end = parse_availability_instant(row.get("end"), field=f"{label}.end")
        if end <= start:
            raise argparse.ArgumentTypeError(
                f"{label}.end must be later than start"
            )
        if (
            start.astimezone(expected_timezone).utcoffset() != start.utcoffset()
            or end.astimezone(expected_timezone).utcoffset() != end.utcoffset()
        ):
            raise argparse.ArgumentTypeError(
                f"{label} UTC offsets do not match {expected_timezone_name}"
            )
        note = row.get("note")
        if note is not None and not isinstance(note, str):
            raise argparse.ArgumentTypeError(f"{label}.note must be a string or null")
        windows.append(
            {
                "start": start.astimezone(expected_timezone),
                "end": end.astimezone(expected_timezone),
                "time_zone": time_zone,
                "note": note.strip() if isinstance(note, str) and note.strip() else None,
            }
        )
    return sorted(windows, key=lambda window: window["start"])


def parse_availability_instant(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError(f"{field} must be an ISO-8601 string")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{field} must be a valid ISO-8601 timestamp"
        ) from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            f"{field} must include an explicit UTC offset"
        )
    return instant


def validate_planned_at_in_available_windows(
    parser: argparse.ArgumentParser,
    *,
    planned_at: datetime,
    available_windows: list[dict[str, datetime]],
) -> None:
    if not available_windows:
        return
    if any(window["start"] <= planned_at < window["end"] for window in available_windows):
        return
    parser.error(
        "planning_context planned_at must fall inside one of the supplied "
        "availability windows."
    )


def serialize_available_windows(windows: list[dict[str, datetime]]) -> list[dict[str, Any]]:
    return [serialize_available_window(window) for window in windows]


def serialize_available_window(window: dict[str, Any] | None) -> dict[str, Any] | None:
    if not window:
        return None
    return {
        "start": window["start"].isoformat(timespec="seconds"),
        "end": window["end"].isoformat(timespec="seconds"),
        "time_zone": window.get("time_zone"),
        "minutes": round((window["end"] - window["start"]).total_seconds() / 60, 1),
        "label": f"{window['start'].strftime('%H:%M')}-{window['end'].strftime('%H:%M')}",
        "note": window.get("note"),
    }


def run_json(command: list[str]) -> Any:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        message = f"Command failed ({exc.returncode}): {format_command(command)}"
        if details:
            message += f"\n{details}"
        raise SystemExit(message) from exc
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        preview = result.stdout[:1000].strip()
        raise SystemExit(
            "Command did not return valid JSON: "
            f"{format_command(command)}\nOutput preview: {preview}"
        ) from exc


def garmin_source_day(day: str, *, now: datetime) -> str:
    """Use the latest real Garmin day when the recommendation date is in the future."""

    requested = date.fromisoformat(day)
    return min(requested, now.date()).isoformat()


def run_parallel_steps(steps: dict[str, Any]) -> None:
    if not steps:
        return
    with ThreadPoolExecutor(max_workers=len(steps)) as executor:
        futures = {executor.submit(step): name for name, step in steps.items()}
        for future, name in futures.items():
            try:
                future.result()
            except Exception as exc:
                raise SystemExit(f"{name} failed: {exc}") from exc


def run_json_to_file(command: list[str], path: Path) -> None:
    payload = run_json(command)
    write_json(path, payload)


def build_progression_advice(
    *,
    day: str,
    cutoff: datetime,
    local_timezone: Any,
    source_files: dict[str, Path],
    plan_progression: dict[str, Any],
    plan_state_path: Path,
) -> dict[str, Any]:
    """Collect evidence without a competing progression ladder or default power."""
    advice = {}
    for workout_type, key in (("vt2", "progression_vt2"), ("vo2max", "progression_vo2max")):
        family = plan_progression.get(workout_type) or {}
        command = [
            sys.executable, "-B", "scripts/progression_advisor.py",
            "--type", workout_type, "--date", day,
            "--as-of", cutoff.isoformat(), "--local-timezone", str(local_timezone),
            "--plan-state", str(plan_state_path),
            "--plan-progression-json", json.dumps(family),
            "--output", str(source_files[key]),
        ]
        payload = run_json(command)
        write_json(source_files[key], payload)
        advice[workout_type] = payload
    return {
        "meaning": (
            "Historical evidence requires coaching synthesis. The selected plan and "
            "explicit quality workout own the next dose; these helpers never prescribe "
            "progression or establish current readiness."
        ),
        **advice,
    }


def required_plan_target_power(
    plan_progression: dict[str, Any],
    *,
    workout_type: str,
) -> float:
    family = plan_progression.get(workout_type) or {}
    value = number(family.get("target_power_w"))
    if value is None or value <= 0:
        raise SystemExit(
            f"plan-state progression.{workout_type}.target_power_w must be an explicit positive number"
        )
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def ensure_source_files_exist(
    source_files: dict[str, Path],
    *,
    required: tuple[str, ...],
    policy: str = "none",
) -> None:
    missing = [str(source_files[key]) for key in required if not source_files[key].exists()]
    if missing:
        raise SystemExit(
            f"refresh mode {policy} requires source files after refresh planning. Missing: "
            + ", ".join(missing)
        )


def format_command(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def resolve_xert_activity_path(
    activity: dict[str, Any] | None,
    *,
    local_timezone: Any,
    xert_activities: dict[str, Any] | None = None,
) -> str | None:
    if not activity or not activity.get("start_local"):
        return None
    start_local = parse_local_datetime(
        str(activity["start_local"]),
        local_timezone=local_timezone,
    )
    activities = (xert_activities or {}).get("activities")
    if not isinstance(activities, list):
        return None
    candidates = []
    for candidate in activities:
        if not isinstance(candidate, dict) or not candidate.get("path"):
            continue
        candidate_start = xert_activity_start_local(
            candidate,
            local_timezone=local_timezone,
        )
        if candidate_start is None:
            continue
        delta = abs((candidate_start - start_local).total_seconds())
        candidates.append((delta, str(candidate["path"])))
    if not candidates:
        return None
    delta, path = min(candidates, key=lambda item: item[0])
    if delta <= 30 * 60:
        return path
    return None


def enrich_route_packet_with_xert_maps(
    route_packet: dict[str, Any],
    *,
    xert_activities: dict[str, Any] | None = None,
    local_timezone: Any,
    limit: int | None = None,
) -> dict[str, Any]:
    """Attach Xert activity/map URLs to route recommendations when they match."""

    recommendations = route_packet.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        return route_packet

    activity_rows = (xert_activities or {}).get("activities")
    if not isinstance(activity_rows, list):
        activity_rows = []
    xert_by_date: dict[str, list[dict[str, Any]]] = {}
    for row in activity_rows:
        if not isinstance(row, dict):
            continue
        start = xert_activity_start_local(row, local_timezone=local_timezone)
        if start is not None:
            xert_by_date.setdefault(start.date().isoformat(), []).append(row)
    enriched = []
    for index, route in enumerate(recommendations, start=1):
        if not isinstance(route, dict):
            enriched.append(route)
            continue
        if limit is not None and index > limit:
            enriched.append(route)
            continue
        route_date = str(route.get("date") or "")
        match = match_xert_activity_for_route(route, xert_by_date.get(route_date) or [])
        route = dict(route)
        if match:
            route["xert_path"] = match.get("path")
            route["xert_activity_url"] = xert_activity_url(match.get("path"))
            route["xert_map_url"] = match.get("map_url")
            route["xert_map_source"] = "xert_activity_map_url"
        enriched.append(route)

    packet = dict(route_packet)
    packet["recommendations"] = enriched
    packet["xert_route_maps"] = {
        "source": "xert_plugin_activities",
        "meaning": (
            "Xert activity list rows can include map_url, a ready-made map image "
            "for the activity. Attach xert_map_url when proposing an outdoor route."
        ),
        "matched_count": sum(1 for route in enriched if isinstance(route, dict) and route.get("xert_map_url")),
        "scope": "all" if limit is None else f"top_{limit}",
    }
    return packet


def annotate_route_map_status(
    route_packet: dict[str, Any],
    *,
    map_scope: str,
) -> dict[str, Any]:
    """Distinguish unrequested route maps from requested-but-missing maps."""

    packet = dict(route_packet)
    recommendations = packet.get("recommendations")
    routes = recommendations if isinstance(recommendations, list) else []
    available = any(
        isinstance(route, dict)
        and bool(route.get("xert_map_local_path") or route.get("xert_map_url"))
        for route in routes
    )
    status = (
        "not_requested"
        if map_scope == "none"
        else "available"
        if available
        else "requested_but_unavailable"
    )
    route_map_status = {
        "status": status,
        "map_scope": map_scope,
    }
    packet["route_map_status"] = route_map_status
    packet["recommendations"] = [
        {**route, "route_map_status": route_map_status}
        if isinstance(route, dict)
        else route
        for route in routes
    ]
    return packet


def cache_xert_route_map_images(
    route_packet: dict[str, Any],
    *,
    output_dir: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    """Download matched Xert route maps so local chat surfaces can embed them."""

    recommendations = route_packet.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        return route_packet

    maps_dir = output_dir / "maps"
    enriched: list[Any] = []
    local_images: list[dict[str, Any]] = []
    for index, route in enumerate(recommendations, start=1):
        if not isinstance(route, dict):
            enriched.append(route)
            continue
        route = dict(route)
        if limit is not None and index > limit:
            enriched.append(route)
            continue
        map_url = str(route.get("xert_map_url") or "")
        if not map_url:
            enriched.append(route)
            continue
        filename = xert_map_filename(route, index=index, map_url=map_url)
        destination = maps_dir / filename
        result = download_xert_map_image(map_url, destination)
        if result.get("local_path"):
            route["xert_map_local_path"] = result["local_path"]
            route["xert_map_local_path_meaning"] = (
                "Local PNG copy of xert_map_url for chat surfaces that cannot "
                "reliably render external Markdown images."
            )
        elif result.get("error"):
            route["xert_map_local_error"] = result["error"]
        local_images.append(
            {
                "route_id": route.get("id"),
                "route_name": route.get("name"),
                "xert_map_url": map_url,
                **result,
            }
        )
        enriched.append(route)

    packet = dict(route_packet)
    packet["recommendations"] = enriched
    route_maps = dict(packet.get("xert_route_maps") or {})
    route_maps["local_image_count"] = sum(1 for image in local_images if image.get("local_path"))
    route_maps["local_images"] = local_images
    route_maps["local_image_meaning"] = (
        "Use xert_map_local_path for Codex/app Markdown image embeds when present; "
        "fall back to xert_map_url as a link or browser image."
    )
    packet["xert_route_maps"] = route_maps
    return packet


def xert_map_filename(route: dict[str, Any], *, index: int, map_url: str) -> str:
    parsed = urllib.parse.urlparse(map_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    route_id = safe_filename_part(str(route.get("id") or f"route-{index}"))
    route_name = safe_filename_part(str(route.get("name") or "xert-map"))[:48]
    route_date = safe_filename_part(str(route.get("date") or "unknown-date"))
    return f"{route_date}-{route_id}-{route_name}{suffix}"


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned or "unknown"


def download_xert_map_image(map_url: str, destination: Path) -> dict[str, Any]:
    if destination.exists() and destination.stat().st_size > 0:
        return {"local_path": str(destination.resolve()), "status": "cached"}
    request = urllib.request.Request(
        map_url,
        headers={"User-Agent": "training-ai-recommend-training/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
    except OSError as exc:
        return {"error": f"download_failed: {exc}", "status": "failed"}
    if not data:
        return {"error": "download_failed: empty response", "status": "failed"}
    if not is_supported_image_payload(data, content_type=content_type):
        return {
            "error": f"download_failed: unexpected content type {content_type or 'unknown'}",
            "status": "failed",
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return {
        "local_path": str(destination.resolve()),
        "status": "downloaded",
        "bytes": len(data),
        "content_type": content_type,
    }


def is_supported_image_payload(data: bytes, *, content_type: str) -> bool:
    content_type = content_type.lower()
    if content_type.startswith("image/"):
        return True
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    )


def match_xert_activity_for_route(
    route: dict[str, Any],
    activities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    route_name = normalize_route_name(str(route.get("name") or ""))
    route_distance = number(route.get("distance_km"))
    candidates: list[tuple[float, dict[str, Any]]] = []
    for activity in activities:
        path = activity.get("path")
        if not path:
            continue
        name = normalize_route_name(str(activity.get("name") or ""))
        distance = number(activity.get("distance"))
        name_penalty = 0.0 if route_name and route_name == name else 10.0
        distance_delta = abs(distance - route_distance) if distance is not None and route_distance is not None else 5.0
        if name_penalty and distance_delta > 0.75:
            continue
        candidates.append((name_penalty + distance_delta, activity))
    if not candidates:
        return None
    score, match = min(candidates, key=lambda item: item[0])
    if score <= 10.75:
        return match
    return None


def normalize_route_name(name: str) -> str:
    name = re.sub(r"\s+-\s+xert.*$", "", name.lower())
    name = re.sub(r"\s+landeveissykling$", "", name)
    return re.sub(r"\s+", " ", name).strip()


def xert_activity_url(path: Any) -> str | None:
    if not path:
        return None
    return f"https://www.xertonline.com/activity/{path}"


def xert_activity_start_local(
    activity: dict[str, Any],
    *,
    local_timezone: Any,
) -> datetime | None:
    start_date = activity.get("start_date")
    raw = None
    if isinstance(start_date, dict):
        raw = start_date.get("date")
    elif isinstance(start_date, str):
        raw = start_date
    if not raw:
        return None
    parsed = datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(local_timezone)


def parse_local_datetime(raw: str, *, local_timezone: Any) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(local_timezone)


def parse_optional_local_datetime(
    raw: Any,
    *,
    local_timezone: Any,
) -> datetime | None:
    if not raw:
        return None
    try:
        return parse_local_datetime(str(raw), local_timezone=local_timezone)
    except ValueError:
        return None


def first_recommendation(route_packet: dict[str, Any]) -> dict[str, Any] | None:
    recommendations = route_packet.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        first = recommendations[0]
        if isinstance(first, dict):
            return first
    return None


def load_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compact_xert_activity_load(
    activity: dict[str, Any],
    detail: dict[str, Any],
    *,
    local_timezone: Any,
) -> dict[str, Any]:
    summary = detail.get("summary") if isinstance(detail, dict) else {}
    progression = (summary or {}).get("progression") or {}
    xss = (progression.get("xss") or {}).get("total")
    if xss is None:
        xss = (summary or {}).get("xss")
    raw_start = (summary or {}).get("start_date") or activity.get("start_date")
    return {
        "path": activity.get("path") or (summary or {}).get("path"),
        "name": (summary or {}).get("name") or activity.get("name"),
        "start_local": xert_start_local(
            raw_start,
            local_timezone=local_timezone,
        ),
        "start_utc": xert_start_utc(
            raw_start,
            local_timezone=local_timezone,
        ),
        "distance_km": number((summary or {}).get("distance") or activity.get("distance")),
        "duration_minutes": minutes_from_seconds(number((summary or {}).get("duration"))),
        "xss": number(xss),
        "low_xss": number((summary or {}).get("xlss") or (progression.get("xss") or {}).get("xlss")),
        "high_xss": number((summary or {}).get("xhss") or (progression.get("xss") or {}).get("xhss")),
        "peak_xss": number((summary or {}).get("xpss") or (progression.get("xss") or {}).get("xpss")),
        "difficulty": number((summary or {}).get("difficulty")),
    }


def xert_start_local(raw: Any, *, local_timezone: Any) -> str | None:
    parsed = xert_start_datetime(raw)
    return (
        format_local(parsed, local_timezone=local_timezone)
        if parsed is not None
        else None
    )


def xert_start_utc(raw: Any, *, local_timezone: Any) -> str | None:
    parsed = xert_start_datetime(raw)
    return (
        format_utc(parsed, local_timezone=local_timezone)
        if parsed is not None
        else None
    )


def xert_start_datetime(raw: Any) -> datetime | None:
    value = raw.get("date") if isinstance(raw, dict) else raw
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def xert_load_windows(payload: dict[str, Any] | None, *, cutoff: datetime, local_timezone: Any) -> dict[str, Any]:
    """Native elapsed duration and strain for completed days and today's rolling week."""
    if not payload:
        return {}
    activities = payload.get("activities")
    if not isinstance(activities, list):
        return {}
    if (
        payload.get("filters") != []
        or payload.get("limit", False) is not None
        or any(
            type(payload.get(key)) is not int or payload[key] != len(activities)
            for key in ("source_count", "matched_count", "count")
        )
    ):
        return {}
    try:
        first = date.fromisoformat(payload["start_date"])
        last = date.fromisoformat(payload["end_date"])
    except (KeyError, TypeError, ValueError):
        return {}
    today = cutoff.astimezone(local_timezone).date()
    windows = {}
    yesterday = today - timedelta(days=1)
    periods = [(n, yesterday) for n in (3, 7, 14, 21)]
    for days, end in [(7, today), *periods]:
        start = end - timedelta(days=days - 1)
        if first > start or last < end:
            continue
        seconds_total = 0.0
        xss_total = 0.0
        count = 0
        for row in activities:
            if not isinstance(row, dict) or len(str(row.get("start_local") or "")) <= 10:
                break
            timestamp = parse_optional_local_datetime(row.get("start_local"), local_timezone=local_timezone)
            if timestamp is None:
                break
            if not start <= timestamp.date() <= end or timestamp >= cutoff:
                continue
            seconds = number(row.get("duration_s"))
            load = xert_total_xss(row)
            if seconds is None or not 0 < seconds < math.inf or load is None or not 0 <= load < math.inf:
                break
            if not completed_activity_start(None, row["start_local"], seconds, cutoff=cutoff,
                                            local_timezone=local_timezone):
                continue
            seconds_total += seconds
            xss_total += load
            count += 1
        else:
            key = "week_including_today" if end == today else f"completed_{days}d"
            windows[key] = {"start_date": start.isoformat(), "end_date": end.isoformat(),
                            "activity_count": count, "elapsed_hours": round(seconds_total / 3600, 2),
                            "weekly_equivalent_elapsed_hours": round(seconds_total * 7 / (3600 * days), 2),
                            "xss": round(xss_total, 1)}
    return windows


def verified_moving_time_history(activity_list: dict, *, workout_date: date, cutoff: datetime) -> dict:
    """Summarize completed work before the workout day and within its projection windows."""
    end = min(workout_date - timedelta(days=1), cutoff.date())
    first = end - timedelta(days=20)
    rows = activity_list["activities"]
    try:
        fetched_start = date.fromisoformat(activity_list["start_date"])
        fetched_end = date.fromisoformat(activity_list["end_date"])
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError("Keep the inclusive start_date and end_date returned by list_activities.") from exc
    fields = {"moving_time", "icu_ignore_time", "duration_s"}
    if (fetched_start > first or fetched_end < cutoff.date()
            or activity_list.get("filters") or activity_list.get("limit") is not None
            or activity_list.get("source_limited")
            or any(activity_list.get(key, len(rows)) != len(rows)
                   for key in ("source_count", "matched_count", "count"))
            or not fields.issubset(activity_list.get("includeFields", []))):
        raise ValueError(f"Fetch the complete unfiltered Intervals.icu activity list from {first} to {cutoff.date()} "
                         "inclusive with moving_time, duration_s and icu_ignore_time.")
    completed = []
    for row in rows:
        if row.get("icu_ignore_time"):
            continue
        stamp = row.get("start_date_local")
        if not isinstance(stamp, str) or len(stamp) <= 10:
            raise ValueError(f"Missing Intervals.icu start time for {row.get('id')}")
        start = parse_local_datetime(stamp, local_timezone=cutoff.tzinfo)
        day = start.date()
        if not first <= day <= cutoff.date():
            continue
        seconds = row.get("moving_time")
        if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"Missing or invalid Intervals.icu moving_time for {row.get('id')}")
        if seconds == 0:
            continue
        elapsed = row.get("duration_s")
        if type(elapsed) not in (float, int) or not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError(f"Missing or invalid Intervals.icu duration_s for {row.get('id')}")
        seconds_to_cutoff = (cutoff.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()
        if elapsed <= seconds_to_cutoff:
            completed.append((day, seconds))

    history = {"completed_moving_time": []}
    for days in (14, 21):
        start = end - timedelta(days=days - 1)
        seconds = sum(moving for day, moving in completed if start <= day <= end)
        history["completed_moving_time"].append({
            "days": days, "start_date": start.isoformat(), "end_date": end.isoformat(),
            "moving_seconds": seconds, "weekly_equivalent_hours": round(seconds * 7 / (3600 * days), 1),
        })
        rolling_start = workout_date - timedelta(days=days - 1)
        rolling = [moving for day, moving in completed if rolling_start <= day <= workout_date]
        hours = sum(rolling) / 3600
        history[f"rolling_{days}d"] = {
            "start_date": rolling_start.isoformat(), "end_date": workout_date.isoformat(),
            "activity_count": len(rolling), "moving_hours": hours,
            "weekly_equivalent_hours": round(hours * 7 / days, 1), "coverage": "intervals_activity_volume",
        }
    return history


def training_history_context(
    day: str,
    *,
    cutoff: datetime,
    artifacts_dir: Path,
    xert_activity_loads: dict[str, Any] | None,
    local_timezone: Any,
) -> dict[str, Any]:
    activities_dir = artifacts_dir / "activities"
    target_day = date.fromisoformat(day)
    xert_loads = [
        row for row in xert_load_index(xert_activity_loads)
        if completed_activity_start(row.get("start_utc"), row.get("start_local"),
                                    number(row.get("duration_s")) or (number(row.get("elapsed_minutes")) or 0) * 60,
                                    cutoff=cutoff, local_timezone=local_timezone) is not None
    ]
    rows: list[dict[str, Any]] = []
    duration_rows: list[dict[str, Any]] = []
    if activities_dir.exists():
        for metadata_path in activities_dir.glob("*/activity.json"):
            metadata = load_json_if_exists(metadata_path)
            if not isinstance(metadata, dict):
                continue
            metadata = metadata.get("activity", metadata)
            start = completed_activity_start(metadata.get("start_date"), metadata.get("start_date_local"),
                                             metadata.get("elapsed_time"), cutoff=cutoff,
                                             local_timezone=local_timezone)
            if start is None:
                continue
            activity_day = start.date()
            if activity_day > target_day:
                continue
            elapsed_seconds = number(metadata.get("elapsed_time")) or number(metadata.get("moving_time"))
            moving_seconds = number(metadata.get("moving_time")) or elapsed_seconds
            duration_rows.append(
                {
                    "date": activity_day,
                    "elapsed_minutes": (elapsed_seconds or 0.0) / 60,
                    "moving_minutes": (moving_seconds or 0.0) / 60,
                    "type": metadata.get("type"),
                    "name": metadata.get("name"),
                    "id": metadata.get("id"),
                }
            )
            load = activity_xss_from_metadata(metadata)
            if load is None:
                load = matched_xert_xss(
                    metadata,
                    xert_loads,
                    local_timezone=local_timezone,
                )
            if load is None:
                continue
            rows.append(
                {
                    "date": activity_day,
                    "load": load,
                    "elapsed_minutes": (elapsed_seconds or 0.0) / 60,
                    "moving_minutes": (moving_seconds or 0.0) / 60,
                    "type": metadata.get("type"),
                    "name": metadata.get("name"),
                    "id": metadata.get("id"),
                }
            )

    window_start = target_day - timedelta(days=6)
    current_rows = [row for row in rows if window_start <= row["date"] <= target_day]
    current_load = sum(row["load"] for row in current_rows)
    current_minutes = sum(row["moving_minutes"] for row in current_rows)
    current_count = len(current_rows)
    rolling_duration = {}
    for days in (14, 21):
        start = target_day - timedelta(days=days - 1)
        minutes = sum(
            row["moving_minutes"]
            for row in duration_rows
            if start <= row["date"] <= target_day
        )
        rolling_duration[f"rolling_{days}d"] = {
            "start_date": start.isoformat(),
            "end_date": target_day.isoformat(),
            "moving_hours": round(minutes / 60.0, 1),
            "weekly_equivalent_hours": round(minutes / 60.0 / days * 7.0, 1),
            "activity_count": sum(1 for row in duration_rows if start <= row["date"] <= target_day),
            "coverage": "local_recorded_activities_only",
        }

    xss_history_start = min((row["date"] for row in rows), default=None)
    xss_history_end = max((row["date"] for row in rows), default=None)
    daily_duration_totals: dict[date, dict[str, float]] = {}
    for row in duration_rows:
        if row["date"].year != target_day.year:
            continue
        total = daily_duration_totals.setdefault(row["date"], {"moving_minutes": 0.0})
        total["moving_minutes"] += row["moving_minutes"]
    baseline_days = [
        total
        for total in daily_duration_totals.values()
        if 45 <= total["moving_minutes"] <= 240
    ]
    baseline_minutes = [day_total["moving_minutes"] for day_total in baseline_days]
    xss_per_min_values = [
        row["load"] / row["moving_minutes"]
        for row in rows
        if row["moving_minutes"] >= 30 and row["load"] > 0
    ]
    xss_per_min = median(xss_per_min_values)

    return {
        "source": "local_intervals_activity_artifacts",
        "xert_load_windows": xert_load_windows(xert_activity_loads, cutoff=cutoff, local_timezone=local_timezone),
        "completed_by": cutoff.isoformat(),
        "load_source": "xert_xss",
        "artifacts_dir": str(artifacts_dir),
        "rolling_7d": {
            "start_date": window_start.isoformat(),
            "end_date": target_day.isoformat(),
            "activity_count": current_count,
            "xss": round(current_load, 1),
            "training_load": round(current_load, 1),
            "moving_hours": round(current_minutes / 60, 1),
            "xss_percentile": None,
            "percentile_status": "insufficient_history",
            "percentile_meaning": (
                "The recent Xert activity-load fetch is suitable for the current "
                "seven-day XSS total, but not for a historical percentile."
            ),
            "xss_history_start": xss_history_start.isoformat() if xss_history_start else None,
            "xss_history_end": xss_history_end.isoformat() if xss_history_end else None,
        },
        **rolling_duration,
        "typical_training_day_baseline": {
            "day_count": len(baseline_days),
            "selection": (
                "target-year calendar days aggregated across all saved activities, "
                "with daily total 45-240 min. Duration baseline is independent "
                "of Intervals/Garmin TL."
            ),
            "median_minutes": median(baseline_minutes),
            "mean_minutes": rounded_mean(baseline_minutes),
            "xss_per_min_from_available_xert_window": xss_per_min,
            "xss_match_count": len(xss_per_min_values),
        },
        "activity_history_count": len(duration_rows),
        "xss_activity_match_count": len(rows),
        "meaning": (
            "Rolling volume and typical training days describe overall load. Choose VT1 duration "
            "using reviewed rides of the same aerobic role and their response. Typical-day "
            "baseline aggregates multiple activities on the same calendar day "
            "before taking median/mean."
        ),
    }


def annotate_volume_density(
    target_resolution: dict[str, Any],
    *,
    history_context: dict[str, Any],
) -> None:
    """Describe recorded volume with its available coverage."""
    planned_hours = (number(target_resolution.get("target_minutes")) or 0.0) / 60.0
    native_week = (history_context.get("xert_load_windows") or {}).get("week_including_today")
    composition = target_resolution.get("dose_composition") or {}
    solution = target_resolution.get("endurance_duration_solution") or {}
    if composition:
        prescription = composition.get("estimated_total") or {}
        minutes = number(prescription.get("duration_minutes"))
        session_xss = number(prescription.get("xss"))
    else:
        minutes = number(solution.get("duration_minutes"))
        session_xss = number((solution.get("achieved_xss") or {}).get("total"))
    target_date = (history_context.get("rolling_7d") or {}).get("end_date")
    if native_week and native_week["end_date"] == target_date and minutes is not None and session_xss is not None:
        target_resolution["week_if_full_remaining_session_ridden_today"] = {
            "start_date": native_week["start_date"], "end_date": native_week["end_date"],
            "session_minutes": minutes, "session_xss": round(session_xss, 1),
            "elapsed_hours": round(native_week["elapsed_hours"] + minutes / 60, 2),
            "xss": round(native_week["xss"] + session_xss, 1),
        }
    windows = []
    for days in (14, 21):
        history = history_context.get(f"rolling_{days}d") or {}
        prior_hours = number(history.get("moving_hours"))
        if history.get("activity_count") == 0 and history.get("coverage") != "intervals_activity_volume":
            prior_hours = None
        projected_hours = prior_hours + planned_hours if prior_hours is not None else None
        windows.append({
            "days": days,
            "prior_moving_hours": prior_hours,
            "planned_hours": round(planned_hours, 1),
            "projected_moving_hours": round(projected_hours, 1) if projected_hours is not None else None,
            "projected_weekly_equivalent_hours": (
                round(projected_hours / days * 7, 1) if projected_hours is not None else None
            ),
            "coverage": history.get("coverage", "local_recorded_activities_only") if prior_hours is not None else "unavailable",
        })
    has_history = any(row["prior_moving_hours"] is not None for row in windows)
    target_resolution["volume_density"] = {
        "classification": "recorded_volume_only" if has_history else "unavailable",
        "windows": windows,
        "dose_is_automatically_capped": False,
        "meaning": (
            "Coverage is reported for each window. Missing history leaves volume unknown. "
            "Compare with the athlete's reviewed plan."
        ),
    }


def percentile_rank(value: float, values: list[float]) -> float | None:
    if not values:
        return None
    at_or_below = sum(1 for item in values if item <= value)
    return round(at_or_below / len(values) * 100, 1)


def activity_xss_from_metadata(metadata: dict[str, Any]) -> float | None:
    for path in (
        ("xert_load", "xss", "total"),
        ("xert", "xss"),
        ("xss",),
    ):
        value: Any = metadata
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        parsed = number(value)
        if parsed is not None:
            return parsed
    return None


def xert_load_index(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    activities = (payload or {}).get("activities")
    if not isinstance(activities, list):
        return []
    rows = []
    for row in activities:
        if not isinstance(row, dict):
            continue
        xss = xert_total_xss(row)
        if xss is None:
            continue
        normalized = dict(row)
        normalized["xss_total"] = xss
        rows.append(normalized)
    return rows


def xert_total_xss(row: dict[str, Any]) -> float | None:
    xss = row.get("xss")
    if isinstance(xss, dict):
        return number(xss.get("total"))
    return number(xss)


def matched_xert_xss(
    metadata: dict[str, Any],
    xert_loads: list[dict[str, Any]],
    *,
    local_timezone: Any,
) -> float | None:
    if not xert_loads:
        return None
    start = parse_optional_local_datetime(
        metadata.get("start_date_local"),
        local_timezone=local_timezone,
    )
    name = normalize_activity_name(str(metadata.get("name") or ""))
    distance_km = None
    distance_m = number(metadata.get("distance")) or number(metadata.get("icu_distance"))
    if distance_m is not None:
        distance_km = distance_m / 1000
    candidates: list[tuple[float, float]] = []
    for row in xert_loads:
        row_start = parse_optional_local_datetime(
            row.get("start_local"),
            local_timezone=local_timezone,
        )
        if start is None or row_start is None or start.date() != row_start.date():
            continue
        delta_minutes = abs((row_start - start).total_seconds()) / 60
        row_name = normalize_activity_name(str(row.get("name") or ""))
        name_penalty = 0 if row_name == name else 20
        row_distance = number(row.get("distance_km"))
        distance_penalty = abs(row_distance - distance_km) if row_distance is not None and distance_km is not None else 2
        score = delta_minutes + name_penalty + distance_penalty
        xss = xert_total_xss(row)
        if xss is not None:
            candidates.append((score, xss))
    if not candidates:
        return None
    score, xss = min(candidates, key=lambda item: item[0])
    return xss if score <= 45 else None


def normalize_activity_name(name: str) -> str:
    name = re.sub(r"\s+-\s+xert.*$", "", name.lower())
    name = re.sub(r"\s+landeveissykling$", "", name)
    return re.sub(r"\s+", " ", name).strip()


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 1)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 1)


def rounded_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def resolve_training_targets(
    *,
    selection: dict[str, Any] | None,
    readiness_packet: dict[str, Any],
    history_context: dict[str, Any],
) -> dict[str, Any]:
    inputs = readiness_packet.get("recommendation_inputs") or {}
    xert_training_advice = inputs.get("xert_training_advice") or {}
    xert_remaining_xss = xert_training_advice.get("remaining_xss") or {}
    remaining_parts = {
        key: number(xert_remaining_xss.get(key))
        for key in ("low", "high", "peak")
        if number(xert_remaining_xss.get(key)) is not None
    }
    xert_target_xss = xert_training_advice.get("target_xss") or {}
    target_parts = {
        key: number(xert_target_xss.get(key))
        for key in ("low", "high", "peak")
        if number(xert_target_xss.get(key)) is not None
    }
    xert_original_xss = xert_training_advice.get("original_target_xss") or {}
    original_parts = {
        key: number(xert_original_xss.get(key))
        for key in ("low", "high", "peak")
        if number(xert_original_xss.get(key)) is not None
    }
    xert_completed_xss = xert_training_advice.get("completed_xss") or {}
    completed_parts = {
        key: number(xert_completed_xss.get(key))
        for key in ("low", "high", "peak")
        if number(xert_completed_xss.get(key)) is not None
    }
    xert_load_basis = "remaining_xss" if remaining_parts else "target_xss"
    xert_load_parts = {
        **(remaining_parts or target_parts)
    }
    xert_recommended_total_xss = (
        sum(xert_load_parts.values()) if xert_load_parts else None
    )
    xert_planning_context = {
        key: xert_training_advice.get(key)
        for key in (
            "xss_deficit",
            "xss_goal",
            "availability",
            "is_availability_restricted",
            "targets_source",
            "based_on_day",
            "improvement_rate",
            "weekly_hours",
            "training_gradient",
            "phase",
            "recommended_athlete",
        )
        if xert_training_advice.get(key) is not None
    }
    if xert_planning_context or xert_load_parts:
        xert_planning_context["interpretation"] = (
            "Xert target/remaining XSS is an adaptive planning and progression dose. "
            "It is not total physiological need, maximum absorbable load, or the "
            "source of the workout's intensity role."
        )

    if selection is None:
        raise SystemExit("Dose requires assessment: supply --training-target-json with a coach-selected dose, reason and evidence. Xert advice is comparison data only.")
    selection = parse_training_target_json(json.dumps(selection))
    return {
        "source": "explicit_coaching_selection",
        "target_minutes": selection["minutes"],
        "target_load": selection["load"],
        "selected_low_xss": selection.get("low_xss"),
        "coaching_selection": selection,
        "endurance_extension": selection.get("endurance_extension"),
        "capacity_decision": selection.get("capacity_decision"),
        "xert_recommended_target_xss": xert_load_parts or None,
        "xert_recommended_total_xss": rounded_number(xert_recommended_total_xss),
        "xert_dose_basis": xert_load_basis,
        "xert_original_target_xss": original_parts or target_parts or None,
        "xert_completed_xss": completed_parts or None,
        "xert_planning_context": xert_planning_context,
        "difference_from_xert_xss": round(selection["load"] - xert_recommended_total_xss, 1) if xert_recommended_total_xss is not None else None,
        "reason": selection["reason"],
        "evidence": selection["evidence"],
        "meaning": "Coach-selected dose. Xert advice and capacity are model comparisons, not automatic targets or limits.",
    }


def apply_quality_workout_vt1_composition(
    target_resolution: dict[str, Any],
    *,
    quality_calculation: dict[str, Any],
    selected_intensity: str,
    quality_workout_status: str = "planned",
) -> dict[str, Any]:
    """Compose calculated quality with an Xert-solved adjustable VT1 segment."""

    if quality_workout_status not in {"planned", "completed"}:
        raise ValueError("quality_workout_status must be planned or completed")
    if (
        quality_workout_status == "planned"
        and selected_intensity not in {"vt2", "vo2max", "sprint", "mixed"}
    ):
        raise SystemExit(
            "A quality-workout calculation was supplied, but the selected "
            f"intensity is {selected_intensity or 'missing'}."
        )
    result = quality_calculation.get("result") or {}
    stats = result.get("stats") if isinstance(result, dict) else None
    if not isinstance(stats, dict):
        stats = quality_calculation.get("stats")
    compact_summary = quality_calculation.get("source") == "xert_workout_calculate"
    if not isinstance(stats, dict) and compact_summary:
        stats = {
            "duration_minutes": quality_calculation.get("duration_minutes"),
            "xss": quality_calculation.get("xss"),
            "xlss": quality_calculation.get("low_xss"),
            "xhss": quality_calculation.get("high_xss"),
            "xpss": quality_calculation.get("peak_xss"),
        }
    if not isinstance(stats, dict):
        raise SystemExit(
            "Xert quality-workout calculation has no result.stats object."
        )

    quality_xss = number(stats.get("xss"))
    quality_minutes = (
        number(stats.get("duration_minutes"))
        if compact_summary
        else xert_calculation_duration_minutes(stats.get("duration"))
    )
    if quality_xss is None or quality_minutes is None:
        raise SystemExit(
            "Xert quality-workout calculation must contain numeric XSS and duration."
        )

    target_xss = number(target_resolution.get("target_load"))
    if target_xss is None:
        raise ValueError("target_resolution has no numeric target_load")

    quality_xss_counted_in_remaining_plan = quality_workout_status == "planned"
    extension = target_resolution.get("endurance_extension")
    required_filler_xss = (
        max(0.0, target_xss - quality_xss)
        if quality_xss_counted_in_remaining_plan
        else target_xss
    ) if extension else 0.0
    solution = target_resolution.get("endurance_duration_solution")
    if required_filler_xss > 0 and not isinstance(solution, dict):
        raise SystemExit(
            "A quality workout with VT1 filler requires --endurance-workout-json "
            "from Xert solve_segment_duration for the complete structure."
        )
    solution = (solution or {}) if required_filler_xss > 0 else {}
    solution_xss = solution.get("achieved_xss") or {}
    if required_filler_xss > 0 and quality_xss_counted_in_remaining_plan:
        segments = solution.get("segments")
        adjustable_index = solution.get("adjustable_segment_index")
        duration_seconds = number(solution.get("duration_seconds"))
        adjustable_seconds = number(solution.get("adjustable_duration_seconds"))
        signature = solution.get("signature") or {}
        tp = number(signature.get("tp"))
        if (
            not isinstance(segments, list)
            or not segments
            or isinstance(adjustable_index, bool)
            or not isinstance(adjustable_index, int)
            or not 0 <= adjustable_index < len(segments)
            or duration_seconds is None
            or adjustable_seconds is None
            or tp is None
        ):
            raise ValueError(
                "quality VT1 solver result must include its signature, segments, "
                "valid adjustable_segment_index, and exact durations"
            )
        adjustable_segment = segments[adjustable_index]
        if not isinstance(adjustable_segment, dict):
            raise ValueError("quality VT1 adjustable segment must be an object")
        adjustable_power = number(adjustable_segment.get("power"))
        adjustable_end_power = number(adjustable_segment.get("end_power"))
        if (
            adjustable_power is None
            or adjustable_power >= tp
            or (adjustable_end_power is not None and adjustable_end_power >= tp)
        ):
            raise ValueError("quality VT1 adjustable segment must remain below TP")
        segment_durations = [
            number(segment.get("duration_seconds"))
            if isinstance(segment, dict)
            else None
            for segment in segments
        ]
        if any(value is None or value < 0 for value in segment_durations):
            raise ValueError("quality VT1 solver segments require valid durations")
        segment_seconds = sum(float(value) for value in segment_durations)
        if abs(segment_seconds - duration_seconds) > 1.0:
            raise ValueError("quality VT1 solver segment durations do not match total duration")
        if abs((duration_seconds - adjustable_seconds) - quality_minutes * 60.0) > 1.0:
            raise ValueError(
                "quality VT1 solver fixed duration does not match the calculated "
                "quality workout"
            )
    composed_minutes = (
        number(solution.get("duration_minutes"))
        if required_filler_xss > 0
        else quality_minutes if quality_xss_counted_in_remaining_plan else 0.0
    )
    estimated_total_xss = (
        number(solution_xss.get("total"))
        if required_filler_xss > 0
        else quality_xss if quality_xss_counted_in_remaining_plan else 0.0
    )
    filler_minutes = number(solution.get(
        "adjustable_duration_minutes"
        if quality_xss_counted_in_remaining_plan
        else "duration_minutes"
    )) or 0.0
    filler_xss = (
        max(0.0, (number(solution_xss.get("low")) or 0.0) - (number(stats.get("xlss")) or 0.0))
        if quality_xss_counted_in_remaining_plan
        else number(solution_xss.get("low")) or 0.0
    )
    original_target_minutes = number(target_resolution.get("target_minutes"))

    composition = {
        "method": "xert_calculated_quality_plus_explicit_extension" if required_filler_xss > 0 else "quality_only",
        "selected_intensity": selected_intensity,
        "quality_workout_status": quality_workout_status,
        "daily_target_xss": round(target_xss, 1),
        "quality_base": {
            "calculation_binding": quality_calculation.get("calculation_binding"),
            "canonical_structure": quality_calculation.get("canonical_structure"),
            "source": "xert_workout_calculate",
            "status": quality_workout_status,
            "counted_in_remaining_plan": quality_xss_counted_in_remaining_plan,
            "includes": [
                "warmup",
                "work_intervals",
                "recoveries",
                "cooldown",
            ],
            "duration_minutes": round(quality_minutes, 1),
            "xss": round(quality_xss, 1),
            "low_xss": rounded_number(stats.get("xlss")),
            "high_xss": rounded_number(stats.get("xhss")),
            "peak_xss": rounded_number(stats.get("xpss")),
        },
        "vt1_filler": {
            "xss": round(filler_xss, 1),
            "duration_minutes": round(filler_minutes, 1),
            "source": solution.get("source"),
            "execution": (
                "Follow the canonical solver timeline for segment order. Quality "
                "and filler totals are accounting groups; warm-up and cool-down "
                "already occur in that timeline and must not be added again."
            ),
        },
        "estimated_total": {
            "duration_minutes": round(composed_minutes, 1),
            "xss": round(estimated_total_xss, 1),
        },
        "pre_composition_target_minutes": (
            round(original_target_minutes, 1)
            if original_target_minutes is not None
            else None
        ),
    }
    target_resolution["dose_composition"] = composition
    target_resolution["target_minutes"] = round(composed_minutes, 1)
    target_resolution["target_load"] = round(estimated_total_xss, 1)
    target_resolution["duration_source"] = (
        "Complete calculated quality and explicitly selected endurance addition"
    )
    target_resolution["reason"] = (
        f"{target_resolution.get('reason') or ''}; complete quality workout "
        f"calculated by Xert ({round(quality_xss, 1)} XSS) and "
        f"{'combined with' if quality_xss_counted_in_remaining_plan else 'already completed, not subtracted again from'} "
        f"{round(filler_xss, 1)} low XSS in explicitly selected endurance addition"
    ).strip("; ")

    final_plan = (target_resolution.get("plan_trace") or {}).get("final_plan")
    if isinstance(final_plan, dict):
        final_plan["minutes"] = round(composed_minutes, 1)
        final_plan["load_xss"] = round(estimated_total_xss, 1)
        final_plan["dose_composition"] = composition
    return composition


def apply_xert_endurance_duration_solution(
    target_resolution: dict[str, Any],
    *,
    calculation: dict[str, Any],
    selected_intensity: str,
) -> dict[str, Any]:
    """Apply an Xert-solved endurance duration instead of mixed-history XSS/min."""

    if calculation.get("canonical_structure") and not calculation.get("calculation_binding"):
        calculation = bind_workout_calculation(calculation, calculation["canonical_structure"])
    selection = target_resolution.get("coaching_selection") or {}
    if selection.get("basis") == "duration" and calculation.get("source") != "local_xert_segment_duration_solver":
        return apply_fixed_duration_calculation(target_resolution, calculation, selected_intensity)
    calculation = normalize_endurance_calculation(calculation)
    quality_domain = selected_intensity in {"vt2", "vo2max", "sprint", "mixed"}
    if selected_intensity not in {
        "vt1",
        "easy_vt1",
        "recovery",
        "active_recovery",
        "vt2",
        "vo2max",
        "sprint",
        "mixed",
    }:
        raise ValueError(
            "endurance-workout calculation requires a recovery or VT1 domain"
        )
    if calculation.get("source") != "local_xert_segment_duration_solver":
        raise ValueError(
            "endurance-workout calculation must come from Xert solve_segment_duration"
        )
    if calculation.get("network_used") is not False:
        raise ValueError("endurance-workout calculation must be offline")
    if calculation.get("matched_within_tolerance") is not True:
        raise ValueError("endurance-workout low XSS did not match within tolerance")
    if not ((calculation.get("feasibility") or {}).get("valid")):
        raise ValueError("endurance-workout calculation is not Xert-feasible")

    achieved = calculation.get("achieved_xss") or {}
    def checked_number(raw, field, *, positive=False):
        value = number(raw)
        if isinstance(raw, bool) or value is None or not math.isfinite(value) or value < 0 or (positive and value == 0):
            raise ValueError(f"endurance-workout {field} must be a finite {'positive' if positive else 'nonnegative'} number")
        return value

    achieved_low = checked_number(achieved.get("low"), "low XSS")
    achieved_high = checked_number(achieved.get("high"), "high XSS")
    achieved_peak = checked_number(achieved.get("peak"), "peak XSS")
    achieved_total = checked_number(achieved.get("total"), "total XSS")
    duration_seconds = checked_number(calculation.get("duration_seconds"), "duration", positive=True)
    target_low = checked_number(calculation.get("target_low_xss"), "target low XSS", positive=True)
    tolerance = checked_number(calculation.get("tolerance_xss", 0.05), "tolerance", positive=True)
    if abs(achieved_low - target_low) > tolerance + 1e-9:
        raise ValueError("endurance-workout achieved low XSS does not match target within tolerance")
    # Allow display rounding of components, independently of the solver's target tolerance.
    if abs(achieved_total - (achieved_low + achieved_high + achieved_peak)) > 0.2 + 1e-9:
        raise ValueError("endurance-workout XSS components do not sum to total")
    if not quality_domain and (achieved_high > 0.05 or achieved_peak > 0.05):
        raise ValueError("recovery/VT1 endurance solution must not add high/peak XSS")
    expected_low = applicable_endurance_low_xss_target(target_resolution)
    if abs(target_low - expected_low) > tolerance + 1e-9 or abs(achieved_low - expected_low) > tolerance + 1e-9:
        raise ValueError(
            "endurance-workout target_low_xss does not match the applicable "
            "coach-selected low-XSS target"
        )

    illness_cap = target_resolution.get("illness_return_guardrail") or {}
    if illness_cap.get("active") and duration_seconds > float(illness_cap["max_minutes"]) * 60 + 1:
        raise ValueError("Solved workout exceeds the reviewed illness-return duration; revise the whole workout")
    if selection.get("basis") == "duration" and abs(duration_seconds / 60 - target_resolution["target_minutes"]) > 0.02:
        raise ValueError("Solver changed the coach-selected duration; calculate the selected complete workout instead")
    previous_minutes = number(target_resolution.get("target_minutes"))
    target_resolution["pre_endurance_solution_target_minutes"] = previous_minutes
    target_resolution["target_minutes"] = round(duration_seconds / 60.0, 1)
    target_resolution["target_load"] = round(achieved_total, 1)
    target_resolution["duration_source"] = (
        "xert_solved_quality_plus_endurance_structure"
        if quality_domain
        else "xert_solved_plan_endurance_structure"
    )
    previous_position = target_resolution.get("dose_position_vs_typical")
    if previous_position is not None:
        target_resolution["pre_endurance_solution_dose_position_vs_typical"] = (
            previous_position
        )
    target_resolution["dose_position_vs_typical"] = {
        "label": "xert_solved_for_selected_domain",
        "ratio": None,
        "phrase": "duration solved for the selected endurance structure",
        "reason": (
            "Xert solve_segment_duration calculated the complete structured workout; "
            "a mixed-domain historical XSS/min rate is not used for prescription"
        ),
    }
    target_resolution["endurance_duration_solution"] = {
        "calculation_binding": calculation.get("calculation_binding"),
        "source": calculation.get("source"),
        "selected_intensity": selected_intensity,
        "signature": calculation.get("signature"),
        "target_low_xss": round(target_low, 3),
        "achieved_xss": {
            key: round(float(achieved[key]), 3)
            for key in ("total", "low", "high", "peak")
        },
        "duration_minutes": round(duration_seconds / 60.0, 1),
        "duration_seconds": round(duration_seconds),
        "adjustable_segment_index": calculation.get("adjustable_segment_index"),
        "adjustable_duration_seconds": round(
            number(calculation.get("adjustable_duration_seconds")) or 0.0
        ),
        "adjustable_duration_minutes": round(
            (number(calculation.get("adjustable_duration_seconds")) or 0.0) / 60.0,
            1,
        ),
        "segments": calculation.get("segments"),
        "difficulty": calculation.get("difficulty"),
        "model_basis": calculation.get("model_basis"),
        "low_xss_error": calculation.get("low_xss_error"),
        "tolerance_xss": tolerance,
    }
    target_resolution["reason"] = (
        f"{target_resolution.get('reason') or ''}; complete {selected_intensity} structure calculated: "
        f"{round(achieved_low, 1)} low XSS in {round(duration_seconds / 60.0, 1)} min"
    )
    return target_resolution["endurance_duration_solution"]


def apply_fixed_duration_calculation(target, calculation, selected_intensity):
    """Calculate load for an already selected complete duration; never solve a quota."""
    compact = calculation.get("source") == "xert_workout_calculate"
    stats = (calculation.get("result") or {}).get("stats") or {}
    if compact:
        minutes = number(calculation.get("duration_minutes"))
        achieved = {key: number(calculation.get(field)) for key, field in
                    (("total", "xss"), ("low", "low_xss"), ("high", "high_xss"), ("peak", "peak_xss"))}
    elif calculation.get("submit") == "calculate" and stats:
        minutes = xert_calculation_duration_minutes(stats.get("duration"))
        achieved = {key: number(stats.get(field)) for key, field in
                    (("total", "xss"), ("low", "xlss"), ("high", "xhss"), ("peak", "xpss"))}
    else:
        raise ValueError("Duration-selected workout requires a complete Xert calculate_workout result")
    if minutes is None or not math.isfinite(minutes) or abs(minutes - target["target_minutes"]) > 0.02:
        raise ValueError("Calculated workout does not match the coach-selected duration")
    if any(v is None or not math.isfinite(v) or v < 0 for v in achieved.values()) or abs(achieved["total"] - sum(achieved[k] for k in ("low", "high", "peak"))) > 0.2:
        raise ValueError("Calculated workout requires consistent finite XSS values")
    if selected_intensity in {"vt1", "easy_vt1", "recovery", "active_recovery"} and (achieved["high"] > 0.05 or achieved["peak"] > 0.05):
        raise ValueError("recovery/VT1 calculation must not add high/peak XSS")
    if abs(achieved["total"] - target["target_load"]) > 0.2:
        raise ValueError("Selected load must come from the complete duration-selected calculation")
    structure = calculation.get("canonical_structure") or {}
    segments = structure.get("segments") or []
    index = structure.get("adjustable_segment_index")
    canonical = {}
    if segments:
        durations = [number(segment.get("duration_seconds")) for segment in segments]
        if any(value is None or not math.isfinite(value) or value < 0 for value in durations) or abs(sum(durations) - minutes * 60) > 1:
            raise ValueError("Canonical structure does not match the calculated duration")
        canonical = {"segments": segments, "signature": structure.get("signature")}
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(segments):
            canonical.update(adjustable_segment_index=index,
                adjustable_duration_seconds=durations[index], adjustable_duration_minutes=durations[index]/60)
    target["target_load"] = achieved["total"]
    target["endurance_duration_solution"] = {
        "calculation_binding": calculation.get("calculation_binding"),
        **canonical,
        "source": "xert_workout_calculate", "duration_minutes": minutes,
        "duration_seconds": round(minutes * 60), "achieved_xss": achieved,
        "selected_intensity": selected_intensity,
    }
    return target["endurance_duration_solution"]


def validate_final_coaching_dose(target):
    selection = target.get("coaching_selection")
    if not selection:
        return
    # Explicit health caps can change the reviewed target, but cannot excuse a larger workout.
    guarded = any((target.get(key) or {}).get("active") for key in ("illness_return_guardrail", "readiness_domain_cap"))
    field, tolerance = ("minutes", 0.1) if selection["basis"] == "duration" else ("load", 0.2)
    actual = target[f"target_{field}"]
    if (guarded and actual > selection[field] + tolerance) or (not guarded and abs(actual - selection[field]) > tolerance):
        raise ValueError("Complete workout differs from the coach-selected dose; revise the explicit selection or workout with evidence")


def apply_recovery_protection_capacity(
    target_resolution: dict[str, Any],
    *,
    capacity: dict[str, Any],
    selected_intensity: str,
    quality_low_xss: float | None = None,
) -> dict[str, Any] | None:
    """Compare the selected workout with model capacity without modifying it."""
    normalized = validate_capacity_values(capacity)
    solution = target_resolution.get("endurance_duration_solution") or {}
    composition = target_resolution.get("dose_composition") or {}
    quality = composition.get("quality_base") or {}
    if solution and (not composition or target_resolution.get("endurance_extension")):
        actual = solution.get("achieved_xss") or {}
    elif quality and quality.get("counted_in_remaining_plan"):
        actual = {key: quality.get(f"{key}_xss") for key in normalized}
    elif selected_intensity in {"vt1", "easy_vt1", "recovery", "active_recovery", "rest"}:
        actual = {"low": number(target_resolution.get("target_load")), "high": 0.0, "peak": 0.0}
    else:
        actual = {"low": quality_low_xss}
    exceeded = [key for key in normalized if number(actual.get(key)) is not None and normalized[key] is not None and actual[key] > normalized[key] + 0.05]
    complete = all(number(actual.get(key)) is not None and normalized[key] is not None for key in normalized)
    decision = target_resolution.get("capacity_decision") or {}
    accepted = decision.get("action") == "accept_model_conflict" and bool(decision.get("reason")) and bool(decision.get("evidence"))
    report = {
        "status": "model_conflict" if exceeded else "within_model_capacity" if complete else "assessment_pending",
        "review_required": (bool(exceeded) and not accepted) or not complete,
        "automatic_dose_cap": False,
        "horizon": target_resolution.get("capacity_horizon"),
        "workout_capacity_xss": normalized,
        "selected_workout_xss": actual,
        "exceeded_systems": exceeded,
        "as_of": capacity.get("as_of"), "fresh_at": capacity.get("fresh_at"),
        "decision": decision or None,
        "resolution": "Reduce the selected dose and recalculate, move the next workout and recalculate capacity, or explicitly justify accepting the model conflict.",
        "assumption": "Xert fresh boundary, no intervening training; not a physiological safety limit",
    }
    target_resolution["recovery_protection_capacity"] = report
    return report


def require_resolved_capacity_review(target_resolution: dict[str, Any]) -> None:
    report = target_resolution.get("recovery_protection_capacity") or {}
    if report.get("review_required"):
        raise SystemExit("Xert capacity conflict requires review: reduce dose, move next workout and recalculate, or justify accept_model_conflict. No automatic dose cut was applied.")


def normalize_endurance_calculation(
    calculation: dict[str, Any],
) -> dict[str, Any]:
    """Map the raw solve_segment_duration result to recommendation fields."""

    normalized = dict(calculation)
    if normalized.get("target_metric") == "low_xss":
        normalized.setdefault("target_low_xss", normalized.get("target_value"))
        normalized.setdefault(
            "tolerance_xss",
            normalized.get("absolute_tolerance"),
        )
        normalized.setdefault("low_xss_error", normalized.get("target_error"))
    return normalized


def applicable_endurance_low_xss_target(
    target_resolution: dict[str, Any],
) -> float:
    """Use only the selected dose, never XATA advice or model capacity."""
    target_low = number(target_resolution.get("selected_low_xss"))
    if target_low is None:
        target_low = number(target_resolution.get("target_load"))
    capped_load = number(target_resolution.get("target_load"))
    if capped_load is not None and target_low is not None:
        target_low = min(target_low, capped_load)
    if target_low is None or target_low <= 0:
        raise ValueError("target resolution has no coach-selected low-XSS target")
    return target_low


def build_endurance_solver_request(
    target_resolution: dict[str, Any],
    *,
    structure: dict[str, Any],
) -> dict[str, Any]:
    """Build the MCP solve_segment_duration request for a selected load."""

    if (target_resolution.get("coaching_selection") or {}).get("basis") == "duration":
        raise ValueError("Duration is already selected; use calculate_workout for the complete structure")
    request = {
        "signature": structure.get("signature"),
        "segments": structure.get("segments"),
        "adjustable_segment_index": structure.get("adjustable_segment_index"),
        "target_metric": "low_xss",
        "target_value": applicable_endurance_low_xss_target(target_resolution),
        "minimum_duration_seconds": structure.get("minimum_duration_seconds", 1),
        "maximum_duration_seconds": structure.get(
            "maximum_duration_seconds", 8 * 60 * 60
        ),
        "absolute_tolerance": structure.get("tolerance_xss", 0.05),
    }
    return request


def require_endurance_solution_for_selected_domain(
    *,
    intensity_decision: dict[str, Any],
    target_resolution: dict[str, Any],
) -> None:
    selected = str(intensity_decision.get("selected_domain") or "")
    if selected not in {"vt1", "easy_vt1", "recovery"}:
        return
    if target_resolution.get("endurance_duration_solution"):
        return
    raise SystemExit(
        "A recovery/VT1 recommendation requires --endurance-workout-json from "
        "Xert calculate_workout (duration basis) or solve_segment_duration (load basis). Mixed-history XSS/min cannot define "
        "the prescribed endurance duration."
    )


def xert_calculation_duration_minutes(value: Any) -> float | None:
    numeric = number(value)
    if numeric is not None:
        return numeric / 60.0
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    try:
        parsed = [float(part) for part in parts]
    except ValueError:
        return None
    if len(parsed) == 2:
        return parsed[0] + parsed[1] / 60.0
    if len(parsed) == 3:
        return parsed[0] * 60.0 + parsed[1] + parsed[2] / 60.0
    return None


def annotate_dose_composition_window_fit(
    target_resolution: dict[str, Any],
    *,
    planned_at: datetime,
    now: datetime,
    available_windows: list[dict[str, datetime]],
) -> None:
    composition = target_resolution.get("dose_composition")
    if not isinstance(composition, dict):
        return
    intended_minutes = number(
        (composition.get("estimated_total") or {}).get("duration_minutes")
    )
    if intended_minutes is None or not available_windows:
        composition["calendar_fit"] = {
            "available": False,
            "reason": "no_available_windows",
        }
        return

    execution_floor = max(planned_at, now)
    available_minutes = sum(
        max(
            0.0,
            (
                window["end"] - max(window["start"], execution_floor)
            ).total_seconds()
            / 60.0,
        )
        for window in available_windows
        if window["end"] > execution_floor
    )
    split = target_resolution.get("split") or {}
    scheduled_from_allocations = number(split.get("scheduled_minutes"))
    executable_minutes = (
        min(intended_minutes, scheduled_from_allocations)
        if scheduled_from_allocations is not None
        else min(intended_minutes, available_minutes)
    )
    shortfall_minutes = max(0.0, intended_minutes - executable_minutes)

    quality = composition.get("quality_base") or {}
    filler = composition.get("vt1_filler") or {}
    quality_is_counted = bool(quality.get("counted_in_remaining_plan", True))
    quality_minutes = (
        (number(quality.get("duration_minutes")) or 0.0)
        if quality_is_counted
        else 0.0
    )
    quality_xss = (
        (number(quality.get("xss")) or 0.0)
        if quality_is_counted
        else 0.0
    )
    filler_minutes = number(filler.get("duration_minutes")) or 0.0
    filler_xss_per_minute = (
        (number(filler.get("xss")) or 0.0) / filler_minutes
        if filler_minutes > 0
        else 0.0
    )
    allocation_xss = [
        number(allocation.get("estimated_xss"))
        for allocation in split.get("allocations") or []
    ]
    executable_xss = (
        sum(value for value in allocation_xss if value is not None)
        if allocation_xss and all(value is not None for value in allocation_xss)
        else None
    )
    shortfall_xss = None
    if executable_xss is None and executable_minutes >= quality_minutes:
        executable_filler_minutes = min(
            max(0.0, executable_minutes - quality_minutes),
            filler_minutes,
        )
        executable_xss = quality_xss + (
            executable_filler_minutes * filler_xss_per_minute
        )
    intended_xss = number(
        (composition.get("estimated_total") or {}).get("xss")
    )
    if executable_xss is not None and intended_xss is not None:
        shortfall_xss = max(0.0, intended_xss - executable_xss)

    composition["calendar_fit"] = {
        "available": True,
        "available_minutes": round(available_minutes, 1),
        "intended_minutes": round(intended_minutes, 1),
        "executable_minutes": round(executable_minutes, 1),
        "shortfall_minutes": round(shortfall_minutes, 1),
        "estimated_executable_xss": rounded_number(executable_xss),
        "estimated_shortfall_xss": rounded_number(shortfall_xss),
        "fits": shortfall_minutes < WINDOW_FIT_TOLERANCE_MINUTES,
    }


def rounded_number(value: Any, digits: int = 1) -> float | None:
    parsed = number(value)
    return round(parsed, digits) if parsed is not None else None


def outdoor_target_distance_km(*, target_minutes: float, surface_preference: str) -> float:
    speed_kmh_by_surface = {
        "road": 28.0,
        "gravel": 24.0,
        "any": 26.0,
        "unknown-ok": 26.0,
    }
    speed_kmh = speed_kmh_by_surface.get(surface_preference, 26.0)
    return round(clamp(target_minutes / 60.0 * speed_kmh, 15.0, 140.0), 1)


def dose_position_vs_typical(
    *,
    target_minutes: float,
    typical_minutes: float,
    caution: float,
    load_pct: float | None,
) -> dict[str, Any]:
    ratio = target_minutes / typical_minutes if typical_minutes else 1.0
    if ratio < 0.9:
        label = "less_than_typical"
        phrase = "less than a typical training day"
    elif ratio > 1.1:
        label = "more_than_typical"
        phrase = "more than a typical training day"
    else:
        label = "about_typical"
        phrase = "about a typical training day"

    reasons = []
    if caution >= 1.0:
        reasons.append(f"numeric readiness caution {round(caution, 2)} pulls dose down")
    elif caution <= 0.35:
        reasons.append(f"low numeric readiness caution {round(caution, 2)} does not pull dose down")
    if load_pct is not None:
        if load_pct >= 60:
            reasons.append(f"recent rolling XSS is not low ({round(load_pct, 1)} percentile in available Xert window)")
        elif load_pct <= 35:
            reasons.append(f"recent rolling XSS is low ({round(load_pct, 1)} percentile in available Xert window)")
    return {
        "label": label,
        "ratio": round(ratio, 2),
        "phrase": phrase,
        "reason": "; ".join(reasons) if reasons else "based on continuous readiness and recent XSS adjustment",
    }


WINDOW_FIT_TOLERANCE_MINUTES = 10.0
MIN_SEPARATE_VT1_SESSION_MINUTES = 30.0


def apply_split_preference_to_windows(
    available_windows: list[dict[str, datetime]],
    *,
    planned_at: datetime,
    split_preference: dict[str, Any],
) -> list[dict[str, Any]]:
    first_minutes = float(split_preference["first_session_minutes"])
    first_end = planned_at + timedelta(minutes=first_minutes)
    second_start = datetime.fromisoformat(split_preference["second_session_start"])
    first_source = next(
        (
            window
            for window in available_windows
            if window["start"] <= planned_at and first_end <= window["end"]
        ),
        None,
    )
    second_source = next(
        (
            window
            for window in available_windows
            if window["start"] <= second_start < window["end"]
        ),
        None,
    )
    if first_source is None:
        raise SystemExit(
            "split_preference first session does not fit an availability window"
        )
    if second_source is None:
        raise SystemExit(
            "split_preference second_session_start is outside availability windows"
        )
    if second_start < first_end:
        raise SystemExit(
            "split_preference second_session_start must not overlap the first session"
        )
    return [
        {
            **first_source,
            "start": planned_at,
            "end": first_end,
            "note": first_source.get("note") or "preferred first session",
        },
        {
            **second_source,
            "start": second_start,
            "note": second_source.get("note") or "preferred second session",
        },
    ]


def split_endurance_structure(
    structure: dict[str, Any],
    *,
    first_session_minutes: float,
) -> dict[str, Any]:
    segments = [dict(segment) for segment in structure.get("segments") or []]
    adjustable_index = structure.get("adjustable_segment_index")
    if (
        not segments
        or isinstance(adjustable_index, bool)
        or not isinstance(adjustable_index, int)
        or not 0 <= adjustable_index < len(segments)
    ):
        raise SystemExit("split endurance structure requires one adjustable segment")
    prefix = [dict(segment) for segment in segments[:adjustable_index]]
    adjustable = dict(segments[adjustable_index])
    suffix = [dict(segment) for segment in segments[adjustable_index + 1 :]]
    fixed_seconds = sum(
        number(segment.get("duration_seconds")) or 0.0
        for segment in (*prefix, *suffix)
    )
    first_adjustable_seconds = first_session_minutes * 60.0 - fixed_seconds
    if first_adjustable_seconds < MIN_SEPARATE_VT1_SESSION_MINUTES * 60:
        raise SystemExit(
            "split_preference first session leaves less than 30 minutes in the adjustable VT1 segment"
        )
    first_adjustable = {
        **adjustable,
        "duration_seconds": round(first_adjustable_seconds),
    }
    split_segments = [
        *prefix,
        first_adjustable,
        *suffix,
        *[dict(segment) for segment in prefix],
        adjustable,
        *[dict(segment) for segment in suffix],
    ]
    second_adjustable_index = len(prefix) + 1 + len(suffix) + len(prefix)
    return {
        **structure,
        "segments": split_segments,
        "adjustable_segment_index": second_adjustable_index,
        "split_preference": {
            "first_session_minutes": round(first_session_minutes, 1),
            "extra_start_finish_segments": len(prefix) + len(suffix),
        },
    }


def split_session_info(
    target_resolution: dict[str, Any],
    *,
    planned_at: datetime,
    now: datetime,
    available_windows: list[dict[str, datetime]],
) -> dict[str, Any]:
    target_minutes = number(target_resolution.get("target_minutes"))
    if target_minutes is None:
        return {
            "available": False,
            "reason": "missing_target_minutes",
            "guidance": (
                "Treat this as a day-dose target. If calendar/logistics are tight, "
                "split it into shorter sessions rather than changing the physiological dose."
            ),
        }
    if not available_windows:
        return {
            "available": False,
            "reason": "no_available_windows",
            "target_minutes": target_minutes,
            "guidance": (
                "This is a day-dose target; it can be done as one ride or split into "
                "shorter sessions if calendar/logistics make that better."
            ),
        }

    execution_start = max(planned_at, now)
    usable_windows = []
    for index, window in enumerate(available_windows):
        start = max(window["start"], execution_start)
        end = window["end"]
        if end <= start:
            continue
        usable_windows.append(
            {
                "index": index,
                "source": window,
                "start": start,
                "end": end,
                "minutes": (end - start).total_seconds() / 60.0,
            }
        )

    if not usable_windows:
        return {
            "available": True,
            "target_minutes": round(target_minutes, 1),
            "current_window": None,
            "available_minutes_from_planned": 0.0,
            "fits_current_window": False,
            "split_needed": False,
            "first_session_minutes": 0.0,
            "remaining_minutes": round(target_minutes, 1),
            "next_window": None,
            "allocations": [],
            "sessions": [],
            "scheduled_minutes": 0.0,
            "unscheduled_minutes": round(target_minutes, 1),
            "reason": "no_remaining_candidate_window",
            "guidance": (
                f"No availability remains from {execution_start.strftime('%H:%M')}; "
                "leave the complete workout unscheduled."
            ),
        }

    composition = target_resolution.get("dose_composition") or {}
    quality = composition.get("quality_base") or {}
    quality_counted = bool(quality.get("counted_in_remaining_plan", False))
    quality_minutes = number(quality.get("duration_minutes")) or 0.0
    domain = str(composition.get("selected_intensity") or "quality").upper()

    candidate_window = next(
        (
            window
            for window in usable_windows
            if window["source"]["start"] <= planned_at < window["source"]["end"]
        ),
        None,
    )
    complete_window = (
        candidate_window
        if candidate_window is not None
        and candidate_window["minutes"] >= target_minutes
        else None
    )
    if complete_window is not None:
        allocations = []
        allocation_start = complete_window["start"]
        if quality_counted and quality_minutes > 0:
            quality_end = allocation_start + timedelta(minutes=quality_minutes)
            allocations.append(
                split_allocation(
                    window=complete_window,
                    role=str(composition.get("selected_intensity") or "quality"),
                    start=allocation_start,
                    end=quality_end,
                    minutes=quality_minutes,
                    xss=number(quality.get("xss")),
                    complete_workout=True,
                )
            )
            allocation_start = quality_end
        endurance_minutes = target_minutes - sum(
            number(allocation.get("duration_minutes")) or 0.0
            for allocation in allocations
        )
        if endurance_minutes > 0:
            endurance_end = allocation_start + timedelta(minutes=endurance_minutes)
            filler = composition.get("vt1_filler") or {}
            filler_xss = number(filler.get("xss"))
            if filler_xss is None and allocations:
                target_load = number(target_resolution.get("target_load"))
                quality_xss = number(quality.get("xss"))
                if target_load is not None and quality_xss is not None:
                    filler_xss = max(0.0, target_load - quality_xss)
            allocations.append(
                split_allocation(
                    window=complete_window,
                    role="vt1" if allocations else str(
                        composition.get("selected_intensity") or "workout"
                    ),
                    start=allocation_start,
                    end=endurance_end,
                    minutes=endurance_minutes,
                    xss=(
                        filler_xss
                        if filler_xss is not None
                        else number(target_resolution.get("target_load"))
                    ),
                    complete_workout=True,
                )
            )
        sessions = group_split_allocations(allocations)
        return {
            "available": True,
            "target_minutes": round(target_minutes, 1),
            "current_window": serialize_available_window(complete_window["source"]),
            "available_minutes_from_planned": round(complete_window["minutes"], 1),
            "fits_current_window": True,
            "split_needed": False,
            "first_session_minutes": round(target_minutes, 1),
            "remaining_minutes": 0.0,
            "next_window": None,
            "allocations": allocations,
            "sessions": sessions,
            "scheduled_minutes": round(target_minutes, 1),
            "unscheduled_minutes": 0.0,
            "selected_window_index": complete_window["index"],
            "guidance": (
                "The complete candidate-specific workout fits this window."
            ),
        }

    allocations: list[dict[str, Any]] = []
    filler_remaining = target_minutes

    if quality_counted:
        quality_window = next(
            (
                window
                for window in [candidate_window]
                if window is not None
                if window["minutes"] >= quality_minutes
            ),
            None,
        )
        if quality_window is None:
            available_now = usable_windows[0]["minutes"] if usable_windows else 0.0
            return {
                "available": True,
                "target_minutes": round(target_minutes, 1),
                "current_window": (
                    serialize_available_window(usable_windows[0]["source"])
                    if usable_windows
                    else None
                ),
                "available_minutes_from_planned": round(available_now, 1),
                "fits_current_window": False,
                "split_needed": True,
                "first_session_minutes": 0.0,
                "remaining_minutes": round(target_minutes, 1),
                "next_window": None,
                "allocations": [],
                "sessions": [],
                "scheduled_minutes": 0.0,
                "unscheduled_minutes": round(target_minutes, 1),
                "reason": "complete_quality_workout_does_not_fit",
                "guidance": (
                    f"This candidate window cannot contain the complete "
                    f"{round(quality_minutes)} min {domain} workout, including its "
                    "warm-up, recoveries, and cool-down. Reject this candidate and "
                    "evaluate the next window; do not split the quality workout."
                ),
            }
        quality_end = quality_window["start"] + timedelta(minutes=quality_minutes)
        allocations.append(
            split_allocation(
                window=quality_window,
                role=str(composition.get("selected_intensity") or "quality"),
                start=quality_window["start"],
                end=quality_end,
                minutes=quality_minutes,
                xss=number(quality.get("xss")),
                complete_workout=True,
            )
        )
        filler_remaining = max(0.0, target_minutes - quality_minutes)
    if filler_remaining > 0:
        scheduled_minutes = sum(
            number(allocation.get("duration_minutes")) or 0.0
            for allocation in allocations
        )
        sessions = group_split_allocations(allocations)
        if quality_counted:
            guidance = (
                f"Keep the complete {round(quality_minutes)} min {domain} quality "
                "workout with its built-in warm-up, recoveries, and cool-down. "
                f"The remaining {round(filler_remaining)} min VT1 requires a "
                "complete structure solve with its own warm-up, main set, and "
                "cool-down for every separate session; do not convert it with an "
                "assumed XSS-per-hour rate."
            )
        else:
            guidance = (
                "No single candidate window contains the complete workout. Solve "
                "every separate endurance session with its own warm-up, main set, "
                "and cool-down; do not convert the remaining dose with an assumed "
                "XSS-per-hour rate."
            )
        return {
            "available": True,
            "target_minutes": round(target_minutes, 1),
            "current_window": (
                sessions[0]["window"]
                if sessions
                else serialize_available_window(usable_windows[0]["source"])
            ),
            "available_minutes_from_planned": round(
                usable_windows[0]["minutes"] if usable_windows else 0.0,
                1,
            ),
            "fits_current_window": False,
            "split_needed": True,
            "split_requires_recalculation": True,
            "first_session_minutes": round(scheduled_minutes, 1),
            "remaining_minutes": round(filler_remaining, 1),
            "next_window": None,
            "allocations": allocations,
            "sessions": sessions,
            "scheduled_minutes": round(scheduled_minutes, 1),
            "unscheduled_minutes": round(filler_remaining, 1),
            "reason": "separate_endurance_sessions_require_structure_solves",
            "guidance": guidance,
        }

    sessions = group_split_allocations(allocations)
    scheduled_minutes = sum(
        number(allocation.get("duration_minutes")) or 0.0
        for allocation in allocations
    )
    unscheduled_minutes = max(0.0, target_minutes - scheduled_minutes)
    first_session = sessions[0] if sessions else None
    second_session = sessions[1] if len(sessions) > 1 else None
    first_session_minutes = (
        number(first_session.get("duration_minutes")) or 0.0
        if first_session
        else 0.0
    )
    return {
        "available": True,
        "target_minutes": round(target_minutes, 1),
        "current_window": (
            first_session["window"]
            if first_session
            else (
                serialize_available_window(usable_windows[0]["source"])
                if usable_windows
                else None
            )
        ),
        "available_minutes_from_planned": round(
            usable_windows[0]["minutes"] if usable_windows else 0.0,
            1,
        ),
        "fits_current_window": len(sessions) <= 1 and unscheduled_minutes < 0.1,
        "split_needed": len(sessions) > 1,
        "first_session_minutes": round(first_session_minutes, 1),
        "remaining_minutes": round(
            max(0.0, target_minutes - first_session_minutes),
            1,
        ),
        "next_window": (
            second_session["window"]
            if second_session
            else None
        ),
        "allocations": allocations,
        "sessions": sessions,
        "scheduled_minutes": round(scheduled_minutes, 1),
        "unscheduled_minutes": round(unscheduled_minutes, 1),
        "guidance": split_allocation_guidance(
            sessions,
            unscheduled_minutes=unscheduled_minutes,
            quality_domain=domain,
            execution_start=execution_start,
        ),
    }


def split_allocation(
    *,
    window: dict[str, Any],
    role: str,
    start: datetime,
    end: datetime,
    minutes: float,
    xss: float | None,
    complete_workout: bool,
) -> dict[str, Any]:
    return {
        "window_index": window["index"],
        "window": serialize_available_window(window["source"]),
        "role": role,
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
        "duration_minutes": round(minutes, 1),
        "estimated_xss": rounded_number(xss),
        "complete_workout_required": complete_workout,
    }


def group_split_allocations(
    allocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    by_window: dict[int, dict[str, Any]] = {}
    for allocation in allocations:
        window_index = int(allocation["window_index"])
        session = by_window.get(window_index)
        if session is None:
            session = {
                "window_index": window_index,
                "window": allocation["window"],
                "start": allocation["start"],
                "end": allocation["end"],
                "duration_minutes": 0.0,
                "estimated_xss": 0.0,
                "segments": [],
            }
            by_window[window_index] = session
            sessions.append(session)
        session["end"] = allocation["end"]
        session["duration_minutes"] = round(
            (number(session["duration_minutes"]) or 0.0)
            + (number(allocation["duration_minutes"]) or 0.0),
            1,
        )
        if allocation.get("estimated_xss") is None:
            session["estimated_xss"] = None
        elif session.get("estimated_xss") is not None:
            session["estimated_xss"] = round(
                (number(session["estimated_xss"]) or 0.0)
                + (number(allocation["estimated_xss"]) or 0.0),
                1,
            )
        session["segments"].append(allocation)
    return sessions


def split_allocation_guidance(
    sessions: list[dict[str, Any]],
    *,
    unscheduled_minutes: float,
    quality_domain: str,
    execution_start: datetime,
) -> str:
    descriptions = []
    for session in sessions:
        segment_descriptions = []
        for segment in session.get("segments") or []:
            minutes = round(number(segment.get("duration_minutes")) or 0.0)
            if segment.get("role") == "vt1":
                prefix = "remaining " if segment_descriptions == [] and descriptions else ""
                segment_descriptions.append(
                    f"{prefix}{minutes} min VT1 including its easy start and finish"
                )
            else:
                segment_descriptions.append(
                    f"complete {minutes} min {quality_domain} quality workout "
                    "including its built-in warm-up, recoveries, and cool-down"
                )
        descriptions.append(
            f"{str(session.get('start'))[11:16]}-{str(session.get('end'))[11:16]}: "
            + ", then ".join(segment_descriptions)
        )
    guidance = (
        "Calendar allocation: " + "; ".join(descriptions)
        if descriptions
        else (
            f"No executable training allocation from "
            f"{execution_start.strftime('%H:%M')}."
        )
    )
    if unscheduled_minutes >= 0.1:
        guidance += (
            f" The remaining {round(unscheduled_minutes)} min VT1 is unscheduled; "
            "do not invent another session without an actual available window."
        )
    return guidance


def select_intensity_domain(
    *,
    readiness_ceiling: str,
    intensity_goal: str,
    progression_advice: dict[str, Any],
    plan_progression: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select an intensity within the readiness ceiling."""

    ceiling_domains = {
        "rest": {"rest"},
        "active_recovery_only": {"active_recovery"},
        "easy_vt1": {"active_recovery", "easy_vt1"},
        "normal_vt1": {"active_recovery", "easy_vt1", "vt1"},
        "vt2_ok": {
            "active_recovery",
            "easy_vt1",
            "vt1",
            "vt2",
        },
        "high_intensity_ok": {
            "active_recovery",
            "easy_vt1",
            "vt1",
            "vt2",
            "vo2max",
            "sprint",
            "mixed",
        },
    }
    allowed = ceiling_domains.get(readiness_ceiling, {"easy_vt1"})
    goal_domain = {
        "recovery": "active_recovery",
        "vt1": "vt1",
        "vt2": "vt2",
        "vo2max": "vo2max",
        "sprint": "sprint",
        "mixed": "mixed",
    }.get(intensity_goal, "vt1")

    if readiness_ceiling in {"readiness_unknown", "review_recovery"}:
        selected = goal_domain
        reason = "planned_goal_pending_readiness_review"
    elif readiness_ceiling == "rest":
        selected = "rest"
        reason = "readiness_requires_rest"
    elif goal_domain not in allowed:
        selected = {
            "active_recovery_only": "active_recovery",
            "easy_vt1": "easy_vt1",
            "normal_vt1": "vt1",
            "vt2_ok": "vt2",
        }.get(readiness_ceiling, "easy_vt1")
        reason = "goal_reduced_to_readiness_ceiling"
    else:
        selected = goal_domain
        reason = "goal_within_readiness_ceiling"

    progression = (
        progression_advice.get(intensity_goal) or {}
        if intensity_goal in {"vt2", "vo2max"}
        else {}
    )
    state_progression = (
        (plan_progression or {}).get(intensity_goal) or {}
        if intensity_goal in {"vt2", "vo2max"}
        else {}
    )
    return {
        "readiness_ceiling": readiness_ceiling,
        "requested_goal": intensity_goal,
        "selected_domain": selected,
        "selection_reason": reason,
        "progression_status": (
            state_progression.get("status") or progression.get("status")
        ),
        "progression_next_step": (
            {
                "summary": state_progression.get("next_step"),
                "anchor": state_progression.get("anchor"),
                "source": "plan_state",
            }
            if state_progression.get("next_step")
            else (progression.get("next_step") or {}).get("prescription")
        ),
    }


READINESS_DOMAIN_CAPS = {
    "rest": {"minutes": 0.0, "load": 0.0},
    "active_recovery": {"minutes": 45.0, "load": 30.0},
}


def validate_final_dose_limits(target: dict[str, Any], selected_domain: str) -> None:
    values = {field: number(target.get(f"target_{field}")) for field in ("minutes", "load")}
    if any(isinstance(target.get(f"target_{field}"), bool) or value is None or not math.isfinite(value) or value < 0 for field, value in values.items()):
        raise ValueError("Final workout requires finite nonnegative duration and load")
    limits = []
    if selected_domain in READINESS_DOMAIN_CAPS:
        limits.append((selected_domain, READINESS_DOMAIN_CAPS[selected_domain]))
    for key in ("readiness_domain_cap", "illness_return_guardrail"):
        guard = target.get(key) or {}
        if guard.get("active"):
            limits.append((key, {"minutes": guard.get("max_minutes"), "load": guard.get("max_load")}))
    for name, limit in limits:
        for field, slack in (("minutes", 0.02), ("load", 0.05)):
            maximum = number(limit.get(field))
            if maximum is None or not math.isfinite(maximum) or maximum < 0:
                raise ValueError(f"Invalid {name} {field} limit")
            if values[field] > maximum + slack:
                raise ValueError(f"Final workout exceeds {name} {field} limit ({maximum})")


def apply_readiness_domain_target_cap(
    target_resolution: dict[str, Any],
    *,
    intensity_decision: dict[str, Any],
) -> None:
    """Keep a readiness downgrade from retaining an incompatible model dose."""

    selected = str(intensity_decision.get("selected_domain") or "")
    cap = READINESS_DOMAIN_CAPS.get(selected)
    if cap is None:
        return

    previous_minutes = number(target_resolution.get("target_minutes")) or 0.0
    previous_load = number(target_resolution.get("target_load")) or 0.0
    capped_minutes = min(previous_minutes, cap["minutes"])
    capped_load = min(previous_load, cap["load"])
    if capped_minutes == previous_minutes and capped_load == previous_load:
        return

    target_resolution["pre_readiness_domain_cap_target_minutes"] = previous_minutes
    target_resolution["pre_readiness_domain_cap_target_load"] = previous_load
    target_resolution["target_minutes"] = capped_minutes
    target_resolution["target_load"] = capped_load
    target_resolution["readiness_domain_cap"] = {
        "active": True,
        "selected_domain": selected,
        "max_minutes": cap["minutes"],
        "max_load": cap["load"],
        "discarded_minutes": round(previous_minutes - capped_minutes, 1),
        "discarded_load": round(previous_load - capped_load, 1),
        "remainder_disposition": "dropped_not_rescheduled",
        "meaning": (
            "The readiness-selected domain caps both intensity and dose. The "
            "discarded model dose is diagnostic only and is not scheduled later."
        ),
    }


def apply_execution_modality_constraint(
    intensity_decision: dict[str, Any],
    *,
    indoor_gym_only: bool,
) -> None:
    """Cap a generic gym bike at continuous aerobic work for execution."""
    if not indoor_gym_only:
        return
    selected = str(intensity_decision.get("selected_domain") or "")
    intensity_decision["execution_modality"] = "indoor_cycling_gym"
    intensity_decision["execution_control"] = "heart_rate_breathing_rpe"
    intensity_decision["load_measurement"] = "estimated_without_reliable_power"
    if selected in {"vt2", "vo2max", "sprint", "mixed"}:
        intensity_decision["pre_modality_selected_domain"] = selected
        intensity_decision["selected_domain"] = "vt1"
        intensity_decision["selection_reason"] = (
            "gym_bike_continuous_aerobic_only"
        )
        intensity_decision["quality_role_remains_queued"] = True


def build_primary_decision(
    *,
    readiness_packet: dict[str, Any],
    target_resolution: dict[str, Any],
    intensity_decision: dict[str, Any],
    cycling_available: bool = True,
    remainder_disposition: str = "unscheduled",
) -> dict[str, Any]:
    """Expose the physiological plan as an explicit LLM decision contract."""
    validate_final_dose_limits(target_resolution, str(intensity_decision.get("selected_domain") or "easy_vt1"))
    validate_final_coaching_dose(target_resolution)
    require_resolved_capacity_review(target_resolution)
    inputs = readiness_packet.get("recommendation_inputs") or {}
    events = inputs.get("intervals_wellness_events") or {}
    split = target_resolution.get("split") or {}
    target_minutes = number(target_resolution.get("target_minutes")) or 0.0
    target_load = number(target_resolution.get("target_load")) or 0.0

    selected_intensity = str(intensity_decision.get("selected_domain") or "easy_vt1")
    if events.get("current_day_illness") or events.get("illness_training_blocked") or selected_intensity == "rest" or target_minutes <= 0:
        action = "rest"
    elif events.get("illness_followup_needed"):
        action = "form_check"
    elif not cycling_available:
        action = "unavailable"
    else:
        action = "train"

    if action == "train":
        require_quality_workout_for_selected_domain(
            intensity_decision=intensity_decision,
            dose_composition=target_resolution.get("dose_composition"),
        )

    intensity = selected_intensity
    if action == "rest":
        intensity = "none"
    elif action == "form_check":
        intensity = "pending_form_check"
    elif action == "unavailable":
        intensity = "none_available"

    xert_remaining = bool(target_resolution.get("xert_completed_xss")) and target_resolution.get("xert_dose_basis") == "remaining_xss"
    executable_minutes = (
        number(split.get("first_session_minutes"))
        if split.get("available")
        else target_minutes
    )
    unscheduled_minutes = number(split.get("unscheduled_minutes")) or 0.0
    if action != "train":
        executable_minutes = 0.0
    if action == "unavailable":
        unscheduled_minutes = target_minutes
    executable_segments = executable_dose_segments(
        target_resolution.get("dose_composition"),
        executable_minutes=executable_minutes or 0.0,
        fallback_intensity=intensity,
        allocated_segments=(
            ((split.get("sessions") or [{}])[0].get("segments") or [])
            if split.get("available")
            else []
        ),
    )
    if action == "train" and intensity == "active_recovery":
        executable_segments = [
            {
                "role": "active_recovery",
                "duration_minutes": round(executable_minutes or 0.0, 1),
            }
        ]

    return {
        "action": action,
        "readiness_evidence": readiness_evidence_status(inputs),
        "provisional": action == "train" and (
            intensity_decision.get("readiness_ceiling") in {"readiness_unknown", "review_recovery"}
            or bool((inputs.get("intervals_wellness_events") or {}).get("current_day_review_signals"))
        ),
        "selected_intensity": intensity,
        "intensity_decision": intensity_decision,
        "physiological_remaining_dose": {
            "minutes": round(target_minutes, 1),
            "load_xss": round(target_load, 1),
        },
        "coaching_selection": target_resolution.get("coaching_selection"),
        **{key: target_resolution[key] for key in ("vt1_power_review", "vt1_dose_comparison")
           if key in target_resolution},
        "xert_comparison": {"suggested_xss": target_resolution.get("xert_recommended_total_xss"),
            "difference_xss": round(target_load - target_resolution["xert_recommended_total_xss"], 1) if number(target_resolution.get("xert_recommended_total_xss")) is not None else None,
            "capacity": target_resolution.get("recovery_protection_capacity")},
        "dose_composition": target_resolution.get("dose_composition"),
        "executable_now": {
            "minutes": round(executable_minutes or 0.0, 1),
            "intensity": intensity,
            "segments": executable_segments,
            "timeline": executable_timeline(
                target_resolution, executable_minutes=executable_minutes or 0.0,
                action=action,
            ),
        },
        "unexecuted_remainder": {
            "minutes": round(unscheduled_minutes, 1),
            "schedule_automatically": False,
            "disposition": (
                "none" if unscheduled_minutes < 0.1 else remainder_disposition
            ),
        },
        "dose_semantics": (
            "remaining_after_completed_activities"
            if xert_remaining
            else "explicit_or_guardrailed_target"
        ),
        "completed_activities_already_accounted_for": xert_remaining,
        "decision_basis": [
            "illness_and_return_to_training_rules",
            "readiness_intensity_ceiling",
            "resolved_intensity_goal",
            "reviewed_plan_role_and_quality_spacing",
            "progression_next_step",
            "xert_recovery_vs_training",
            "available_time_and_modalities_for_execution",
        ],
        "llm_rule": (
            "Explain the coaching_selection reason and evidence, compare with Xert advice, "
            "and report capacity conflicts and their explicit resolution. "
            "When readiness_evidence.review_required is true, assess body feel, recent "
            "response and session demands before adopting the model dose; justify "
            "retaining or adjusting it. Otherwise use action and executable_now as "
            "the default recommendation. "
            "Any different recommendation must be labelled as a coaching override "
            "and justified by specific evidence not accounted for in the model "
            "decision. Such evidence may already appear as narrative context "
            "in this packet; missing data alone does not justify a reduction."
        ),
    }


def readiness_evidence_status(inputs: dict[str, Any]) -> dict[str, Any]:
    """Describe evidence coverage separately from the model's intensity policy."""
    wellness = inputs.get("wellness") or {}
    risks = {
        "hrv": hrv_readiness_risk(wellness),
        "sleep": sleep_score_caution(number(wellness.get("sleep_score"))),
        "resting_hr": resting_hr_readiness_risk(wellness),
    }
    assessed = [key for key, value in risks.items() if value is not None]
    missing = [key for key, value in risks.items() if value is None]
    agreement = intensity_signal_agreement(
        wellness=wellness, xert=inputs.get("xert_recovery") or {},
        intervals_events=inputs.get("intervals_wellness_events") or {},
    )
    return {
        "readiness_status": agreement["readiness_status"],
        "direct_signal_coverage": "complete" if not missing else "partial" if assessed else "unavailable",
        "assessed_direct_signals": assessed,
        "unassessed_direct_signals": missing,
        "observed_limitations": agreement["blockers"],
        "observed_cautions": agreement["review_signals"],
        "review_required": agreement["review_required"],
        "intervals_soreness_value": agreement["soreness"],
        "intervals_soreness_missing": agreement["soreness"] is None,
        "current_day_athlete_answers": inputs.get("current_day_athlete_answers", []),
        "interpretation": (
            "The intensity ceiling is a model screening result, not confirmed physiological "
            "readiness. Missing direct evidence lowers confidence, not the dose by itself. "
            "Interpret observed values and current body feel before prescribing hard work."
        ),
    }


def executable_timeline(
    target: dict[str, Any], *, executable_minutes: float, action: str,
) -> dict[str, Any]:
    """Expose exact solver order only when the full solved workout is executable."""
    solution = target.get("endurance_duration_solution") or {}
    composition = target.get("dose_composition") or {}
    quality = composition.get("quality_base") or {}
    if quality.get("counted_in_remaining_plan") and not (composition.get("vt1_filler") or {}).get("duration_minutes"):
        structure = quality.get("canonical_structure") or {}
        if structure.get("segments"):
            solution = {**structure, "source":"xert_workout_calculate",
                        "duration_seconds":sum(segment["duration_seconds"] for segment in structure["segments"])}
    segments = solution.get("segments") or []
    total = number(solution.get("duration_seconds"))
    if action != "train" or total is None or not segments:
        return {"status": "unavailable"}
    if abs(executable_minutes * 60 - total) > 6:
        return {"status": "requires_session_specific_calculation"}
    cursor = 0.0
    timeline = []
    for segment in segments:
        seconds = number(segment.get("duration_seconds"))
        if seconds is None or seconds < 0:
            raise ValueError("canonical timeline requires nonnegative segment durations")
        timeline.append({**segment, "start_seconds": cursor, "end_seconds": cursor + seconds})
        cursor += seconds
    if abs(cursor - total) > 1:
        raise ValueError("canonical timeline duration does not match solver total")
    return {"status": "complete", "source": "xert_calculated_segments" if solution.get("source") == "xert_workout_calculate" else "xert_solver_segments",
            "duration_seconds": total, "segments": timeline,
            "meaning": "Execution order is authoritative; quality/filler totals are accounting groups, not additional segments."}


QUALITY_WORKOUT_REQUIRED_DOMAINS = {"vt2", "vo2max", "sprint", "mixed"}


def require_quality_workout_for_selected_domain(
    *,
    intensity_decision: dict[str, Any],
    dose_composition: Any,
) -> None:
    """Prevent a selected quality domain from degrading into an all-VT1 dose."""

    selected_domain = str(intensity_decision.get("selected_domain") or "")
    if selected_domain not in QUALITY_WORKOUT_REQUIRED_DOMAINS:
        return
    if isinstance(dose_composition, dict):
        quality = dose_composition.get("quality_base")
        if isinstance(quality, dict):
            return
    raise SystemExit(
        f"Selected intensity domain {selected_domain!r} requires "
        "--quality-workout-json with a complete Xert workout calculation. "
        "Refusing to convert the quality dose into VT1 filler."
    )


def executable_dose_segments(
    composition: Any,
    *,
    executable_minutes: float,
    fallback_intensity: str,
    allocated_segments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if executable_minutes <= 0:
        return []
    if not isinstance(composition, dict):
        if allocated_segments:
            return [
                {
                    "role": fallback_intensity if segment.get("role") in (None, "workout") else str(segment["role"]),
                    "duration_minutes": round(
                        number(segment.get("duration_minutes")) or 0.0,
                        1,
                    ),
                    **(
                        {"complete_workout_required": True}
                        if segment.get("complete_workout_required")
                        else {}
                    ),
                }
                for segment in allocated_segments
                if (number(segment.get("duration_minutes")) or 0.0) > 0
            ]
        return [
            {
                "role": fallback_intensity,
                "duration_minutes": round(executable_minutes, 1),
            }
        ]

    quality = composition.get("quality_base") or {}
    quality_counted = bool(quality.get("counted_in_remaining_plan", False))
    quality_minutes = number(quality.get("duration_minutes")) or 0.0
    quality_role = str(composition.get("selected_intensity") or "quality")
    segments: list[dict[str, Any]] = []

    if quality_counted:
        if executable_minutes + WINDOW_FIT_TOLERANCE_MINUTES < quality_minutes:
            return [
                {
                    "role": quality_role,
                    "duration_minutes": round(quality_minutes, 1),
                    "fits_executable_window": False,
                    "available_minutes": round(executable_minutes, 1),
                    "complete_workout_required": True,
                }
            ]
        segments.append(
            {
                "role": quality_role,
                "duration_minutes": round(quality_minutes, 1),
                "complete_workout_required": True,
                "includes": quality.get("includes"),
            }
        )
        executable_minutes = max(0.0, executable_minutes - quality_minutes)

    if executable_minutes > 0:
        segments.append(
            {
                "role": "vt1",
                "duration_minutes": round(executable_minutes, 1),
                "includes_easy_start_and_finish": True,
            }
        )
    return segments


def split_session_guidance(
    split_info: dict[str, Any],
    *,
    remainder_disposition: str = "unscheduled",
) -> str:
    guidance = str(split_info.get("guidance") or "")
    unscheduled = number(split_info.get("unscheduled_minutes")) or 0.0
    if unscheduled < 0.1 or remainder_disposition == "unscheduled":
        return guidance
    disposition_text = {
        "dropped": "The unexecuted remainder is dropped today.",
        "moved": "The unexecuted remainder is moved to another real window.",
        "conditionally_split": "The unexecuted remainder is split only if the stated condition is met.",
    }.get(remainder_disposition)
    if not disposition_text:
        return guidance
    marker = " The remaining "
    if marker in guidance:
        guidance = guidance.split(marker, 1)[0]
    return f"{guidance} {disposition_text}".strip()


def current_available_window(
    planned_at: datetime,
    available_windows: list[dict[str, datetime]],
) -> dict[str, datetime] | None:
    for window in available_windows:
        if window["start"] <= planned_at < window["end"]:
            return window
    return None


def spacing_offer_comparison(review, target, planned_at, minutes):
    """Compare both optional finishes against the same reference and next start."""
    dose = target.get("vt1_dose_comparison") or {}
    evidence = dose.get("reference_vs_prescription") or {}
    next_start = ((evidence.get("prescription") or {}).get("next_workout_at")
                  or (target.get("capacity_horizon") or {}).get("next_workout_at"))
    reference = evidence.get("reference")
    if reference:
        ride = next((r for r in dose.get("candidates", []) if r["activity_id"] == reference["activity_id"]), {})
        quality = ride.get("next_quality_session") or {}
        reference = {**reference, "subsequent_quality": {
            k: quality[k] for k in ("activity_id", "planned_role", "planned_workout_completed", "quality_role_fulfilled")
            if quality.get(k) is not None}}
    comparison = {"reference": reference, "primary_work_watts": dose.get("working_power_w"),
                  "extension_intensity": review["intensity"]}
    for name, key in (("offered", "extra_minutes"), ("alternative", "alternative_extra_minutes")):
        extra = review[key]
        total = minutes + extra
        candidate = {"total_minutes": total, "extra_minutes": extra}
        if dose.get("prescribed_steady_work_minutes") is not None:
            candidate["work_minutes_including_extension"] = dose["prescribed_steady_work_minutes"] + extra
        if next_start:
            end = planned_at + timedelta(minutes=total)
            candidate["finish_to_next_start_minutes"] = round((datetime.fromisoformat(next_start) - end).total_seconds() / 60, 1)
        comparison[name] = candidate
    return comparison


def resolve_aerobic_finish(primary, target, *, planned_at, available_windows, calendar, required, spacing_day=False):
    """Resolve the coach's optional finish separately from the selected ride."""
    selection = primary.get("coaching_selection") or {}
    split = target.get("split") or {}
    minutes = primary["executable_now"]["minutes"]
    if (primary["action"] != "train" or primary["selected_intensity"] in {"recovery", "active_recovery"}
            or not selection or minutes <= 0 or len(split.get("sessions") or []) > 1):
        return None
    if any((target.get(key) or {}).get("active") for key in ("readiness_domain_cap", "illness_return_guardrail")):
        return {"decision": "finish", "reason": "Follow the reviewed readiness or return-to-training dose."}
    if abs(minutes - target["target_minutes"]) > 0.1:
        return {"decision": "finish", "reason": "Only part of the selected dose fits this session."}
    window = current_available_window(planned_at, available_windows)
    if window:
        primary_end = planned_at + timedelta(minutes=minutes)
        clean_at = primary_end + timedelta(minutes=calendar.get("cleanup_buffer_minutes", 0))
        if primary_end >= window["end"]:
            return {"decision": "finish", "reason": "The primary ride fills the verified riding window."}
        for key in ("hard_stop", "practical_stop"):
            stop = calendar.get(key)
            if stop and clean_at >= datetime.fromisoformat(stop["at"]):
                return {"decision": "finish", "reason": f"The primary ride and cleanup fill the window to {stop['at']}."}
    review = selection.get("aerobic_finish")
    if review is None:
        if required:
            raise ValueError(
                "Review the longer aerobic finish before issuing today's recommendation. Set "
                "training_target.aerobic_finish to {decision: finish, reason, alternative_extra_minutes, "
                "good_response_limit} or {decision: offer, "
                "reason, extra_minutes, alternative_extra_minutes, intensity, check_at_minute, cue}. "
                "Compare plausible lengths using the athlete's history and surrounding sessions. "
                "Use the saved evidence and rerun this request."
            )
        return None
    if review["decision"] == "finish":
        if required and spacing_day and window and not review.get("smaller_extra_minutes"):
            raise ValueError(
                "A long alternative alone cannot settle an aerobic spacing-day finish. Compare the primary "
                "with a smaller useful addition on good legs and with the longer option. If the smaller one "
                "serves the volume goal and fits, offer it. To finish, set smaller_extra_minutes below "
                "alternative_extra_minutes and explain in good_response_limit why even that addition is "
                "unhelpful. Check actual recovery time from each finish to quality in the successful and "
                "abbreviated sequences. Also justify any simultaneous reduction in working watts and minutes."
            )
        if required and not (review.get("alternative_extra_minutes") and review.get("good_response_limit")):
            raise ValueError(
                "Reassess the saved finish decision on a favorable late response. Use the reviewed "
                "history in vt1_dose.py --quality-sequences with the decision --as-of. For an aerobic "
                "spacing day, add --aerobic-references and compare the intervening rides and subsequent "
                "quality outcomes. "
                "If extra aerobic work serves the plan and fits, offer it. To decline, supply "
                "alternative_extra_minutes and good_response_limit explaining the specific cost "
                "or constraint even then. An open calendar tomorrow alone is insufficient."
            )
        return review

    total = minutes + review["extra_minutes"]
    if review["check_at_minute"] > minutes:
        raise ValueError("aerobic_finish checkpoint falls after the executable ride")
    end = planned_at + timedelta(minutes=total)
    cleanup_end = end + timedelta(minutes=calendar.get("cleanup_buffer_minutes", 0))
    if not window:
        return {"decision": "finish", "reason": "Available time for the longer ride has not been confirmed."}
    if end > window["end"]:
        return {"decision": "finish", "reason": "The longer ride does not fit the verified riding window."}
    for key in ("hard_stop", "practical_stop"):
        stop = calendar.get(key)
        if stop and cleanup_end > datetime.fromisoformat(stop["at"]):
            return {"decision": "finish", "reason": f"The longer ride and cleanup run past {stop['at']}."}
    result = {**review, "total_minutes": total,
              "finish_at": end.isoformat(), "cleanup_end": cleanup_end.isoformat()}
    timeline = primary["executable_now"].get("timeline") or {}
    if timeline.get("status") == "complete":
        checkpoint_seconds = review["check_at_minute"] * 60
        for index, segment in enumerate(timeline["segments"], start=1):
            if segment["start_seconds"] < checkpoint_seconds <= segment["end_seconds"]:
                result["checkpoint_segment"] = {
                    "number": index,
                    "minutes_completed": (checkpoint_seconds - segment["start_seconds"]) / 60,
                }
                break
        # A response check can precede completion of the last prescribed VT1 block.
        watts = (target.get("vt1_dose_comparison") or {}).get("working_power_w")
        if primary["selected_intensity"] == "vt1" and watts is not None:
            for index, work in reversed(list(enumerate(timeline["segments"], start=1))):
                if work.get("power") == work.get("end_power", work.get("power")) == watts:
                    result["extension_start"] = {
                        "segment": index, "work_minutes": work["duration_seconds"] / 60,
                        "ridden_minutes": work["end_seconds"] / 60,
                    }
                    break
    if calendar.get("events"):
        placements = place_movable_events(
            calendar, sessions=[{"start": planned_at.isoformat(), "end": end.isoformat()}],
            local_timezone=planned_at.tzinfo, day=planned_at.date().isoformat(),
        )
        if placements["status"] == "conflict":
            return {"decision": "finish", "reason": "The longer ride leaves insufficient room for movable events."}
        if placements["placements"]:
            result["movable_event_placements"] = placements["placements"]
    if required and "alternative_extra_minutes" not in review:
        raise ValueError(
            "Review the length of the optional finish. Set aerobic_finish.alternative_extra_minutes "
            "to a different positive addition to the same primary ride. Explain in reason why the "
            "chosen duration serves this training sequence better. Check older comparable rides for "
            "a materially longer option before reusing the saved dose."
        )
    if required and review["extra_minutes"] < review["alternative_extra_minutes"] and not review.get("good_response_limit"):
        raise ValueError(
            "Reassess the shorter offer on a favorable late response. If retaining it, set "
            "aerobic_finish.good_response_limit to the concrete reason to omit the difference "
            "or move it. For a transfer, compare the same work today versus closer to the next "
            "priority session, including the intervening ride. A free slot supplies no planned "
            "dose. If the longer option is useful and fits, update the offer and its cue."
        )
    if spacing_day and review.get("alternative_extra_minutes"):
        comparison = spacing_offer_comparison(review, target, planned_at, minutes)
        result["spacing_comparison"] = comparison
        if required and review["extra_minutes"] < review["alternative_extra_minutes"] and not review.get("limit_basis"):
            raise ValueError(
                f"Compare these spacing-day finishes on good legs: {json.dumps(comparison)}. "
                "Does the longer total repeat tolerated work at similar power, benefit current volume "
                "and leave a comparable recovery window? If so, offer it unless something specific "
                "still favors the shorter option. To retain the cap, set aerobic_finish.limit_basis "
                "(observed_response, practical_limit, plan_limit or coaching_judgment). Name the deciding "
                "fact in good_response_limit and carry it into the athlete's answer. A difference in kJ/XSS "
                "quantifies the work; pre-ride uncertainty alone does not distinguish the two late finishes."
            )
        block = (comparison.get("reference") or {}).get("detected_steady_block") or {}
        shorter_work = comparison["alternative"].get("work_minutes_including_extension")
        if (required and review["extra_minutes"] > review["alternative_extra_minutes"]
                and shorter_work is not None and block.get("minutes") is not None
                and round(shorter_work) > round(block["minutes"]) and not review.get("marginal_benefit")):
            raise ValueError(
                f"Both options already exceed the selected reference block: {json.dumps(comparison)}. "
                "Check the powers and how often comparable work was tolerated. One longer successful ride "
                "establishes feasibility. To choose the larger dose, give aerobic_finish.marginal_benefit: "
                "what does the extra work beyond the shorter extended ride contribute specifically today, "
                "given other volume opportunities and the next quality dose? If there is no distinct "
                "benefit, compare a finish near the routinely tolerated dose instead."
            )
    return result


def available_window_label(window: dict[str, Any], *, include_note: bool = False) -> str:
    label = f"{window['start'].strftime('%H:%M')}-{window['end'].strftime('%H:%M')}"
    note = str(window.get("note") or "").strip()
    if include_note and note:
        return f"{label} ({note})"
    return label


def current_window_minutes(
    *,
    planned_at: datetime,
    available_windows: list[dict[str, datetime]],
) -> float | None:
    window = current_available_window(planned_at, available_windows)
    if window is None:
        return None
    return max(0.0, (window["end"] - planned_at).total_seconds() / 60)


def window_fit(duration_minutes: Any, window_minutes: float | None) -> dict[str, Any]:
    duration = number(duration_minutes)
    if duration is None or window_minutes is None:
        return {
            "available": False,
            "reason": "missing_duration_or_window",
            "fits_first_window": None,
        }
    over_by = max(0.0, duration - window_minutes)
    fits = over_by <= WINDOW_FIT_TOLERANCE_MINUTES
    return {
        "available": True,
        "duration_minutes": round(duration, 1),
        "first_window_minutes": round(window_minutes, 1),
        "tolerance_minutes": WINDOW_FIT_TOLERANCE_MINUTES,
        "fits_first_window": fits,
        "over_by_minutes": round(over_by, 1),
    }


def annotate_indoor_window_fit(
    packet: dict[str, Any],
    *,
    planned_at: datetime,
    now: datetime,
    available_windows: list[dict[str, datetime]],
) -> None:
    window_minutes = current_window_minutes(
        planned_at=max(planned_at, now),
        available_windows=available_windows,
    )
    for key in ("recommended",):
        if isinstance(packet.get(key), dict):
            packet[key]["window_fit"] = window_fit(packet[key].get("duration_minutes"), window_minutes)
    for list_key in ("candidates", "higher_intensity_candidates", "relevant_options"):
        for option in packet.get(list_key) or []:
            if isinstance(option, dict):
                option["window_fit"] = window_fit(option.get("duration_minutes"), window_minutes)
    packet["first_window_minutes"] = round(window_minutes, 1) if window_minutes is not None else None
    packet["first_window_fit_tolerance_minutes"] = WINDOW_FIT_TOLERANCE_MINUTES
    packet["shorter_window_options"] = shorter_fitting_options(
        packet.get("candidates") or packet.get("relevant_options") or [],
        duration_key="duration_minutes",
        window_minutes=window_minutes,
    )


def annotate_route_window_fit(
    packet: dict[str, Any],
    *,
    target_minutes: float,
    planned_at: datetime,
    now: datetime,
    available_windows: list[dict[str, datetime]],
) -> None:
    window_minutes = current_window_minutes(
        planned_at=max(planned_at, now),
        available_windows=available_windows,
    )
    recommendations = packet.get("recommendations") or []
    for route in recommendations:
        if isinstance(route, dict):
            route["window_fit"] = window_fit(route.get("moving_minutes"), window_minutes)
            route["dose_fit"] = route_dose_fit(
                route.get("moving_minutes"),
                target_minutes,
            )
    packet["first_window_minutes"] = round(window_minutes, 1) if window_minutes is not None else None
    packet["first_window_fit_tolerance_minutes"] = WINDOW_FIT_TOLERANCE_MINUTES
    packet["prescribed_duration_minutes"] = round(target_minutes, 1)
    packet["shorter_window_options"] = shorter_fitting_options(
        recommendations,
        duration_key="moving_minutes",
        window_minutes=window_minutes,
    )


def route_dose_fit(route_minutes: Any, prescribed_minutes: Any) -> dict[str, Any]:
    route_duration = number(route_minutes)
    prescribed_duration = number(prescribed_minutes)
    if route_duration is None or prescribed_duration is None:
        return {
            "available": False,
            "reason": "missing_route_or_prescribed_duration",
        }

    difference = route_duration - prescribed_duration
    under_by = max(0.0, -difference)
    over_by = max(0.0, difference)
    matches = abs(difference) <= WINDOW_FIT_TOLERANCE_MINUTES
    if matches:
        action = "use_route_duration_as_is"
    elif under_by > 0:
        action = "extend_route_or_add_vt1_minutes"
    else:
        action = "shorten_route_or_use_turnaround"

    return {
        "available": True,
        "route_minutes": round(route_duration, 1),
        "prescribed_minutes": round(prescribed_duration, 1),
        "tolerance_minutes": WINDOW_FIT_TOLERANCE_MINUTES,
        "covers_prescribed_duration": matches,
        "under_by_minutes": round(under_by, 1),
        "over_by_minutes": round(over_by, 1),
        "action": action,
    }


def shorter_fitting_options(
    options: list[dict[str, Any]],
    *,
    duration_key: str,
    window_minutes: float | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if window_minutes is None:
        return []
    fitting = [
        option
        for option in options
        if isinstance(option, dict)
        and (number(option.get(duration_key)) is not None)
        and number(option.get(duration_key)) <= window_minutes + WINDOW_FIT_TOLERANCE_MINUTES
    ]
    fitting = sorted(fitting, key=lambda option: number(option.get(duration_key)) or 0.0, reverse=True)
    return [compact_window_option(option, duration_key=duration_key) for option in fitting[:limit]]


def compact_window_option(option: dict[str, Any], *, duration_key: str) -> dict[str, Any]:
    return {
        "name": option.get("name"),
        "duration_minutes": option.get(duration_key),
        "distance_km": option.get("distance_km"),
        "xss": option.get("xss"),
        "url": option.get("url") or option.get("intervals_activity_url"),
        "option_label": option.get("option_label"),
        "window_fit": option.get("window_fit"),
    }


def latest_activity_is_meaningful_same_day(latest: dict[str, Any], *, day: str) -> bool:
    if not latest or not day:
        return False
    start = str(latest.get("start_local") or "")
    if not start.startswith(day):
        return False
    return any(
        value is not None and value >= threshold
        for value, threshold in (
            (number(latest.get("elapsed_minutes")), 45),
            (number(latest.get("xert_xss")), 50),
        )
    )


def minutes_from_seconds(seconds: float | None) -> float | None:
    if seconds is None:
        return None
    return round(seconds / 60, 1)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compact_decision_inputs(
    readiness: dict[str, Any],
    *,
    routes: dict[str, Any],
    weather_home: dict[str, Any] | None,
    weather_route: dict[str, Any] | None,
    indoor_workouts: dict[str, Any] | None,
    target_resolution: dict[str, Any],
    history_context: dict[str, Any],
    progression_advice: dict[str, Any] | None,
) -> dict[str, Any]:
    inputs = readiness.get("recommendation_inputs") or {}
    freshness = inputs.get("input_freshness") or {}
    return {
        "time_context": inputs.get("time_context"),
        "target_resolution": target_resolution,
        "training_history_context": history_context,
        "input_freshness": freshness,
        "freshness_summary": compact_freshness_summary(
            freshness,
            garmin_recovery_readiness=inputs.get("garmin_recovery_readiness") or {},
            wellness=inputs.get("wellness") or {},
            target_date=readiness.get("date"),
            snapshot_time_local=readiness.get("snapshot_time_local"),
        ),
        "latest_activity_load": inputs.get("latest_activity_load"),
        "xert_training_advice": inputs.get("xert_training_advice"),
        "xert_recovery": inputs.get("xert_recovery"),
        "garmin_recovery_readiness": inputs.get("garmin_recovery_readiness"),
        "garmin_vo2max": inputs.get("garmin_vo2max"),
        "wellness": inputs.get("wellness"),
        "intensity_signal_agreement": inputs.get("intensity_signal_agreement"),
        "intervals_wellness_events": inputs.get("intervals_wellness_events"),
        "garmin_load_focus": inputs.get("garmin_load_focus"),
        "top_route": routes if routes.get("available") is False else first_recommendation(routes),
        "indoor_workouts": indoor_workouts,
        "progression_advice": progression_advice,
        "weather_home_hourly": (weather_home or {}).get("hourly"),
        "weather_route_hourly": (weather_route or {}).get("hourly"),
    }


def compact_freshness_summary(
    freshness: dict[str, Any],
    *,
    garmin_recovery_readiness: dict[str, Any],
    wellness: dict[str, Any],
    target_date: str | None = None,
    snapshot_time_local: str | None = None,
) -> dict[str, Any]:
    stale = []
    details = {}
    for key, value in sorted(freshness.items()):
        if not isinstance(value, dict):
            continue
        entry = {
            "freshness": value.get("freshness"),
            "latest_local": value.get("latest_local"),
            "age_minutes": value.get("age_minutes"),
        }
        details[key] = entry
        if value.get("freshness") == "stale":
            stale.append(key)

    recovery_timestamp = garmin_recovery_readiness.get("recovery_time_timestamp_local")
    completed_daily_signals = [
        label
        for label, value in (
            ("sleep", wellness.get("sleep_score")),
            ("overnight_hrv", wellness.get("hrv_last_night_avg")),
            ("resting_hr", wellness.get("resting_hr")),
            ("body_battery_at_wake", wellness.get("body_battery_at_wake")),
        )
        if value is not None
    ]
    future_day = False
    try:
        if target_date and snapshot_time_local:
            future_day = date.fromisoformat(target_date) > datetime.fromisoformat(
                snapshot_time_local
            ).date()
    except ValueError:
        future_day = False
    future_daily_signals = (
        ["sleep", "overnight_hrv", "resting_hr", "body_battery_at_wake"]
        if future_day
        else []
    )
    if future_day:
        guidance = "current_sources_fresh_future_daily_signals_not_available_yet"
        completed_daily_signals = []
    elif stale and completed_daily_signals:
        guidance = "dynamic_signals_stale_completed_daily_signals_usable"
    elif stale:
        guidance = "sync_watch_before_hard_session"
    else:
        guidance = "fresh_enough_for_now_decision"

    return {
        "guidance": guidance,
        "stale_inputs": stale,
        "stale_dynamic_inputs": stale,
        "completed_daily_signals_usable": completed_daily_signals,
        "future_daily_signals_not_available_yet": future_daily_signals,
        "details": details,
        "garmin_training_readiness_timestamp_local": recovery_timestamp,
        "meaning": (
            "Source freshness is evaluated at snapshot time. For a future target day, "
            "that day's completed sleep, overnight HRV, resting HR, and Body Battery "
            "at wake are not available yet and require a morning gate. Otherwise stale "
            "dynamic Garmin values describe the current moment only."
        ),
    }


def practical_fueling_defaults() -> dict[str, Any]:
    return {}


def initialize_plan_trace(target_resolution: dict[str, Any]) -> None:
    """Preserve the unadjusted model or explicit plan before guardrails run."""

    source = str(target_resolution.get("source") or "unknown")
    target_resolution["plan_trace"] = {
        "base_plan": {
            "label": "xert_recommended_remaining_dose"
            if source == "xert_training_advice_target_xss"
            else "explicit_coaching_selection"
            if source == "explicit_coaching_selection"
            else "explicit_user_or_cli_plan"
            if source.startswith("explicit_")
            else "fallback_plan",
            "source": source,
            "minutes": number(target_resolution.get("target_minutes")),
            "load_xss": number(target_resolution.get("target_load")),
            "reason": target_resolution.get("reason"),
        }
    }


def finalize_plan_trace(target_resolution: dict[str, Any]) -> None:
    """Explain whether physiological guardrails changed the base plan and why."""

    trace = target_resolution.setdefault("plan_trace", {})
    base = trace.get("base_plan") or {}
    final_minutes = number(target_resolution.get("target_minutes"))
    final_load = number(target_resolution.get("target_load"))
    reasons = []
    adjustment_types = []

    illness = target_resolution.get("illness_return_guardrail") or {}
    if illness.get("active"):
        adjustment_types.append("illness_return_guardrail")
        reasons.append(
            "Reviewed return phase "
            f"{illness.get('phase')} capped the base plan at "
            f"{illness.get('max_minutes')} min / {illness.get('max_load')} XSS."
        )

    domain_cap = target_resolution.get("readiness_domain_cap") or {}
    if domain_cap.get("active"):
        adjustment_types.append("readiness_domain_cap")
        reasons.append(
            "The selected readiness domain capped the base plan at "
            f"{domain_cap.get('max_minutes')} min / "
            f"{domain_cap.get('max_load')} XSS; discarded model dose is not rescheduled."
        )

    endurance_solution = target_resolution.get("endurance_duration_solution") or {}
    if endurance_solution:
        adjustment_types.append("xert_endurance_duration_recalculation")
        reasons.append(
            "Xert calculated the complete structure for the coach-selected dose; "
            "the calculation does not independently justify that dose."
        )

    base_minutes = number(base.get("minutes"))
    base_load = number(base.get("load_xss"))
    # Composition rounds display values; that is not a prescription change.
    changed = any(
        before != after if before is None or after is None
        else not math.isclose(before, after, rel_tol=0, abs_tol=0.05)
        for before, after in ((base_minutes, final_minutes), (base_load, final_load))
    )
    recalculated = bool(endurance_solution) and changed
    reduced_by_guardrail = changed and bool(illness.get("active") or domain_cap.get("active"))
    trace["adjustment"] = {
        "status": (
            "recalculated" if recalculated else "reduced" if reduced_by_guardrail
            else "adjusted" if changed else "unchanged"
        ),
        "types": adjustment_types,
        "reasons": reasons
        or [
            "No physiological or illness guardrail changed the base plan. "
            "Later timing, route, and session-split choices are logistical execution, "
            "not a reduction of the training dose."
        ],
    }
    trace["final_plan"] = {
        "minutes": final_minutes,
        "load_xss": final_load,
        "relationship_to_base": (
            "recalculated_for_selected_domain"
            if recalculated
            else "reduced_by_guardrail"
            if reduced_by_guardrail
            else "adjusted_prescription" if changed else "same_as_base"
        ),
    }


def apply_intervals_illness_target_guardrail(
    target_resolution: dict[str, Any],
    intervals_events: dict[str, Any],
) -> None:
    """Enforce the reviewed return dose, never a calendar-day progression."""
    if not intervals_events.get("return_to_training_active"):
        return
    guidance = intervals_events.get("return_to_training_guidance") or {}
    minutes = number(guidance.get("max_minutes"))
    load = number(guidance.get("max_load"))
    if minutes is None or load is None:
        raise ValueError("Illness return requires a reviewed duration and load before scheduling")
    cap = {"minutes": minutes, "load": load}
    target_resolution["pre_illness_guardrail_target_minutes"] = target_resolution.get(
        "target_minutes"
    )
    target_resolution["pre_illness_guardrail_target_load"] = target_resolution.get(
        "target_load"
    )
    target_resolution["target_minutes"] = min(
        number(target_resolution.get("target_minutes")) or cap["minutes"], cap["minutes"]
    )
    target_resolution["target_load"] = min(
        number(target_resolution.get("target_load")) or cap["load"], cap["load"]
    )
    target_resolution["illness_return_guardrail"] = {
        "active": True,
        "phase": intervals_events.get("illness_return_phase"),
        "max_minutes": cap["minutes"],
        "max_load": cap["load"],
        "avoid_intensity": True,
        "meaning": (
            "The model dose is limited by the explicit symptom- and response-based return assessment."
        ),
    }


def annotate_readiness_dose_review(
    target_resolution: dict[str, Any],
    readiness_packet: dict[str, Any],
) -> None:
    """Expose dose-review evidence without translating wearable scores into minutes."""

    inputs = readiness_packet.get("recommendation_inputs") or {}
    readiness = inputs.get("garmin_recovery_readiness") or {}
    wellness = inputs.get("wellness") or {}
    load_focus = inputs.get("garmin_load_focus") or {}
    xert = inputs.get("xert_recovery") or {}
    sleep_score = number(wellness.get("sleep_score"))
    hrv_risk = hrv_readiness_risk(wellness)
    resting_hr_risk = resting_hr_readiness_risk(wellness)
    body_battery_risk = body_battery_readiness_risk(wellness)
    autonomic_recovery_components = {
        "hrv": hrv_risk,
        "resting_hr": resting_hr_risk,
        "sleep_score": sleep_score_caution(sleep_score),
    }
    direct_domains = {
        "autonomic_recovery": max_present(*autonomic_recovery_components.values()),
    }

    acwr = number(load_focus.get("acwr"))
    recovery_load = xert.get("recovery_load") or {}
    training_load = xert.get("training_load") or {}
    recovery_hours = xert.get("projected_recovery_hours_at_planned_time") or xert.get("recovery_hours") or {}
    low_recovery_load = number(recovery_load.get("low"))
    low_training_load = number(training_load.get("low"))
    low_training_to_recovery_ratio = (
        low_training_load / low_recovery_load
        if low_training_load is not None
        and low_recovery_load is not None
        and low_recovery_load > 0
        else None
    )
    low_recovery_hours = number(recovery_hours.get("low"))
    xert_recovery_components = {
        "low_recovery_hours": linear_risk_optional(
            low_recovery_hours, good=0.0, bad=24.0
        ),
    }
    xert_modeled_recovery_risk = max_present(*xert_recovery_components.values())
    acwr_risk = linear_risk_optional(acwr, good=0.8, bad=1.4)
    cumulative_load_risk = xert_modeled_recovery_risk
    cumulative_load_source = (
        "xert_projected_low_recovery_hours"
        if xert_modeled_recovery_risk is not None
        else None
    )
    target_resolution["xert_recovery_training_diagnostic"] = {
        "source": cumulative_load_source,
        "modeled_recovery_risk": round(cumulative_load_risk, 3)
        if cumulative_load_risk is not None
        else None,
        "low_recovery_load": low_recovery_load,
        "low_training_load": low_training_load,
        "low_training_to_recovery_ratio": round(low_training_to_recovery_ratio, 3)
        if low_training_to_recovery_ratio is not None
        else None,
        "low_recovery_hours": low_recovery_hours,
        "garmin_acwr": acwr,
        "garmin_acwr_risk_diagnostic": round(acwr_risk, 3)
        if acwr_risk is not None
        else None,
        "meaning": (
            "Xert low-system recovery hours at the planned start describe modeled load recovery. "
            "Training Load / Recovery Load is diagnostic only; increasing it must not "
            "increase recovery concern. Garmin ACWR is retained as a separate "
            "diagnostic and never substitutes for missing Xert recovery context."
        ),
    }
    grouped_risk = direct_domains["autonomic_recovery"]
    direct_signal = (
        "unknown" if grouped_risk is None else "poor" if grouped_risk >= 0.75 else "caution"
        if grouped_risk is not None and grouped_risk >= 0.4 else "normal"
    )
    garmin_score = number(readiness.get("training_readiness_score"))
    garmin_signal = (
        "poor" if garmin_score is not None and garmin_score < 35 else "normal"
        if garmin_score is not None else "missing"
    )
    target_resolution["training_readiness_diagnostic"] = {
        "score": garmin_score,
        "level": readiness.get("training_readiness_level"),
        "used_for_dose": False,
        "direct_input_signal": direct_signal,
        "agreement": "agrees" if garmin_signal == direct_signal else "differs",
        "meaning": (
            "Garmin Training Readiness is retained as a diagnostic composite only. "
            "Dose decisions use direct physiological domains and normalized load."
        ),
    }

    # HRV can justify an intensity/response review, but does not quantify an
    # individual's maximum endurance dose. Sleep/RHR corroboration remains one
    # related recovery family, not additional independent votes.
    non_hrv_risk = max_present(
        resting_hr_risk, sleep_score_caution(sleep_score)
    )
    isolated_hrv = (
        hrv_risk is not None and hrv_risk >= 0.4
        and (non_hrv_risk is None or non_hrv_risk < 0.4)
    )
    target_resolution["hrv_dose_review"] = {
        "history_status": (
            "three_nights" if wellness.get("hrv_nights_used_3d") == 3
            else "last_night_fallback" if hrv_risk is not None else "unavailable"
        ),
        "isolated_hrv_caution": isolated_hrv,
        "automatic_dose_cap_from_hrv_alone": False,
        "meaning": (
            "HRV caution requires body-feel and execution review; it does not establish "
            "a physiological maximum or automatically validate the full XATA dose."
        ),
    }
    agreement = intensity_signal_agreement(
        wellness=wellness, xert=xert,
        intervals_events=inputs.get("intervals_wellness_events") or {},
    )
    target_resolution["readiness_dose_review"] = {
        "required": agreement["review_required"],
        "cautions": agreement["review_signals"],
        "intensity_blockers": agreement["blockers"],
        "automatic_dose_cap": False,
        "dose_status": "requires_coaching_assessment" if agreement["review_required"] else "no_observed_readiness_adjustment",
        "meaning": (
            "Assess body feel, symptoms, recent execution and recovery against this "
            "session's demands. Explain any chosen dose change separately from intensity. "
            "Wearable scores, alone or combined, do not determine minutes or XSS. "
            "An unchanged model target is not approval of the full dose."
        ),
    }


def build_coach_summary(
    decision: dict[str, Any],
    *,
    fueling_defaults: dict[str, Any],
    readiness_notes: list[str],
    now: datetime,
    planned_at: datetime,
    planned_at_source: str,
) -> dict[str, Any]:
    readiness = decision.get("garmin_recovery_readiness") or {}
    wellness = decision.get("wellness") or {}
    intervals_events = decision.get("intervals_wellness_events") or {}
    latest = decision.get("latest_activity_load") or {}
    xert = decision.get("xert_recovery") or {}
    workouts = decision.get("indoor_workouts") or {}
    route = decision.get("top_route") or {}
    target_resolution = decision.get("target_resolution") or {}
    freshness = decision.get("freshness_summary") or {}
    home_weather = decision.get("weather_home_hourly") or []
    route_weather = decision.get("weather_route_hourly") or []
    same_day_activity = same_day_activity_context(
        latest,
        day=planned_at.date().isoformat(),
        now=now,
        planned_at=planned_at,
    )

    bias = recommendation_bias(
        wellness=wellness,
        xert=xert,
        intervals_events=intervals_events,
    )
    current_illness = bool(intervals_events.get("current_day_illness"))
    illness_followup_needed = bool(intervals_events.get("illness_followup_needed"))
    return_to_training_active = bool(intervals_events.get("return_to_training_active"))
    primary_indoor = None if current_illness else primary_indoor_option(
        workouts,
        bias=bias,
        target_resolution=decision.get("target_resolution") or {},
    )
    primary_outdoor = None if current_illness else primary_outdoor_option(
        route, route_weather=route_weather, bias=bias
    )
    why = coach_summary_reasons(
        bias=bias,
        readiness=readiness,
        wellness=wellness,
        xert=xert,
        latest=latest,
        freshness=freshness,
        same_day_activity=same_day_activity,
        intervals_events=intervals_events,
        route_weather=route_weather,
    )
    timing = timing_guidance(
        bias=bias,
        freshness=freshness,
        home_weather=home_weather,
        route_weather=route_weather,
        now=now,
        planned_at=planned_at,
        planned_at_source=planned_at_source,
    )

    return {
        "recommended_bias": bias,
        "same_day_activity_context": same_day_activity,
        "target_resolution": target_resolution,
        "timing_guidance": timing,
        "why": why,
        "intensity_guardrails": intensity_guardrails(
            wellness=wellness,
            freshness=freshness,
            intervals_events=intervals_events,
        ),
        "primary_indoor_option": primary_indoor,
        "primary_outdoor_option": primary_outdoor,
        "weather_signal": {
            "home": compact_weather_signal(home_weather),
            "route": compact_weather_signal(route_weather),
        },
        "freshness_warnings": freshness.get("stale_inputs") or [],
        "freshness_guidance": freshness.get("guidance"),
        "fueling_defaults": fueling_defaults,
        "source_notes": readiness_notes,
        "meaning": (
            "Decision support for chat recommendations. The caller should still "
            "combine this with user context, goals, and how the body feels."
        ),
    }


def build_llm_context(
    decision: dict[str, Any],
    *,
    fueling_defaults: dict[str, Any],
    readiness_notes: list[str],
    now: datetime,
    planned_at: datetime,
    planned_at_source: str,
    available_windows: list[dict[str, datetime]],
    calendar_context: dict[str, Any],
) -> dict[str, Any]:
    latest = decision.get("latest_activity_load") or {}
    freshness = decision.get("freshness_summary") or {}
    home_weather = decision.get("weather_home_hourly") or []
    route_weather = decision.get("weather_route_hourly") or []
    same_day_activity = same_day_activity_context(
        latest,
        day=planned_at.date().isoformat(),
        now=now,
        planned_at=planned_at,
    )
    intervals_events = decision.get("intervals_wellness_events") or {}
    current_illness = bool(intervals_events.get("current_day_illness"))
    illness_followup_needed = bool(intervals_events.get("illness_followup_needed"))
    return_to_training_active = bool(intervals_events.get("return_to_training_active"))
    return {
        "purpose": (
            "Authoritative decision contract plus supporting data for an LLM-authored "
            "training recommendation. When primary_decision is provisional, assess recent "
            "execution, recovery and current body feel against the planned demands. "
            "Explain whether to proceed, postpone or change the session. Keep the "
            "recommendation conditional while material evidence is missing."
        ),
        "time_context": {
            "now_local": now.isoformat(timespec="seconds"),
            "planned_at_local": planned_at.isoformat(timespec="seconds"),
            "planned_at_source": planned_at_source,
            "assumed_planned_at": planned_at_source == "default",
            "available_windows": serialize_available_windows(available_windows),
            "evaluated_weather_window": weather_time_window(route_weather)
            or weather_time_window(home_weather),
            "calendar": calendar_context_with_slack(
                calendar_context,
                sessions=(decision.get("target_resolution") or {}).get("split", {}).get("sessions") or [],
            ),
        },
        "same_day_activity_context": same_day_activity,
        "intervals_wellness_events": intervals_events,
        "health_constraints": {
            "no_training_today": current_illness or bool(intervals_events.get("illness_training_blocked")),
            "form_check_needed": illness_followup_needed,
            "return_to_training_active": return_to_training_active,
            "illness_return_phase": intervals_events.get("illness_return_phase"),
            "return_to_training_guidance": intervals_events.get("return_to_training_guidance"),
            "followup_question": intervals_events.get("followup_question"),
            "soreness_status_missing": intervals_events.get("soreness_status_missing"),
            "current_day_soreness": intervals_events.get("current_day_soreness"),
            "reason": (
                "current_day_sickness_annotation"
                if current_illness
                else "illness_return_requires_review"
                if illness_followup_needed
                else None
            ),
            "meaning": (
                "An explicit current-day sickness annotation overrides Garmin/Xert readiness, "
                "training-load targets, workout candidates, and route candidates. For unresolved "
                "illness return, ask for current form and keep the provisional "
                "recommendation to rest until symptom and response assessment is resolved. "
                "Use the reviewed return phase and dose, never elapsed days, to progress. If today's Intervals "
                "soreness is missing, consult the available athlete feedback first. Ask only if the "
                "answer would change the prescription. "
                "Missing soreness never blocks or downgrades intensity by itself."
            ),
        },
        "target_resolution": decision.get("target_resolution") or {},
        "presentation_requirements": presentation_requirements(),
        "progression_advice": decision.get("progression_advice") or {},
        "freshness_summary": freshness,
        "weather_signal": {
            "home": compact_weather_signal(home_weather),
            "route": compact_weather_signal(route_weather),
        },
        "fueling_defaults": fueling_defaults,
        "source_notes": readiness_notes,
    }


def calendar_context_with_slack(
    calendar_context: dict[str, Any],
    *,
    sessions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Measure stop margins from scheduled session ends, including cleanup."""
    result = dict(calendar_context)
    session_ends = [
        datetime.fromisoformat(session["end"])
        for session in sessions or []
        if session.get("end")
    ]
    if not session_ends:
        result["cleanup_ends_at"] = None
        result["practical_stop_slack_minutes"] = None
        result["hard_stop_slack_minutes"] = None
        return result
    cleanup_end = max(session_ends) + timedelta(
        minutes=float(calendar_context.get("cleanup_buffer_minutes") or 0)
    )
    result["cleanup_ends_at"] = cleanup_end.isoformat(timespec="seconds")
    if not result.get("hard_stop"):
        next_fixed = min(
            (
                event
                for event in calendar_context.get("events") or []
                if event["classification"] == "fixed_blocker"
                and datetime.fromisoformat(event["start"]) >= cleanup_end
            ),
            key=lambda event: event["start"],
            default=None,
        )
        if next_fixed:
            result["hard_stop"] = {
                "subject": next_fixed["subject"],
                "at": next_fixed["start"],
            }
    for field, output_field in (
        ("practical_stop", "practical_stop_slack_minutes"),
        ("hard_stop", "hard_stop_slack_minutes"),
    ):
        stop = result.get(field)
        if not stop:
            result[output_field] = None
            continue
        stop_at = datetime.fromisoformat(stop["at"])
        result[output_field] = round(
            (stop_at - cleanup_end).total_seconds() / 60,
            1,
        )
    return result


def presentation_requirements() -> dict[str, Any]:
    return {
        "body_battery": {
            "required_when_present": [
                "body_battery_at_wake",
                "body_battery_most_recent",
            ],
            "meaning": (
                "For same-day recommendations, explicitly show Body Battery at "
                "wake and the most recent current value when present. Use both as "
                "part of the holistic readiness assessment alongside HRV, resting "
                "heart rate, sleep, stress, cumulative load, Xert, and body feel."
            ),
            "interpretation_rule": (
                "Treat the wake value as overnight recovery context and the current "
                "value as modeled time-of-day body-resource context. It is not "
                "measured metabolic energy, glycogen, or calorie balance. Do not let "
                "either value decide "
                "the recommendation alone, and mention staleness when the latest "
                "Body Battery datapoint is not fresh enough for the decision."
            ),
        },
        "target_watts": {
            "required": ["recovery", "vt1", "vt2", "vo2max"],
            "meaning": (
                "When presenting the final chat recommendation, the LLM should "
                "suggest day-specific target watts for recovery, VT1, VT2, and "
                "VO2Max from the context packet, user history, recent workout "
                "response, and readiness."
            ),
            "separation_rule": (
                "Keep the selected session's target watts clearly separate from "
                "the other watt anchors, which are reference targets for "
                "alternative intensities."
            ),
            "user_facing_rule": (
                "Use readable training language and do not expose raw model or "
                "JSON field names."
            ),
        }
    }


def recommendation_bias(
    *,
    wellness: dict[str, Any],
    xert: dict[str, Any],
    intervals_events: dict[str, Any],
    intensity_goal: str | None = None,
) -> str:
    if intervals_events.get("current_day_illness") or intervals_events.get("illness_training_blocked"):
        return "rest"
    if intervals_events.get("illness_followup_needed"):
        return "easy_vt1"
    if intervals_events.get("return_to_training_active"):
        return "easy_vt1"
    agreement = intensity_signal_agreement(
        wellness=wellness,
        xert=xert,
        intervals_events=intervals_events,
    )
    if "concordant_recovery_signals" in agreement["blockers"]:
        return "easy_vt1"
    if agreement["blockers"]:
        return "normal_vt1"
    if agreement["readiness_status"] == "unknown":
        return "readiness_unknown"
    if intervals_events.get("current_day_review_signals"):
        return "review_recovery"
    systems = agreement["xert_recovery_systems_to_review"]
    if systems:
        if intensity_goal in {"recovery", "vt1", "vt2"} and "low" not in systems:
            return "vt2_ok"
        return "review_recovery"
    return "high_intensity_ok"


def recommendation_bias_from_readiness_packet(
    readiness_packet: dict[str, Any], *, intensity_goal: str | None = None,
) -> str:
    """Resolve the workout-selection bias before workout candidates are ranked."""

    inputs = readiness_packet.get("recommendation_inputs") or {}
    return recommendation_bias(
        intensity_goal=intensity_goal,
        wellness=inputs.get("wellness") or {},
        xert=inputs.get("xert_recovery") or {},
        intervals_events=inputs.get("intervals_wellness_events") or {},
    )


def coach_summary_reasons(
    *,
    bias: str,
    readiness: dict[str, Any],
    wellness: dict[str, Any],
    xert: dict[str, Any],
    latest: dict[str, Any],
    freshness: dict[str, Any],
    same_day_activity: dict[str, Any],
    intervals_events: dict[str, Any],
    route_weather: list[dict[str, Any]],
) -> list[str]:
    reasons = []
    current_event = intervals_events.get("current_day") or {}
    if intervals_events.get("current_day_illness"):
        reasons.append(
            "Intervals.icu wellness marks today as sick"
            + (f": {current_event.get('comments')}." if current_event.get("comments") else ".")
        )
    else:
        recent_illness = intervals_events.get("recent_illness_events") or []
        if recent_illness:
            latest_illness = recent_illness[-1]
            reasons.append(
                "Recent Intervals.icu sickness event: {date}{comment}.".format(
                    date=latest_illness.get("date"),
                    comment=(f" ({latest_illness.get('comments')})" if latest_illness.get("comments") else ""),
                )
            )
    if intervals_events.get("illness_followup_needed"):
        reasons.append(
            intervals_events.get("followup_question")
            or "Confirm whether illness continues or this is the first healthy day."
        )
    elif intervals_events.get("return_to_training_active"):
        guidance = intervals_events.get("return_to_training_guidance") or {}
        reasons.append(
            "Return-to-training phase {day}: {duration} min, {intensity}.".format(
                day=intervals_events.get("illness_return_phase"),
                duration=guidance.get("duration_minutes"),
                intensity=guidance.get("intensity"),
            )
        )
    if same_day_activity.get("has_same_day_activity"):
        reasons.append(
            "Same-day activity already completed: {name}, {minutes} min, ended {end}.".format(
                name=same_day_activity.get("name"),
                minutes=same_day_activity.get("elapsed_minutes"),
                end=same_day_activity.get("end_local"),
            )
        )
    hrv = wellness.get("hrv_status")
    sleep_h = seconds_to_hours(wellness.get("sleep_time_seconds"))
    if hrv or sleep_h is not None:
        reasons.append(
            "Wellness: HRV {hrv}, sleep {sleep_h} h.".format(
                hrv=hrv_summary_line(wellness),
                sleep_h=round(sleep_h, 1) if sleep_h is not None else None,
            )
        )
    xert_recovery = (xert.get("projected_recovery_hours_at_planned_time") or {})
    if xert_recovery:
        reasons.append(xert_recovery_line(xert_recovery) + ".")
    if latest.get("name"):
        reasons.append(
            "{name} latest load: {minutes} min, Xert XSS {xss}, difficulty {difficulty}.".format(
                name=latest.get("name"),
                minutes=latest.get("elapsed_minutes"),
                xss=latest.get("xert_xss"),
                difficulty=latest.get("xert_difficulty"),
            )
        )
    if freshness.get("stale_inputs"):
        reasons.append(
            "Stale same-day Garmin time-series inputs: "
            + ", ".join(freshness.get("stale_inputs") or [])
            + "."
        )
    weather = compact_weather_signal(route_weather)
    if weather.get("rideable") is not None:
        reasons.append(
            "Outdoor weather: {temp}, wind {wind}, precip {precip}.".format(
                temp=weather.get("temperature_range"),
                wind=weather.get("wind_range"),
                precip=weather.get("precipitation_range"),
            )
        )
    if bias in {"readiness_unknown", "review_recovery"}:
        if intervals_events.get("current_day_review_signals"):
            reasons.insert(0, intervals_wellness_events_line(intervals_events))
        else:
            reasons.insert(0, "Provisional plan: review current body feel and recovery after recent work against the planned effort.")
    elif bias in {"vt2_ok", "high_intensity_ok"}:
        reasons.append("No major readiness guardrail blocks intensity from the input packet.")
    return reasons[:6]


def same_day_activity_context(
    latest: dict[str, Any],
    *,
    day: str,
    now: datetime,
    planned_at: datetime,
) -> dict[str, Any]:
    if not latest:
        return {"has_same_day_activity": False}

    start = parse_optional_local_datetime(
        latest.get("start_local"),
        local_timezone=now.tzinfo,
    )
    end = parse_optional_local_datetime(
        latest.get("end_local"),
        local_timezone=now.tzinfo,
    )
    if start is None or start.date().isoformat() != day:
        return {"has_same_day_activity": False}

    elapsed_minutes = number(latest.get("elapsed_minutes"))
    xert_xss = number(latest.get("xert_xss"))
    meaningful = any(
        value is not None and value >= threshold
        for value, threshold in (
            (elapsed_minutes, 45),
            (xert_xss, 50),
        )
    )
    if end is not None and end <= planned_at:
        timing = "completed_before_planned_time"
    elif end is not None and end <= now:
        timing = "completed_before_now"
    else:
        timing = "same_day_activity_detected"

    return {
        "has_same_day_activity": True,
        "name": latest.get("name"),
        "start_local": latest.get("start_local"),
        "end_local": latest.get("end_local"),
        "elapsed_minutes": elapsed_minutes,
        "icu_training_load": number(latest.get("icu_training_load")),
        "xert_xss": xert_xss,
        "xert_difficulty": latest.get("xert_difficulty"),
        "meaningful_training_load": meaningful,
        "timing": timing,
        "meaning": (
            "Use this to scale the remaining same-day dose and ambition; a prior "
            "same-day activity should not by itself block more training."
        ),
    }


def hrv_summary_line(wellness: dict[str, Any]) -> str:
    status = wellness.get("hrv_status")
    last = wellness.get("hrv_last_night_avg")
    mean_3d = wellness.get("hrv_3day_mean")
    mean_7d = wellness.get("hrv_7day_mean")
    garmin_weekly = wellness.get("hrv_weekly_avg")
    trend = wellness.get("hrv_trend_status")
    low = wellness.get("hrv_balanced_low")
    upper = wellness.get("hrv_balanced_upper")
    low_upper = wellness.get("hrv_low_upper")

    parts = []
    if last is not None:
        parts.append(f"last night {last} ms")
    if mean_3d is not None:
        parts.append(f"3-day mean {mean_3d}")
    if mean_7d is not None:
        parts.append(f"7-day mean {mean_7d}")
    elif garmin_weekly is not None:
        parts.append(f"Garmin weekly {garmin_weekly} diagnostic")
    if trend is not None:
        parts.append(f"trend={trend}")
    if low is not None and upper is not None:
        parts.append(f"balanced {low}-{upper}")
    elif low_upper is not None:
        parts.append(f"low<= {low_upper}")
    if not parts:
        return f"missing numeric HRV context; status={status}" if status is not None else "missing"
    if status:
        return f"{', '.join(parts)}; status={status}"
    return ", ".join(parts)


def garmin_readiness_line(readiness: dict[str, Any]) -> str:
    score = readiness.get("training_readiness_score")
    level = readiness.get("training_readiness_level")
    recovery = readiness.get("projected_recovery_time_hours_at_planned")
    if recovery is None:
        recovery = readiness.get("projected_recovery_time_hours_now")
    recovery_factor = readiness.get("recovery_time_factor_feedback")
    status = readiness.get("training_status_feedback")
    pieces = [f"Garmin Training Readiness {score}/100"]
    if level:
        pieces.append(f"level={level}")
    if recovery is not None:
        recovery_text = (
            f"Garmin Recovery Time {recovery} h to modeled full recovery for "
            "the next hard workout; not a ban on easy or moderate activity"
        )
        if recovery_factor:
            recovery_text += f"; recovery_factor={recovery_factor}"
        pieces.append(recovery_text)
    if status:
        pieces.append(f"training_status={status}")
    driver_text = garmin_readiness_driver_line(readiness)
    if driver_text:
        pieces.append(driver_text)
    return ", ".join(pieces) + "."


def garmin_readiness_driver_line(readiness: dict[str, Any]) -> str:
    drivers = readiness.get("training_readiness_drivers") or {}
    families = readiness.get("training_readiness_driver_families") or {}
    labels = {
        "sleep_score": "sleep score",
        "hrv_status": "HRV status",
        "sleep_history": "sleep history",
        "stress_history": "stress history",
        "acute_load": "acute load",
        "recovery_time": "Recovery Time",
    }
    family_labels = {
        "autonomic_lifestyle": "sleep/HRV/stress",
        "load_recovery": "load/recovery",
    }
    summaries = []
    for family in ("autonomic_lifestyle", "load_recovery"):
        observations = []
        for key in families.get(family) or []:
            feedback = (drivers.get(key) or {}).get("feedback")
            if feedback:
                observations.append(f"{labels.get(key, key)}={feedback}")
        if observations:
            summaries.append(f"{family_labels[family]}: {', '.join(observations)}")
    if not summaries:
        return ""
    return (
        "grouped drivers (diagnostic only; overlapping signals): "
        + "; ".join(summaries)
    )


def garmin_vo2max_line(vo2max: dict[str, Any] | None) -> str:
    estimates = (vo2max or {}).get("estimates") or {}
    parts = []
    for category in ("cycling", "generic"):
        estimate = estimates.get(category) or {}
        value = estimate.get("precise_value")
        if value is None:
            value = estimate.get("value")
        if value is None:
            continue
        detail = f"{category}={value} ml/kg/min"
        if estimate.get("calendar_date"):
            detail += f" on {estimate['calendar_date']}"
        if estimate.get("age_days_at_requested_date") is not None:
            detail += f" ({estimate['age_days_at_requested_date']} d old)"
        parts.append(detail)
    if not parts:
        return "missing"
    return (
        ", ".join(parts)
        + "; modeled sport-category estimates, trend context only—not acute "
        "readiness or a workout-dose input"
    )


def sleep_summary_line(wellness: dict[str, Any], readiness: dict[str, Any] | None = None) -> str:
    score = wellness.get("sleep_score")
    sleep_h = seconds_to_hours(wellness.get("sleep_time_seconds"))
    factor = (readiness or {}).get("sleep_score_factor_feedback")
    parts = []
    if score is not None:
        text = f"score {score}"
        if factor:
            text += f"; factor={factor}"
        parts.append(text)
    if sleep_h is not None:
        parts.append(f"{round(sleep_h, 1)} h")
    return ", ".join(parts) if parts else "missing"


def body_battery_summary_line(wellness: dict[str, Any]) -> str:
    at_wake = wellness.get("body_battery_at_wake")
    most_recent = wellness.get("body_battery_most_recent")
    if at_wake is not None and most_recent is not None:
        return f"at wake={at_wake}, now={most_recent}"
    if most_recent is not None:
        return f"now={most_recent}"
    if at_wake is not None:
        prefix = f"at wake={at_wake}"
    else:
        prefix = ""

    observed = wellness.get("body_battery_most_recent_observed")
    current_status = (wellness.get("garmin_signal_status") or {}).get(
        "body_battery_current"
    ) or {}
    if observed is not None and current_status.get("reason") == "stale_or_wrong_day":
        detail = f"observed now={observed}, but stale"
        age_minutes = number(current_status.get("age_minutes"))
        if age_minutes is not None:
            detail += f" ({round(age_minutes, 1)} min old)"
        detail += "; excluded from readiness decisions"
        return f"{prefix}, {detail}" if prefix else detail
    if prefix:
        return prefix
    return "missing"


def xert_recovery_line(projected: dict[str, Any]) -> str:
    low = number(projected.get("low"))
    high = number(projected.get("high"))
    peak = number(projected.get("peak"))
    if low is None and high is None and peak is None:
        return ""
    values = "{low}/{high}/{peak}".format(
        low=low if low is not None else projected.get("low"),
        high=high if high is not None else projected.get("high"),
        peak=peak if peak is not None else projected.get("peak"),
    )
    if xert_supports_intensity(projected):
        return f"Xert projected recovery low/high/peak: {values} h; all systems fresh"
    if low is not None and low <= 0:
        return f"Xert projected recovery low/high/peak: {values} h; low system fresh"
    return f"Xert projected recovery low/high/peak: {values} h"


def xert_supports_intensity(projected: dict[str, Any]) -> bool | None:
    values = [
        number(projected.get(key))
        for key in ("low", "high", "peak")
    ]
    known = [value for value in values if value is not None]
    if len(known) < 3:
        return None
    return all(value <= 0 for value in known)


def xert_supports_vt2(projected: dict[str, Any]) -> bool | None:
    low = number(projected.get("low"))
    if low is None:
        return None
    return low <= 0


def load_focus_summary_line(load_focus: dict[str, Any] | None) -> str:
    load_focus = load_focus or {}
    feedback = load_focus.get("feedback")
    monthly = load_focus.get("monthly_load") or {}
    targets = load_focus.get("target_ranges") or {}
    parts = []
    for key, label in (
        ("aerobic_low", "low aerobic"),
        ("aerobic_high", "high aerobic"),
        ("anaerobic", "anaerobic"),
    ):
        value = monthly.get(key)
        target = targets.get(key) or {}
        if value is None:
            continue
        if target.get("min") is not None and target.get("max") is not None:
            parts.append(f"{label} {round(value)} target {target.get('min')}-{target.get('max')}")
        else:
            parts.append(f"{label} {round(value)}")
    acwr = load_focus.get("acwr")
    acwr_status = load_focus.get("acwr_status")
    if acwr is not None:
        acwr_text = f"ACWR {acwr}"
        if acwr_status:
            acwr_text += f"; acwr_status={acwr_status}"
        parts.append(acwr_text)
    if feedback:
        parts.append(f"load_focus_feedback={feedback}")
    return "; ".join(parts) if parts else "missing"


def caution_summary_line(readiness: dict[str, Any], wellness: dict[str, Any]) -> str:
    sleep_score = number(wellness.get("sleep_score"))
    hrv = hrv_readiness_risk(wellness)
    resting_hr = resting_hr_readiness_risk(wellness)
    body_battery = body_battery_readiness_risk(wellness)
    parts = [
        ("sleep_score", sleep_score_caution(sleep_score)),
        ("hrv", hrv),
        ("resting_hr", resting_hr),
    ]
    visible = [f"{name} {round(value, 2)}" for name, value in parts if value is not None]
    total = numeric_caution_score(
        sleep_score=sleep_score,
        hrv_risk=hrv,
        resting_hr_risk=resting_hr,
        body_battery_risk=body_battery,
    )
    if not visible:
        return (
            f"grouped autonomic/recovery missing; body_resources_support "
            f"{round(body_battery, 2)} (diagnostic only)"
            if body_battery is not None
            else "missing"
        )
    body_support = (
        f"; body_resources_support {round(body_battery, 2)} (diagnostic only)"
        if body_battery is not None
        else ""
    )
    return (
        f"grouped autonomic/recovery {round(total, 2)} "
        f"({', '.join(visible)}){body_support}"
    )


def hrv_readiness_risk(wellness: dict[str, Any]) -> float | None:
    """Return a continuous HRV caution score from 0.0 to 1.0.

    Use the actual three-night mean as the acute decision signal. Garmin's
    rounded weekly average remains diagnostic-only. Fall back to last night
    when three valid nights are unavailable.
    """

    acute = number(wellness.get("hrv_3day_mean"))
    nights_used = number(wellness.get("hrv_nights_used_3d"))
    last = number(wellness.get("hrv_last_night_avg"))
    low = number(wellness.get("hrv_balanced_low"))
    upper = number(wellness.get("hrv_balanced_upper"))

    value = acute if acute is not None and nights_used == 3 else last
    return hrv_value_risk(value=value, low=low, upper=upper)


def hrv_last_night_risk(wellness: dict[str, Any]) -> float | None:
    return hrv_value_risk(
        value=number(wellness.get("hrv_last_night_avg")),
        low=number(wellness.get("hrv_balanced_low")),
        upper=number(wellness.get("hrv_balanced_upper")),
    )


def hrv_value_risk(
    *,
    value: float | None,
    low: float | None,
    upper: float | None,
) -> float | None:
    if value is None or low is None or upper is None:
        return None
    if low <= value <= upper:
        return 0.0
    if value < low:
        return min(1.0, max(0.0, (low - value) / max(1.0, low * 0.12)))
    return min(0.75, max(0.0, (value - upper) / max(1.0, upper * 0.12)))


def hrv_trend_status(wellness: dict[str, Any]) -> str:
    value = number(wellness.get("hrv_7day_mean"))
    low = number(wellness.get("hrv_balanced_low"))
    upper = number(wellness.get("hrv_balanced_upper"))
    if value is None or low is None or upper is None:
        return "unavailable"
    if value < low:
        return "below_balanced_trend"
    if value > upper:
        return "above_balanced_trend"
    return "within_balanced_trend"


def intensity_signal_agreement(
    *,
    wellness: dict[str, Any],
    xert: dict[str, Any],
    intervals_events: dict[str, Any],
) -> dict[str, Any]:
    """Require agreement before direct signals block hard intensity."""

    risks = {
        "hrv_3day": hrv_readiness_risk(wellness),
        "hrv_last_night": hrv_last_night_risk(wellness),
        "sleep": sleep_score_caution(number(wellness.get("sleep_score"))),
        "resting_hr": resting_hr_readiness_risk(wellness),
        "body_battery": body_battery_readiness_risk(wellness),
    }
    autonomic_recovery_risk = max_present(
        risks["hrv_3day"],
        risks["sleep"],
        risks["resting_hr"],
    )
    moderate = [
        key
        for key in ("hrv_3day", "sleep", "resting_hr")
        if risks[key] is not None and risks[key] >= 0.25
    ]
    severe = [
        key
        for key in ("hrv_3day", "hrv_last_night", "sleep", "resting_hr")
        if risks[key] is not None and risks[key] >= 0.75
    ]
    projected = xert.get("projected_recovery_hours_at_planned_time") or {}
    xert_vt2_ready = xert_supports_vt2(projected)
    xert_high_ready = xert_supports_intensity(projected)
    soreness = number(intervals_events.get("current_day_soreness"))

    direct_blockers = []
    # Conservative screening policy, not independent votes or a validated
    # physiological cutoff. Last night never overrides a complete three-night
    # mean; without history it already enters once through hrv_readiness_risk.
    decision_severe = [key for key in moderate if risks[key] >= 0.75]
    if decision_severe and len(moderate) >= 2:
        direct_blockers.append("concordant_recovery_signals")
    if soreness is not None and soreness >= 3:
        direct_blockers.append("high_soreness")

    systems_to_review = [
        system for system in ("low", "high", "peak")
        if (hours := number(projected.get(system))) is not None and hours > 0
    ]
    subjective_review = intervals_events.get("current_day_review_signals") or []
    review_signals = [*moderate, *subjective_review]
    if autonomic_recovery_risk is None:
        review_signals.append("direct_recovery_evidence_unavailable")
    review_signals.extend(f"xert_{system}_recovery" for system in systems_to_review)
    if risks["hrv_last_night"] is not None and risks["hrv_last_night"] >= 0.25:
        review_signals.append("hrv_last_night")
    sleep_hours = seconds_to_hours(wellness.get("sleep_time_seconds"))
    if sleep_hours is not None and sleep_hours < 6:
        review_signals.append("short_sleep")

    readiness_status = "screened"
    if direct_blockers:
        readiness_status = "limited"
    elif subjective_review:
        readiness_status = "review"
    elif autonomic_recovery_risk is None:
        readiness_status = "unknown"
    elif systems_to_review:
        readiness_status = "review"
    direct_permission = not direct_blockers
    if direct_permission and (readiness_status == "unknown" or subjective_review):
        direct_permission = None
    return {
        "readiness_status": readiness_status,
        "review_required": bool(review_signals or direct_blockers),
        "review_signals": review_signals,
        "xert_recovery_systems_to_review": systems_to_review,
        "vt2_allowed": None if "low" in systems_to_review and not direct_blockers else direct_permission,
        "high_intensity_allowed": None if systems_to_review and not direct_blockers else direct_permission,
        "blockers": direct_blockers,
        "vt2_blockers": list(direct_blockers),
        "high_intensity_blockers": list(direct_blockers),
        "moderate_signals": moderate,
        "severe_signals": severe,
        "risks": rounded_optional_map(risks),
        "grouped_families": {
            "autonomic_recovery": round(autonomic_recovery_risk, 3)
            if autonomic_recovery_risk is not None
            else None,
            "body_resources_support": round(risks["body_battery"], 3)
            if risks["body_battery"] is not None
            else None,
        },
        "body_resources_used_as_independent_signal": False,
        "xert_vt2_ready": xert_vt2_ready,
        "xert_high_intensity_ready": xert_high_ready,
        "soreness": soreness,
        "rule": (
            "HRV, resting heart rate, and Sleep Score are one overlapping "
            "autonomic/recovery family. Isolated deviations require body-feel and "
            "execution review, not automatic intensity rejection. A severe decision "
            "signal with another adverse signal invokes conservative intensity "
            "screening; this is a heuristic, not independent confirmation or a "
            "validated physiological cutoff. It does not prescribe duration. "
            "Body Battery is supporting diagnostic context, not an "
            "additional independent signal. High soreness can limit intensity. "
            "Review projected Xert hours for the systems relevant to the planned "
            "effort alongside actual load, recovery and current body feel."
        ),
    }


def annotate_hrv_decision_context(readiness_packet: dict[str, Any]) -> None:
    inputs = readiness_packet.get("recommendation_inputs") or {}
    wellness = inputs.get("wellness") or {}
    wellness["hrv_acute_risk"] = hrv_readiness_risk(wellness)
    wellness["hrv_last_night_risk"] = hrv_last_night_risk(wellness)
    wellness["hrv_trend_status"] = hrv_trend_status(wellness)
    wellness["hrv_decision_source"] = (
        "three_night_mean"
        if number(wellness.get("hrv_nights_used_3d")) == 3
        else "last_night_fallback"
    )
    inputs["intensity_signal_agreement"] = intensity_signal_agreement(
        wellness=wellness,
        xert=inputs.get("xert_recovery") or {},
        intervals_events=inputs.get("intervals_wellness_events") or {},
    )


def numeric_caution_score(
    *,
    sleep_score: float | None,
    hrv_risk: float | None,
    resting_hr_risk: float | None,
    body_battery_risk: float | None,
) -> float:
    # These signals share upstream autonomic and overnight-recovery evidence.
    # Keep Body Battery visible elsewhere as support, but do not count it as an
    # additional independent vote after HRV, resting HR, and sleep are used.
    _ = body_battery_risk
    return max_present(
        sleep_score_caution(sleep_score),
        hrv_risk,
        resting_hr_risk,
    ) or 0.0


def sleep_score_caution(score: float | None) -> float | None:
    if score is None:
        return None
    return inverse_linear_risk(score, good=80.0, bad=50.0)


def resting_hr_readiness_risk(wellness: dict[str, Any]) -> float | None:
    current = number(wellness.get("resting_hr"))
    baseline = number(wellness.get("resting_hr_7day"))
    if current is None or baseline is None or baseline <= 0:
        return None
    relative_increase = (current - baseline) / baseline
    return linear_risk(relative_increase, good=0.02, bad=0.10)


def body_battery_readiness_risk(wellness: dict[str, Any]) -> float | None:
    at_wake = number(wellness.get("body_battery_at_wake"))
    current = number(wellness.get("body_battery_most_recent"))
    value = at_wake if at_wake is not None else current
    if value is None:
        return None
    return inverse_linear_risk(value, good=55.0, bad=25.0)


def max_present(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def rounded_optional_map(values: dict[str, float | None]) -> dict[str, float | None]:
    return {
        key: round(value, 3) if value is not None else None
        for key, value in values.items()
    }


def linear_risk_optional(
    value: float | None, *, good: float, bad: float
) -> float | None:
    return None if value is None else linear_risk(value, good=good, bad=bad)


def linear_risk(value: float, *, good: float, bad: float) -> float:
    if value <= good:
        return 0.0
    if value >= bad:
        return 1.0
    return (value - good) / (bad - good)


def inverse_linear_risk(value: float, *, good: float, bad: float) -> float:
    if value >= good:
        return 0.0
    if value <= bad:
        return 1.0
    return (good - value) / (good - bad)


def intensity_guardrails(
    *,
    wellness: dict[str, Any],
    freshness: dict[str, Any],
    intervals_events: dict[str, Any] | None = None,
) -> list[str]:
    guardrails = []
    if (intervals_events or {}).get("current_day_illness"):
        guardrails.extend(["no_training_current_illness", "avoid_intensity_current_illness"])
    elif (intervals_events or {}).get("illness_followup_needed"):
        guardrails.extend(
            ["ask_current_form_after_sickness", "avoid_intensity_until_illness_review"]
        )
    elif (intervals_events or {}).get("return_to_training_active"):
        guardrails.extend(
            ["return_to_training_ramp_after_illness", "avoid_intensity_during_graded_return"]
        )
    hrv_risk = hrv_readiness_risk(wellness)
    resting_hr_risk = resting_hr_readiness_risk(wellness)
    sleep_h = seconds_to_hours(wellness.get("sleep_time_seconds"))
    hrv_review_risk = max_present(hrv_risk, hrv_last_night_risk(wellness))
    if hrv_review_risk is not None and hrv_review_risk >= 0.25:
        guardrails.append("caution_hrv_near_or_outside_baseline")
    if resting_hr_risk is not None and resting_hr_risk >= 0.75:
        guardrails.append("review_elevated_resting_hr")
    if sleep_h is not None and sleep_h < 6:
        guardrails.append("review_short_sleep_and_session_demands")
    if freshness.get("guidance") == "sync_watch_before_hard_session":
        guardrails.append("sync_watch_before_hard_session")
    return guardrails


def primary_indoor_option(
    workouts: dict[str, Any],
    *,
    bias: str,
    target_resolution: dict[str, Any],
) -> dict[str, Any] | None:
    if workouts.get("available") is False:
        return None
    if bias == "active_recovery_only":
        return {
            "option_label": "optional",
            "name": "Active recovery spin",
            "duration_minutes": 45.0,
            "xss": None,
            "difficulty": None,
            "execution_note": (
                "Very easy recovery ride, normally 45 min within a 30-60 min range, "
                "roughly 130-165 W, "
                "no structured workout and no added training target."
            ),
        }
    options = workouts.get("relevant_options") or []
    if not options:
        return workouts.get("recommended")
    target_minutes = number(target_resolution.get("target_minutes"))
    easy_vt1_order = (
        ("longer", "normal", "conservative", "shorter")
        if target_minutes is not None and target_minutes >= 100
        else
        ("normal", "conservative", "shorter", "longer")
        if target_minutes is not None and target_minutes >= 84
        else
        ("conservative", "shorter", "normal", "longer")
        if target_minutes is not None and target_minutes >= 72
        else ("shorter", "conservative", "normal", "longer")
    )
    preferred_labels = {
        "rest": ("shorter", "conservative", "normal", "longer"),
        "easy_vt1": easy_vt1_order,
        "normal_vt1": ("normal", "conservative", "longer", "shorter"),
        "vt2_ok": ("normal", "longer", "conservative", "shorter"),
        "high_intensity_ok": ("normal", "longer", "conservative", "shorter"),
    }.get(bias, ("normal", "conservative", "shorter", "longer"))
    target_load = number(target_resolution.get("target_load"))
    if bias == "easy_vt1" and target_load is not None:
        near_or_below = [
            option
            for option in options
            if (number(option.get("xss")) is not None and number(option.get("xss")) <= target_load * 1.05)
        ]
        if near_or_below:
            return min(
                near_or_below,
                key=lambda option: abs((number(option.get("xss")) or 0.0) - target_load),
            )
    for label in preferred_labels:
        for option in options:
            if option.get("option_label") == label:
                return option
    return options[0] if options else None


def primary_outdoor_option(
    route: dict[str, Any],
    *,
    route_weather: list[dict[str, Any]],
    bias: str,
) -> dict[str, Any] | None:
    if route and route.get("available") is False:
        return None
    if bias == "active_recovery_only":
        return {
            "name": "Active recovery only",
            "moving_minutes": 45.0,
            "distance_km": None,
            "training_load": None,
            "execution_note": (
                "Optional only: 30-60 min, normally 45 min, flat and very easy. Avoid turning it "
                "into a second endurance workout."
            ),
            "weather": compact_weather_signal(route_weather),
        }
    if not route:
        return None
    option = {
        "name": route.get("name"),
        "date": route.get("date"),
        "id": route.get("id"),
        "moving_minutes": route.get("moving_minutes"),
        "distance_km": route.get("distance_km"),
        "training_load": route.get("training_load"),
        "xss": route.get("xss"),
        "load_source": route.get("load_source"),
        "url": route.get("url"),
        "url_meaning": route.get("url_meaning"),
        "intervals_activity_url": route.get("intervals_activity_url") or route.get("url"),
        "xert_activity_url": route.get("xert_activity_url"),
        "xert_map_url": route.get("xert_map_url"),
        "xert_map_local_path": route.get("xert_map_local_path"),
        "route_map_status": route.get("route_map_status"),
        "route_reference_note": route.get("route_reference_note"),
        "weather": compact_weather_signal(route_weather),
    }
    if bias in {"rest", "easy_vt1"}:
        option["execution_note"] = "Keep it easier than the historical route load; avoid threshold/VO2 work."
    elif bias in {"vt2_ok", "high_intensity_ok"}:
        option["execution_note"] = "Outdoor route is viable if it matches the session goal."
    else:
        option["execution_note"] = "Use as controlled endurance/VT1 unless a harder goal is explicit."
    return option


def compact_weather_signal(hourly: list[dict[str, Any]]) -> dict[str, Any]:
    if not hourly:
        return {"rideable": None, "summary": "missing"}
    temps = compact_numbers(row.get("air_temperature") for row in hourly)
    winds = compact_numbers(row.get("wind_speed") for row in hourly)
    precip = compact_numbers(row.get("precipitation_amount_next_1h") for row in hourly)
    max_precip = max(precip) if precip else 0.0
    max_wind = max(winds) if winds else 0.0
    max_temp = max(temps) if temps else None
    rideable = max_precip <= 0.2 and max_wind <= 8.0
    heat_note = "warm" if max_temp is not None and max_temp >= 24 else "normal"
    return {
        "rideable": rideable,
        "heat_note": heat_note,
        "temperature_range": range_text(temps, "C"),
        "wind_range": range_text(winds, "m/s"),
        "precipitation_range": range_text(precip, "mm"),
        "symbols": sorted(
            {
                str(row.get("symbol_code_next_1h"))
                for row in hourly
                if row.get("symbol_code_next_1h")
            }
        ),
    }


def timing_guidance(
    *,
    bias: str,
    freshness: dict[str, Any],
    home_weather: list[dict[str, Any]],
    route_weather: list[dict[str, Any]],
    now: datetime,
    planned_at: datetime,
    planned_at_source: str,
) -> dict[str, Any]:
    route_signal = compact_weather_signal(route_weather)
    home_signal = compact_weather_signal(home_weather)
    evaluated_window = weather_time_window(route_weather) or weather_time_window(home_weather)
    coolest = coolest_weather_time(route_weather) or coolest_weather_time(home_weather)
    planned_label = planned_at.strftime("%H:%M")
    assumed = planned_at_source == "default"

    guidance_parts: list[str] = []
    if assumed:
        guidance_parts.append(
            f"No workout time was supplied, so {planned_label} is an assumed planning anchor."
        )
    else:
        guidance_parts.append(f"Workout time evaluated around {planned_label}.")

    if route_signal.get("rideable") is True:
        if route_signal.get("heat_note") == "warm" and coolest:
            guidance_parts.append(
                f"Outdoor riding is viable, but the cooler edge of the checked window is around {coolest}."
            )
        elif evaluated_window:
            guidance_parts.append(f"Outdoor riding looks viable through {evaluated_window}.")
        else:
            guidance_parts.append("Outdoor riding looks viable in the checked weather window.")
    elif route_signal.get("rideable") is False:
        guidance_parts.append("Outdoor timing is weather-limited; prefer indoor unless conditions improve.")
    else:
        guidance_parts.append("Outdoor timing could not be judged from the available forecast.")

    if bias == "rest":
        guidance_parts.append("If you train anyway, make it a short easy spin later in the day only if feel improves.")
    elif bias == "active_recovery_only":
        guidance_parts.append("A meaningful same-day ride is already done; only active recovery is sensible now.")
    elif bias == "easy_vt1":
        guidance_parts.append("For easy VT1, indoor timing is flexible; for anything harder, sync Garmin first.")
    elif bias in {"vt2_ok", "high_intensity_ok"}:
        guidance_parts.append("Intensity is best placed after a normal warmup window, not squeezed in late.")
    else:
        guidance_parts.append("Indoor timing is flexible; choose the slot that leaves time to eat and cool down.")

    if freshness.get("guidance") == "sync_watch_before_hard_session":
        guidance_parts.append("Do not upgrade intensity from this packet without a fresh watch/Garmin sync.")

    return {
        "planned_at_local": planned_at.isoformat(timespec="seconds"),
        "planned_at_source": planned_at_source,
        "assumed_planned_at": assumed,
        "now_local": now.isoformat(timespec="seconds"),
        "evaluated_weather_window": evaluated_window,
        "coolest_checked_time": coolest,
        "home_weather": home_signal,
        "route_weather": route_signal,
        "summary": " ".join(guidance_parts),
    }


def weather_time_window(hourly: list[dict[str, Any]]) -> str | None:
    times = [parse_hourly_time(row) for row in hourly if parse_hourly_time(row) is not None]
    if not times:
        return None
    return f"{times[0].strftime('%H:%M')}-{times[-1].strftime('%H:%M')}"


def coolest_weather_time(hourly: list[dict[str, Any]]) -> str | None:
    candidates = []
    for row in hourly:
        temp = number(row.get("air_temperature"))
        timestamp = parse_hourly_time(row)
        if temp is None or timestamp is None:
            continue
        candidates.append((temp, timestamp))
    if not candidates:
        return None
    _, timestamp = min(candidates, key=lambda item: item[0])
    return timestamp.strftime("%H:%M")


def parse_hourly_time(row: dict[str, Any]) -> datetime | None:
    raw = row.get("time_local")
    if not raw:
        return None
    parsed = datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        raise ValueError("Weather time_local must include an explicit UTC offset.")
    return parsed


def compact_xert_workout_recommendations(
    payload: dict[str, Any],
    *,
    target_minutes: float,
    target_load: float,
    readiness_bias: str = "normal_vt1",
    preferred_workout_name_contains: str | None = None,
) -> dict[str, Any]:
    from_mcp_workouts = isinstance(payload, dict) and "workouts" in payload
    exercises = (
        payload.get("workouts") if from_mcp_workouts else payload.get("exercises")
    ) if isinstance(payload, dict) else []
    if not isinstance(exercises, list):
        exercises = []
    workouts = [
        compact_xert_workout(row, target_minutes=target_minutes, target_load=target_load)
        for row in exercises
        if isinstance(row, dict)
        and (row.get("exerciseType") == "Workout" or from_mcp_workouts)
    ]
    workouts = [row for row in workouts if row is not None]
    low_intensity = [row for row in workouts if row["low_intensity_candidate"]]
    higher_intensity = [row for row in workouts if not row["low_intensity_candidate"]]
    eligible_low_intensity, bias_suppressed = filter_workouts_for_readiness_bias(
        low_intensity,
        readiness_bias=readiness_bias,
        target_minutes=target_minutes,
        target_load=target_load,
    )
    preferred_name = (preferred_workout_name_contains or "").casefold()

    def rank(row: dict[str, Any]) -> tuple[bool, float]:
        return (
            bool(preferred_name and preferred_name in row["name"].casefold()),
            workout_rank_key(row, target_minutes=target_minutes, target_load=target_load),
        )

    ranked = sorted(eligible_low_intensity, key=rank, reverse=True)
    ranked_higher_intensity = sorted(higher_intensity, key=rank, reverse=True)
    if readiness_bias in {"rest", "active_recovery_only", "easy_vt1"}:
        bias_suppressed.extend(higher_intensity)
        ranked_higher_intensity = []
    return {
        "source": "xert_recommended_training_compact",
        "policy": (
            "Prioritize suitable workouts whose name contains the configured text. "
            "Rank all other eligible workouts as well. "
            "Present a small menu when several indoor workouts fit the same goal. "
            "Assume indoor trainer workouts are ridden in ERG mode by default; "
            "describe fixed workout targets or workout-intensity adjustments, "
            "not free-riding or gliding above target watts. "
            "Reserve slope mode language for explicitly requested slope sessions "
            "or VO2Max/opener/standing/harder over-threshold work. "
            "For default same-day advice, keep threshold/VO2 or other high-intensity "
            "structures out of the primary candidate list unless the session goal and "
            "readiness explicitly support intensity. "
            "Suggest power, duration or repetition changes only when they serve readiness, "
            "load target or session goal; do not vary structure just for variety."
        ),
        "target_minutes": target_minutes,
        "target_load": target_load,
        "readiness_bias": readiness_bias,
        "readiness_bias_filter": {
            "active": readiness_bias in {"rest", "active_recovery_only", "easy_vt1"},
            "meaning": (
                "Workout structure is filtered by readiness bias. Route ranking is unchanged."
            ),
            "suppressed_count": len(bias_suppressed),
        },
        "preferred_workout_name_contains": preferred_workout_name_contains,
        "candidates": ranked[:5],
        "higher_intensity_candidates": ranked_higher_intensity[:5],
        "suppressed_by_readiness_bias": [
            suppressed_workout_trace(row, readiness_bias=readiness_bias)
            for row in bias_suppressed[:10]
        ],
        "recommended": ranked[0] if ranked else None,
        "relevant_options": relevant_indoor_options(ranked),
    }


def filter_workouts_for_readiness_bias(
    workouts: list[dict[str, Any]],
    *,
    readiness_bias: str,
    target_minutes: float,
    target_load: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if readiness_bias not in {"rest", "active_recovery_only", "easy_vt1"}:
        return workouts, []

    allowed_tags = (
        {"recovery"}
        if readiness_bias in {"rest", "active_recovery_only"}
        else {"recovery", "endurance"}
    )
    eligible = []
    suppressed = []
    for row in workouts:
        tags = set(row.get("intensity_tags") or [])
        duration = number(row.get("duration_minutes"))
        xss = number(row.get("xss"))
        dose_fits = (
            (duration is None or duration <= target_minutes * 1.25)
            and (xss is None or xss <= target_load * 1.35)
        )
        if tags & allowed_tags and dose_fits:
            eligible.append(row)
        else:
            suppressed_row = dict(row)
            reasons = []
            if not tags & allowed_tags:
                reasons.append("workout_structure")
            if not dose_fits:
                reasons.append("workout_dose")
            suppressed_row["readiness_bias_suppression_reasons"] = reasons
            suppressed.append(suppressed_row)
    return eligible, suppressed


def suppressed_workout_trace(
    row: dict[str, Any],
    *,
    readiness_bias: str,
) -> dict[str, Any]:
    return {
        "name": row.get("name"),
        "path": row.get("path"),
        "url": row.get("url"),
        "duration_minutes": row.get("duration_minutes"),
        "xss": row.get("xss"),
        "intensity_tags": row.get("intensity_tags"),
        "suppression_reasons": row.get("readiness_bias_suppression_reasons"),
        "suppressed_reason": (
            f"Workout does not match readiness bias {readiness_bias} for structure and/or dose."
        ),
    }


def relevant_indoor_options(
    ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a compact menu of viable indoor options for chat recommendations."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in ranked:
        label = indoor_option_label(row)
        if not label:
            continue
        key = str(row.get("path") or row.get("url") or row.get("name"))
        if key in seen:
            continue
        seen.add(key)
        option = dict(row)
        option["option_label"] = label
        options.append(option)
        if len(options) >= 4:
            break

    return options


def indoor_option_label(row: dict[str, Any]) -> str | None:
    minutes = number(row.get("duration_minutes"))
    if minutes is None:
        return None
    if minutes <= 70:
        return "shorter"
    if minutes <= 82:
        return "conservative"
    if minutes <= 98:
        return "normal"
    return "longer"


def compact_xert_workout(
    row: dict[str, Any],
    *,
    target_minutes: float,
    target_load: float,
) -> dict[str, Any] | None:
    name = str(row.get("name") or "")
    path = row.get("path") or (row.get("workout") or {}).get("path")
    if not name or not path:
        return None
    duration_seconds = number(row.get("duration_seconds"))
    if duration_seconds is None:
        duration_seconds = number(row.get("duration"))
    duration_minutes = round((duration_seconds or 0) / 60, 1)
    xss_payload = row.get("xss")
    if isinstance(xss_payload, dict):
        xss = number(xss_payload.get("total"))
        low_xss = number(xss_payload.get("low"))
        high_xss = number(xss_payload.get("high"))
        peak_xss = number(xss_payload.get("peak"))
    else:
        xss = number(xss_payload)
        low_xss = number(row.get("xlss"))
        high_xss = number(row.get("xhss"))
        peak_xss = number(row.get("xpss"))
    intensity = workout_intensity_profile(row, name=name)
    structure = workout_structure_guidance(name=name, duration_minutes=duration_minutes)
    result = {
        "name": name,
        "path": path,
        "url": row.get("url"),
        "intensity_tags": intensity["tags"],
        "low_intensity_candidate": intensity["low_intensity_candidate"],
        "suppressed_from_default": intensity["suppressed_from_default"],
        "suppressed_reason": intensity["suppressed_reason"],
        "owner": row.get("owner"),
        "liked": row.get("liked"),
        "disliked": row.get("disliked"),
        "duration_minutes": duration_minutes,
        "xss": xss,
        "low_xss": low_xss,
        "high_xss": high_xss,
        "peak_xss": peak_xss,
        "difficulty": row.get("difficulty"),
        "rating": row.get("rating"),
        "focus": row.get("focus"),
        "specificity": row.get("specificity"),
        "spec_rating": row.get("specRating"),
        "suitability": row.get("suitability"),
        "target_suitability": row.get("targetSuitability"),
        "avg_power": row.get("avg_power"),
        "max_power": row.get("max_power"),
        "total_intervals": row.get("total_intervals"),
        "structure": structure,
        "suggested_adjustment": workout_adjustment(
            name=name,
            duration_minutes=duration_minutes,
            xss=xss,
            target_minutes=target_minutes,
            target_load=target_load,
        ),
    }
    return result


def workout_structure_guidance(name: str, *, duration_minutes: float) -> dict[str, Any]:
    """Return chat guidance that avoids adding warmup on top of a workout."""

    main_set_minutes = workout_main_set_minutes(name)
    guidance = {
        "total_workout_minutes": duration_minutes,
        "main_set_minutes": main_set_minutes,
        "warmup_instruction": "use_built_in_warmup",
        "chat_rule": (
            "When recommending this as an existing Xert workout, tell the user "
            "to ride the workout as-is in ERG and use its built-in warmup/cooldown. "
            "Do not prescribe an extra warmup unless the recommendation explicitly "
            "modifies or extends the workout."
        ),
    }
    if main_set_minutes is not None and duration_minutes > main_set_minutes:
        guidance["built_in_non_work_minutes"] = round(duration_minutes - main_set_minutes, 1)
        guidance["summary"] = (
            f"Workout totals {duration_minutes:g} min and appears to include a "
            f"{main_set_minutes:g} min main set plus built-in warmup/cooldown."
        )
    else:
        guidance["built_in_non_work_minutes"] = None
        guidance["summary"] = (
            f"Workout totals {duration_minutes:g} min; treat warmup/cooldown as "
            "part of the selected workout unless the structure is explicitly changed."
        )
    return guidance


def workout_main_set_minutes(name: str) -> float | None:
    match = re.search(r"\bVT[12]\s+(\d+(?:[.,]\d+)?)\s*min\b", name, flags=re.IGNORECASE)
    if not match:
        return None
    return number(match.group(1).replace(",", "."))


def workout_intensity_profile(row: dict[str, Any], *, name: str) -> dict[str, Any]:
    """Classify workout intent from structure hints, not just Xert XSS split."""

    lowered = name.lower()
    tags = set()
    if any(token in lowered for token in ("vo2", "vo2max", "anaerobic", "sprint")):
        tags.add("high_intensity")
    if any(token in lowered for token in ("vt2", "threshold", "terskel", "closer")):
        tags.add("threshold")
    if any(token in lowered for token in ("recovery", "active recovery")):
        tags.add("recovery")
    if any(token in lowered for token in ("vt1", "endurance", "base")):
        tags.add("endurance")

    max_power = number(row.get("max_power"))
    avg_power = number(row.get("avg_power"))
    difficulty = number(row.get("difficulty"))
    high_xss = number(row.get("xhss")) or 0.0
    peak_xss = number(row.get("xpss")) or 0.0

    if max_power is not None and max_power >= 290:
        tags.add("hard_power")
    if avg_power is not None and avg_power >= 240:
        tags.add("high_average_power")
    if difficulty is not None and difficulty >= 75:
        tags.add("high_difficulty")
    if high_xss + peak_xss >= 5:
        tags.add("hard_system_load")

    suppressed_tags = {
        "high_intensity",
        "threshold",
        "hard_power",
        "high_average_power",
        "high_difficulty",
        "hard_system_load",
    }
    suppressed = bool(tags & suppressed_tags)
    low_intensity = not suppressed
    return {
        "tags": sorted(tags),
        "low_intensity_candidate": low_intensity,
        "suppressed_from_default": suppressed and not low_intensity,
        "suppressed_reason": (
            "Contains threshold/VO2/hard-power structure; keep out of default same-day "
            "candidate list unless intensity is explicitly wanted."
            if suppressed and not low_intensity
            else None
        ),
    }


def workout_adjustment(
    *,
    name: str,
    duration_minutes: float,
    xss: float | None,
    target_minutes: float,
    target_load: float,
) -> dict[str, Any]:
    if duration_minutes and duration_minutes > target_minutes * 1.25:
        return {
            "action": "shorten_duration",
            "reason": "Workout duration is materially above today's target window.",
            "suggested_minutes": round(target_minutes),
        }
    if xss is not None and xss > target_load * 1.35:
        return {
            "action": "reduce_duration_or_repetitions",
            "reason": "Workout XSS is materially above today's load target.",
            "suggested_xss_cap": round(target_load),
        }
    if xss is not None and xss < target_load * 0.55 and "Recovery" not in name:
        return {
            "action": "consider_longer_option",
            "reason": "Workout is well below the load target unless recovery is the goal.",
        }
    return {
        "action": "use_as_is",
        "reason": "Duration and load are close enough; no structure change needed.",
    }


def workout_rank_key(
    row: dict[str, Any],
    *,
    target_minutes: float,
    target_load: float,
) -> float:
    duration_score = closeness_score(row.get("duration_minutes"), target_minutes, max(20.0, target_minutes * 0.35))
    load_score = closeness_score(row.get("xss"), target_load, max(25.0, target_load * 0.45))
    difficulty = number(row.get("difficulty")) or 999
    suitability = str(row.get("suitability") or "")
    suitability_score = 1.0 if "Good" in suitability else 0.5 if "Fair" in suitability else 0.0
    liked_score = 1.0 if row.get("liked") else 0.0
    disliked_penalty = -1.0 if row.get("disliked") else 0.0
    hard_system_penalty = (number(row.get("high_xss")) or 0) + (number(row.get("peak_xss")) or 0)
    intensity_penalty = 25 if row.get("suppressed_from_default") else 0
    return (
        duration_score * 45
        + load_score * 35
        + suitability_score * 10
        + liked_score * 5
        + disliked_penalty * 20
        - abs(difficulty - 55) * 0.15
        - hard_system_penalty * 0.4
        - intensity_penalty
    )


def freshness_summary_lines(freshness: dict[str, Any]) -> list[str]:
    guidance = freshness.get("guidance") or "missing"
    lines = [f"  Freshness: {guidance}"]
    stale = freshness.get("stale_dynamic_inputs") or freshness.get("stale_inputs") or []
    completed = freshness.get("completed_daily_signals_usable") or []
    future = freshness.get("future_daily_signals_not_available_yet") or []
    if stale:
        lines.append("  Stale dynamic inputs: " + ", ".join(map(str, stale)))
    if completed:
        lines.append("  Completed daily signals still usable: " + ", ".join(map(str, completed)))
    if future:
        lines.append(
            "  Future-day signals not available yet: " + ", ".join(map(str, future))
        )
    return lines


def calendar_summary_lines(calendar: dict[str, Any]) -> list[str]:
    if not isinstance(calendar, dict) or not calendar:
        return []
    lines = [f"  Calendar assumption: {value}" for value in calendar.get("assumptions") or []]
    for field, slack_field, label in (
        ("practical_stop", "practical_stop_slack_minutes", "Practical stop"),
        ("hard_stop", "hard_stop_slack_minutes", "Hard stop"),
    ):
        stop = calendar.get(field)
        if not stop:
            continue
        lines.append(
            "  {label}: {subject} at {at}; slack after cleanup={slack} min".format(
                label=label,
                subject=stop.get("subject"),
                at=stop.get("at"),
                slack=calendar.get(slack_field),
            )
        )
    return lines


def quality_history_summary_lines(history: dict[str, Any], goal: str | None) -> list[str]:
    """Show same-role attempts and their observed follow-up beside the proposed dose."""
    def ride(row):
        return {key: row[key] for key in ("activity_id", "completed_role", "moving_minutes", "session_rpe")
                if row.get(key) is not None}

    def quality(session):
        intervals = session.get("work_intervals")
        return {**ride(session["attempt"]), "recorded_work_seconds_watts": (
            [[bout["seconds"], bout.get("average_watts")] for bout in intervals]
            if intervals is not None else None
        )}

    lines = []
    for session in history.get("quality_sequences", []):
        if session["role"] != goal:
            continue
        following = session.get("following_day") or {}
        next_quality = session.get("next_quality_session")
        comparison = {
            "attempt": quality(session),
            "following_day_records": [ride(row) for row in following.get("activities", [])],
            "next_quality": quality(next_quality) if next_quality else None,
        }
        lines.append("QUALITY HISTORY: " + json.dumps(comparison, ensure_ascii=False))
    return lines


def aerobic_finish_lines(
    review: dict[str, Any] | None, *, include_spacing_details: bool = True,
) -> list[str]:
    if not review:
        return []
    if review["decision"] == "finish":
        lines = ["AEROBIC FINISH: end at the primary duration. " + review["reason"]]
        if review.get("good_response_limit"):
            choices = f"+{review['alternative_extra_minutes']:g}"
            if review.get("smaller_extra_minutes"):
                choices = f"+{review['smaller_extra_minutes']:g} / {choices}"
            lines.append(f"WHY SKIP {choices} MIN EVEN ON GOOD LEGS: "
                         + review["good_response_limit"])
        return lines
    end, cleanup = (
        datetime.fromisoformat(review[key]).strftime("%H:%M")
        for key in ("finish_at", "cleanup_end")
    )
    checkpoint = f"{review['check_at_minute']:g} min from workout start"
    segment = review.get("checkpoint_segment")
    if segment:
        checkpoint = (f"after {segment['minutes_completed']:g} min of segment {segment['number']} "
                      f"({checkpoint} as prescribed)")
    extension_start = review.get("extension_start")
    start_cue = checkpoint
    if extension_start:
        start_cue = (f"after completing {extension_start['work_minutes']:g} min of segment "
                     f"{extension_start['segment']} ({extension_start['ridden_minutes']:g} ridden minutes)")
    lines = [
        f"OPTIONAL AEROBIC FINISH: {start_cue}, +{review['extra_minutes']:g} min "
        f"at {review['intensity']}. Total {review['total_minutes']:g} min, "
        f"finish {end}, cleanup complete {cleanup}.",
        "CONTINUE IF: " + review["cue"],
        "TRAINING PURPOSE: " + review["reason"],
    ]
    if extension_start and review["check_at_minute"] < extension_start["ridden_minutes"]:
        lines.append(f"EARLIER RESPONSE CHECK: {checkpoint}; the extension starts after the full work block.")
    if review.get("good_response_limit") and review["extra_minutes"] < review["alternative_extra_minutes"]:
        lines.append(f"WHY STOP SHORT OF +{review['alternative_extra_minutes']:g} MIN ON GOOD LEGS: "
                     + review["good_response_limit"])
    if review.get("spacing_comparison"):
        if include_spacing_details:
            lines.append("SPACING-DAY DOSES: " + json.dumps(review["spacing_comparison"], ensure_ascii=False))
        if review.get("marginal_benefit"):
            lines.append("BENEFIT OF THE LAST MINUTES: " + review["marginal_benefit"])
        if review.get("limit_basis"):
            lines.append("BASIS FOR SHORTER OFFER: " + review["limit_basis"])
    return lines


def format_compact_summary(packet: dict[str, Any], packet_path: Path) -> str:
    """Summarize the decision without repeating the diagnostic packet."""
    primary = packet["primary_decision"]
    intensity = primary["intensity_decision"]
    decision = packet["decision_inputs"]
    context = packet["llm_context"]
    target = packet["target_resolution"]
    time_context = context["time_context"]
    executable = primary["executable_now"]
    timeline = executable["timeline"]
    remainder = primary["unexecuted_remainder"]
    plan = packet["plan_context"]
    split = target.get("split") or {}
    lines = [
        f"PACKET: {packet_path}",
        f"PRIMARY DECISION: {primary['action'].upper()}",
        f"PLANNED TIME: {packet['planned_at']} ({packet['planned_at_source']})",
        ("PROVISIONAL SESSION: " if primary["provisional"] else "DO NOW: ")
        + executable_now_line(primary),
        f"WORKOUT GOAL: {intensity['requested_goal']}",
        f"READINESS CEILING: {intensity['readiness_ceiling']} (model screening)",
        f"TIMELINE: {timeline['status']}",
    ]
    if remainder["minutes"]:
        lines.append(f"REMAINDER: {remainder['minutes']:g} min; {remainder['disposition']}; "
                     "do not schedule automatically")
    history = packet.get("training_history_context", {})
    for row in history.get("completed_moving_time", []):
        days = row["days"]
        line = (f"INTERVALS.ICU MOVING TIME ({row['start_date']} to {row['end_date']}): "
                f"{row['weekly_equivalent_hours']:g} h/week over {days} days")
        rolling = history.get(f"rolling_{days}d", {})
        if primary["action"] == "train" and rolling.get("coverage") == "intervals_activity_volume":
            rolling_hours = rolling["moving_hours"]
            durations = [executable["minutes"]]
            finish = primary.get("aerobic_finish") or {}
            if finish.get("decision") == "offer":
                durations.append(finish["total_minutes"])
            for minutes in durations:
                weekly = (rolling_hours + minutes / 60) * 7 / days
                line += f" | with {minutes:g} min on {packet['date']}: {weekly:.1f} h/week"
        lines.append(line)
    lines.extend(aerobic_finish_lines(primary.get("aerobic_finish"), include_spacing_details=False))
    lines.extend(line.strip() for line in calendar_summary_lines(time_context["calendar"]))
    lines.extend(line.strip() for line in freshness_summary_lines(decision["freshness_summary"]))
    for item in plan.get("dated_athlete_constraints", []):
        if item["active"]:
            lines.append(f"ACTIVE ATHLETE INSTRUCTION: {item['quote']} ({item['source']})")

    sections = [
        ("SEGMENT", segment, ("name", "type", "duration_seconds", "power", "end_power"))
        for segment in timeline.get("segments", [])
    ]
    if primary["action"] == "train":
        sections.extend(
            ("SESSION WINDOW", session, ("start", "end", "duration_minutes"))
            for session in split.get("sessions", [])
        )
    sections.extend([
        ("HEALTH", context["health_constraints"], (
            "no_training_today", "form_check_needed", "reason", "return_to_training_active",
            "illness_return_phase", "return_to_training_guidance", "followup_question",
        )),
        ("DIRECT EVIDENCE", primary["readiness_evidence"], (
            "readiness_status", "direct_signal_coverage", "unassessed_direct_signals",
            "observed_limitations", "observed_cautions", "review_required",
            "intervals_soreness_value",
        )),
        ("WELLNESS", decision["wellness"], (
            "sleep_time_seconds", "sleep_score", "hrv_last_night_avg", "hrv_weekly_avg",
            "hrv_trend_status", "resting_hr", "resting_hr_7day",
        )),
        ("DOSE", primary.get("coaching_selection") or {}, ("minutes", "load", "reason", "evidence")),
        ("PLAN", plan, ("next_role", "next_quality_role", "mismatch_reason")),
        ("XERT ADVICE", target, ("xert_recommended_total_xss", "xert_dose_basis")),
        ("XERT CAPACITY", target.get("recovery_protection_capacity") or {}, (
            "status", "fresh_at", "review_required", "exceeded_systems", "decision",
        )),
        ("CALENDAR FIT", split, (
            "fits_current_window", "available_minutes_from_planned", "guidance",
        )),
    ])
    for label, values, keys in sections:
        selected = {key: values[key] for key in keys if values.get(key) is not None}
        if selected:
            lines.append(f"{label}: " + json.dumps(selected, ensure_ascii=False, separators=(",", ":")))
    if primary["action"] == "unavailable":
        lines.extend(f"UNAVAILABLE {mode}: {reason}" for mode, reason in packet["unavailable_reasons"].items())
    return "\n".join(lines)


def format_summary(packet: dict[str, Any]) -> str:
    decision = packet.get("decision_inputs") or {}
    context = packet.get("llm_context") or {}
    fueling = packet.get("fueling_defaults") or {}
    freshness = decision.get("freshness_summary") or {}
    readiness = decision.get("garmin_recovery_readiness") or {}
    vo2max = decision.get("garmin_vo2max") or {}
    load_focus = decision.get("garmin_load_focus") or {}
    wellness = decision.get("wellness") or {}
    intensity_agreement = decision.get("intensity_signal_agreement") or {}
    intervals_events = decision.get("intervals_wellness_events") or {}
    latest = decision.get("latest_activity_load") or {}
    xert_training_advice = decision.get("xert_training_advice") or {}
    xert = decision.get("xert_recovery") or {}
    workouts = decision.get("indoor_workouts") or {}
    route = decision.get("top_route") or {}
    routes_packet = packet.get("routes") or {}
    home_weather = decision.get("weather_home_hourly") or []
    route_weather = decision.get("weather_route_hourly") or []
    relevant_options = workouts.get("relevant_options") or []
    recommended = workouts.get("recommended") or {}
    higher_intensity_options = workouts.get("higher_intensity_candidates") or []
    progression = context.get("progression_advice") or decision.get("progression_advice") or {}
    presentation = context.get("presentation_requirements") or {}
    time_context = context.get("time_context") or {}
    target_resolution = context.get("target_resolution") or decision.get("target_resolution") or {}
    same_day_activity = context.get("same_day_activity_context") or {}
    health_constraints = context.get("health_constraints") or {}
    no_training_today = bool(health_constraints.get("no_training_today"))
    form_check_needed = bool(health_constraints.get("form_check_needed"))
    return_to_training_active = bool(health_constraints.get("return_to_training_active"))
    primary = packet.get("primary_decision") or context.get("primary_decision") or {}
    intensity_decision = primary.get("intensity_decision") or {}
    plan_context = packet.get("plan_context") or context.get("plan_context") or {}
    calendar_context = time_context.get("calendar") or packet.get("calendar") or {}
    remainder = primary.get("unexecuted_remainder") or {}
    remainder_minutes = number(remainder.get("minutes"))
    remainder_line = (
        "REMAINDER: none"
        if remainder_minutes is not None and remainder_minutes < 0.1
        else "REMAINDER: {minutes} min; disposition={disposition}; do not schedule automatically".format(
            minutes=remainder.get("minutes"),
            disposition=remainder.get("disposition") or "unscheduled",
        )
    )

    lines = [
        "PRIMARY DECISION: {action}".format(
            action=str(primary.get("action") or "missing").upper()
        ),
        ("PROVISIONAL SESSION: " if primary.get("provisional")
         else "DO NOW: ") + executable_now_line(primary),
        *aerobic_finish_lines(primary.get("aerobic_finish")),
        *(f"INTERVALS.ICU COMPLETED MOVING TIME ({row['start_date']} to {row['end_date']}): "
          f"{row['weekly_equivalent_hours']:g} h/week over {row['days']} days"
          for row in (packet.get("training_history_context") or {}).get("completed_moving_time", [])),
        "READINESS CEILING: {ceiling} (model screening, not confirmed readiness)".format(
            ceiling=intensity_decision.get("readiness_ceiling") or "missing",
        ),
        "READINESS EVIDENCE: " + json.dumps(primary.get("readiness_evidence") or {}, ensure_ascii=False),
        "CANONICAL EXECUTION TIMELINE: " + json.dumps(
            (primary.get("executable_now") or {}).get("timeline") or {}, ensure_ascii=False,
        ),
        "WORKOUT GOAL: {goal}".format(
            goal=intensity_decision.get("requested_goal") or "missing",
        ),
        *("DATED ATHLETE INSTRUCTION: " + json.dumps(item, ensure_ascii=False)
          for item in plan_context.get("dated_athlete_constraints", [])),
        "PLAN ROLE: {role}; next quality={quality}; goal matches state={matches}".format(
            role=plan_context.get("next_role") or "missing",
            quality=plan_context.get("next_quality_role") or "missing",
            matches=plan_context.get("goal_matches_state"),
        ),
        "COACHING DOSE: " + json.dumps(primary.get("coaching_selection"), ensure_ascii=False),
        *quality_history_summary_lines(
            (packet.get("training_history_context") or {}).get("prior_quality_sequences") or {},
            intensity_decision.get("requested_goal"),
        ),
        *(["VT1 WORKING POWER: " + json.dumps(primary["vt1_power_review"], ensure_ascii=False)]
          if "vt1_power_review" in primary else []),
        *(["VT1 DOSE COMPARISON: " + json.dumps(primary["vt1_dose_comparison"], ensure_ascii=False)]
          if "vt1_dose_comparison" in primary else []),
        *(["PROJECTED SEVEN-DAY LOAD: " + json.dumps(
            target_resolution["week_if_full_remaining_session_ridden_today"], ensure_ascii=False)]
          if "week_if_full_remaining_session_ridden_today" in target_resolution else []),
        "XERT COMPARISON: " + json.dumps(primary.get("xert_comparison"), ensure_ascii=False),
        *dose_composition_summary_lines(target_resolution),
        "DOSE SEMANTICS: {semantics}; completed activities already accounted for={accounted}".format(
            semantics=primary.get("dose_semantics"),
            accounted=primary.get("completed_activities_already_accounted_for"),
        ),
        "XATA PLANNING CONTEXT: {context}".format(
            context=xert_planning_context_line(target_resolution),
        ),
        remainder_line,
        (
            "LLM DEFAULT: follow PRIMARY DECISION; show READINESS CEILING and "
            "WORKOUT GOAL to the user; deviations require a labelled coaching override."
        ),
        "",
        f"Recommendation context packet: {packet.get('date')} planned {packet.get('planned_at')}",
        "",
        "LLM context:",
        "  Purpose: PRIMARY DECISION is the default recommendation; supporting data explains and executes it.",
        *freshness_summary_lines(freshness),
        "  Planned time: {planned} ({source})".format(
            planned=time_context.get("planned_at_local") or packet.get("planned_at"),
            source=time_context.get("planned_at_source") or packet.get("planned_at_source"),
        ),
        *calendar_summary_lines(calendar_context),
        "  Activity context: {context}".format(
            context=same_day_activity_line(same_day_activity),
        ),
        "  Health constraint: {constraint}".format(
            constraint=(
                "NO TRAINING TODAY; explicit Intervals.icu sickness annotation overrides dose and candidates"
                if no_training_today
                else "FORM CHECK REQUIRED; illness return unresolved; review symptoms and exercise response before training"
                if form_check_needed
                else "RETURN-TO-TRAINING PHASE {phase}; use {guidance} min, no quality intensity".format(
                    phase=health_constraints.get("illness_return_phase"),
                    guidance=(health_constraints.get("return_to_training_guidance") or {}).get(
                        "duration_minutes"
                    ),
                )
                if return_to_training_active
                else "none from Intervals.icu wellness events"
            ),
        ),
        "  Dose target: {dose}".format(
            dose=dose_target_line(target_resolution),
        ),
        "  Base plan: {plan}".format(
            plan=base_plan_line(target_resolution),
        ),
        "  Plan adjustment: {adjustment}".format(
            adjustment=plan_adjustment_line(target_resolution),
        ),
        "  Final physiological plan: {plan}".format(
            plan=final_plan_line(target_resolution),
        ),
        "  Xert advice source: {source}".format(
            source=xert_advice_source_line(xert_training_advice),
        ),
        "  Dose vs typical: {position}".format(
            position=dose_position_line(target_resolution),
        ),
        "  Projected moving-time density including the proposed ride: {density}".format(
            density=volume_density_line(target_resolution),
        ),
        "  Dose split: {split}".format(
            split=target_resolution.get("split_note") or "one ride or split if practical",
        ),
        "  Weather window: {window}".format(
            window=time_context.get("evaluated_weather_window")
            or weather_time_window(route_weather)
            or weather_time_window(home_weather)
            or "missing",
        ),
        "  Top route candidate: {outdoor}".format(
            outdoor=outdoor_line(route),
        ),
        "  Route map: {map}".format(
            map=route_map_line(route),
        ),
        "  Dose-matched low-intensity indoor candidate: {indoor}".format(
            indoor=indoor_availability_line(workouts, recommended),
        ),
        "  Candidate execution note: {execution}".format(
            execution=indoor_execution_line(workouts, recommended),
        ),
        "  Higher-intensity indoor candidates: {candidates}".format(
            candidates=indoor_higher_intensity_line(workouts, higher_intensity_options),
        ),
        "  Presentation target watts: {targets}".format(
            targets=(
                "not applicable for indoor_cycling_gym; prescribe heart rate, "
                "breathing, and RPE"
                if workouts.get("source") == "indoor_cycling_gym"
                else presentation_target_watts_line(presentation)
            ),
        ),
        "  VT2 progression: {progression}".format(
            progression=authoritative_progression_line(
                plan_context,
                progression,
                "vt2",
            ),
        ),
        "  VO2Max progression: {progression}".format(
            progression=authoritative_progression_line(
                plan_context,
                progression,
                "vo2max",
            ),
        ),
        "  Fueling: {fueling}".format(
            fueling=fueling_modalities_line(
                fueling,
                indoor_available=workouts.get("available") is not False,
                outdoor_available=routes_packet.get("available") is not False,
            ),
        ),
        "  Carb counting: {carbs}".format(
            carbs=fueling_counting_context_line(
                fueling,
                outdoor_available=routes_packet.get("available") is not False,
            ),
        ),
        "",
        "Readiness:",
        "  Dose basis: {dose}".format(
            dose=dose_target_line(target_resolution),
        ),
        "  Garmin composite diagnostics (not dose inputs): readiness {score}/100; Garmin Recovery Time {recovery} h at planned start to modeled full recovery for the next hard workout, not a ban on easy or moderate activity (projection assumes no intervening training); level={level}, recovery_factor={factor}, training_status={status}".format(
            score=readiness.get("training_readiness_score"),
            recovery=readiness.get("projected_recovery_time_hours_at_planned")
            if readiness.get("projected_recovery_time_hours_at_planned") is not None
            else readiness.get("projected_recovery_time_hours_now"),
            level=readiness.get("training_readiness_level"),
            factor=readiness.get("recovery_time_factor_feedback"),
            status=readiness.get("training_status_feedback"),
        ),
        "  Training Readiness explanation: {drivers}".format(
            drivers=garmin_readiness_driver_line(readiness) or "missing",
        ),
        "  Garmin VO2max context: {vo2max}".format(
            vo2max=garmin_vo2max_line(vo2max),
        ),
        "  Numeric caution: {caution}".format(
            caution=caution_summary_line(readiness, wellness),
        ),
        "  Intensity signal agreement: vt2_allowed={vt2_allowed}; high_intensity_allowed={high_allowed}; blockers={blockers}; moderate={moderate}; severe={severe}".format(
            vt2_allowed=intensity_agreement.get("vt2_allowed"),
            high_allowed=intensity_agreement.get("high_intensity_allowed"),
            blockers=intensity_agreement.get("blockers"),
            moderate=intensity_agreement.get("moderate_signals"),
            severe=intensity_agreement.get("severe_signals"),
        ),
        "  Load focus: {load_focus}".format(
            load_focus=load_focus_summary_line(load_focus),
        ),
        "  Wellness numeric: HRV {hrv}, sleep {sleep}, Body Battery {bb}".format(
            hrv=hrv_summary_line(wellness),
            sleep=sleep_summary_line(wellness, readiness),
            bb=body_battery_summary_line(wellness),
        ),
        "  Intervals wellness/events: {events}".format(
            events=intervals_wellness_events_line(intervals_events),
        ),
        "  Xert: low/high/peak recovery {recovery_hours}".format(
            recovery_hours=(xert.get("projected_recovery_hours_at_planned_time") or {}),
        ),
        "",
        "Recent load:",
        "  {name}: {minutes} min, Xert XSS {xss}, difficulty {difficulty}".format(
            name=latest.get("name"),
            minutes=latest.get("elapsed_minutes"),
            xss=latest.get("xert_xss"),
            difficulty=latest.get("xert_difficulty"),
        ),
        "",
        "Indoor options:",
    ]
    if relevant_options:
        for option in relevant_options:
            lines.append(
                "  {label}: {name} | {minutes} min | XSS {xss} | difficulty {difficulty} | {url}".format(
                    label=option.get("option_label") or "option",
                    name=option.get("name"),
                    minutes=option.get("duration_minutes"),
                    xss=option.get("xss"),
                    difficulty=option.get("difficulty"),
                    url=option.get("url"),
                )
            )
            fit = window_fit_line(option.get("window_fit"))
            if fit:
                lines[-1] += f" | {fit}"
    elif workouts.get("available") is False:
        lines.append(
            "  unavailable: {reason}".format(
                reason=workouts.get("reason") or "indoor_equipment_not_available",
            )
        )
    else:
        lines.append(
            "  {name} | {minutes} min | XSS {xss} | difficulty {difficulty} | {url}".format(
                name=recommended.get("name"),
                minutes=recommended.get("duration_minutes"),
                xss=recommended.get("xss"),
                difficulty=recommended.get("difficulty"),
                url=recommended.get("url"),
            )
        )
        fit = window_fit_line(recommended.get("window_fit"))
        if fit:
            lines[-1] += f" | {fit}"
    if higher_intensity_options:
        lines.extend(["", "Higher-intensity indoor candidates:"])
        for option in higher_intensity_options[:5]:
            lines.append(
                "  candidate: {name} | {minutes} min | XSS {xss} | high/peak XSS {high}/{peak} | difficulty {difficulty} | tags {tags} | {url}".format(
                    name=option.get("name"),
                    minutes=option.get("duration_minutes"),
                    xss=option.get("xss"),
                    high=option.get("high_xss"),
                    peak=option.get("peak_xss"),
                    difficulty=option.get("difficulty"),
                    tags=",".join(option.get("intensity_tags") or []),
                    url=option.get("url"),
                )
            )
    if progression.get("available") is False:
        lines.extend(
            [
                "",
                "Progression advice:",
                "  unavailable: {reason}".format(
                    reason=progression.get("reason") or "progression_matching_disabled",
                ),
            ]
        )
    elif progression:
        lines.extend(["", "Progression advice:"])
        for workout_type in ("vt2", "vo2max"):
            advice = progression.get(workout_type) or {}
            plan_family = (plan_context.get("progression") or {}).get(workout_type) or {}
            if advice or plan_family:
                lines.append(
                    f"  {workout_type.upper()}: "
                    + authoritative_progression_line(
                        plan_context,
                        progression,
                        workout_type,
                    )
                )
    lines.extend(["", "Outdoor candidate:"])
    if routes_packet.get("available") is False:
        lines.append(
            "  unavailable: {reason}".format(
                reason=routes_packet.get("reason") or "outdoor_riding_not_realistic",
            )
        )
    elif route:
        steady_endurance = route.get("steady_endurance") or {}
        lines.append(
            "  {name} ({date}, {id}) | {distance} km | {elevation} hm | {downhill} | {url}".format(
                name=route.get("name"),
                date=route.get("date"),
                id=route.get("id"),
                distance=route.get("distance_km"),
                elevation=route.get("elevation_gain_m"),
                downhill=downhill_summary_line(steady_endurance),
                url=route.get("url"),
            )
        )
        fit = window_fit_line(route.get("window_fit"))
        if fit:
            lines[-1] += f" | {fit}"
        dose_fit = route_dose_fit_line(route.get("dose_fit"))
        if dose_fit:
            lines[-1] += f" | {dose_fit}"
        shorter = routes_packet.get("shorter_window_options") or []
        if route.get("window_fit", {}).get("fits_first_window") is False and shorter:
            lines.append(
                "  Shorter window-fit alternative: {name} ({minutes} min, {distance} km)".format(
                    name=shorter[0].get("name"),
                    minutes=shorter[0].get("duration_minutes"),
                    distance=shorter[0].get("distance_km"),
                )
            )
        route_note = route.get("route_reference_note") or {}
        if route_note.get("text"):
            lines.append(f"  Note: {route_note.get('text')}")
    else:
        lines.append("  missing")
    lines.extend(
        [
            "",
            "Weather:",
            f"  Home: {weather_range(home_weather)}",
            f"  Route: {weather_range(route_weather)}",
        ]
    )
    notes = (packet.get("readiness") or {}).get("notes") or []
    if notes:
        lines.extend(["", "Notes:", *[f"  {note}" for note in notes]])
    return "\n".join(lines)


def intervals_wellness_events_line(events: dict[str, Any]) -> str:
    if not events or not events.get("source_present"):
        return "missing"
    current = events.get("current_day") or {}
    if events.get("current_day_illness"):
        return "today marked sick" + (
            f" ({current.get('comments')})" if current.get("comments") else ""
        )
    if events.get("illness_followup_needed"):
        latest = events.get("latest_illness_event") or {}
        return "illness return unresolved; symptom and exercise-response review required" + (
            f" ({latest.get('comments')})" if latest.get("comments") else ""
        )
    if events.get("return_to_training_active"):
        guidance = events.get("return_to_training_guidance") or {}
        return "return phase {day}: {duration}, {intensity}".format(
            day=events.get("illness_return_phase"),
            duration=guidance.get("duration_minutes"),
            intensity=guidance.get("intensity"),
        )
    review = events.get("current_day_review_signals") or []
    if "clarify_current_illness_comment" in review:
        pending = events.get("unresolved_illness_comment") or current
        return f"Clarify who has symptoms and whether they are present today ({pending.get('date')}, {pending.get('comments')})."
    if review:
        return ("Check whether unusual fatigue persists today before hard training. "
                "If otherwise well, assess effort at familiar easy power during warm-up. "
                "Defer hard work if easy power still feels unusually demanding.")
    recent_illness = events.get("recent_illness_events") or []
    if recent_illness:
        latest = recent_illness[-1]
        return "recent sickness {date}{comment}".format(
            date=latest.get("date"),
            comment=f" ({latest.get('comments')})" if latest.get("comments") else "",
        )
    recent = events.get("recent_events") or []
    if recent:
        return f"{len(recent)} recent annotated wellness event(s), no sickness detected"
    return "no annotated wellness events in lookback window"


def indoor_availability_line(workouts: dict[str, Any], recommended: dict[str, Any]) -> str:
    if workouts.get("available") is False:
        return f"unavailable ({workouts.get('reason') or 'indoor_equipment_not_available'})"
    line = workout_line(recommended)
    fit = window_fit_line(recommended.get("window_fit") if isinstance(recommended, dict) else None)
    return f"{line}; {fit}" if fit else line


def indoor_execution_line(workouts: dict[str, Any], recommended: dict[str, Any]) -> str:
    if workouts.get("available") is False:
        return "Indoor workouts were not fetched or ranked for this location context."
    if workouts.get("source") == "indoor_cycling_gym":
        return (
            "Use continuous aerobic riding controlled by heart rate, breathing, "
            "and RPE; watts and ERG instructions do not apply."
        )
    return workout_execution_line(recommended)


def indoor_higher_intensity_line(
    workouts: dict[str, Any],
    higher_intensity_options: list[dict[str, Any]],
) -> str:
    if workouts.get("available") is False:
        return "unavailable"
    return higher_intensity_summary_line(higher_intensity_options)


def fueling_modalities_line(
    fueling: dict[str, Any],
    *,
    indoor_available: bool,
    outdoor_available: bool,
) -> str:
    parts = []
    if indoor_available:
        indoor = (fueling.get("indoor") or {}).get("default_bottles")
        if indoor:
            parts.append(f"indoor {indoor}")
    if outdoor_available:
        outdoor = (fueling.get("outdoor") or {}).get("short_moderate")
        outdoor_long = (fueling.get("outdoor") or {}).get("long_hot_or_hard")
        if outdoor and outdoor_long:
            parts.append(f"outdoor {outdoor}/{outdoor_long}")
    return (
        "; ".join(parts)
        if parts
        else "no script-provided fueling defaults; use agent/profile context"
    )


def fueling_counting_context_line(
    fueling: dict[str, Any],
    *,
    outdoor_available: bool,
) -> str:
    if not outdoor_available:
        return "outdoor carb-counting cues suppressed because outdoor riding is unavailable"
    return fueling_counting_line(fueling)


def downhill_summary_line(steady_endurance: dict[str, Any]) -> str:
    if not isinstance(steady_endurance, dict) or not steady_endurance:
        return "bratt nedover missing"
    weighted = steady_endurance.get("downhill_disruption_pct")
    gt4_km = steady_endurance.get("descent_gt4_km")
    gt4_pct = steady_endurance.get("descent_gt4_pct")
    gt5_km = steady_endurance.get("descent_gt5_km")
    gt5_pct = steady_endurance.get("descent_gt5_pct")
    parts = []
    if weighted is not None:
        parts.append(f"vektet {weighted}%")
    if gt4_km is not None and gt4_pct is not None:
        parts.append(f">4%: {gt4_km} km / {gt4_pct}%")
    if gt5_km is not None and gt5_pct is not None:
        parts.append(f">5%: {gt5_km} km / {gt5_pct}%")
    if not parts:
        return "bratt nedover missing"
    return "bratt nedover " + "; ".join(parts)


def fueling_counting_line(fueling: dict[str, Any]) -> str:
    counting = fueling.get("carb_counting") or {}
    rules = counting.get("practical_rules") or []
    if rules:
        return rules[-1]
    return (
        "For 60-80 g carbohydrate/hour, translate the target into countable food "
        "portions plus the planned sports drink from agent/profile context."
    )


def workout_line(option: dict[str, Any] | None) -> str:
    if not isinstance(option, dict) or not option:
        return "missing"
    return "{label}: {name} ({minutes} min, XSS {xss}, difficulty {difficulty})".format(
        label=option.get("option_label") or "option",
        name=option.get("name"),
        minutes=option.get("duration_minutes"),
        xss=option.get("xss"),
        difficulty=option.get("difficulty"),
    )


def higher_intensity_summary_line(options: list[dict[str, Any]]) -> str:
    if not options:
        return "none in Xert recommended-training packet"
    compact = []
    for option in options[:3]:
        compact.append(
            "{name} ({minutes} min, XSS {xss}, high/peak {high}/{peak}, difficulty {difficulty})".format(
                name=option.get("name"),
                minutes=option.get("duration_minutes"),
                xss=option.get("xss"),
                high=option.get("high_xss"),
                peak=option.get("peak_xss"),
                difficulty=option.get("difficulty"),
            )
        )
    return "; ".join(compact)


def presentation_target_watts_line(presentation: dict[str, Any]) -> str:
    target_watts = presentation.get("target_watts") if isinstance(presentation, dict) else None
    if not isinstance(target_watts, dict):
        return "LLM should suggest day-specific recovery/VT1/VT2/VO2Max watts in chat"
    required = target_watts.get("required") or []
    if required:
        label_map = {
            "recovery": "recovery",
            "vt1": "VT1",
            "vt2": "VT2",
            "vo2max": "VO2Max",
        }
        labels = "/".join(label_map.get(str(label).lower(), str(label)) for label in required)
    else:
        labels = "recovery/VT1/VT2/VO2Max"
    return f"LLM should suggest day-specific {labels} watts in chat"


def progression_summary_line(advice: dict[str, Any]) -> str:
    if not isinstance(advice, dict) or not advice:
        return "missing"
    next_step = advice.get("next_step") or {}
    prescription = next_step.get("prescription") or {}
    matching = advice.get("matching_existing_workouts") or {}
    best = matching.get("best") or {}
    parts = [str(advice.get("coach_summary") or advice.get("status") or "missing summary")]
    if prescription.get("summary"):
        parts.append(f"prescription={prescription.get('summary')}")
    if matching:
        if matching.get("available") and best.get("name"):
            parts.append(
                "workout_match={name} ({quality})".format(
                    name=best.get("name"),
                    quality=matching.get("match_quality"),
                )
            )
        elif matching.get("reason"):
            parts.append(f"workout_match={matching.get('reason')}")
    avoid = advice.get("avoid") or []
    if avoid:
        avoid_prescription = (avoid[0].get("prescription") or {}).get("summary")
        if avoid_prescription:
            parts.append(f"avoid={avoid_prescription}")
    return "; ".join(parts)


def progression_context_line(progression: dict[str, Any], workout_type: str) -> str:
    if progression.get("available") is False:
        return f"unavailable ({progression.get('reason') or 'progression_matching_disabled'})"
    return progression_summary_line((progression.get(workout_type) or {}))


def authoritative_progression_line(
    plan_context: dict[str, Any],
    progression: dict[str, Any],
    workout_type: str,
) -> str:
    plan_family = (plan_context.get("progression") or {}).get(workout_type) or {}
    plan_step = plan_family.get("next_step") or plan_family.get("anchor")
    historical = progression_context_line(progression, workout_type)
    if not plan_step:
        return historical
    parts = [f"PLAN STATE (authoritative): {plan_step}"]
    if plan_family.get("status"):
        parts.append(f"status={plan_family.get('status')}")
    return "; ".join(parts)


def workout_execution_line(option: dict[str, Any] | None) -> str:
    if not isinstance(option, dict) or not option:
        return "missing"
    if option.get("execution_note"):
        return str(option["execution_note"])
    structure = option.get("structure") or {}
    summary = structure.get("summary")
    if summary:
        return f"ride as-is in ERG; {summary} No extra warmup."
    return "ride as-is in ERG; use the workout's built-in warmup/cooldown. No extra warmup."


def outdoor_line(option: dict[str, Any] | None) -> str:
    if not isinstance(option, dict) or not option:
        return "missing"
    if option.get("available") is False:
        return f"unavailable ({option.get('reason') or 'outdoor_riding_not_realistic'})"
    line = "{name} ({minutes} min, {distance} km, XSS {xss})".format(
        name=option.get("name"),
        minutes=option.get("moving_minutes"),
        distance=option.get("distance_km"),
        xss=option.get("xss"),
    )
    fit = window_fit_line(option.get("window_fit"))
    dose_fit = route_dose_fit_line(option.get("dose_fit"))
    details = [detail for detail in (fit, dose_fit) if detail]
    return f"{line}; {'; '.join(details)}" if details else line


def window_fit_line(fit: Any) -> str | None:
    if not isinstance(fit, dict) or fit.get("available") is False:
        return None
    if fit.get("fits_first_window") is True:
        return (
            f"fits first window ({fit.get('duration_minutes')} <= "
            f"{fit.get('first_window_minutes')}+{fit.get('tolerance_minutes')} min)"
        )
    if fit.get("fits_first_window") is False:
        return f"does not fit first window (over by {fit.get('over_by_minutes')} min)"
    return None


def route_dose_fit_line(fit: Any) -> str | None:
    if not isinstance(fit, dict) or fit.get("available") is False:
        return None
    if fit.get("covers_prescribed_duration") is True:
        return (
            "covers prescribed duration "
            f"({fit.get('route_minutes')} vs {fit.get('prescribed_minutes')} min)"
        )
    if (fit.get("under_by_minutes") or 0) > 0:
        return (
            f"short of prescribed duration by {fit.get('under_by_minutes')} min; "
            "extend route or add VT1 time"
        )
    if (fit.get("over_by_minutes") or 0) > 0:
        return (
            f"over prescribed duration by {fit.get('over_by_minutes')} min; "
            "shorten route or use a turnaround"
        )
    return None


def route_map_line(option: dict[str, Any] | None) -> str:
    if not isinstance(option, dict) or not option:
        return "missing"
    if option.get("available") is False:
        return "unavailable"
    if option.get("name") == "Active recovery only":
        return "not applicable"
    map_status = option.get("route_map_status") or {}
    if map_status.get("status") == "not_requested":
        return "not requested (map_scope=none)"
    if option.get("xert_map_local_path"):
        return str(option["xert_map_local_path"])
    if option.get("xert_map_url"):
        return str(option["xert_map_url"])
    if option.get("xert_activity_url"):
        return str(option["xert_activity_url"])
    if option.get("intervals_activity_url"):
        return f"missing Xert map_url; activity {option['intervals_activity_url']}"
    if option.get("url"):
        return f"missing Xert map_url; activity {option['url']}"
    return "missing Xert map_url and activity URL"


def same_day_activity_line(context: dict[str, Any]) -> str:
    if not context.get("has_same_day_activity"):
        return "no same-day activity detected before the planned workout"
    load = "meaningful load" if context.get("meaningful_training_load") else "small load"
    return "{name}: {minutes} min, {load}, {timing}".format(
        name=context.get("name"),
        minutes=context.get("elapsed_minutes"),
        load=load,
        timing=context.get("timing"),
    )


def executable_now_line(primary: dict[str, Any]) -> str:
    executable = primary.get("executable_now") or {}
    segments = executable.get("segments") or []
    if not segments:
        return "{minutes} min {intensity}".format(
            minutes=executable.get("minutes"),
            intensity=executable.get("intensity"),
        )

    labels = []
    for segment in segments:
        role = str(segment.get("role") or "unknown")
        minutes = segment.get("duration_minutes")
        if segment.get("fits_executable_window") is False:
            labels.append(
                "{minutes} min {role} complete workout required, but only "
                "{available} min available".format(
                    minutes=minutes,
                    role=role.upper(),
                    available=segment.get("available_minutes"),
                )
            )
        elif role == "active_recovery":
            labels.append(f"{minutes} min ACTIVE_RECOVERY")
        elif role in {"vt1", "easy_vt1", "recovery"}:
            labels.append(f"{minutes} min {role.upper()}")
        else:
            labels.append(f"{minutes} min {role.upper()} quality workout")
    return " + ".join(labels)


def dose_target_line(target_resolution: dict[str, Any]) -> str:
    if not isinstance(target_resolution, dict) or not target_resolution:
        return "missing"
    return "{minutes} min / XSS {load}: {reason}".format(
        minutes=target_resolution.get("target_minutes"),
        load=target_resolution.get("target_load"),
        reason=target_resolution.get("reason") or "missing reason",
    )


def xert_planning_context_line(target_resolution: dict[str, Any]) -> str:
    context = target_resolution.get("xert_planning_context") or {}
    if not isinstance(context, dict) or not context:
        return "missing"
    return (
        "source={source}; planning target={goal}; deficit={deficit}; "
        "availability={availability}; restricted={restricted}; phase={phase}; "
        "intensity role remains plan-owned"
    ).format(
        source=context.get("targets_source") or "unknown",
        goal=context.get("xss_goal"),
        deficit=context.get("xss_deficit"),
        availability=context.get("availability"),
        restricted=context.get("is_availability_restricted"),
        phase=context.get("phase") or "unknown",
    )


def dose_composition_summary_lines(
    target_resolution: dict[str, Any],
) -> list[str]:
    composition = target_resolution.get("dose_composition") or {}
    if not isinstance(composition, dict) or not composition:
        return []
    xert_parts = target_resolution.get("xert_recommended_target_xss") or {}
    xert_total = target_resolution.get("xert_recommended_total_xss")
    xert_original = target_resolution.get("xert_original_target_xss") or {}
    xert_completed = target_resolution.get("xert_completed_xss") or {}
    quality = composition.get("quality_base") or {}
    filler = composition.get("vt1_filler") or {}
    total = composition.get("estimated_total") or {}
    calendar_fit = composition.get("calendar_fit") or {}
    parts = ", ".join(
        f"{key}={rounded_number(value)}"
        for key, value in xert_parts.items()
    )
    lines = [
        "XERT REMAINING DOSE: {total} XSS{parts} (basis={basis})".format(
            total=xert_total if xert_total is not None else "unavailable",
            parts=f" ({parts})" if parts else "",
            basis=target_resolution.get("xert_dose_basis") or "unknown",
        ),
        "XERT ORIGINAL/COMPLETED: {original}/{completed} XSS".format(
            original=xss_triplet_total(xert_original),
            completed=xss_triplet_total(xert_completed),
        ),
        "CHOSEN DAILY TARGET: {target} XSS".format(
            target=composition.get("daily_target_xss"),
        ),
        (
            "QUALITY BASE: {minutes} min / {xss} XSS "
            "(low={low}, high={high}, peak={peak}; complete workout)"
        ).format(
            minutes=quality.get("duration_minutes"),
            xss=quality.get("xss"),
            low=quality.get("low_xss"),
            high=quality.get("high_xss"),
            peak=quality.get("peak_xss"),
        ),
        "VT1 FILLER: {minutes} min / {xss} low XSS ({method})".format(
            method="Xert-calculated" if filler.get("source") == "xert_workout_calculate" else "none selected" if not filler.get("duration_minutes") else "Xert-solved",
            minutes=filler.get("duration_minutes"),
            xss=filler.get("xss"),
        ),
        "EXPECTED TOTAL: {minutes} min / {xss} XSS".format(
            minutes=total.get("duration_minutes"),
            xss=total.get("xss"),
        ),
    ]
    if calendar_fit.get("available"):
        lines.append(
            (
                "CALENDAR DOSE: executable {executable}/{intended} min; "
                "shortfall {shortfall} min / {shortfall_xss} XSS"
            ).format(
                executable=calendar_fit.get("executable_minutes"),
                intended=calendar_fit.get("intended_minutes"),
                shortfall=calendar_fit.get("shortfall_minutes"),
                shortfall_xss=(
                    calendar_fit.get("estimated_shortfall_xss")
                    if calendar_fit.get("estimated_shortfall_xss") is not None
                    else "not estimable before quality base fits"
                ),
            )
        )
    else:
        lines.append(
            "CALENDAR DOSE: no explicit available windows; fit not verified"
        )
    return lines


def base_plan_line(target_resolution: dict[str, Any]) -> str:
    base = ((target_resolution.get("plan_trace") or {}).get("base_plan") or {})
    if not base:
        return "missing"
    return "{label}: {minutes} min / XSS {load}".format(
        label=base.get("label"),
        minutes=base.get("minutes"),
        load=base.get("load_xss"),
    )


def plan_adjustment_line(target_resolution: dict[str, Any]) -> str:
    adjustment = ((target_resolution.get("plan_trace") or {}).get("adjustment") or {})
    if not adjustment:
        return "missing"
    return "{status}: {reasons}".format(
        status=adjustment.get("status"),
        reasons=" ".join(str(reason) for reason in adjustment.get("reasons") or []),
    )


def final_plan_line(target_resolution: dict[str, Any]) -> str:
    final = ((target_resolution.get("plan_trace") or {}).get("final_plan") or {})
    if not final:
        return "missing"
    return "{minutes} min / XSS {load} ({relationship})".format(
        minutes=final.get("minutes"),
        load=final.get("load_xss"),
        relationship=final.get("relationship_to_base"),
    )


def xert_advice_source_line(training_advice: dict[str, Any]) -> str:
    if not isinstance(training_advice, dict) or not training_advice:
        return "missing"
    debug = training_advice.get("debug") or {}
    decision = debug.get("decision") if isinstance(debug, dict) else {}
    current = debug.get("current") if isinstance(debug, dict) else {}
    planned = debug.get("planned") if isinstance(debug, dict) else None
    endpoint = training_advice.get("source_endpoint") or training_advice.get("source")
    reason = decision.get("reason") if isinstance(decision, dict) else None
    if isinstance(planned, dict):
        return "{endpoint}; {reason}; current {current} planned {planned}".format(
            endpoint=endpoint,
            reason=reason or "no decision reason",
            current=xss_triplet_total((current or {}).get("target_xss")),
            planned=xss_triplet_total(planned.get("target_xss")),
        )
    return "{endpoint}; {reason}; current {current}".format(
        endpoint=endpoint,
        reason=reason or "no decision reason",
        current=xss_triplet_total(training_advice.get("target_xss")),
    )


def xss_triplet_total(value: Any) -> str:
    if not isinstance(value, dict):
        return "missing"
    parts = [number(value.get(key)) for key in ("low", "high", "peak")]
    if any(part is None for part in parts):
        return "missing"
    return str(round(sum(part for part in parts if part is not None), 1))


def dose_position_line(target_resolution: dict[str, Any]) -> str:
    position = target_resolution.get("dose_position_vs_typical") or {}
    if not isinstance(position, dict) or not position:
        return "missing"
    return "{phrase} ({ratio}x): {reason}".format(
        phrase=position.get("phrase"),
        ratio=position.get("ratio"),
        reason=position.get("reason"),
    )


def volume_density_line(target_resolution: dict[str, Any]) -> str:
    density = target_resolution.get("volume_density") or {}
    windows = density.get("windows") or []
    if not density or not windows:
        return "missing"
    if density.get("classification") == "unavailable":
        return "unavailable: no usable recorded history; missing data is not zero training"
    equivalents = ", ".join(
        f"{row.get('days')}d={row.get('projected_weekly_equivalent_hours')} h/week"
        for row in windows
    )
    return f"{density.get('classification')} ({equivalents}); diagnostic, not an automatic cap"


def weather_range(hourly: list[dict[str, Any]]) -> str:
    if not hourly:
        return "missing"
    temps = [number(row.get("air_temperature")) for row in hourly]
    winds = [number(row.get("wind_speed")) for row in hourly]
    precip = [number(row.get("precipitation_amount_next_1h")) for row in hourly]
    temps = [value for value in temps if value is not None]
    winds = [value for value in winds if value is not None]
    precip = [value for value in precip if value is not None]
    symbols = [row.get("symbol_code_next_1h") for row in hourly if row.get("symbol_code_next_1h")]
    start_time = parse_hourly_time(hourly[0])
    end_time = parse_hourly_time(hourly[-1])
    return "{start}-{end}, {temp}, wind {wind}, precip {precip}, {symbol}".format(
        start=start_time.strftime("%H:%M") if start_time else "missing",
        end=end_time.strftime("%H:%M") if end_time else "missing",
        temp=range_text(temps, "C"),
        wind=range_text(winds, "m/s"),
        precip=range_text(precip, "mm"),
        symbol=", ".join(sorted(set(symbols))) if symbols else "no symbol",
    )


def range_text(values: list[float], unit: str) -> str:
    if not values:
        return f"missing {unit}"
    return f"{min(values):.1f}-{max(values):.1f} {unit}"


def compact_numbers(values: Any) -> list[float]:
    result = []
    for raw in values:
        value = number(raw)
        if value is not None:
            result.append(value)
    return result


def seconds_to_hours(raw_seconds: Any) -> float | None:
    seconds = number(raw_seconds)
    if seconds is None:
        return None
    return seconds / 3600


def closeness_score(raw_value: Any, target: float, tolerance: float) -> float:
    value = number(raw_value)
    if value is None:
        return 0.0
    return max(0.0, 1.0 - abs(value - target) / tolerance)


def number(raw: Any) -> float | None:
    if raw in ("", None):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
