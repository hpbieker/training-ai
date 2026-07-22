#!/usr/bin/env python3
"""Build an incremental route catalog from saved outdoor ride activities."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import route_recommendations as rr
from analysis import ARTIFACTS_DIR, load_activity_metadata, value


ROUTE_CATALOG_SCHEMA = "training-ai-route-catalog-v1"
RAW_ROUTE_SCHEMA = "training-ai-raw-route-v1"
CLEANED_ROUTE_SCHEMA = "training-ai-cleaned-route-v1"
SCORED_ROUTE_SCHEMA = "training-ai-scored-route-v1"
GPS_CLEANING_MODEL_VERSION = "gps-clean-v2-spike-jump-filter-with-group-samples"
OSM_MAP_MATCH_MODEL_VERSION = "osm-way-sequence-v1"
OSM_TILE_SCHEMA = "training-ai-osm-tile-v1"
OSM_TILE_LAT_STEP_DEG = 0.01
OSM_TILE_LNG_STEP_DEG = 0.02
OSM_TILE_PADDING_M = 200.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cached raw, cleaned, grouped, and scored route files.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/routes"))
    parser.add_argument("--max-activities", type=int)
    parser.add_argument("--activity-id", action="append", help="Only build selected activity id(s). Can be repeated.")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--map-match-osm",
        action="store_true",
        help="Fetch OSM ways and add an ordered way-sequence to cleaned routes.",
    )
    parser.add_argument(
        "--max-map-match-routes",
        type=int,
        help="Limit OSM map-matching to the first N GPS routes in this run.",
    )
    parser.add_argument("--osm-tile-cache-dir", type=Path, default=Path("outputs/osm-cache/tiles"))
    parser.add_argument("--osm-tile-lat-step", type=float, default=OSM_TILE_LAT_STEP_DEG)
    parser.add_argument("--osm-tile-lng-step", type=float, default=OSM_TILE_LNG_STEP_DEG)
    parser.add_argument("--osm-tile-padding-m", type=float, default=OSM_TILE_PADDING_M)
    parser.add_argument("--start-anchor-displayname", dest="start_anchor_name")
    parser.add_argument("--start-anchor-lat", type=float)
    parser.add_argument("--start-anchor-lng", type=float)
    parser.add_argument("--start-radius-km", type=float, default=rr.DEFAULT_START_RADIUS_KM)
    parser.add_argument(
        "--surface-preference",
        choices=("road", "gravel", "any", "unknown-ok"),
        default="road",
    )
    parser.add_argument("--target-distance-km", type=float)
    args = parser.parse_args()

    result = build_route_catalog(
        day=rr.parse_date(args.date),
        years=args.years,
        artifacts_dir=args.artifacts_dir,
        output_dir=args.output_dir,
        max_activities=args.max_activities,
        activity_ids=set(args.activity_id or []),
        rebuild=args.rebuild,
        map_match_osm=args.map_match_osm,
        max_map_match_routes=args.max_map_match_routes,
        osm_tile_cache_dir=args.osm_tile_cache_dir,
        osm_tile_lat_step=args.osm_tile_lat_step,
        osm_tile_lng_step=args.osm_tile_lng_step,
        osm_tile_padding_m=args.osm_tile_padding_m,
        start_anchor_name=args.start_anchor_name,
        start_anchor_lat=args.start_anchor_lat,
        start_anchor_lng=args.start_anchor_lng,
        start_radius_km=args.start_radius_km,
        surface_preference=args.surface_preference,
        target_distance_km=args.target_distance_km,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def build_route_catalog(
    *,
    day: date,
    years: float,
    artifacts_dir: Path,
    output_dir: Path,
    max_activities: int | None,
    activity_ids: set[str],
    rebuild: bool,
    map_match_osm: bool,
    max_map_match_routes: int | None,
    osm_tile_cache_dir: Path,
    osm_tile_lat_step: float,
    osm_tile_lng_step: float,
    osm_tile_padding_m: float,
    start_anchor_name: str | None,
    start_anchor_lat: float | None,
    start_anchor_lng: float | None,
    start_radius_km: float,
    surface_preference: str,
    target_distance_km: float | None,
) -> dict[str, Any]:
    since = day - timedelta(days=round(365.25 * years))
    raw_dir = output_dir / "raw"
    cleaned_dir = output_dir / "cleaned"
    scored_dir = output_dir / "scored"
    for path in (raw_dir, cleaned_dir, scored_dir):
        path.mkdir(parents=True, exist_ok=True)

    activities, exclusions = outdoor_ride_activity_dirs(
        artifacts_dir,
        since=since,
        until=day,
        activity_ids=activity_ids,
    )
    if max_activities is not None:
        activities = activities[:max_activities]

    raw_written = 0
    cleaned_written = 0
    scored_written = 0
    scored_routes: list[dict[str, Any]] = []
    skipped = 0
    skip_reasons: defaultdict[str, int] = defaultdict(int)
    map_match_attempted = 0
    map_match_available = 0
    for activity_dir in activities:
        try:
            raw_route, raw_changed = ensure_raw_route(activity_dir, raw_dir=raw_dir, rebuild=rebuild)
            raw_written += int(raw_changed)
            if raw_route.get("available") is False:
                skipped += 1
                skip_reasons[str(raw_route.get("reason") or "raw_route_unavailable")] += 1
                continue
            map_match_this = map_match_osm and (
                max_map_match_routes is None or map_match_attempted < max_map_match_routes
            )
            map_match_attempted += int(map_match_this)
            cleaned_route, cleaned_changed = ensure_cleaned_route(
                raw_route,
                cleaned_dir=cleaned_dir,
                rebuild=rebuild,
                map_match_osm=map_match_this,
                osm_tile_cache_dir=osm_tile_cache_dir,
                osm_tile_lat_step=osm_tile_lat_step,
                osm_tile_lng_step=osm_tile_lng_step,
                osm_tile_padding_m=osm_tile_padding_m,
            )
            map_match_available += int(bool((cleaned_route.get("osm_match") or {}).get("available")))
            scored_route, scored_changed = ensure_scored_route(
                cleaned_route,
                scored_dir=scored_dir,
                rebuild=rebuild,
                start_anchor_name=start_anchor_name,
                start_anchor_lat=start_anchor_lat,
                start_anchor_lng=start_anchor_lng,
                start_radius_km=start_radius_km,
                surface_preference=surface_preference,
                target_distance_km=target_distance_km,
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            skipped += 1
            skip_reasons[skip_reason(exc)] += 1
            continue
        cleaned_written += int(cleaned_changed)
        scored_written += int(scored_changed)
        scored_routes.append(scored_route)

    groups = group_scored_routes(scored_routes)
    groups_path = output_dir / "groups.json"
    manifest_path = output_dir / "manifest.json"
    write_json(
        groups_path,
        {
            "schema": ROUTE_CATALOG_SCHEMA,
            "kind": "route_groups",
            "generated_at": now_iso(),
            "group_count": len(groups),
            "groups": groups,
        },
    )
    manifest = {
        "schema": ROUTE_CATALOG_SCHEMA,
        "generated_at": now_iso(),
        "source": "local_saved_intervals_activities",
        "filters": {
            "since": since.isoformat(),
            "until": day.isoformat(),
            "surface_preference": surface_preference,
            "target_distance_km": target_distance_km,
            "activity_ids": sorted(activity_ids),
            "osm_tile_cache_dir": str(osm_tile_cache_dir),
            "osm_tile": {
                "lat_step_deg": osm_tile_lat_step,
                "lng_step_deg": osm_tile_lng_step,
                "padding_m": osm_tile_padding_m,
            },
            "start_anchor": anchor_payload(start_anchor_name, start_anchor_lat, start_anchor_lng),
            "start_radius_km": start_radius_km,
        },
        "models": {
            "gps_cleaning": GPS_CLEANING_MODEL_VERSION,
            "osm_map_matching": OSM_MAP_MATCH_MODEL_VERSION,
            "scoring": "route_recommendations.score_route",
        },
        "outputs": {
            "raw_dir": str(raw_dir),
            "cleaned_dir": str(cleaned_dir),
            "scored_dir": str(scored_dir),
            "groups": str(groups_path),
        },
        "counts": {
            "activities_seen": len(activities),
            "activities_excluded": sum(exclusions.values()),
            "exclusions": dict(sorted(exclusions.items())),
            "activities_scored": len(scored_routes),
            "activities_skipped": skipped,
            "skip_reasons": dict(sorted(skip_reasons.items())),
            "raw_written": raw_written,
            "cleaned_written": cleaned_written,
            "scored_written": scored_written,
            "map_match_requested": map_match_osm,
            "map_match_attempted": map_match_attempted,
            "map_match_available": map_match_available,
            "groups": len(groups),
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def skip_reason(exc: Exception) -> str:
    message = str(exc)
    if message.startswith("missing GPS points"):
        return "missing_gps_points"
    if message.startswith("route vanished during cleaning"):
        return "route_vanished_during_cleaning"
    if isinstance(exc, json.JSONDecodeError):
        return "json_decode_error"
    if isinstance(exc, OSError):
        return type(exc).__name__
    return type(exc).__name__


def outdoor_ride_activity_dirs(
    artifacts_dir: Path,
    *,
    since: date,
    until: date,
    activity_ids: set[str],
) -> tuple[list[Path], dict[str, int]]:
    activities_dir = artifacts_dir / "activities"
    result: list[tuple[date, Path]] = []
    exclusions: defaultdict[str, int] = defaultdict(int)
    if not activities_dir.exists():
        return [], {}
    for activity_dir in sorted(activities_dir.iterdir()):
        metadata_path = activity_dir / "activity.json"
        streams_path = activity_dir / "streams.csv"
        if not metadata_path.exists() or not streams_path.exists():
            continue
        metadata = load_activity_metadata(activity_dir)
        metadata_id = str(metadata.get("id") or activity_dir.name)
        if activity_ids and metadata_id not in activity_ids:
            continue
        activity_date = activity_local_date(metadata)
        if activity_date is None or not (since <= activity_date <= until):
            continue
        if str(metadata.get("type") or "").lower() != "ride":
            exclusions["not_ride"] += 1
            continue
        if metadata.get("trainer") is True:
            exclusions["trainer_true"] += 1
            continue
        if not stream_has_gps_columns(streams_path):
            exclusions["ride_without_gps_columns"] += 1
            continue
        result.append((activity_date, activity_dir))
    return [path for _, path in sorted(result, key=lambda item: (item[0], item[1].name))], dict(exclusions)


def stream_has_gps_columns(streams_path: Path) -> bool:
    try:
        with streams_path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            fields = set(reader.fieldnames or [])
    except OSError:
        return False
    return {"lat", "lng", "distance"}.issubset(fields)


def ensure_raw_route(activity_dir: Path, *, raw_dir: Path, rebuild: bool) -> tuple[dict[str, Any], bool]:
    metadata_path = activity_dir / "activity.json"
    streams_path = activity_dir / "streams.csv"
    metadata = load_activity_metadata(activity_dir)
    activity_id = str(metadata.get("id") or activity_dir.name)
    output_path = raw_dir / f"{activity_id}.json"
    source = source_fingerprint(metadata_path, streams_path)
    if not rebuild:
        cached = load_cached_payload(output_path, schema=RAW_ROUTE_SCHEMA, source=source)
        if cached is not None:
            return cached, False

    points = read_stream_points(streams_path)
    if len(points) < 2:
        activity_date = activity_local_date(metadata)
        payload = {
            "schema": RAW_ROUTE_SCHEMA,
            "source": source,
            "generated_at": now_iso(),
            "available": False,
            "reason": "missing_gps_points",
            "activity": {
                "id": metadata.get("id"),
                "name": str(metadata.get("name") or activity_dir.name),
                "date": activity_date.isoformat() if activity_date else None,
                "start_date_local": metadata.get("start_date_local"),
                "url": rr.intervals_url(metadata.get("id")),
                "activity_dir": str(activity_dir),
            },
            "point_count": len(points),
        }
        write_json(output_path, payload)
        return payload, True
    activity_date = activity_local_date(metadata)
    payload = {
        "schema": RAW_ROUTE_SCHEMA,
        "source": source,
        "generated_at": now_iso(),
        "available": True,
        "activity": {
            "id": metadata.get("id"),
            "name": str(metadata.get("name") or activity_dir.name),
            "date": activity_date.isoformat() if activity_date else None,
            "start_date_local": metadata.get("start_date_local"),
            "url": rr.intervals_url(metadata.get("id")),
            "activity_dir": str(activity_dir),
            "distance_km": rounded_km(metadata.get("distance") or metadata.get("icu_distance")),
            "elevation_gain_m": rr.number(metadata.get("total_elevation_gain")),
            "gear": metadata.get("gear"),
            "surface": rr.surface_classification(metadata),
        },
        "points": points,
        "point_count": len(points),
    }
    write_json(output_path, payload)
    return payload, True


def ensure_cleaned_route(
    raw_route: dict[str, Any],
    *,
    cleaned_dir: Path,
    rebuild: bool,
    map_match_osm: bool,
    osm_tile_cache_dir: Path,
    osm_tile_lat_step: float,
    osm_tile_lng_step: float,
    osm_tile_padding_m: float,
) -> tuple[dict[str, Any], bool]:
    activity = raw_route["activity"]
    activity_id = str(activity.get("id"))
    output_path = cleaned_dir / f"{activity_id}.json"
    source = {
        "raw_schema": raw_route.get("schema"),
        "raw_source": raw_route.get("source"),
        "cleaning_model": GPS_CLEANING_MODEL_VERSION,
        "map_matching_model": OSM_MAP_MATCH_MODEL_VERSION if map_match_osm else None,
        "osm_tile": {
            "cache_dir": str(osm_tile_cache_dir) if map_match_osm else None,
            "lat_step_deg": osm_tile_lat_step if map_match_osm else None,
            "lng_step_deg": osm_tile_lng_step if map_match_osm else None,
            "padding_m": osm_tile_padding_m if map_match_osm else None,
        },
    }
    if not rebuild:
        cached = load_cached_payload(output_path, schema=CLEANED_ROUTE_SCHEMA, source=source)
        if cached is not None:
            return cached, False

    clean_points, cleaning = clean_gps_points(raw_route.get("points") or [])
    if len(clean_points) < 2:
        raise ValueError(f"route vanished during cleaning: {activity_id}")
    metrics = route_metrics(clean_points)
    osm_match = None
    if map_match_osm:
        osm_match = osm_way_sequence_for_points(
            clean_points,
            tile_cache_dir=osm_tile_cache_dir,
            lat_step_deg=osm_tile_lat_step,
            lng_step_deg=osm_tile_lng_step,
            padding_m=osm_tile_padding_m,
        )
    map_matched = bool((osm_match or {}).get("available"))
    limitation = (
        "OSM way-sequence map match from cleaned GPS. It is a lightweight nearest-way match, "
        "not full turn-by-turn routing; weak match coverage should be treated cautiously."
        if map_matched
        else (
            "First-pass GPS cleaning only. It removes obvious jumps/spikes and recalculates route distance, "
            "but it does not yet snap the route to OSM ways."
        )
    )
    payload = {
        "schema": CLEANED_ROUTE_SCHEMA,
        "source": source,
        "generated_at": now_iso(),
        "activity": activity,
        "cleaning": cleaning,
        "map_matched": map_matched,
        "limitation": limitation,
        "osm_match": osm_match,
        "fingerprints": route_fingerprints(clean_points, osm_match=osm_match),
        "metrics": metrics,
        "steady_endurance": steady_endurance_from_points(clean_points),
        "points": clean_points,
    }
    write_json(output_path, payload)
    return payload, True


def ensure_scored_route(
    cleaned_route: dict[str, Any],
    *,
    scored_dir: Path,
    rebuild: bool,
    start_anchor_name: str | None,
    start_anchor_lat: float | None,
    start_anchor_lng: float | None,
    start_radius_km: float,
    surface_preference: str,
    target_distance_km: float | None,
) -> tuple[dict[str, Any], bool]:
    activity = cleaned_route["activity"]
    activity_id = str(activity.get("id"))
    output_path = scored_dir / f"{activity_id}.json"
    source = {
        "cleaned_schema": cleaned_route.get("schema"),
        "cleaned_source": cleaned_route.get("source"),
        "cleaned_fingerprints": cleaned_route.get("fingerprints"),
        "scoring": {
            "surface_preference": surface_preference,
            "target_distance_km": target_distance_km,
            "start_anchor": anchor_payload(start_anchor_name, start_anchor_lat, start_anchor_lng),
            "start_radius_km": start_radius_km,
        },
    }
    if not rebuild:
        cached = load_cached_payload(output_path, schema=SCORED_ROUTE_SCHEMA, source=source)
        if cached is not None:
            return cached, False

    metrics = cleaned_route.get("metrics") or {}
    points = cleaned_route.get("points") or []
    start_distance = end_distance = None
    starts_ends_near_anchor = False
    if start_anchor_lat is not None and start_anchor_lng is not None and points:
        start_distance = rr.distance_km(points[0]["lat"], points[0]["lng"], start_anchor_lat, start_anchor_lng)
        end_distance = rr.distance_km(points[-1]["lat"], points[-1]["lng"], start_anchor_lat, start_anchor_lng)
        starts_ends_near_anchor = start_distance <= start_radius_km and end_distance <= start_radius_km
    route_for_score = {
        "distance_km": metrics.get("distance_km"),
        "starts_ends_near_start_anchor": starts_ends_near_anchor,
        "steady_endurance": cleaned_route.get("steady_endurance"),
        "surface": activity.get("surface"),
    }
    score = rr.score_route(
        route_for_score,
        target_distance_km=target_distance_km,
        prefer_terrain_steady_endurance=True,
        surface_preference=surface_preference,
    )
    payload = {
        "schema": SCORED_ROUTE_SCHEMA,
        "source": source,
        "generated_at": now_iso(),
        "activity": activity,
        "fingerprints": cleaned_route.get("fingerprints"),
        "route_group_key": (
            (cleaned_route.get("fingerprints") or {}).get("osm_family")
            or (cleaned_route.get("fingerprints") or {}).get("group")
        ),
        "score": score,
        "score_inputs": {
            "surface_preference": surface_preference,
            "target_distance_km": target_distance_km,
            "start_anchor_name": start_anchor_name,
            "start_distance_from_anchor_km": round(start_distance, 2) if start_distance is not None else None,
            "end_distance_from_anchor_km": round(end_distance, 2) if end_distance is not None else None,
            "starts_ends_near_start_anchor": starts_ends_near_anchor,
            "steady_endurance": cleaned_route.get("steady_endurance"),
            "surface": activity.get("surface"),
        },
        "metrics": metrics,
        "cleaning": cleaned_route.get("cleaning"),
        "map_matched": cleaned_route.get("map_matched"),
        "osm_match": compact_osm_match_for_scored(cleaned_route.get("osm_match")),
        "limitation": cleaned_route.get("limitation"),
        "cleaned_route_path": str(cleaned_dir_path(scored_dir) / f"{activity_id}.json"),
    }
    write_json(output_path, payload)
    return payload, True


def cleaned_dir_path(scored_dir: Path) -> Path:
    return scored_dir.parent / "cleaned"


def compact_osm_match_for_scored(osm_match: Any) -> dict[str, Any] | None:
    if not isinstance(osm_match, dict):
        return None
    return {
        "available": osm_match.get("available"),
        "source": osm_match.get("source"),
        "model": osm_match.get("model"),
        "fetch_strategy": osm_match.get("fetch_strategy"),
        "matched_sample_pct": osm_match.get("matched_sample_pct"),
        "matched_way_count": osm_match.get("matched_way_count"),
        "compact_way_count": osm_match.get("compact_way_count"),
        "reason": osm_match.get("reason"),
        "detail": osm_match.get("detail"),
    }


def group_scored_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_representatives: dict[str, dict[str, Any]] = {}
    for route in routes:
        key = matching_group_key(route, group_representatives)
        if key is None:
            key = str(route.get("route_group_key") or route.get("activity", {}).get("id"))
            group_representatives[key] = route
        grouped[key].append(route)
    groups = []
    for key, items in grouped.items():
        best = max(items, key=lambda item: (rr.number(item.get("score")) or -9999, str(item.get("activity", {}).get("date") or "")))
        display_info = preferred_group_display_info(items)
        preferred_name = display_info.get("display_name")
        groups.append(
            {
                "route_group_key": key,
                "display_name": preferred_name or str(best.get("activity", {}).get("name") or key),
                "display_name_source": display_info.get("display_name_source"),
                "display_name_reason": display_info.get("display_name_reason"),
                "reference_count": len(items),
                "best_activity_id": best.get("activity", {}).get("id"),
                "best_activity_date": best.get("activity", {}).get("date"),
                "best_score": best.get("score"),
                "distance_km": best.get("metrics", {}).get("distance_km"),
                "elevation_gain_m": best.get("metrics", {}).get("elevation_gain_m"),
                "steady_endurance": best.get("score_inputs", {}).get("steady_endurance"),
                "surface": best.get("score_inputs", {}).get("surface"),
                "map_matched": best.get("map_matched"),
                "osm_match": best.get("osm_match"),
                "limitation": best.get("limitation"),
                "references": [
                    {
                        "activity_id": item.get("activity", {}).get("id"),
                        "date": item.get("activity", {}).get("date"),
                        "name": item.get("activity", {}).get("name"),
                        "score": item.get("score"),
                    }
                    for item in sorted(items, key=lambda item: str(item.get("activity", {}).get("date") or ""))
                ],
            }
        )
    return sorted(groups, key=lambda item: (-(rr.number(item.get("best_score")) or -9999), item["route_group_key"]))


def matching_group_key(route: dict[str, Any], representatives: dict[str, dict[str, Any]]) -> str | None:
    for key, representative in representatives.items():
        if routes_are_similar(route, representative):
            return key
    return None


def routes_are_similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if osm_sequences_are_similar(a, b):
        return True
    a_metrics = a.get("metrics") or {}
    b_metrics = b.get("metrics") or {}
    a_distance = rr.number(a_metrics.get("distance_km"))
    b_distance = rr.number(b_metrics.get("distance_km"))
    if a_distance is None or b_distance is None:
        return False
    if abs(a_distance - b_distance) > max(2.0, min(a_distance, b_distance) * 0.08):
        return False
    a_samples = ((a.get("fingerprints") or {}).get("group_samples") or [])
    b_samples = ((b.get("fingerprints") or {}).get("group_samples") or [])
    if len(a_samples) != len(b_samples) or len(a_samples) < 10:
        return False
    forward = average_sample_distance_m(a_samples, b_samples)
    reverse = average_sample_distance_m(a_samples, list(reversed(b_samples)))
    return min(forward, reverse) <= 350.0


def osm_sequences_are_similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_sequence = ((a.get("fingerprints") or {}).get("osm_way_sequence") or [])
    b_sequence = ((b.get("fingerprints") or {}).get("osm_way_sequence") or [])
    if len(a_sequence) < 5 or len(b_sequence) < 5:
        return False
    forward = sequence_jaccard(a_sequence, b_sequence)
    reverse = sequence_jaccard(a_sequence, list(reversed(b_sequence)))
    return max(forward, reverse) >= 0.88


def sequence_jaccard(a_sequence: list[int], b_sequence: list[int]) -> float:
    a = set(a_sequence)
    b = set(b_sequence)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def average_sample_distance_m(a_samples: list[dict[str, float]], b_samples: list[dict[str, float]]) -> float:
    distances = [
        rr.distance_km(float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])) * 1000
        for a, b in zip(a_samples, b_samples)
    ]
    return sum(distances) / len(distances) if distances else float("inf")


def preferred_group_display_info(items: list[dict[str, Any]]) -> dict[str, str | None]:
    routes = [
        {
            "name": str(item.get("activity", {}).get("name") or ""),
            "distance_km": item.get("metrics", {}).get("distance_km"),
        }
        for item in items
    ]
    return rr.preferred_route_display_info_for_group(routes)


def read_stream_points(streams_path: Path) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    with streams_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            lat = value(row, "lat")
            lng = value(row, "lng")
            distance_m = value(row, "distance")
            if lat is None or lng is None or distance_m is None:
                continue
            point: dict[str, Any] = {
                "lat": round(float(lat), 7),
                "lng": round(float(lng), 7),
                "source_distance_m": round(float(distance_m), 1),
            }
            altitude = value(row, "altitude")
            if altitude is not None:
                point["altitude_m"] = round(float(altitude), 1)
            time_s = value(row, "time")
            if time_s is not None:
                point["time_s"] = round(float(time_s), 1)
            points.append(point)
    return points


def clean_gps_points(raw_points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    points = remove_invalid_or_duplicate_points(raw_points)
    before_jump = len(points)
    points = remove_impossible_jumps(points)
    jump_removed = before_jump - len(points)
    spike_removed = 0
    for _ in range(3):
        before = len(points)
        points = remove_spikes(points)
        spike_removed += before - len(points)
        if before == len(points):
            break
    points = with_recalculated_distance(points)
    return points, {
        "model": GPS_CLEANING_MODEL_VERSION,
        "raw_point_count": len(raw_points),
        "cleaned_point_count": len(points),
        "removed_point_count": len(raw_points) - len(points),
        "removed_duplicate_or_invalid_count": len(raw_points) - before_jump,
        "removed_impossible_jump_count": jump_removed,
        "removed_spike_count": spike_removed,
        "method": (
            "Remove invalid/duplicate GPS points, impossible high-speed jumps, and short isolated "
            "detour spikes; then recalculate cumulative route distance from cleaned coordinates."
        ),
    }


def remove_invalid_or_duplicate_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    previous: tuple[float, float] | None = None
    for point in points:
        lat = rr.number(point.get("lat"))
        lng = rr.number(point.get("lng"))
        if lat is None or lng is None or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            continue
        current = (round(lat, 7), round(lng, 7))
        if previous == current:
            continue
        previous = current
        cleaned.append(dict(point))
    return cleaned


def remove_impossible_jumps(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(points) < 3:
        return points
    cleaned = [points[0]]
    for point in points[1:]:
        previous = cleaned[-1]
        gap_m = haversine_m(previous, point)
        time_gap = time_gap_s(previous, point)
        if gap_m > 150 and time_gap is not None and time_gap > 0 and gap_m / time_gap > 22:
            continue
        cleaned.append(point)
    return cleaned


def remove_spikes(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(points) < 3:
        return points
    keep = [points[0]]
    for previous, point, following in zip(points, points[1:], points[2:]):
        prev_next_m = haversine_m(previous, following)
        detour_m = haversine_m(previous, point) + haversine_m(point, following)
        lateral_m = point_to_segment_distance_m(point, previous, following)
        if 5 <= prev_next_m <= 250 and lateral_m > 18 and detour_m > max(prev_next_m * 2.5, prev_next_m + 40):
            continue
        keep.append(point)
    keep.append(points[-1])
    return keep


def with_recalculated_distance(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    distance_m = 0.0
    previous = None
    for point in points:
        if previous is not None:
            distance_m += haversine_m(previous, point)
        updated = dict(point)
        updated["distance_m"] = round(distance_m, 1)
        result.append(updated)
        previous = point
    return result


def route_metrics(points: list[dict[str, Any]]) -> dict[str, Any]:
    distance_m = points[-1]["distance_m"] if points else 0.0
    altitudes = [rr.number(point.get("altitude_m")) for point in points]
    altitudes = [altitude for altitude in altitudes if altitude is not None]
    elevation_gain = 0.0
    previous_altitude = None
    for point in points:
        altitude = rr.number(point.get("altitude_m"))
        if altitude is not None and previous_altitude is not None:
            elevation_gain += max(0.0, altitude - previous_altitude)
        if altitude is not None:
            previous_altitude = altitude
    lats = [float(point["lat"]) for point in points]
    lngs = [float(point["lng"]) for point in points]
    return {
        "point_count": len(points),
        "distance_km": round(distance_m / 1000, 1),
        "elevation_gain_m": round(elevation_gain, 0) if altitudes else None,
        "bbox": {
            "min_lat": min(lats),
            "min_lng": min(lngs),
            "max_lat": max(lats),
            "max_lng": max(lngs),
        },
    }


def steady_endurance_from_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        (rr.number(point.get("distance_m")), rr.number(point.get("altitude_m")))
        for point in points
    ]
    usable = [(distance, altitude) for distance, altitude in usable if distance is not None and altitude is not None]
    if len(usable) < 100:
        return {"available": False, "reason": "too_few_altitude_points"}
    total_m = usable[-1][0] - usable[0][0]
    if total_m <= 0:
        return {"available": False, "reason": "invalid_distance"}
    gt4_m = gt5_m = longest_gt4_m = current_gt4_m = 0.0
    window_end = 0
    for index in range(len(usable) - 1):
        distance_m, altitude_m = usable[index]
        if window_end < index + 1:
            window_end = index + 1
        while window_end < len(usable) and usable[window_end][0] < distance_m + 200:
            window_end += 1
        step_m = max(0.0, usable[index + 1][0] - distance_m)
        gt4_here = False
        if window_end < len(usable):
            window_distance_m = usable[window_end][0] - distance_m
            if window_distance_m >= 150:
                grade = (usable[window_end][1] - altitude_m) / window_distance_m
                if grade < -0.04:
                    gt4_m += step_m
                    gt4_here = True
                if grade < -0.05:
                    gt5_m += step_m
        if gt4_here:
            current_gt4_m += step_m
            longest_gt4_m = max(longest_gt4_m, current_gt4_m)
        else:
            current_gt4_m = 0.0
    gt4_pct = 100 * gt4_m / total_m
    gt5_pct = 100 * gt5_m / total_m
    downhill_disruption_pct = 0.3 * gt4_pct + 0.7 * gt5_pct
    return {
        "available": True,
        "method": (
            "cleaned GPS route; 200m rolling downhill; "
            "downhill_disruption_pct=0.3*gt4_pct+0.7*gt5_pct; "
            "lower is better for steady endurance"
        ),
        "downhill_disruption_pct": round(downhill_disruption_pct, 3),
        "descent_gt4_km": round(gt4_m / 1000, 2),
        "descent_gt4_pct": round(gt4_pct, 2),
        "descent_gt5_km": round(gt5_m / 1000, 2),
        "descent_gt5_pct": round(gt5_pct, 2),
        "longest_gt4_km": round(longest_gt4_m / 1000, 2),
    }


def osm_way_sequence_for_points(
    points: list[dict[str, Any]],
    *,
    tile_cache_dir: Path,
    lat_step_deg: float,
    lng_step_deg: float,
    padding_m: float,
) -> dict[str, Any]:
    rr_points = [
        {
            "lat": float(point["lat"]),
            "lng": float(point["lng"]),
            "distance": float(point["distance_m"]),
        }
        for point in points
        if point.get("lat") is not None and point.get("lng") is not None and point.get("distance_m") is not None
    ]
    if len(rr_points) < 2:
        return {"available": False, "reason": "too_few_points"}
    try:
        osm_fetch = fetch_osm_highways_for_route_tiles(
            rr_points,
            tile_cache_dir=tile_cache_dir,
            lat_step_deg=lat_step_deg,
            lng_step_deg=lng_step_deg,
            padding_m=padding_m,
        )
    except Exception as exc:
        return {
            "available": False,
            "source": "osm_overpass",
            "reason": type(exc).__name__,
            "detail": str(exc)[:200],
        }
    elements = osm_fetch.get("elements") or []
    nodes = {
        int(element["id"]): {
            "lat": float(element["lat"]),
            "lng": float(element["lon"]),
            "tags": element.get("tags") or {},
        }
        for element in elements
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    ways = [
        element
        for element in elements
        if element.get("type") == "way" and isinstance(element.get("nodes"), list)
    ]
    reference_lat_rad = rr.projection_reference_lat(rr_points)
    way_geometries = rr.highway_way_geometries(ways, nodes, reference_lat_rad=reference_lat_rad)
    match_samples = rr.sample_points_by_distance(rr_points, step_m=50.0)
    matches: list[dict[str, Any]] = []
    unmatched_count = 0
    for point in match_samples:
        match = rr.nearest_highway_at_point(
            point,
            way_geometries,
            reference_lat_rad=reference_lat_rad,
            max_distance_m=35.0,
        )
        if not match:
            unmatched_count += 1
            continue
        matches.append(
            {
                "route_distance_km": round(point["distance"] / 1000, 3),
                "way_id": int(match["way_id"]),
                "name": match.get("name"),
                "highway": match.get("highway"),
                "rank": match.get("rank"),
                "distance_to_way_m": match.get("distance_to_way_m"),
            }
        )
    compact = compact_way_matches(matches)
    if not compact:
        return {
            "available": False,
            "source": "osm_overpass",
            "reason": "no_way_matches",
            "fetch_strategy": osm_fetch.get("strategy"),
            "osm_way_count": len(ways),
            "match_sample_count": len(match_samples),
        }
    matched_pct = 100 * len(matches) / max(1, len(match_samples))
    return {
        "available": True,
        "source": "osm_overpass",
        "model": OSM_MAP_MATCH_MODEL_VERSION,
        "method": (
            "Resolve cleaned GPS route to fixed lat/lng OSM corridor tiles, fetch/cache missing tile bboxes, "
            "filter to relevant non-service cycling roads, sample every 50m, match each sample to nearest way "
            "within 35m, then compact consecutive way_ids."
        ),
        "fetch_strategy": osm_fetch.get("strategy"),
        "tile_count": osm_fetch.get("tile_count"),
        "tile_cache_hit_count": osm_fetch.get("tile_cache_hit_count"),
        "tile_cache_miss_count": osm_fetch.get("tile_cache_miss_count"),
        "tile_cache_dir": str(tile_cache_dir),
        "tile_lat_step_deg": lat_step_deg,
        "tile_lng_step_deg": lng_step_deg,
        "tile_padding_m": padding_m,
        "osm_way_count": len(ways),
        "matched_way_count": len({item["way_id"] for item in matches}),
        "match_sample_count": len(match_samples),
        "matched_sample_count": len(matches),
        "unmatched_sample_count": unmatched_count,
        "matched_sample_pct": round(matched_pct, 1),
        "compact_way_count": len(compact),
        "compact_way_sequence": compact,
    }


def fetch_osm_highways_for_route_tiles(
    points: list[dict[str, float]],
    *,
    tile_cache_dir: Path,
    lat_step_deg: float,
    lng_step_deg: float,
    padding_m: float,
) -> dict[str, Any]:
    sampled_points = rr.sample_points_by_distance(points, step_m=150.0)
    tile_ids = route_tile_ids(
        sampled_points,
        lat_step_deg=lat_step_deg,
        lng_step_deg=lng_step_deg,
    )
    all_elements: dict[tuple[str, int], dict[str, Any]] = {}
    hit_count = 0
    miss_count = 0
    for tile_id in tile_ids:
        payload, cache_hit = ensure_osm_tile(
            tile_id,
            tile_cache_dir=tile_cache_dir,
            lat_step_deg=lat_step_deg,
            lng_step_deg=lng_step_deg,
            padding_m=padding_m,
        )
        hit_count += int(cache_hit)
        miss_count += int(not cache_hit)
        for element in payload.get("elements") or []:
            if isinstance(element, dict) and "type" in element and "id" in element:
                key = (str(element["type"]), int(element["id"]))
                all_elements[key] = rr.merge_osm_element(all_elements.get(key), element)
    return {
        "strategy": "route_tiles",
        "tile_count": len(tile_ids),
        "tile_cache_hit_count": hit_count,
        "tile_cache_miss_count": miss_count,
        "elements": list(all_elements.values()),
    }


def route_tile_ids(
    points: list[dict[str, float]],
    *,
    lat_step_deg: float,
    lng_step_deg: float,
) -> list[str]:
    tile_ids = {
        tile_id_for_point(
            float(point["lat"]),
            float(point["lng"]),
            lat_step_deg=lat_step_deg,
            lng_step_deg=lng_step_deg,
        )
        for point in points
    }
    return sorted(tile_ids)


def tile_id_for_point(lat: float, lng: float, *, lat_step_deg: float, lng_step_deg: float) -> str:
    lat_i = math.floor(lat / lat_step_deg)
    lng_i = math.floor(lng / lng_step_deg)
    return f"lat{lat_i}_lng{lng_i}"


def ensure_osm_tile(
    tile_id: str,
    *,
    tile_cache_dir: Path,
    lat_step_deg: float,
    lng_step_deg: float,
    padding_m: float,
) -> tuple[dict[str, Any], bool]:
    path = osm_tile_path(tile_cache_dir, tile_id)
    expected_source = {
        "tile_id": tile_id,
        "lat_step_deg": lat_step_deg,
        "lng_step_deg": lng_step_deg,
        "padding_m": padding_m,
    }
    cached = load_cached_payload(path, schema=OSM_TILE_SCHEMA, source=expected_source)
    if cached is not None:
        return cached, True
    bbox = tile_bbox(tile_id, lat_step_deg=lat_step_deg, lng_step_deg=lng_step_deg)
    fetch_bbox = padded_bbox(bbox, padding_m=padding_m)
    elements = fetch_osm_highways_bbox(fetch_bbox)
    payload = {
        "schema": OSM_TILE_SCHEMA,
        "source": expected_source,
        "generated_at": now_iso(),
        "tile_id": tile_id,
        "bbox": bbox_payload(bbox),
        "fetch_bbox": bbox_payload(fetch_bbox),
        "element_count": len(elements),
        "elements": elements,
    }
    write_json(path, payload)
    return payload, False


def osm_tile_path(tile_cache_dir: Path, tile_id: str) -> Path:
    return tile_cache_dir / f"{tile_id}.json"


def tile_bbox(tile_id: str, *, lat_step_deg: float, lng_step_deg: float) -> tuple[float, float, float, float]:
    try:
        lat_part, lng_part = tile_id.split("_")
        lat_i = int(lat_part.removeprefix("lat"))
        lng_i = int(lng_part.removeprefix("lng"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid tile id: {tile_id}") from exc
    south = lat_i * lat_step_deg
    north = south + lat_step_deg
    west = lng_i * lng_step_deg
    east = west + lng_step_deg
    return (south, west, north, east)


def padded_bbox(bbox: tuple[float, float, float, float], *, padding_m: float) -> tuple[float, float, float, float]:
    south, west, north, east = bbox
    mid_lat = (south + north) / 2
    lat_pad = padding_m / 111_320
    lng_pad = padding_m / (111_320 * max(0.2, math.cos(math.radians(mid_lat))))
    return (south - lat_pad, west - lng_pad, north + lat_pad, east + lng_pad)


def bbox_payload(bbox: tuple[float, float, float, float]) -> dict[str, float]:
    south, west, north, east = bbox
    return {
        "south": round(south, 7),
        "west": round(west, 7),
        "north": round(north, 7),
        "east": round(east, 7),
    }


def fetch_osm_highways_bbox(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    south, west, north, east = bbox
    query = "\n".join(
        [
            "[out:json][timeout:30];",
            "(",
            f'  way["highway"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});',
            f'  node["highway"~"^(give_way|stop|traffic_signals|crossing)$"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});',
            ");",
            "out body;",
            ">;",
            "out skel qt;",
        ]
    )
    data = rr.fetch_overpass_json(urllib.parse.urlencode({"data": query}).encode("utf-8"))
    return rr.dedupe_osm_elements(data.get("elements", []))


def compact_way_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for match in matches:
        if compact and compact[-1]["way_id"] == match["way_id"]:
            compact[-1]["end_route_km"] = match["route_distance_km"]
            compact[-1]["sample_count"] += 1
            continue
        compact.append(
            {
                "way_id": match["way_id"],
                "name": match.get("name"),
                "highway": match.get("highway"),
                "rank": match.get("rank"),
                "start_route_km": match["route_distance_km"],
                "end_route_km": match["route_distance_km"],
                "sample_count": 1,
            }
        )
    return compact


def route_fingerprints(points: list[dict[str, Any]], *, osm_match: dict[str, Any] | None = None) -> dict[str, Any]:
    precise_samples = sampled_shape(points, samples=101, decimals=5)
    group_samples = sampled_shape(points, samples=31, decimals=4)
    precise_payload = sampled_shape_payload(precise_samples, points, distance_bucket_km=1)
    group_payload = sampled_shape_payload(group_samples, points, distance_bucket_km=3)
    result = {
        "precise": "clean-gps-v1:" + hashlib.sha256(precise_payload.encode("utf-8")).hexdigest()[:24],
        "group": "clean-group-v1:" + hashlib.sha256(group_payload.encode("utf-8")).hexdigest()[:20],
        "precise_method": "101 cleaned-route samples rounded to 5 decimals plus 1 km distance bucket",
        "group_method": "31 cleaned-route samples rounded to 4 decimals plus 3 km distance bucket; final grouping also uses sample-distance similarity",
        "group_samples": group_samples,
    }
    if osm_match and osm_match.get("available"):
        way_sequence = [
            int(item["way_id"])
            for item in osm_match.get("compact_way_sequence") or []
            if item.get("way_id") is not None
        ]
        sequence_payload = "|".join(str(way_id) for way_id in way_sequence)
        canonical_sequence = min(sequence_payload, "|".join(str(way_id) for way_id in reversed(way_sequence)))
        result.update(
            {
                "osm_way_sequence": way_sequence,
                "osm_sequence": "osm-seq-v1:" + hashlib.sha256(sequence_payload.encode("utf-8")).hexdigest()[:24],
                "osm_family": "osm-family-v1:" + hashlib.sha256(canonical_sequence.encode("utf-8")).hexdigest()[:24],
                "osm_method": "ordered compact OSM way_id sequence from nearest-way samples on cleaned GPS",
            }
        )
    return result


def sampled_shape(points: list[dict[str, Any]], *, samples: int, decimals: int) -> list[dict[str, float]]:
    total_m = rr.number(points[-1].get("distance_m")) or 0.0
    sampled: list[dict[str, float]] = []
    index = 0
    for step in range(samples):
        target = total_m * step / max(1, samples - 1)
        while index + 1 < len(points) and (rr.number(points[index + 1].get("distance_m")) or 0.0) < target:
            index += 1
        sampled.append(
            {
                "lat": round(float(points[index]["lat"]), decimals),
                "lng": round(float(points[index]["lng"]), decimals),
            }
        )
    return sampled


def sampled_shape_payload(samples: list[dict[str, float]], points: list[dict[str, Any]], *, distance_bucket_km: int) -> str:
    total_m = rr.number(points[-1].get("distance_m")) or 0.0
    distance_bucket = round((total_m / 1000) / distance_bucket_km) * distance_bucket_km
    shape = "|".join(f"{point['lat']},{point['lng']}" for point in samples)
    return f"{distance_bucket}km|{shape}"


def point_to_segment_distance_m(point: dict[str, Any], start: dict[str, Any], end: dict[str, Any]) -> float:
    reference_lat_rad = math.radians((float(start["lat"]) + float(end["lat"]) + float(point["lat"])) / 3)
    px, py = rr.project_lat_lng(float(point["lat"]), float(point["lng"]), reference_lat_rad=reference_lat_rad)
    sx, sy = rr.project_lat_lng(float(start["lat"]), float(start["lng"]), reference_lat_rad=reference_lat_rad)
    ex, ey = rr.project_lat_lng(float(end["lat"]), float(end["lng"]), reference_lat_rad=reference_lat_rad)
    return rr.point_to_segment_distance((px, py), (sx, sy), (ex, ey))


def haversine_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    return rr.distance_km(float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])) * 1000


def time_gap_s(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    a_time = rr.number(a.get("time_s"))
    b_time = rr.number(b.get("time_s"))
    if a_time is None or b_time is None:
        return None
    return b_time - a_time


def source_fingerprint(*paths: Path) -> dict[str, Any]:
    return {
        "files": [
            {
                "path": str(path),
                "mtime_ns": path.stat().st_mtime_ns,
                "size": path.stat().st_size,
            }
            for path in paths
        ]
    }


def load_cached_payload(path: Path, *, schema: str, source: dict[str, Any]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema") != schema or payload.get("source") != source:
        return None
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def activity_local_date(metadata: dict[str, Any]) -> date | None:
    start_local = str(metadata.get("start_date_local") or "")
    if not start_local:
        return None
    try:
        return datetime.fromisoformat(start_local).date()
    except ValueError:
        return None


def anchor_payload(name: str | None, lat: float | None, lng: float | None) -> dict[str, Any] | None:
    if lat is None or lng is None:
        return None
    return {"name": name, "lat": lat, "lng": lng}


def rounded_km(raw_m: Any) -> float | None:
    meters = rr.number(raw_m)
    return round(meters / 1000, 1) if meters is not None else None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
