#!/usr/bin/env python3
"""Collect the standard inputs for a same-day training recommendation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from readiness_snapshot import (
    ARTIFACTS_DIR,
    build_readiness_snapshot,
    latest_activity_on_or_before,
    load_garmin_input,
    load_xert_input,
    parse_cli_local_datetime,
)
from route_recommendations import parse_date, recommend_routes


DEFAULT_OUTPUT_DIR = Path("outputs/recommendations")
SLEMDAL_LAT = 59.9556
SLEMDAL_LON = 10.6875
SORKEDALEN_LAT = 60.0189
SORKEDALEN_LON = 10.5834
REFRESH_GROUPS = frozenset({"garmin", "xert", "intervals", "weather"})
SOURCE_REFRESH_POLICY = {
    "garmin": ("garmin", 15),
    "xert": ("xert", 30),
    "intervals_wellness": ("intervals", 30),
    "intervals_events": ("intervals", 30),
    "xert_activity_loads": ("xert", 30),
    "xert_recommended_training": ("xert", 30),
    "xert_route_maps": ("xert", 24 * 60),
    "weather_home": ("weather", 60),
    "weather_route": ("weather", 60),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Garmin/Xert/Yr inputs and build one recommendation packet.",
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument(
        "--planned-at",
        help=(
            "Planned local workout time. Accepts HH:MM or an ISO local datetime. "
            "When omitted, the script assumes a practical same-day time and "
            "marks it as assumed in the recommendation packet."
        ),
    )
    parser.add_argument(
        "--now",
        help=(
            "Current local time for freshness/projection. Accepts HH:MM "
            "for --date or an ISO local datetime."
        ),
    )
    parser.add_argument(
        "--target-minutes",
        type=float,
        help=(
            "Explicit workout-duration target. When omitted, recommend_today "
            "derives the target from readiness, recent history, and session goal."
        ),
    )
    parser.add_argument(
        "--target-load",
        type=float,
        help=(
            "Explicit training-load target. When omitted, recommend_today derives "
            "the target from readiness, recent history, and session goal."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--garmin-json",
        type=Path,
        help=(
            "Use this Garmin Connect day JSON as an explicit input override. "
            "It cannot be combined with a forced Garmin refresh."
        ),
    )
    parser.add_argument(
        "--refresh",
        type=parse_refresh_spec,
        default=parse_refresh_spec("auto"),
        metavar="auto|all|none|SOURCE[,SOURCE...]",
        help=(
            "Source refresh policy. 'auto' reuses snapshots within source-specific "
            "TTLs; 'all' forces every source; 'none' uses local files only; a "
            "comma-separated list forces selected sources: garmin,xert,intervals,weather."
        ),
    )
    parser.add_argument("--route-index", type=Path, default=Path("outputs/route-index.json"))
    parser.add_argument("--rebuild-route-index", action="store_true")
    parser.add_argument(
        "--surface-preference",
        choices=("road", "gravel", "any", "unknown-ok"),
        default="road",
        help="Preferred outdoor route surface for the planned bike.",
    )
    parser.add_argument(
        "--start-anchor-displayname",
        dest="start_anchor_displayname",
        help=(
            "Optional display label for the start/end anchor."
        ),
    )
    parser.add_argument(
        "--start-anchor-lat",
        type=float,
        help="Latitude of the start/end anchor to pass to route recommendations.",
    )
    parser.add_argument(
        "--start-anchor-lng",
        type=float,
        help="Longitude of the start/end anchor to pass to route recommendations.",
    )
    parser.add_argument(
        "--start-radius-km",
        type=float,
        default=0.25,
        help="Start/end anchor radius for route recommendations.",
    )
    parser.add_argument(
        "--available-window",
        action="append",
        default=[],
        metavar="HH:MM-HH:MM[; note]",
        help=(
            "LLM-selected available training window. Can be repeated for split "
            "opportunities. Optional text after ';' is stored as a note. If "
            "--planned-at is omitted, the first window start becomes the "
            "planned workout time."
        ),
    )
    parser.add_argument(
        "--route-map-scope",
        choices=("top", "all", "none"),
        default="top",
        help=(
            "How many Xert route maps to fetch/cache. Daily recommendations only "
            "need the top route; use all for image-backed route menus."
        ),
    )
    parser.add_argument(
        "--available-modalities",
        required=True,
        type=parse_available_modalities,
        metavar="indoor,outdoor|indoor|outdoor",
        help=(
            "Comma-separated training modalities available in the current context. "
            "The caller/LLM must choose this explicitly."
        ),
    )
    parser.add_argument(
        "--unavailable-reason",
        action="append",
        default=[],
        type=parse_unavailable_reason,
        metavar="indoor=reason|outdoor=reason",
        help=(
            "Reason for an unavailable modality. Can be repeated. The value is "
            "used only when the modality is not present in --available-modalities."
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact chat-oriented summary instead of the full JSON packet.",
    )
    args = parser.parse_args()
    indoor_available = "indoor" in args.available_modalities
    outdoor_available = "outdoor" in args.available_modalities
    requested_unavailable_reasons = unavailable_reason_map(args.unavailable_reason)
    indoor_unavailable_reason = requested_unavailable_reasons.get(
        "indoor", "no_indoor_equipment_available"
    )
    outdoor_unavailable_reason = requested_unavailable_reasons.get(
        "outdoor", "outdoor_riding_not_realistic"
    )
    unavailable_reasons = {}
    if not indoor_available:
        unavailable_reasons["indoor"] = indoor_unavailable_reason
    if not outdoor_available:
        unavailable_reasons["outdoor"] = outdoor_unavailable_reason
    validate_context(parser, args=args, outdoor_available=outdoor_available)

    output_dir = args.output_dir / args.date
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now().astimezone()
    now = (
        parse_cli_local_datetime(args.now, default_day=args.date)
        if args.now
        else generated_at
    )
    available_windows = parse_available_windows(
        args.available_window,
        default_day=args.date,
        tzinfo=now.tzinfo,
    )
    if args.planned_at:
        planned_at = parse_cli_local_datetime(args.planned_at, default_day=args.date)
        planned_at_source = "cli"
        validate_planned_at_in_available_windows(
            parser,
            planned_at=planned_at,
            available_windows=available_windows,
        )
    elif available_windows:
        planned_at = available_windows[0]["start"]
        planned_at_source = "available_window"
    else:
        planned_at = default_planned_at(args.date, now=now)
        planned_at_source = "default"
    source_files = source_paths(output_dir, args.date)
    if args.garmin_json and refresh_spec_forces(args.refresh, "garmin"):
        parser.error("--garmin-json cannot be combined with --refresh all or --refresh garmin.")
    if args.garmin_json:
        garmin_override = load_json_if_exists(args.garmin_json)
        if not isinstance(garmin_override, dict):
            parser.error(f"--garmin-json must contain one JSON object: {args.garmin_json}")
        garmin_override.setdefault("source_file", str(args.garmin_json))
        write_json(source_files["garmin"], garmin_override)
    required_sources = {
        "garmin", "xert", "intervals_wellness", "intervals_events",
        "xert_activity_loads", "weather_home",
    }
    if indoor_available:
        required_sources.add("xert_recommended_training")
    if outdoor_available:
        required_sources.add("weather_route")
        if args.route_map_scope != "none":
            required_sources.add("xert_route_maps")
    source_refresh = build_source_refresh_plan(
        source_files,
        required=required_sources,
        refresh_spec=args.refresh,
        checked_at=generated_at,
        overrides={"garmin"} if args.garmin_json else set(),
    )
    intervals_cache_refresh = None
    if source_group_will_refresh(source_refresh, "intervals"):
        intervals_cache_refresh = refresh_recent_intervals_cache()
    latest_activity = latest_activity_on_or_before(args.date, artifacts_dir=ARTIFACTS_DIR)
    primary_sources = {
        key for key in ("garmin", "xert", "intervals_wellness", "intervals_events")
        if source_refresh.get(key, {}).get("refresh")
    }
    if primary_sources:
        fetch_primary_live_inputs(
            day=args.date,
            now=now,
            planned_at=planned_at,
            latest_activity=latest_activity,
            source_files=source_files,
            sources=primary_sources,
        )
    if source_refresh.get("xert_activity_loads", {}).get("refresh"):
        write_json(
            source_files["xert_activity_loads"],
            fetch_xert_activity_loads_for_recent_window(args.date),
        )
    if indoor_available and source_refresh.get("xert_recommended_training", {}).get("refresh"):
        recommended_training = run_json(
            [
                sys.executable,
                "-B",
                "plugins/xert/scripts/xert_cli.py",
                "recommended-training",
                "--date",
                args.date,
            ]
        )
        write_json(source_files["xert_recommended_training"], recommended_training)
    ensure_source_files_exist(
        source_files,
        required=tuple(
            sorted(
                required_sources
                - {"xert_route_maps", "weather_home", "weather_route"}
            )
        ),
        policy=args.refresh["mode"],
    )

    readiness_packet = build_readiness_snapshot(
        args.date,
        artifacts_dir=ARTIFACTS_DIR,
        now=now,
        planned_at=planned_at,
        garmin_input=load_garmin_input(str(source_files["garmin"])),
        xert_input=load_xert_input(str(source_files["xert"])),
        intervals_wellness_input=load_json_if_exists(source_files["intervals_wellness"]),
        intervals_events_input=load_json_if_exists(source_files["intervals_events"]),
    )
    history_context = training_history_context(
        args.date,
        artifacts_dir=ARTIFACTS_DIR,
        xert_activity_loads=load_json_if_exists(source_files["xert_activity_loads"]),
    )
    target_resolution = resolve_training_targets(
        explicit_minutes=args.target_minutes,
        explicit_load=args.target_load,
        readiness_packet=readiness_packet,
        history_context=history_context,
    )
    apply_acute_readiness_target_guardrail(target_resolution, readiness_packet)
    apply_intervals_illness_target_guardrail(
        target_resolution,
        (readiness_packet.get("recommendation_inputs") or {}).get(
            "intervals_wellness_events"
        )
        or {},
    )
    target_resolution["split"] = split_session_info(
        target_resolution,
        planned_at=planned_at,
        available_windows=available_windows,
    )
    target_resolution["split_note"] = split_session_guidance(target_resolution["split"])
    target_minutes = float(target_resolution["target_minutes"])
    target_load = float(target_resolution["target_load"])
    target_distance_km = outdoor_target_distance_km(
        target_minutes=target_minutes,
        surface_preference=args.surface_preference,
    )
    target_resolution["target_distance_km"] = target_distance_km
    target_resolution["target_distance_meaning"] = (
        "Derived before route ranking from the recommendation duration target "
        "and the selected surface preference."
    )
    workout_bias = recommendation_bias_from_readiness_packet(
        readiness_packet,
    )

    recommended_training_raw = (
        None if not indoor_available else load_json_if_exists(source_files["xert_recommended_training"])
    )
    if not indoor_available:
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
        )
        annotate_indoor_window_fit(
            indoor_workouts_packet,
            planned_at=planned_at,
            available_windows=available_windows,
        )
        write_json(
            source_files["xert_workouts"],
            indoor_workouts_packet,
        )
    elif args.refresh["mode"] == "none":
        ensure_source_files_exist(source_files, required=("xert_workouts",))
        indoor_workouts_packet = load_json_if_exists(source_files["xert_workouts"])
    else:
        indoor_workouts_packet = load_json_if_exists(source_files["xert_workouts"])
    if indoor_available and isinstance(indoor_workouts_packet, dict):
        annotate_indoor_window_fit(
            indoor_workouts_packet,
            planned_at=planned_at,
            available_windows=available_windows,
        )
        write_json(source_files["xert_workouts"], indoor_workouts_packet)

    progression_advice = (
        progression_unavailable_packet(
            reason=requested_unavailable_reasons.get("indoor", "indoor_workout_matching_disabled")
        )
        if not indoor_available
        else build_progression_advice(
            day=args.date,
            source_files=source_files,
            recommendations_dir=args.output_dir,
        )
    )

    if not outdoor_available:
        route_packet = outdoor_unavailable_packet(reason=outdoor_unavailable_reason)
    else:
        route_packet = recommend_routes(
            day=parse_date(args.date),
            years=5,
            target_minutes=None,
            target_load=None,
            xert_loads_json=source_files["xert_activity_loads"],
            target_distance_km=target_distance_km,
            queries=[],
            max_results=8,
            artifacts_dir=ARTIFACTS_DIR,
            start_anchor_name=args.start_anchor_displayname or "selected start anchor",
            start_anchor_lat=args.start_anchor_lat,
            start_anchor_lng=args.start_anchor_lng,
            start_radius_km=args.start_radius_km,
            allow_away=False,
            surface_preference=args.surface_preference,
            route_index=args.route_index,
            rebuild_index=args.rebuild_route_index,
        )
        annotate_route_window_fit(
            route_packet,
            planned_at=planned_at,
            available_windows=available_windows,
        )
    if (
        outdoor_available
        and args.route_map_scope != "none"
        and source_refresh.get("xert_route_maps", {}).get("refresh")
    ):
        route_map_limit = 1 if args.route_map_scope == "top" else None
        route_packet = enrich_route_packet_with_xert_maps(route_packet, limit=route_map_limit)
        route_packet = cache_xert_route_map_images(
            route_packet,
            output_dir=output_dir,
            limit=route_map_limit,
        )
        write_json(source_files["xert_route_maps"], route_packet.get("xert_route_maps") or {})
    first_route = first_recommendation(route_packet)

    weather_sources = {
        key for key in ("weather_home", "weather_route")
        if source_refresh.get(key, {}).get("refresh")
    }
    if weather_sources:
        home_weather_lat, home_weather_lon = home_weather_coordinates(
            start_anchor_lat=args.start_anchor_lat,
            start_anchor_lng=args.start_anchor_lng,
        )
        fetch_weather_inputs(
            planned_at=planned_at,
            outdoor_available=outdoor_available,
            first_route=first_route,
            home_weather_lat=home_weather_lat,
            home_weather_lon=home_weather_lon,
            source_files=source_files,
            sources=weather_sources,
        )

    ensure_source_files_exist(
        source_files,
        required=tuple(
            sorted(
                key
                for key in ("weather_home", "weather_route")
                if key in required_sources
            )
        ),
        policy=args.refresh["mode"],
    )

    weather_home = load_json_if_exists(source_files["weather_home"])
    weather_route = None if not outdoor_available else load_json_if_exists(source_files["weather_route"])
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
    )

    packet = {
        "source": "training-ai-recommend-today",
        "date": args.date,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "planned_at": planned_at.isoformat(timespec="seconds"),
        "planned_at_source": planned_at_source,
        "available_windows": serialize_available_windows(available_windows),
        "available_modalities": sorted(args.available_modalities),
        "unavailable_reasons": unavailable_reasons,
        "source_files": {key: str(path) for key, path in source_files.items()},
        "source_refresh": source_refresh,
        "intervals_cache_refresh": intervals_cache_refresh,
        "readiness": readiness_packet,
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
    if args.summary:
        print(format_summary(packet))
    else:
        print(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))


def source_paths(output_dir: Path, day: str) -> dict[str, Path]:
    return {
        "garmin": output_dir / f"garmin-readiness-{day}.json",
        "xert": output_dir / f"xert-readiness-{day}.json",
        "intervals_wellness": output_dir / f"intervals-wellness-recent-{day}.json",
        "intervals_events": output_dir / f"intervals-events-recent-{day}.json",
        "xert_activity_loads": output_dir / f"xert-activity-loads-recent-{day}.json",
        "xert_recommended_training": output_dir / f"xert-recommended-training-{day}.json",
        "xert_route_maps": output_dir / f"xert-route-maps-{day}.json",
        "xert_workouts": output_dir / f"xert-workouts-{day}.json",
        "progression_vt2": output_dir / f"progression-vt2-{day}.json",
        "progression_vo2max": output_dir / f"progression-vo2max-{day}.json",
        "weather_home": output_dir / f"yr-home-{day}.json",
        "weather_route": output_dir / f"yr-route-{day}.json",
    }


def parse_refresh_spec(raw: str) -> dict[str, Any]:
    value = raw.strip().lower()
    if value in {"auto", "all", "none"}:
        return {"mode": value, "sources": []}
    sources = sorted({part.strip() for part in value.split(",") if part.strip()})
    unknown = sorted(set(sources) - REFRESH_GROUPS)
    if not sources or unknown:
        detail = f"; unsupported: {', '.join(unknown)}" if unknown else ""
        raise argparse.ArgumentTypeError(
            "expected auto, all, none, or a comma-separated subset of "
            f"{', '.join(sorted(REFRESH_GROUPS))}{detail}"
        )
    return {"mode": "selected", "sources": sources}


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


def source_file_age_minutes(path: Path, *, checked_at: datetime) -> float | None:
    if not path.exists():
        return None
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=checked_at.tzinfo)
    return max(0.0, (checked_at - modified_at).total_seconds() / 60)


def source_group_will_refresh(plan: dict[str, dict[str, Any]], group: str) -> bool:
    return any(row["group"] == group and row["refresh"] for row in plan.values())


def parse_available_modalities(raw: str) -> frozenset[str]:
    modalities = frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
    allowed = {"indoor", "outdoor"}
    unknown = sorted(modalities - allowed)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unsupported modalit{'y' if len(unknown) == 1 else 'ies'}: {', '.join(unknown)}"
        )
    if not modalities:
        raise argparse.ArgumentTypeError(
            "at least one modality must be supplied: indoor, outdoor, or indoor,outdoor"
        )
    return modalities


def parse_unavailable_reason(raw: str) -> tuple[str, str]:
    modality, separator, reason = raw.partition("=")
    modality = modality.strip().lower()
    reason = reason.strip()
    if separator != "=" or not modality or not reason:
        raise argparse.ArgumentTypeError(
            "expected modality=reason, for example indoor=no_trainer_at_location"
        )
    if modality not in {"indoor", "outdoor"}:
        raise argparse.ArgumentTypeError(
            f"unsupported modality for unavailable reason: {modality}"
        )
    return modality, reason


def unavailable_reason_map(reason_pairs: list[tuple[str, str]]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for modality, reason in reason_pairs:
        reasons[modality] = reason
    return reasons


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
            "--start-anchor-lat and --start-anchor-lng must be provided together."
        )
    if outdoor_available and not (has_start_lat and has_start_lng):
        parser.error(
            "--start-anchor-lat and --start-anchor-lng are required when "
            "--available-modalities includes outdoor."
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
        "xmb_candidates": [],
        "other_candidates": [],
        "higher_intensity_candidates": [],
        "non_xmb_candidates_omitted_by_default": 0,
        "recommended": None,
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


def progression_unavailable_packet(*, reason: str) -> dict[str, Any]:
    return {
        "source": "progression_unavailable",
        "available": False,
        "reason": reason,
        "meaning": (
            "Workout-family progression matching was skipped because indoor "
            "workout recommendations are disabled for this context."
        ),
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


def parse_available_windows(
    values: list[str],
    *,
    default_day: str,
    tzinfo: Any,
) -> list[dict[str, datetime]]:
    windows = [
        parse_available_window(value, default_day=default_day, tzinfo=tzinfo)
        for value in values
    ]
    return sorted(windows, key=lambda window: window["start"])


def parse_available_window(
    value: str,
    *,
    default_day: str,
    tzinfo: Any,
) -> dict[str, datetime]:
    time_part, separator, note_part = value.partition(";")
    note = note_part.strip() if separator else None
    match = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*", time_part)
    if not match:
        raise SystemExit(
            f"Invalid --available-window {value!r}; expected HH:MM-HH:MM[; note]."
        )
    start = parse_cli_local_datetime(match.group(1), default_day=default_day).replace(tzinfo=tzinfo)
    end = parse_cli_local_datetime(match.group(2), default_day=default_day).replace(tzinfo=tzinfo)
    if end <= start:
        end += timedelta(days=1)
    return {"start": start, "end": end, "note": note or None}


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
        "--planned-at must fall inside one of the supplied --available-window values."
    )


def serialize_available_windows(windows: list[dict[str, datetime]]) -> list[dict[str, Any]]:
    return [serialize_available_window(window) for window in windows]


def serialize_available_window(window: dict[str, Any] | None) -> dict[str, Any] | None:
    if not window:
        return None
    return {
        "start": window["start"].isoformat(timespec="seconds"),
        "end": window["end"].isoformat(timespec="seconds"),
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


def fetch_primary_live_inputs(
    *,
    day: str,
    now: datetime,
    planned_at: datetime,
    latest_activity: dict[str, Any] | None,
    source_files: dict[str, Path],
    sources: set[str],
) -> None:
    """Fetch independent Garmin, Xert, and Intervals wellness inputs concurrently."""

    def fetch_garmin() -> None:
        run_json_to_file(
            [
                sys.executable,
                "-B",
                "plugins/garmin-connect/scripts/garmin_connect_cli.py",
                "day",
                day,
                "--profile",
                "readiness",
                "--tolerate-errors",
            ],
            source_files["garmin"],
        )

    def fetch_xert() -> None:
        xert_command = [
            sys.executable,
            "-B",
            "plugins/xert/scripts/xert_cli.py",
            "readiness-input",
            "--advice-source",
            "auto",
            "--advice-at",
            planned_at.isoformat(timespec="seconds"),
            "--advice-now",
            now.isoformat(timespec="seconds"),
        ]
        xert_activity_path = resolve_xert_activity_path(latest_activity)
        if xert_activity_path:
            xert_command.extend(["--activity", xert_activity_path])
        run_json_to_file(xert_command, source_files["xert"])

    def fetch_intervals_wellness() -> None:
        end = date.fromisoformat(day)
        start = end - timedelta(days=13)
        run_json_to_file(
            [
                sys.executable,
                "-B",
                "plugins/intervals-icu/scripts/intervals_icu_cli.py",
                "wellness",
                "--since",
                start.isoformat(),
                "--until",
                day,
            ],
            source_files["intervals_wellness"],
        )

    def fetch_intervals_events() -> None:
        end = date.fromisoformat(day)
        start = end - timedelta(days=13)
        run_json_to_file(
            [
                sys.executable, "-B",
                "plugins/intervals-icu/scripts/intervals_icu_cli.py", "events",
                "--since", start.isoformat(), "--until", day,
                "--category", "SICK,INJURED,HOLIDAY",
            ],
            source_files["intervals_events"],
        )

    available_steps = {
        "garmin": fetch_garmin,
        "xert": fetch_xert,
        "intervals_wellness": fetch_intervals_wellness,
        "intervals_events": fetch_intervals_events,
    }
    steps = {key: available_steps[key] for key in sources}
    run_parallel_steps(steps)


def fetch_weather_inputs(
    *,
    planned_at: datetime,
    outdoor_available: bool,
    first_route: dict[str, Any] | None,
    home_weather_lat: float,
    home_weather_lon: float,
    source_files: dict[str, Path],
    sources: set[str],
) -> None:
    """Fetch home and route weather concurrently once the route is known."""

    available_steps = {
        "weather_home": lambda: run_json_to_file(
            weather_command(
                None,
                lat=home_weather_lat,
                lon=home_weather_lon,
                planned_at=planned_at,
                hours=4,
            ),
            source_files["weather_home"],
        )
    }
    if outdoor_available:
        available_steps["weather_route"] = lambda: run_json_to_file(
            weather_command(
                None,
                lat=route_weather_lat(first_route),
                lon=route_weather_lon(first_route),
                planned_at=planned_at,
                hours=4,
            ),
            source_files["weather_route"],
        )
    run_parallel_steps({key: available_steps[key] for key in sources})


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


def refresh_recent_intervals_cache(*, count: int = 5, lookback_days: int = 14) -> dict[str, Any]:
    """Save recent Intervals activities that are missing from local artifacts."""

    payload = run_json(
        [
            sys.executable,
            "-B",
            "plugins/intervals-icu/scripts/intervals_icu_cli.py",
            "recent",
            "--count",
            str(count),
            "--lookback-days",
            str(lookback_days),
        ]
    )
    activities = payload.get("activities") if isinstance(payload, dict) else None
    if not isinstance(activities, list):
        return {"checked": 0, "saved": [], "skipped": [], "reason": "no_recent_activities"}
    saved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        activity_id = str(activity.get("id") or "")
        start = str(activity.get("start_date_local") or "")
        if not activity_id or len(start) < 10:
            continue
        activity_dir = ARTIFACTS_DIR / "activities" / f"{start[:10]}_{activity_id}"
        if (activity_dir / "activity.json").exists() and (activity_dir / "streams.csv").exists():
            skipped.append({"id": activity_id, "reason": "already_cached"})
            continue
        artifact_paths = run_json(
            [
                sys.executable,
                "-B",
                "plugins/intervals-icu/scripts/intervals_icu_cli.py",
                "save-activity",
                activity_id,
                "--output-dir",
                str(ARTIFACTS_DIR),
            ]
        )
        saved.append({"id": activity_id, "artifacts": artifact_paths})
    return {"checked": len(activities), "saved": saved, "skipped": skipped}


def run_json_to_file(command: list[str], path: Path) -> None:
    payload = run_json(command)
    write_json(path, payload)


def build_progression_advice(
    *,
    day: str,
    source_files: dict[str, Path],
    recommendations_dir: Path,
) -> dict[str, Any]:
    """Run workout-family progression advisors as context, not as day readiness."""

    advice = {}
    for workout_type, key in (("vt2", "progression_vt2"), ("vo2max", "progression_vo2max")):
        command = [
            sys.executable,
            "-B",
            "scripts/progression_advisor.py",
            "--type",
            workout_type,
            "--date",
            day,
            "--recommendations-dir",
            str(recommendations_dir),
            "--xert-recommended-training-json",
            str(source_files["xert_recommended_training"]),
            "--output",
            str(source_files[key]),
        ]
        payload = run_json(command)
        write_json(source_files[key], payload)
        advice[workout_type] = payload
    return {
        "meaning": (
            "Progression advisors do not decide whether the athlete is fresh enough "
            "today. They only describe the next sensible progression step if that "
            "workout family is chosen by the coach/LLM layer."
        ),
        **advice,
    }


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
            f"--refresh {policy} requires source files after refresh planning. Missing: "
            + ", ".join(missing)
        )


def format_command(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def resolve_xert_activity_path(activity: dict[str, Any] | None) -> str | None:
    if not activity or not activity.get("start_local"):
        return None
    start_local = parse_local_datetime(str(activity["start_local"]))
    day = start_local.date().isoformat()
    try:
        activities = run_json(
            [
                sys.executable,
                "-B",
                "plugins/xert/scripts/xert_cli.py",
                "activities",
                day,
                day,
            ]
        )
    except SystemExit:
        return None
    if not isinstance(activities, list):
        return None
    candidates = []
    for candidate in activities:
        if not isinstance(candidate, dict) or not candidate.get("path"):
            continue
        candidate_start = xert_activity_start_local(candidate)
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
    limit: int | None = None,
) -> dict[str, Any]:
    """Attach Xert activity/map URLs to route recommendations when they match."""

    recommendations = route_packet.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        return route_packet

    xert_by_date: dict[str, list[dict[str, Any]]] = {}
    enriched = []
    for index, route in enumerate(recommendations, start=1):
        if not isinstance(route, dict):
            enriched.append(route)
            continue
        if limit is not None and index > limit:
            enriched.append(route)
            continue
        route_date = str(route.get("date") or "")
        if route_date and route_date not in xert_by_date:
            xert_by_date[route_date] = fetch_xert_activities_for_route_date(route_date)
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
        headers={"User-Agent": "training-ai-recommend-today/1.0"},
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


def fetch_xert_activities_for_route_date(day: str) -> list[dict[str, Any]]:
    try:
        activities = run_json(
            [
                sys.executable,
                "-B",
                "plugins/xert/scripts/xert_cli.py",
                "activities",
                day,
                day,
            ]
        )
    except SystemExit:
        return []
    if not isinstance(activities, list):
        return []
    return [row for row in activities if isinstance(row, dict)]


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


def xert_activity_start_local(activity: dict[str, Any]) -> datetime | None:
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
    return parsed.astimezone()


def home_weather_coordinates(
    *,
    start_anchor_lat: float | None,
    start_anchor_lng: float | None,
) -> tuple[float, float]:
    if start_anchor_lat is not None and start_anchor_lng is not None:
        return start_anchor_lat, start_anchor_lng
    return SLEMDAL_LAT, SLEMDAL_LON


def weather_command(
    location: str | None,
    *,
    planned_at: datetime,
    hours: int,
    lat: float | None = None,
    lon: float | None = None,
) -> list[str]:
    start = planned_at - timedelta(hours=1)
    end = planned_at + timedelta(hours=hours)
    command = [
        sys.executable,
        "-B",
        "plugins/yr/scripts/yr_cli.py",
    ]
    if location:
        command.append(location)
    else:
        command.extend(["--lat", f"{lat:.4f}", "--lon", f"{lon:.4f}"])
    command.extend(
        [
            "--hourly",
            "--from-local",
            start.isoformat(timespec="seconds"),
            "--to-local",
            end.isoformat(timespec="seconds"),
        ]
    )
    return command


def parse_local_datetime(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed.astimezone()


def parse_optional_local_datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return parse_local_datetime(str(raw))
    except ValueError:
        return None


def first_recommendation(route_packet: dict[str, Any]) -> dict[str, Any] | None:
    recommendations = route_packet.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        first = recommendations[0]
        if isinstance(first, dict):
            return first
    return None


def route_weather_lat(route: dict[str, Any] | None) -> float:
    bbox = (route or {}).get("bbox") or {}
    min_lat = bbox.get("min_lat")
    max_lat = bbox.get("max_lat")
    if isinstance(min_lat, (int, float)) and isinstance(max_lat, (int, float)):
        return (min_lat + max_lat) / 2
    return SORKEDALEN_LAT


def route_weather_lon(route: dict[str, Any] | None) -> float:
    bbox = (route or {}).get("bbox") or {}
    min_lon = bbox.get("min_lng")
    max_lon = bbox.get("max_lng")
    if isinstance(min_lon, (int, float)) and isinstance(max_lon, (int, float)):
        return (min_lon + max_lon) / 2
    return SORKEDALEN_LON


def load_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_xert_activity_loads_for_recent_window(day: str, *, days: int = 14) -> dict[str, Any]:
    target_day = date.fromisoformat(day)
    start_day = (target_day - timedelta(days=days - 1)).isoformat()
    return run_json(
        [
            sys.executable,
            "-B",
            "plugins/xert/scripts/xert_cli.py",
            "activity-loads",
            start_day,
            day,
        ]
    )


def compact_xert_activity_load(activity: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    summary = detail.get("summary") if isinstance(detail, dict) else {}
    progression = (summary or {}).get("progression") or {}
    xss = (progression.get("xss") or {}).get("total")
    if xss is None:
        xss = (summary or {}).get("xss")
    return {
        "path": activity.get("path") or (summary or {}).get("path"),
        "name": (summary or {}).get("name") or activity.get("name"),
        "start_local": xert_start_local((summary or {}).get("start_date") or activity.get("start_date")),
        "distance_km": number((summary or {}).get("distance") or activity.get("distance")),
        "duration_minutes": minutes_from_seconds(number((summary or {}).get("duration"))),
        "xss": number(xss),
        "low_xss": number((summary or {}).get("xlss") or (progression.get("xss") or {}).get("xlss")),
        "high_xss": number((summary or {}).get("xhss") or (progression.get("xss") or {}).get("xhss")),
        "peak_xss": number((summary or {}).get("xpss") or (progression.get("xss") or {}).get("xpss")),
        "difficulty": number((summary or {}).get("difficulty")),
    }


def xert_start_local(raw: Any) -> str | None:
    value = raw.get("date") if isinstance(raw, dict) else raw
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().isoformat(timespec="seconds")


def training_history_context(
    day: str,
    *,
    artifacts_dir: Path,
    xert_activity_loads: dict[str, Any] | None,
) -> dict[str, Any]:
    activities_dir = artifacts_dir / "activities"
    target_day = date.fromisoformat(day)
    xert_loads = xert_load_index(xert_activity_loads)
    rows: list[dict[str, Any]] = []
    duration_rows: list[dict[str, Any]] = []
    if activities_dir.exists():
        for metadata_path in activities_dir.glob("*/activity.json"):
            metadata = load_json_if_exists(metadata_path)
            if not isinstance(metadata, dict):
                continue
            start = str(metadata.get("start_date_local") or "")
            if len(start) < 10:
                continue
            try:
                activity_day = date.fromisoformat(start[:10])
            except ValueError:
                continue
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
                load = matched_xert_xss(metadata, xert_loads)
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

    rolling_loads: list[float] = []
    if rows:
        anchor = min(row["date"] for row in rows)
        while anchor <= target_day:
            start = anchor - timedelta(days=6)
            rolling_loads.append(
                sum(row["load"] for row in rows if start <= row["date"] <= anchor)
            )
            anchor += timedelta(days=1)
    load_percentile = percentile_rank(current_load, rolling_loads)
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
        "load_source": "xert_xss",
        "artifacts_dir": str(artifacts_dir),
        "rolling_7d": {
            "start_date": window_start.isoformat(),
            "end_date": target_day.isoformat(),
            "activity_count": current_count,
            "xss": round(current_load, 1),
            "training_load": round(current_load, 1),
            "moving_hours": round(current_minutes / 60, 1),
            "xss_percentile_in_available_window": load_percentile,
            "load_percentile_this_year": load_percentile,
        },
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
            "Use rolling_7d and typical_training_day_baseline to scale endurance "
            "duration relative to this rider's own recent history. Typical-day "
            "baseline aggregates multiple activities on the same calendar day "
            "before taking median/mean."
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


def matched_xert_xss(metadata: dict[str, Any], xert_loads: list[dict[str, Any]]) -> float | None:
    if not xert_loads:
        return None
    start = parse_optional_local_datetime(metadata.get("start_date_local"))
    name = normalize_activity_name(str(metadata.get("name") or ""))
    distance_km = None
    distance_m = number(metadata.get("distance")) or number(metadata.get("icu_distance"))
    if distance_m is not None:
        distance_km = distance_m / 1000
    candidates: list[tuple[float, float]] = []
    for row in xert_loads:
        row_start = parse_optional_local_datetime(row.get("start_local"))
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
    explicit_minutes: float | None,
    explicit_load: float | None,
    readiness_packet: dict[str, Any],
    history_context: dict[str, Any],
) -> dict[str, Any]:
    inputs = readiness_packet.get("recommendation_inputs") or {}
    readiness = inputs.get("garmin_recovery_readiness") or {}
    readiness = inputs.get("garmin_recovery_readiness") or {}
    wellness = inputs.get("wellness") or {}
    xert_training_advice = inputs.get("xert_training_advice") or {}
    latest = inputs.get("latest_activity_load") or {}
    planned_day = str(readiness_packet.get("date") or "")

    if explicit_minutes is not None and explicit_load is not None:
        return {
            "source": "explicit_cli",
            "target_minutes": round(explicit_minutes, 1),
            "target_load": round(explicit_load, 1),
            "reason": (
                "Both target minutes and target load were supplied on the command "
                "line by the caller; they were not derived by the script."
            ),
        }

    rolling = history_context.get("rolling_7d") or {}
    day_baseline = (
        history_context.get("typical_training_day_baseline")
        or history_context.get("typical_session_baseline")
        or {}
    )
    load_pct = number(rolling.get("load_percentile_this_year"))
    day_baseline_minutes = number(day_baseline.get("median_minutes")) or 90.0
    xss_per_min = number(day_baseline.get("xss_per_min_from_available_xert_window")) or 0.85
    caution = numeric_caution_score(
        sleep_hours=seconds_to_hours(wellness.get("sleep_time_seconds")),
        hrv_risk=hrv_readiness_risk(wellness),
        resting_hr_risk=resting_hr_readiness_risk(wellness),
        body_battery_risk=body_battery_readiness_risk(wellness),
    )
    latest_same_day = latest_activity_is_meaningful_same_day(latest, day=planned_day)

    if explicit_minutes is not None:
        minutes = explicit_minutes
        load = explicit_load if explicit_load is not None else load_from_minutes(minutes)
        source = "explicit_minutes_derived_load"
        band = "explicit_minutes"
        target_xss = None
    elif explicit_load is not None:
        load = explicit_load
        minutes = explicit_minutes if explicit_minutes is not None else minutes_from_load(load)
        source = "explicit_load_derived_minutes"
        band = "explicit_load"
    else:
        target_xss = xert_training_advice.get("target_xss") or {}
        xert_load_parts = {
            key: number(target_xss.get(key))
            for key in ("low", "high", "peak")
            if number(target_xss.get(key)) is not None
        }
        xert_target_load = (
            sum(xert_load_parts.values()) if xert_load_parts else None
        )
        if xert_target_load is not None:
            load = xert_target_load
            minutes = clamp(load / xss_per_min, 30.0, 300.0)
            source = "xert_training_advice_target_xss"
            band = "xert_training_advice"
        else:
            load = load_from_minutes(day_baseline_minutes)
            minutes = day_baseline_minutes
            source = "fallback_history_missing_xert_target"
            band = "fallback_history"

    dose_position = dose_position_vs_typical(
        target_minutes=minutes,
        typical_minutes=day_baseline_minutes,
        caution=caution,
        load_pct=load_pct,
    )
    if source == "xert_training_advice_target_xss":
        dose_position["reason"] = (
            "target load comes from Xert's recommended XSS; duration is estimated "
            "from local Xert XSS/min for candidate ranking"
        )

    reasons = [
        f"daily duration baseline median {day_baseline.get('median_minutes')} min",
        f"XSS/min {round(xss_per_min, 3)} from {day_baseline.get('xss_match_count')} matched Xert activities",
    ]
    if source == "xert_training_advice_target_xss":
        parts_text = ", ".join(
            f"{key} {round(value, 1)}" for key, value in xert_load_parts.items()
        )
        reasons.insert(
            0,
            (
                f"target load from Xert's recommended XSS ({parts_text}; "
                f"total {round(load, 1)} XSS)"
            ),
        )
        reasons.append(
            "duration is estimated from local Xert XSS/min only for route/workout ranking"
        )
        reasons.append(
            "low high/peak XSS argues against over-TP/VO2/peak work, but does not by itself rule out subthreshold VT2"
        )
    elif source == "fallback_history_missing_xert_target":
        reasons.insert(0, "Xert recommended XSS was missing; used local baseline fallback")
    if latest_same_day:
        reasons.append("Xert's recommended XSS reflects activities Xert has already accounted for")

    return {
        "source": source,
        "band": band,
        "target_minutes": round(minutes, 1),
        "target_load": round(load, 1),
        "caution_score": round(caution, 2),
        "dose_position_vs_typical": dose_position,
        "rolling_7d_xss": rolling.get("xss"),
        "rolling_7d_load": rolling.get("xss"),
        "rolling_7d_load_percentile_this_year": rolling.get("load_percentile_this_year"),
        "goal_assumption": "general endurance/VT1 support unless an explicit event or intensity goal is supplied",
        "reason": "; ".join(reasons),
        "xert_intensity_semantics": (
            "Xert high/peak XSS primarily reflects work over threshold power/TP. "
            "Controlled VT2/subthreshold work can still be appropriate with a "
            "low high/peak split when readiness, progression, route/logistics, "
            "and user intent support it."
        )
        if source == "xert_training_advice_target_xss"
        else None,
        "meaning": (
            "This is the dose target used to rank indoor workouts and route "
            "candidates. It is explicit when supplied by CLI; otherwise it is "
            "taken from Xert's recommended XSS. Duration may be estimated from "
            "local Xert XSS/min only so route and workout candidates can be "
            "ranked. Same-day activity context should scale ambition, but should "
            "not be subtracted again from Xert's recommended XSS."
        ),
    }


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


def split_session_info(
    target_resolution: dict[str, Any],
    *,
    planned_at: datetime,
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

    current_window = current_available_window(planned_at, available_windows) or available_windows[0]
    current_label = available_window_label(current_window, include_note=True)
    available_minutes_now = max(
        0.0,
        (current_window["end"] - planned_at).total_seconds() / 60,
    )
    first = max(0.0, min(available_minutes_now, target_minutes))
    remaining = max(0.0, target_minutes - first)
    later_windows = [window for window in available_windows if window["start"] > planned_at]
    next_window = later_windows[0] if later_windows else None
    split_needed = remaining >= 15
    result = {
        "available": True,
        "target_minutes": round(target_minutes, 1),
        "current_window": serialize_available_window(current_window),
        "available_minutes_from_planned": round(available_minutes_now, 1),
        "fits_current_window": not split_needed,
        "split_needed": split_needed,
        "first_session_minutes": round(first, 1),
        "remaining_minutes": round(remaining, 1),
        "next_window": serialize_available_window(next_window) if next_window else None,
    }
    if remaining < 15:
        result["guidance"] = (
            f"Available window {current_label} fits the day-dose: "
            f"do about {round(target_minutes)} min now."
        )
        return result

    next_label = (
        available_window_label(next_window, include_note=True)
        if next_window
        else "the next available window"
    )
    result["guidance"] = (
        f"Calendar/logistics split: do about {round(first)} min now from "
        f"{planned_at.strftime('%H:%M')}, then about {round(remaining)} min after "
        f"{next_label}. Keep both parts easy VT1."
    )
    return result


def split_session_guidance(split_info: dict[str, Any]) -> str:
    return str(split_info.get("guidance") or "")


def current_available_window(
    planned_at: datetime,
    available_windows: list[dict[str, datetime]],
) -> dict[str, datetime] | None:
    for window in available_windows:
        if window["start"] <= planned_at < window["end"]:
            return window
    return None


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
    available_windows: list[dict[str, datetime]],
) -> None:
    window_minutes = current_window_minutes(planned_at=planned_at, available_windows=available_windows)
    for key in ("recommended",):
        if isinstance(packet.get(key), dict):
            packet[key]["window_fit"] = window_fit(packet[key].get("duration_minutes"), window_minutes)
    for list_key in ("xmb_candidates", "other_candidates", "higher_intensity_candidates", "relevant_options"):
        for option in packet.get(list_key) or []:
            if isinstance(option, dict):
                option["window_fit"] = window_fit(option.get("duration_minutes"), window_minutes)
    packet["first_window_minutes"] = round(window_minutes, 1) if window_minutes is not None else None
    packet["first_window_fit_tolerance_minutes"] = WINDOW_FIT_TOLERANCE_MINUTES
    packet["shorter_window_options"] = shorter_fitting_options(
        packet.get("relevant_options") or packet.get("xmb_candidates") or [],
        duration_key="duration_minutes",
        window_minutes=window_minutes,
    )


def annotate_route_window_fit(
    packet: dict[str, Any],
    *,
    planned_at: datetime,
    available_windows: list[dict[str, datetime]],
) -> None:
    window_minutes = current_window_minutes(planned_at=planned_at, available_windows=available_windows)
    recommendations = packet.get("recommendations") or []
    for route in recommendations:
        if isinstance(route, dict):
            route["window_fit"] = window_fit(route.get("moving_minutes"), window_minutes)
    packet["first_window_minutes"] = round(window_minutes, 1) if window_minutes is not None else None
    packet["first_window_fit_tolerance_minutes"] = WINDOW_FIT_TOLERANCE_MINUTES
    packet["shorter_window_options"] = shorter_fitting_options(
        recommendations,
        duration_key="moving_minutes",
        window_minutes=window_minutes,
    )


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


def load_from_minutes(minutes: float) -> float:
    return max(15.0, minutes * 0.85)


def minutes_from_load(load: float) -> float:
    return max(20.0, load / 0.85)


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
        ),
        "latest_activity_load": inputs.get("latest_activity_load"),
        "xert_training_advice": inputs.get("xert_training_advice"),
        "xert_recovery": inputs.get("xert_recovery"),
        "garmin_recovery_readiness": inputs.get("garmin_recovery_readiness"),
        "wellness": inputs.get("wellness"),
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
    if stale:
        guidance = "sync_watch_before_hard_session"
    else:
        guidance = "fresh_enough_for_now_decision"

    return {
        "guidance": guidance,
        "stale_inputs": stale,
        "details": details,
        "garmin_training_readiness_timestamp_local": recovery_timestamp,
        "meaning": (
            "Freshness describes Garmin/Xert input recency for same-day decisions. "
            "Stale Garmin time-series data should reduce confidence for intensity, "
            "before intensity, independently of Garmin's composite Training Readiness score."
        ),
    }


def practical_fueling_defaults() -> dict[str, Any]:
    return {}


def apply_intervals_illness_target_guardrail(
    target_resolution: dict[str, Any],
    intervals_events: dict[str, Any],
) -> None:
    """Cap model-derived dose during the first two days after sickness."""

    day = intervals_events.get("return_to_training_day")
    caps = {
        1: {"minutes": 45.0, "load": 25.0},
        2: {"minutes": 60.0, "load": 45.0},
    }
    cap = caps.get(day)
    if not cap:
        return
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
        "day": day,
        "max_minutes": cap["minutes"],
        "max_load": cap["load"],
        "avoid_intensity": True,
        "meaning": (
            "The model-derived dose is capped for a gradual return during the first "
            "two unmarked days after sickness."
        ),
    }


def apply_acute_readiness_target_guardrail(
    target_resolution: dict[str, Any],
    readiness_packet: dict[str, Any],
) -> None:
    """Cap model-derived dose when several acute recovery signals agree."""

    if str(target_resolution.get("source") or "").startswith("explicit_"):
        return

    inputs = readiness_packet.get("recommendation_inputs") or {}
    readiness = inputs.get("garmin_recovery_readiness") or {}
    wellness = inputs.get("wellness") or {}
    load_focus = inputs.get("garmin_load_focus") or {}
    sleep_hours = seconds_to_hours(wellness.get("sleep_time_seconds"))
    hrv_risk = hrv_readiness_risk(wellness)
    resting_hr_risk = resting_hr_readiness_risk(wellness)
    body_battery_risk = body_battery_readiness_risk(wellness)
    direct_domains = {
        "autonomic": max_present(hrv_risk, resting_hr_risk),
        "sleep": sleep_hours_caution(sleep_hours),
        "energy": body_battery_risk,
    }
    caution = sum(value for value in direct_domains.values() if value is not None)

    acwr = number(load_focus.get("acwr"))
    rolling_percentile = number(target_resolution.get("rolling_7d_load_percentile_this_year"))
    load_components = {
        "acwr": linear_risk_optional(acwr, good=0.8, bad=1.4),
        "rolling_7d_percentile": linear_risk_optional(rolling_percentile, good=50.0, bad=80.0),
    }
    cumulative_load_risk = max_present(
        load_components["acwr"], load_components["rolling_7d_percentile"]
    )
    strong_domains = [
        key for key, value in direct_domains.items() if value is not None and value >= 0.6
    ]
    moderate_domains = [
        key for key, value in direct_domains.items() if value is not None and value >= 0.4
    ]
    direct_signal = (
        "poor" if len(strong_domains) >= 2 else "caution"
        if len(moderate_domains) >= 1 else "normal"
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

    cap = None
    level = None
    if (
        len(strong_domains) >= 2
        and cumulative_load_risk is not None
        and cumulative_load_risk >= 0.6
    ):
        cap = {"minutes": 45.0, "load": 30.0}
        level = "recovery_day"
    elif len(strong_domains) >= 2 or (
        len(moderate_domains) >= 2
        and cumulative_load_risk is not None
        and cumulative_load_risk >= 0.35
    ):
        cap = {"minutes": 60.0, "load": 45.0}
        level = "easy_endurance_only"

    if not cap:
        return

    target_resolution["pre_acute_guardrail_target_minutes"] = target_resolution.get(
        "target_minutes"
    )
    target_resolution["pre_acute_guardrail_target_load"] = target_resolution.get(
        "target_load"
    )
    target_resolution["pre_acute_guardrail_dose_position_vs_typical"] = target_resolution.get(
        "dose_position_vs_typical"
    )
    target_resolution["target_minutes"] = min(
        number(target_resolution.get("target_minutes")) or cap["minutes"], cap["minutes"]
    )
    target_resolution["target_load"] = min(
        number(target_resolution.get("target_load")) or cap["load"], cap["load"]
    )
    pre_minutes = number(target_resolution.get("pre_acute_guardrail_target_minutes"))
    target_resolution["dose_position_vs_typical"] = {
        "label": "acute_readiness_capped",
        "phrase": "capped below the model dose by direct readiness inputs",
        "ratio": round(target_resolution["target_minutes"] / pre_minutes, 2)
        if pre_minutes
        else None,
        "reason": (
            "independent physiological domains agreed before workout and route ranking"
        ),
    }
    target_resolution["acute_readiness_guardrail"] = {
        "active": True,
        "level": level,
        "max_minutes": cap["minutes"],
        "max_load": cap["load"],
        "caution_score": round(caution, 2),
        "decision_input": "direct_readiness_domains_and_cumulative_load_context",
        "training_readiness_used_for_dose": False,
        "direct_domains": rounded_optional_map(direct_domains),
        "strong_domains": strong_domains,
        "cumulative_load_risk": round(cumulative_load_risk, 3)
        if cumulative_load_risk is not None
        else None,
        "load_components": rounded_optional_map(load_components),
        "acwr": acwr,
        "rolling_7d_load_percentile_this_year": rolling_percentile,
        "meaning": (
            "The practical dose is derived from independent physiological domains "
            "and cumulative load context. The previous day's individual workout is "
            "not a separate dose input. Garmin's composite Training "
            "Readiness score is retained for diagnostics but is not a dose input."
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
    routes_packet = packet.get("routes") or {}
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
        readiness=readiness,
        wellness=wellness,
        xert=xert,
        latest=latest,
        freshness=freshness,
        same_day_activity=same_day_activity,
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
    soreness_update_requested_for_vt2_plus = bool(
        intervals_events.get("soreness_update_requested_for_vt2_plus")
    )

    return {
        "purpose": (
            "Data context for an LLM-authored training recommendation. This object "
            "intentionally does not choose intensity, bias, or a primary workout."
        ),
        "time_context": {
            "now_local": now.isoformat(timespec="seconds"),
            "planned_at_local": planned_at.isoformat(timespec="seconds"),
            "planned_at_source": planned_at_source,
            "assumed_planned_at": planned_at_source == "default",
            "available_windows": serialize_available_windows(available_windows),
            "evaluated_weather_window": weather_time_window(route_weather)
            or weather_time_window(home_weather),
        },
        "same_day_activity_context": same_day_activity,
        "intervals_wellness_events": intervals_events,
        "health_constraints": {
            "no_training_today": current_illness,
            "form_check_needed": illness_followup_needed,
            "return_to_training_active": return_to_training_active,
            "return_to_training_day": intervals_events.get("return_to_training_day"),
            "return_to_training_guidance": intervals_events.get("return_to_training_guidance"),
            "followup_question": intervals_events.get("followup_question"),
            "soreness_status_missing": intervals_events.get("soreness_status_missing"),
            "current_day_soreness": intervals_events.get("current_day_soreness"),
            "soreness_assumed_ok_when_missing": intervals_events.get(
                "soreness_assumed_ok_when_missing"
            ),
            "soreness_update_requested_for_vt2_plus": (
                soreness_update_requested_for_vt2_plus
            ),
            "soreness_update_request": intervals_events.get(
                "soreness_update_request"
            ),
            "reason": (
                "current_day_sickness_annotation"
                if current_illness
                else "sick_yesterday_today_unmarked"
                if illness_followup_needed
                else None
            ),
            "meaning": (
                "An explicit current-day sickness annotation overrides Garmin/Xert readiness, "
                "training-load targets, workout candidates, and route candidates. If yesterday "
                "was sick and today is unmarked, ask for current form and keep the provisional "
                "recommendation to rest or a very easy return session. Keep days 1-2 after the "
                "last sick day on a progressive low-intensity return ramp. If today's Intervals "
                "soreness is missing, assume soreness is non-limiting and still provide the "
                "appropriate recommendation. When that recommendation is VT2, VO2Max, threshold, "
                "peak-power, or harder work, ask the user to set today's Intervals soreness value. "
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


def presentation_requirements() -> dict[str, Any]:
    return {
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
) -> str:
    if intervals_events.get("current_day_illness"):
        return "rest"
    if intervals_events.get("illness_followup_needed"):
        return "easy_vt1"
    if intervals_events.get("return_to_training_active"):
        return "easy_vt1"
    sleep_hours = seconds_to_hours(wellness.get("sleep_time_seconds"))
    hrv_risk = hrv_readiness_risk(wellness)
    resting_hr_risk = resting_hr_readiness_risk(wellness)
    body_battery_risk = body_battery_readiness_risk(wellness)
    body_battery = number(wellness.get("body_battery_most_recent"))
    xert_projected = xert.get("projected_recovery_hours_at_planned_time") or {}
    xert_low = number(xert_projected.get("low"))
    xert_intensity_ready = xert_supports_intensity(xert_projected)
    caution_score = numeric_caution_score(
        sleep_hours=sleep_hours,
        hrv_risk=hrv_risk,
        resting_hr_risk=resting_hr_risk,
        body_battery_risk=body_battery_risk,
    )
    direct_inputs_only_caution = (
        caution_score >= 0.75
        and xert_intensity_ready is True
        and (xert_low is None or xert_low <= 0)
        and (sleep_hours is not None and sleep_hours >= 7.0)
        and (hrv_risk is None or hrv_risk <= 0.15)
        and (body_battery is None or body_battery >= 70)
    )

    if caution_score >= 2.7:
        if xert_low is not None and xert_low <= 0 and (body_battery is None or body_battery >= 45):
            return "active_recovery_only"
        return "rest"

    if caution_score >= 1.4:
        return "active_recovery_only"

    if caution_score >= 0.75:
        if direct_inputs_only_caution:
            return "normal_vt1"
        return "easy_vt1"
    if xert_low is not None and xert_low > 4:
        return "rest"
    if (
        (hrv_risk is None or hrv_risk < 0.5)
        and (resting_hr_risk is None or resting_hr_risk < 0.5)
        and caution_score <= 0.35
        and xert_intensity_ready is not False
    ):
        return "intensity_ok"
    return "normal_vt1"


def recommendation_bias_from_readiness_packet(
    readiness_packet: dict[str, Any],
) -> str:
    """Resolve the workout-selection bias before workout candidates are ranked."""

    inputs = readiness_packet.get("recommendation_inputs") or {}
    return recommendation_bias(
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
            "Return-to-training day {day}: {duration} min, {intensity}.".format(
                day=intervals_events.get("return_to_training_day"),
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
    if bias == "intensity_ok":
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

    start = parse_optional_local_datetime(latest.get("start_local"))
    end = parse_optional_local_datetime(latest.get("end_local"))
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
    weekly = wellness.get("hrv_weekly_avg")
    low = wellness.get("hrv_balanced_low")
    upper = wellness.get("hrv_balanced_upper")
    low_upper = wellness.get("hrv_low_upper")

    parts = []
    if last is not None:
        parts.append(f"{last} ms")
    if weekly is not None:
        parts.append(f"weekly {weekly}")
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
        recovery_text = f"recovery {recovery} h"
        if recovery_factor:
            recovery_text += f"; recovery_factor={recovery_factor}"
        pieces.append(recovery_text)
    if status:
        pieces.append(f"training_status={status}")
    return ", ".join(pieces) + "."


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
        return f"{most_recent} now, {at_wake} at wake"
    if most_recent is not None:
        return str(most_recent)
    if at_wake is not None:
        return f"{at_wake} at wake"
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
    sleep_h = seconds_to_hours(wellness.get("sleep_time_seconds"))
    hrv = hrv_readiness_risk(wellness)
    resting_hr = resting_hr_readiness_risk(wellness)
    body_battery = body_battery_readiness_risk(wellness)
    parts = [
        ("sleep", sleep_hours_caution(sleep_h)),
        ("hrv", hrv),
        ("resting_hr", resting_hr),
        ("body_battery", body_battery),
    ]
    visible = [f"{name} {round(value, 2)}" for name, value in parts if value is not None]
    total = numeric_caution_score(
        sleep_hours=sleep_h,
        hrv_risk=hrv,
        resting_hr_risk=resting_hr,
        body_battery_risk=body_battery,
    )
    if not visible:
        return "missing"
    return f"total {round(total, 2)} ({', '.join(visible)})"


def hrv_readiness_risk(wellness: dict[str, Any]) -> float | None:
    """Return a continuous HRV caution score from 0.0 to 1.0.

    Garmin's status can jump at the balanced-range threshold. Prefer the
    numeric weekly HRV average against the balanced range when available. If
    numeric HRV context is missing, return None instead of using the enum as a
    decision input.
    """

    weekly = number(wellness.get("hrv_weekly_avg"))
    last = number(wellness.get("hrv_last_night_avg"))
    low = number(wellness.get("hrv_balanced_low"))
    upper = number(wellness.get("hrv_balanced_upper"))

    value = weekly if weekly is not None else last
    if value is not None and low is not None and upper is not None:
        if low <= value <= upper:
            return 0.0
        if value < low:
            # About 12% below the lower balanced boundary is treated as a
            # strong HRV caution; just below the boundary is only mild.
            return min(1.0, max(0.0, (low - value) / max(1.0, low * 0.12)))
        return min(0.75, max(0.0, (value - upper) / max(1.0, upper * 0.12)))

    return None


def numeric_caution_score(
    *,
    sleep_hours: float | None,
    hrv_risk: float | None,
    resting_hr_risk: float | None,
    body_battery_risk: float | None,
) -> float:
    # Use independent direct-input domains. Garmin Training Readiness is a
    # composite diagnostic and must not be counted again as a dose input.
    autonomic = max_present(hrv_risk, resting_hr_risk)
    return sum(
        value
        for value in (
            sleep_hours_caution(sleep_hours),
            autonomic,
            body_battery_risk,
        )
        if value is not None
    )


def sleep_hours_caution(hours: float | None) -> float | None:
    if hours is None:
        return None
    return inverse_linear_risk(hours, good=7.0, bad=5.5)


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
            ["ask_current_form_after_sickness", "avoid_intensity_first_unmarked_day_after_sickness"]
        )
    elif (intervals_events or {}).get("return_to_training_active"):
        guardrails.extend(
            ["return_to_training_ramp_after_illness", "avoid_intensity_during_return_ramp"]
        )
    hrv_risk = hrv_readiness_risk(wellness)
    resting_hr_risk = resting_hr_readiness_risk(wellness)
    sleep_h = seconds_to_hours(wellness.get("sleep_time_seconds"))
    if hrv_risk is not None and hrv_risk >= 0.75:
        guardrails.append("avoid_intensity_hrv_well_below_baseline")
    elif hrv_risk is not None and hrv_risk >= 0.25:
        guardrails.append("caution_hrv_near_or_outside_baseline")
    if resting_hr_risk is not None and resting_hr_risk >= 0.75:
        guardrails.append("avoid_intensity_elevated_resting_hr")
    if sleep_h is not None and sleep_h < 6:
        guardrails.append("limit_duration_short_sleep")
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
            "duration_minutes": "30-60",
            "xss": None,
            "difficulty": None,
            "execution_note": (
                "Very easy recovery ride, roughly 130-165 W, "
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
        "intensity_ok": ("normal", "longer", "conservative", "shorter"),
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
            "moving_minutes": "20-45",
            "distance_km": None,
            "training_load": None,
            "execution_note": (
                "Optional only: flat, very easy spin or walk. Avoid turning it "
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
        "route_reference_note": route.get("route_reference_note"),
        "weather": compact_weather_signal(route_weather),
    }
    if bias in {"rest", "easy_vt1"}:
        option["execution_note"] = "Keep it easier than the historical route load; avoid threshold/VO2 work."
    elif bias == "intensity_ok":
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
    elif bias == "intensity_ok":
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
    return parse_local_datetime(str(raw))


def compact_xert_workout_recommendations(
    payload: dict[str, Any],
    *,
    target_minutes: float,
    target_load: float,
    readiness_bias: str = "normal_vt1",
) -> dict[str, Any]:
    exercises = payload.get("exercises") if isinstance(payload, dict) else []
    workouts = [
        compact_xert_workout(row, target_minutes=target_minutes, target_load=target_load)
        for row in exercises
        if isinstance(row, dict) and row.get("exerciseType") == "Workout"
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
    xmb = [row for row in eligible_low_intensity if row["is_xmb"]]
    ranked_xmb = sorted(
        xmb,
        key=lambda row: workout_rank_key(row, target_minutes=target_minutes, target_load=target_load),
        reverse=True,
    )
    ranked_other = sorted(
        [row for row in eligible_low_intensity if not row["is_xmb"]],
        key=lambda row: workout_rank_key(row, target_minutes=target_minutes, target_load=target_load),
        reverse=True,
    )
    xmb_higher_intensity = [row for row in higher_intensity if row["is_xmb"]]
    non_xmb_higher_intensity = [row for row in higher_intensity if not row["is_xmb"]]
    ranked_higher_intensity = sorted(
        xmb_higher_intensity,
        key=lambda row: workout_rank_key(row, target_minutes=target_minutes, target_load=target_load),
        reverse=True,
    )
    if readiness_bias in {"rest", "active_recovery_only", "easy_vt1"}:
        bias_suppressed.extend(higher_intensity)
        ranked_higher_intensity = []
    return {
        "source": "xert_recommended_training_compact",
        "policy": (
            "Prefer XMB workouts for indoor recommendations when suitable. "
            "Default summary candidate lists only show XMB workouts because "
            "those are user-authored workouts. "
            "For chat recommendations, present a small menu of relevant indoor "
            "options when multiple XMB workouts fit the same goal, especially "
            "near shorter/normal/longer duration choices. "
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
        "xmb_candidates": ranked_xmb[:5],
        "other_candidates": ranked_other[:3],
        "higher_intensity_candidates": ranked_higher_intensity[:5],
        "suppressed_by_readiness_bias": [
            suppressed_workout_trace(row, readiness_bias=readiness_bias)
            for row in bias_suppressed[:10]
        ],
        "non_xmb_candidates_omitted_by_default": len(ranked_other) + len(non_xmb_higher_intensity),
        "recommended": ranked_xmb[0] if ranked_xmb else None,
        "relevant_options": relevant_indoor_options(ranked_xmb),
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
    ranked_xmb: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a compact menu of viable indoor options for chat recommendations."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in ranked_xmb:
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
    duration_minutes = round((number(row.get("duration")) or 0) / 60, 1)
    xss = number(row.get("xss"))
    intensity = workout_intensity_profile(row, name=name)
    structure = workout_structure_guidance(name=name, duration_minutes=duration_minutes)
    result = {
        "name": name,
        "path": path,
        "url": row.get("url"),
        "is_xmb": name.startswith("XMB: "),
        "intensity_tags": intensity["tags"],
        "low_intensity_candidate": intensity["low_intensity_candidate"],
        "suppressed_from_default": intensity["suppressed_from_default"],
        "suppressed_reason": intensity["suppressed_reason"],
        "owner": row.get("owner"),
        "liked": row.get("liked"),
        "disliked": row.get("disliked"),
        "duration_minutes": duration_minutes,
        "xss": xss,
        "low_xss": row.get("xlss"),
        "high_xss": row.get("xhss"),
        "peak_xss": row.get("xpss"),
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
            "When recommending this as an existing Xert/XMB workout, tell the user "
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


def format_summary(packet: dict[str, Any]) -> str:
    decision = packet.get("decision_inputs") or {}
    context = packet.get("llm_context") or {}
    fueling = packet.get("fueling_defaults") or {}
    freshness = decision.get("freshness_summary") or {}
    readiness = decision.get("garmin_recovery_readiness") or {}
    load_focus = decision.get("garmin_load_focus") or {}
    wellness = decision.get("wellness") or {}
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

    lines = [
        f"Recommendation context packet: {packet.get('date')} planned {packet.get('planned_at')}",
        "",
        "LLM context:",
        "  Purpose: data collection only; LLM should choose the training recommendation.",
        "  Freshness: {freshness}".format(
            freshness=freshness.get("guidance"),
        ),
        "  Planned time: {planned} ({source})".format(
            planned=time_context.get("planned_at_local") or packet.get("planned_at"),
            source=time_context.get("planned_at_source") or packet.get("planned_at_source"),
        ),
        "  Activity context: {context}".format(
            context=same_day_activity_line(same_day_activity),
        ),
        "  Health constraint: {constraint}".format(
            constraint=(
                "NO TRAINING TODAY; explicit Intervals.icu sickness annotation overrides dose and candidates"
                if no_training_today
                else "FORM CHECK REQUIRED; sick yesterday and today unmarked, ask whether still sick or first healthy day; avoid intensity meanwhile"
                if form_check_needed
                else "RETURN-TO-TRAINING RAMP DAY {day}; use {guidance}, no intensity".format(
                    day=health_constraints.get("return_to_training_day"),
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
        "  Xert advice source: {source}".format(
            source=xert_advice_source_line(xert_training_advice),
        ),
        "  Dose vs typical: {position}".format(
            position=dose_position_line(target_resolution),
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
            targets=presentation_target_watts_line(presentation),
        ),
        "  VT2 progression: {progression}".format(
            progression=progression_context_line(progression, "vt2"),
        ),
        "  VO2Max progression: {progression}".format(
            progression=progression_context_line(progression, "vo2max"),
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
        "  Garmin composite diagnostics (not dose inputs): readiness {score}/100; projected recovery {recovery} h; level={level}, recovery_factor={factor}, training_status={status}".format(
            score=readiness.get("training_readiness_score"),
            recovery=readiness.get("projected_recovery_time_hours_at_planned")
            if readiness.get("projected_recovery_time_hours_at_planned") is not None
            else readiness.get("projected_recovery_time_hours_now"),
            level=readiness.get("training_readiness_level"),
            factor=readiness.get("recovery_time_factor_feedback"),
            status=readiness.get("training_status_feedback"),
        ),
        "  Numeric caution: {caution}".format(
            caution=caution_summary_line(readiness, wellness),
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
            if advice:
                lines.append(f"  {workout_type.upper()}: {progression_summary_line(advice)}")
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
        return "sick yesterday, today unmarked; form check required" + (
            f" ({latest.get('comments')})" if latest.get("comments") else ""
        )
    if events.get("return_to_training_active"):
        guidance = events.get("return_to_training_guidance") or {}
        return "return ramp day {day}: {duration}, {intensity}".format(
            day=events.get("return_to_training_day"),
            duration=guidance.get("duration_minutes"),
            intensity=guidance.get("intensity"),
        )
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
                "xmb_match={name} ({quality})".format(
                    name=best.get("name"),
                    quality=matching.get("match_quality"),
                )
            )
        elif matching.get("reason"):
            parts.append(f"xmb_match={matching.get('reason')}")
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
    return f"{line}; {fit}" if fit else line


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


def route_map_line(option: dict[str, Any] | None) -> str:
    if not isinstance(option, dict) or not option:
        return "missing"
    if option.get("available") is False:
        return "unavailable"
    if option.get("name") == "Active recovery only":
        return "not applicable"
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


def dose_target_line(target_resolution: dict[str, Any]) -> str:
    if not isinstance(target_resolution, dict) or not target_resolution:
        return "missing"
    return "{minutes} min / XSS {load}: {reason}".format(
        minutes=target_resolution.get("target_minutes"),
        load=target_resolution.get("target_load"),
        reason=target_resolution.get("reason") or "missing reason",
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
    return "{start}-{end}, {temp}, wind {wind}, precip {precip}, {symbol}".format(
        start=str(hourly[0].get("time_local") or "")[11:16],
        end=str(hourly[-1].get("time_local") or "")[11:16],
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
