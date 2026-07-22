#!/usr/bin/env python3
"""Recommend outdoor routes from saved ride history."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from analysis import ARTIFACTS_DIR, load_activity_metadata, value


DEFAULT_START_RADIUS_KM = 0.25
GENERIC_ROUTE_NAMES = {
    "afternoon ride",
    "evening ride",
    "morning ride",
    "oslo landeveissykling",
    "ride",
}
WORKOUT_ROUTE_NAME_MARKERS = {
    "cycling workout",
    "xert cycling workout",
    "workout",
}
KNOWN_WORKOUT_ROUTE_NAME_SUFFIXES = {
    "kosciuszko",
    "kosciuszko -1",
    "mount deborah",
}
DEFAULT_ROUTE_INDEX = Path("outputs/route-index.json")
DEFAULT_ROUTE_ANALYSIS_CACHE = Path("outputs/route-analysis-cache.json")
DEFAULT_ROUTE_DATA_QUALITY = Path("config/route-data-quality.json")
ROUTE_INDEX_SCHEMA = "training-ai-route-index-v13"
ROUTE_ANALYSIS_CACHE_SCHEMA = "training-ai-route-analysis-cache-v1"
OSM_CONFLICT_MODEL_VERSION = "osm-conflicts-v3-clean-nonservice-right-hand"
OSM_ROUTE_BBOX_MAX_AREA_DEG2 = 0.12
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
TRAFFIC_CONTROL_HIGHWAYS = {"give_way", "stop", "traffic_signals", "crossing"}
HIGHWAY_PRIORITY_RANK = {
    "motorway": 1,
    "motorway_link": 1,
    "trunk": 2,
    "trunk_link": 2,
    "primary": 3,
    "primary_link": 3,
    "secondary": 4,
    "secondary_link": 4,
    "tertiary": 5,
    "tertiary_link": 5,
    "unclassified": 6,
    "residential": 7,
    "living_street": 8,
    "service": 9,
    "road": 10,
    "cycleway": 11,
    "track": 12,
    "path": 13,
    "footway": 14,
    "steps": 15,
}
PRIORITY_YIELD_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "road",
}
GEAR_SURFACE_BY_ID = {
    "b10577453": {
        "surface": "road",
        "label": "landevei",
        "confidence": "gear_id",
        "bike_type": "road",
        "bike": "Trek Madone 9",
    },
    "b11246236": {
        "surface": "unknown",
        "label": "ukjent underlag",
        "confidence": "bike_type_only",
        "bike_type": "gravel",
        "bike": "Trek Checkpoint",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank saved outdoor rides as concrete route candidates.",
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--target-minutes", type=float)
    parser.add_argument("--target-load", type=float)
    parser.add_argument("--xert-loads-json", type=Path)
    parser.add_argument("--target-distance-km", type=float)
    parser.add_argument("--query", action="append", help="Route/name fragment to prefer. Can be repeated.")
    parser.add_argument("--max-results", type=int, default=8)
    parser.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR))
    parser.add_argument(
        "--start-anchor-displayname",
        dest="start_anchor_displayname",
        default=None,
        help="Optional display label for the required start/end anchor.",
    )
    parser.add_argument("--start-anchor-lat", type=float)
    parser.add_argument("--start-anchor-lng", type=float)
    parser.add_argument(
        "--start-radius-km",
        type=float,
        default=DEFAULT_START_RADIUS_KM,
        help="Only include routes whose first and last GPS point are within this distance of the start anchor.",
    )
    parser.add_argument(
        "--allow-away",
        "--no-start-filter",
        dest="allow_away",
        action="store_true",
        help="Include routes that do not start/end near the start anchor. With no anchor lat/lng, disable start filtering entirely.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--route-index", type=Path, default=DEFAULT_ROUTE_INDEX)
    parser.add_argument("--route-analysis-cache", type=Path, default=DEFAULT_ROUTE_ANALYSIS_CACHE)
    parser.add_argument(
        "--route-data-quality",
        type=Path,
        default=DEFAULT_ROUTE_DATA_QUALITY,
        help="Manual data-quality registry for excluding route references with unusable source streams.",
    )
    parser.add_argument(
        "--no-prefer-terrain-steady-endurance",
        dest="no_prefer_terrain_steady_endurance",
        action="store_true",
        help="Do not boost/penalize route ranking by downhill terrain risk for steady endurance suitability.",
    )
    parser.add_argument(
        "--surface-preference",
        choices=("road", "gravel", "any", "unknown-ok"),
        default="road",
        help="Preferred route surface for the planned bike. Use road for landevei, gravel for grus, any to ignore surface, or unknown-ok to avoid penalizing unknown gear.",
    )
    parser.add_argument(
        "--junction-source",
        choices=("none", "osm"),
        default="none",
        help="Add map-backed junction counts for returned routes. 'osm' queries Overpass/OpenStreetMap.",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Re-scan saved activities and refresh the route index cache.",
    )
    parser.add_argument(
        "--rebuild-route-analysis-cache",
        action="store_true",
        help="Recompute OSM route analysis instead of reusing cached conflict points.",
    )
    args = parser.parse_args()
    if not args.allow_away and (args.start_anchor_lat is None or args.start_anchor_lng is None):
        parser.error(
            "pass --start-anchor-lat and --start-anchor-lng from caller context "
            "(memory/preferences/user request), or use --no-start-filter/--allow-away"
        )

    result = recommend_routes(
        day=parse_date(args.date),
        years=args.years,
        target_minutes=args.target_minutes,
        target_load=args.target_load,
        xert_loads_json=args.xert_loads_json,
        target_distance_km=args.target_distance_km,
        queries=args.query or [],
        max_results=args.max_results,
        artifacts_dir=Path(args.artifacts_dir),
        start_anchor_name=args.start_anchor_displayname or ("selected start anchor" if args.start_anchor_lat is not None and args.start_anchor_lng is not None else None),
        start_anchor_lat=args.start_anchor_lat,
        start_anchor_lng=args.start_anchor_lng,
        start_radius_km=args.start_radius_km,
        allow_away=args.allow_away,
        prefer_terrain_steady_endurance=not args.no_prefer_terrain_steady_endurance,
        surface_preference=args.surface_preference,
        junction_source=args.junction_source,
        route_index=args.route_index,
        route_data_quality=args.route_data_quality,
        rebuild_index=args.rebuild_index,
        route_analysis_cache=args.route_analysis_cache,
        rebuild_route_analysis_cache=args.rebuild_route_analysis_cache,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def recommend_routes(
    *,
    day: date,
    years: float,
    target_minutes: float | None,
    target_load: float | None,
    xert_loads_json: Path | None,
    target_distance_km: float | None,
    queries: list[str],
    max_results: int,
    artifacts_dir: Path,
    start_anchor_name: str | None,
    start_anchor_lat: float | None,
    start_anchor_lng: float | None,
    start_radius_km: float,
    allow_away: bool,
    prefer_terrain_steady_endurance: bool = True,
    surface_preference: str = "road",
    junction_source: str = "none",
    route_index: Path | None = DEFAULT_ROUTE_INDEX,
    route_data_quality: Path | None = DEFAULT_ROUTE_DATA_QUALITY,
    rebuild_index: bool = False,
    route_analysis_cache: Path | None = DEFAULT_ROUTE_ANALYSIS_CACHE,
    rebuild_route_analysis_cache: bool = False,
) -> dict[str, Any]:
    since = day - timedelta(days=round(365.25 * years))
    xert_loads = xert_load_index(load_json_if_exists(xert_loads_json))
    data_quality_registry = load_route_data_quality(route_data_quality)
    matched_routes = [
        route
        for route in saved_outdoor_routes(
            artifacts_dir,
            xert_loads=xert_loads,
            route_index=route_index,
            rebuild_index=rebuild_index,
            start_anchor_name=start_anchor_name,
            start_anchor_lat=start_anchor_lat,
            start_anchor_lng=start_anchor_lng,
            start_radius_km=start_radius_km,
        )
        if since <= route["date"] <= day
        and (allow_away or route["starts_ends_near_start_anchor"])
        and query_matches(route, queries)
        and route_matches_target_distance(route, target_distance_km=target_distance_km)
    ]
    excluded_for_quality = [
        route
        for route in matched_routes
        if route_blocking_quality_issue(route, data_quality_registry) is not None
    ]
    candidates = [
        route
        for route in matched_routes
        if route_blocking_quality_issue(route, data_quality_registry) is None
    ]
    route_counts = Counter(route_group_key(route) for route in candidates)
    display_names = preferred_route_display_info_by_group(candidates, registry=data_quality_registry)
    scored = [
        {
            **route,
            **display_names.get(
                route_group_key(route),
                {
                    "display_name": route["name"],
                    "display_name_source": "source_activity_name",
                    "display_name_reason": None,
                },
            ),
            "route_reference_count": route_counts[route_group_key(route)],
            "route_reference_count_used_for_ranking": False,
            "surface_preference": surface_preference,
            "route_reference_note": route_reference_note(route),
            "score": score_route(
                route,
                target_distance_km=target_distance_km,
                prefer_terrain_steady_endurance=prefer_terrain_steady_endurance,
                surface_preference=surface_preference,
            ),
        }
        for route in candidates
    ]
    ranked = sorted(
        scored,
        key=lambda route: (-route["score"], route_group_key(route), route["id"]),
    )
    deduped_ranked = dedupe_ranked_routes(ranked)
    selected = [dict(route) for route in deduped_ranked[:max_results]]
    if junction_source == "osm":
        add_osm_junction_counts(
            selected,
            route_analysis_cache=route_analysis_cache,
            rebuild_route_analysis_cache=rebuild_route_analysis_cache,
        )
    return {
        "date": day.isoformat(),
        "lookback_years": years,
        "source": "local_saved_intervals_activities",
        "filters": {
            "since": since.isoformat(),
            "start_anchor": {
                "name": start_anchor_name,
                "lat": start_anchor_lat,
                "lng": start_anchor_lng,
            }
            if start_anchor_lat is not None and start_anchor_lng is not None
            else None,
            "start_filter_enabled": not allow_away,
            "start_radius_km": None if allow_away else start_radius_km,
            "prefer_terrain_steady_endurance": prefer_terrain_steady_endurance,
            "surface_preference": surface_preference,
            "junction_source": junction_source,
            "recency_used_for_route_ranking": False,
            "query": queries,
            "target_minutes": target_minutes,
            "target_load": target_load,
            "target_fields_used_for_route_ranking": target_distance_km is not None,
            "target_load_meaning": "Accepted for compatibility only; Xert XSS target is not used for route ranking.",
            "target_distance_km": target_distance_km,
            "target_distance_meaning": (
                "Used as a broad eligibility filter plus a small closeness bonus. "
                "Within the eligible distance band, route quality can beat distance closeness."
                if target_distance_km is not None
                else "Not supplied; route ranking uses anchor, terrain flow, and surface preference."
            ),
            "target_distance_filter": target_distance_filter(target_distance_km),
            "route_index": str(route_index) if route_index else None,
            "route_data_quality": str(route_data_quality) if route_data_quality else None,
            "route_data_quality_schema": data_quality_registry.get("schema"),
            "route_data_quality_excluded_count": len(excluded_for_quality),
            "route_data_quality_excluded_activity_ids": [
                str(route.get("id")) for route in excluded_for_quality
            ],
            "rebuild_index": rebuild_index,
            "route_analysis_cache": str(route_analysis_cache) if route_analysis_cache else None,
            "route_analysis_cache_schema": ROUTE_ANALYSIS_CACHE_SCHEMA,
            "osm_conflict_model_version": OSM_CONFLICT_MODEL_VERSION,
            "rebuild_route_analysis_cache": rebuild_route_analysis_cache,
        },
        "matched_count": len(ranked),
        "unique_route_count": len(deduped_ranked),
        "recommendations": [format_route(route) for route in selected],
    }


def dedupe_ranked_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for route in routes:
        key = route_group_key(route)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(route)
    return deduped


def saved_outdoor_routes(
    artifacts_dir: Path,
    *,
    xert_loads: list[dict[str, Any]],
    route_index: Path | None = DEFAULT_ROUTE_INDEX,
    rebuild_index: bool = False,
    start_anchor_name: str | None = None,
    start_anchor_lat: float | None = None,
    start_anchor_lng: float | None = None,
    start_radius_km: float = DEFAULT_START_RADIUS_KM,
) -> list[dict[str, Any]]:
    has_start_anchor = start_anchor_lat is not None and start_anchor_lng is not None
    start_anchor_name = start_anchor_name or ("selected start anchor" if has_start_anchor else None)
    if route_index and not rebuild_index:
        cached = load_route_index(route_index, artifacts_dir=artifacts_dir)
        if cached is not None:
            return [
                with_xert_load(
                    normalize_cached_route(
                        route,
                        start_anchor_name=start_anchor_name,
                        start_anchor_lat=start_anchor_lat,
                        start_anchor_lng=start_anchor_lng,
                        start_radius_km=start_radius_km,
                    ),
                    xert_loads,
                )
                for route in cached
            ]

    routes = []
    activities_dir = artifacts_dir / "activities"
    if not activities_dir.exists():
        return routes
    for activity_dir in sorted(activities_dir.iterdir()):
        metadata_path = activity_dir / "activity.json"
        streams_path = activity_dir / "streams.csv"
        if not metadata_path.exists() or not streams_path.exists():
            continue
        metadata = load_activity_metadata(activity_dir)
        if str(metadata.get("type") or "").lower() != "ride" or metadata.get("trainer") is True:
            continue
        start_local = str(metadata.get("start_date_local") or "")
        if not start_local:
            continue
        try:
            activity_date = datetime.fromisoformat(start_local).date()
        except ValueError:
            continue
        gps = gps_summary(streams_path)
        if not gps["has_gps"]:
            continue
        if has_start_anchor:
            start_distance = distance_km(
                gps["start_lat"],
                gps["start_lng"],
                start_anchor_lat,
                start_anchor_lng,
            )
            end_distance = distance_km(
                gps["end_lat"],
                gps["end_lng"],
                start_anchor_lat,
                start_anchor_lng,
            )
            starts_ends_near_anchor = start_distance <= start_radius_km and end_distance <= start_radius_km
        else:
            start_distance = None
            end_distance = None
            starts_ends_near_anchor = False
        steady_endurance = terrain_steady_endurance_metrics(streams_path)
        moving_seconds = number(metadata.get("moving_time")) or number(metadata.get("elapsed_time"))
        elapsed_seconds = number(metadata.get("elapsed_time"))
        distance_m = number(metadata.get("distance")) or number(metadata.get("icu_distance"))
        surface = surface_classification(metadata)
        route = {
                "activity_dir": str(activity_dir),
                "id": metadata.get("id"),
                "url": intervals_url(metadata.get("id")),
                "date": activity_date,
                "name": str(metadata.get("name") or activity_dir.name),
                "route_key": route_key(str(metadata.get("name") or activity_dir.name)),
                "route_shape_key": gps.get("route_shape_key"),
                "moving_minutes": minutes(moving_seconds),
                "elapsed_minutes": minutes(elapsed_seconds),
                "distance_km": round(distance_m / 1000, 1) if distance_m is not None else None,
                "elevation_gain_m": number(metadata.get("total_elevation_gain")),
                "training_load": metadata.get("icu_training_load"),
                "intensity": metadata.get("icu_intensity"),
                "average_watts": metadata.get("icu_average_watts") or metadata.get("average_watts"),
                "weighted_average_watts": metadata.get("icu_weighted_avg_watts")
                or metadata.get("weighted_average_watts"),
                "average_heartrate": metadata.get("average_heartrate"),
                "max_heartrate": metadata.get("max_heartrate"),
                "gear": metadata.get("gear"),
                "surface": surface,
                "start_anchor_name": start_anchor_name,
                "start_distance_from_anchor_km": round(start_distance, 2) if start_distance is not None else None,
                "end_distance_from_anchor_km": round(end_distance, 2) if end_distance is not None else None,
                "starts_ends_near_start_anchor": starts_ends_near_anchor,
                "steady_endurance": steady_endurance,
                "gps": gps,
            }
        routes.append(with_xert_load(route, xert_loads))
    if route_index:
        write_route_index(route_index, artifacts_dir=artifacts_dir, routes=routes)
    return routes


def load_route_index(route_index: Path, *, artifacts_dir: Path) -> list[dict[str, Any]] | None:
    if not route_index.exists():
        return None
    try:
        payload = json.loads(route_index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != ROUTE_INDEX_SCHEMA:
        return None
    activities_dir = artifacts_dir / "activities"
    newest_source_mtime = latest_activity_source_mtime(activities_dir)
    if newest_source_mtime and route_index.stat().st_mtime < newest_source_mtime:
        return None
    routes = payload.get("routes")
    if not isinstance(routes, list):
        return None
    return [route for route in routes if isinstance(route, dict)]


def load_json_if_exists(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_route_data_quality(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"schema": "training-ai-route-data-quality-v1", "activities": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "training-ai-route-data-quality-v1", "activities": {}}
    activities = payload.get("activities") if isinstance(payload, dict) else None
    if not isinstance(activities, dict):
        activities = {}
    return {
        "schema": payload.get("schema", "training-ai-route-data-quality-v1")
        if isinstance(payload, dict)
        else "training-ai-route-data-quality-v1",
        "activities": {
            str(activity_id): issue
            for activity_id, issue in activities.items()
            if isinstance(issue, dict)
        },
    }


def route_blocking_quality_issue(
    route: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any] | None:
    activity_id = str(route.get("id") or "")
    if not activity_id:
        return None
    issue = (registry.get("activities") or {}).get(activity_id)
    if not isinstance(issue, dict):
        return None
    if str(issue.get("route_recommendation_use") or "").lower() == "exclude":
        return issue
    return None


def load_route_analysis_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"schema": ROUTE_ANALYSIS_CACHE_SCHEMA, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": ROUTE_ANALYSIS_CACHE_SCHEMA, "entries": {}}
    if not isinstance(payload, dict) or payload.get("schema") != ROUTE_ANALYSIS_CACHE_SCHEMA:
        return {"schema": ROUTE_ANALYSIS_CACHE_SCHEMA, "entries": {}}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    return {
        "schema": ROUTE_ANALYSIS_CACHE_SCHEMA,
        "generated_at": payload.get("generated_at"),
        "entries": entries,
    }


def write_route_analysis_cache(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "schema": ROUTE_ANALYSIS_CACHE_SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model_version": OSM_CONFLICT_MODEL_VERSION,
        "entries": payload.get("entries") or {},
    }
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def route_analysis_cache_key(route: dict[str, Any]) -> str | None:
    shape_key = route_analysis_shape_fingerprint(route) or route.get("route_shape_key")
    if shape_key:
        return f"{OSM_CONFLICT_MODEL_VERSION}|shape:{shape_key}"
    route_id = route.get("id")
    if route_id:
        return f"{OSM_CONFLICT_MODEL_VERSION}|activity:{route_id}"
    return None


def route_analysis_shape_fingerprint(route: dict[str, Any]) -> str | None:
    activity_dir = route.get("activity_dir")
    if not activity_dir:
        return None
    points = route_gps_points(Path(str(activity_dir)) / "streams.csv")
    if len(points) < 20:
        return None
    start_distance = points[0]["distance"]
    total_m = points[-1]["distance"] - start_distance
    if total_m <= 0:
        return None
    sampled: list[str] = []
    index = 0
    for step in range(101):
        target = start_distance + total_m * step / 100
        while index + 1 < len(points) and points[index + 1]["distance"] < target:
            index += 1
        sampled.append(f"{points[index]['lat']:.5f},{points[index]['lng']:.5f}")
    payload = f"{round(total_m)}m|" + "|".join(sampled)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"gps-v1:{digest}"


def clone_jsonable(value_: Any) -> Any:
    return json.loads(json.dumps(value_, ensure_ascii=False))


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


def with_xert_load(route: dict[str, Any], xert_loads: list[dict[str, Any]]) -> dict[str, Any]:
    if route.get("xss") is not None:
        route["load_source"] = "xert_xss"
        return route
    xss = matched_xert_xss(route, xert_loads)
    route = dict(route)
    route["xss"] = xss
    route["load_source"] = "xert_xss" if xss is not None else "missing_xert_xss"
    return route


def matched_xert_xss(route: dict[str, Any], xert_loads: list[dict[str, Any]]) -> float | None:
    route_date = route.get("date")
    if not isinstance(route_date, date):
        return None
    name = route_key(str(route.get("name") or ""))
    distance_km = number(route.get("distance_km"))
    candidates: list[tuple[float, float]] = []
    for row in xert_loads:
        start = parse_optional_datetime(row.get("start_local"))
        if start is None or start.date() != route_date:
            continue
        row_name = route_key(str(row.get("name") or ""))
        name_penalty = 0 if row_name == name else 20
        row_distance = number(row.get("distance_km"))
        distance_penalty = (
            abs(row_distance - distance_km)
            if row_distance is not None and distance_km is not None
            else 2
        )
        xss = xert_total_xss(row)
        if xss is not None:
            candidates.append((name_penalty + distance_penalty, xss))
    if not candidates:
        return None
    score, xss = min(candidates, key=lambda item: item[0])
    return xss if score <= 25 else None


def surface_classification(metadata: dict[str, Any]) -> dict[str, Any]:
    gear = metadata.get("gear")
    gear_id = str((gear or {}).get("id") or "") if isinstance(gear, dict) else ""
    gear_name = str((gear or {}).get("name") or "") if isinstance(gear, dict) else ""
    surface_text = " ".join(
        str(metadata.get(key) or "") for key in ("name", "description", "comments")
    ).casefold()
    if re.search(r"\b(grus|gravel)\b", surface_text):
        return {
            "surface": "gravel",
            "label": "grus",
            "confidence": "activity_text",
            "bike_type": (GEAR_SURFACE_BY_ID.get(gear_id) or {}).get("bike_type"),
            "gear_id": gear_id or None,
            "gear_name": gear_name or None,
            "bike": gear_name or (GEAR_SURFACE_BY_ID.get(gear_id) or {}).get("bike"),
            "warning": None,
        }
    if re.search(r"\b(asfalt|landevei)\b", surface_text):
        return {
            "surface": "road",
            "label": "landevei",
            "confidence": "activity_text",
            "bike_type": (GEAR_SURFACE_BY_ID.get(gear_id) or {}).get("bike_type"),
            "gear_id": gear_id or None,
            "gear_name": gear_name or None,
            "bike": gear_name or (GEAR_SURFACE_BY_ID.get(gear_id) or {}).get("bike"),
            "warning": None,
        }
    if gear_id in GEAR_SURFACE_BY_ID:
        known = GEAR_SURFACE_BY_ID[gear_id]
        return {
            **known,
            "gear_id": gear_id,
            "gear_name": gear_name or known["bike"],
            "warning": (
                "Trek Checkpoint identifies the bike type, not the ridden surface; "
                "confirm road versus gravel from the activity or map."
                if known["surface"] == "unknown"
                else None
            ),
        }
    if gear_id or gear_name:
        gear_description = ", ".join(
            part
            for part in (
                f"id={gear_id}" if gear_id else None,
                f"name={gear_name}" if gear_name else None,
            )
            if part
        )
        return {
            "surface": "unknown",
            "label": "ukjent underlag",
            "confidence": "unknown_gear",
            "gear_id": gear_id or None,
            "gear_name": gear_name or None,
            "bike": gear_name or None,
            "warning": (
                "Ukjent sykkel/gear på referanseaktiviteten "
                f"({gear_description}); bekreft om dette er landevei eller grus."
            ),
        }
    return {
        "surface": "unknown",
        "label": "ukjent underlag",
        "confidence": "missing_gear",
        "gear_id": None,
        "gear_name": None,
        "bike": None,
        "warning": "Referanseaktiviteten mangler gear/sykkel; kan ikke bekrefte landevei vs grus fra metadata.",
    }


def parse_optional_datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def write_route_index(
    route_index: Path,
    *,
    artifacts_dir: Path,
    routes: list[dict[str, Any]],
) -> None:
    route_index.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": ROUTE_INDEX_SCHEMA,
        "source": "local_saved_intervals_activities",
        "artifacts_dir": str(artifacts_dir),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "start_anchor_note": "Start anchor is caller supplied at normalization/filter time.",
        "routes": [serialize_route(route) for route in routes],
    }
    route_index.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def latest_activity_source_mtime(activities_dir: Path) -> float | None:
    if not activities_dir.exists():
        return None
    newest = None
    for path in activities_dir.glob("*/activity.json"):
        newest = max(newest or 0.0, path.stat().st_mtime)
    for path in activities_dir.glob("*/streams.csv"):
        newest = max(newest or 0.0, path.stat().st_mtime)
    return newest


def serialize_route(route: dict[str, Any]) -> dict[str, Any]:
    result = dict(route)
    if isinstance(result.get("date"), date):
        result["date"] = result["date"].isoformat()
    return result


def normalize_cached_route(
    route: dict[str, Any],
    *,
    start_anchor_name: str | None,
    start_anchor_lat: float | None,
    start_anchor_lng: float | None,
    start_radius_km: float,
) -> dict[str, Any]:
    result = dict(route)
    if isinstance(result.get("date"), str):
        result["date"] = parse_date(result["date"])
    gps = result.get("gps") or {}
    if start_anchor_lat is None or start_anchor_lng is None:
        result["start_anchor_name"] = None
        result["start_distance_from_anchor_km"] = None
        result["end_distance_from_anchor_km"] = None
        result["starts_ends_near_start_anchor"] = False
        return result
    start_anchor_name = start_anchor_name or "selected start anchor"
    if gps.get("has_gps"):
        start_distance = distance_km(
            gps["start_lat"],
            gps["start_lng"],
            start_anchor_lat,
            start_anchor_lng,
        )
        end_distance = distance_km(
            gps["end_lat"],
            gps["end_lng"],
            start_anchor_lat,
            start_anchor_lng,
        )
        near_anchor = start_distance <= start_radius_km and end_distance <= start_radius_km
        result["start_anchor_name"] = start_anchor_name
        result["start_distance_from_anchor_km"] = round(start_distance, 2)
        result["end_distance_from_anchor_km"] = round(end_distance, 2)
        result["starts_ends_near_start_anchor"] = near_anchor
    return result


def terrain_steady_endurance_metrics(streams_path: Path) -> dict[str, Any]:
    points: list[tuple[float, float]] = []
    with streams_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            distance_m = value(row, "distance")
            altitude_m = value(row, "altitude")
            if distance_m is None or altitude_m is None:
                continue
            points.append((float(distance_m), float(altitude_m)))
    if len(points) < 100:
        return {"available": False, "reason": "too_few_altitude_points"}
    total_m = points[-1][0] - points[0][0]
    if total_m <= 0:
        return {"available": False, "reason": "invalid_distance"}
    altitudes = [altitude for _, altitude in points]
    if total_m > 50_000 and max(altitudes) - min(altitudes) < 30:
        return {"available": False, "reason": "suspect_flat_altitude"}

    gt4_m = 0.0
    gt5_m = 0.0
    longest_gt4_m = 0.0
    current_gt4_m = 0.0
    window_end = 0
    for index in range(len(points) - 1):
        distance_m, altitude_m = points[index]
        if window_end < index + 1:
            window_end = index + 1
        while window_end < len(points) and points[window_end][0] < distance_m + 200:
            window_end += 1
        step_m = max(0.0, points[index + 1][0] - distance_m)
        gt4_here = False
        if window_end < len(points):
            window_distance_m = points[window_end][0] - distance_m
            if window_distance_m >= 150:
                grade = (points[window_end][1] - altitude_m) / window_distance_m
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
            "200m rolling downhill; "
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


def add_osm_junction_counts(
    routes: list[dict[str, Any]],
    *,
    route_analysis_cache: Path | None = DEFAULT_ROUTE_ANALYSIS_CACHE,
    rebuild_route_analysis_cache: bool = False,
) -> None:
    cache_payload = load_route_analysis_cache(route_analysis_cache)
    cache_entries = cache_payload.setdefault("entries", {})
    cache_changed = False
    for route in routes:
        cache_key = route_analysis_cache_key(route)
        if cache_key and not rebuild_route_analysis_cache:
            cached = cache_entries.get(cache_key)
            if isinstance(cached, dict) and cached.get("model_version") == OSM_CONFLICT_MODEL_VERSION:
                map_junctions = clone_jsonable(cached.get("map_junctions"))
                if isinstance(map_junctions, dict):
                    map_junctions["cache"] = {
                        "hit": True,
                        "cache_key": cache_key,
                        "generated_at": cached.get("generated_at"),
                        "path": str(route_analysis_cache) if route_analysis_cache else None,
                    }
                    route["map_junctions"] = map_junctions
                    route["map_yield_situations"] = (map_junctions or {}).get("yield_situations")
                    continue
        try:
            map_junctions = osm_junction_count_for_route(route)
            if isinstance(map_junctions, dict):
                map_junctions["cache"] = {
                    "hit": False,
                    "cache_key": cache_key,
                    "path": str(route_analysis_cache) if route_analysis_cache else None,
                }
            route["map_junctions"] = map_junctions
            route["map_yield_situations"] = (map_junctions or {}).get("yield_situations")
            if cache_key and isinstance(map_junctions, dict) and map_junctions.get("available"):
                cache_entries[cache_key] = {
                    "model_version": OSM_CONFLICT_MODEL_VERSION,
                    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "route_shape_key": route.get("route_shape_key"),
                    "reference_activity_id": route.get("id"),
                    "reference_activity_name": route.get("name"),
                    "distance_km": route.get("distance_km"),
                    "map_junctions": clone_jsonable(map_junctions),
                }
                cache_changed = True
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            route["map_junctions"] = {
                "available": False,
                "source": "osm_overpass",
                "reason": type(exc).__name__,
                "detail": str(exc)[:200],
                "cache": {
                    "hit": False,
                    "cache_key": cache_key,
                    "path": str(route_analysis_cache) if route_analysis_cache else None,
                    "stored": False,
                },
            }
            route["map_yield_situations"] = route["map_junctions"]
    if cache_changed:
        write_route_analysis_cache(route_analysis_cache, cache_payload)


def osm_junction_count_for_route(route: dict[str, Any]) -> dict[str, Any]:
    activity_dir = Path(str(route.get("activity_dir") or ""))
    streams_path = activity_dir / "streams.csv"
    points = route_gps_points(streams_path)
    if len(points) < 2:
        return {"available": False, "source": "osm_overpass", "reason": "missing_route_gps"}
    total_m = points[-1]["distance"] - points[0]["distance"]
    if total_m <= 0:
        return {"available": False, "source": "osm_overpass", "reason": "invalid_route_distance"}

    sampled = sample_points_by_distance(points, step_m=400.0)
    osm_fetch = fetch_osm_highways_for_route(points, sampled_points=sampled, radius_m=60.0)
    elements = osm_fetch["elements"]
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
    node_way_ids: dict[int, set[int]] = {}
    node_priority_way_ids: dict[int, set[int]] = {}
    node_highway_types: dict[int, set[str]] = {}
    node_priority_highway_types: dict[int, set[str]] = {}
    way_summaries: dict[int, dict[str, Any]] = {}
    for way in ways:
        way_id = int(way["id"])
        tags = way.get("tags") or {}
        highway = str(tags.get("highway") or "unknown")
        way_summary = {
            "way_id": way_id,
            "name": tags.get("name"),
            "highway": highway,
            "service": tags.get("service"),
            "rank": highway_priority_rank(highway),
        }
        way_summaries[way_id] = way_summary
        for node_id_raw in way.get("nodes") or []:
            node_id = int(node_id_raw)
            node_way_ids.setdefault(node_id, set()).add(way_id)
            node_highway_types.setdefault(node_id, set()).add(highway)
            if is_priority_yield_way(way_summary):
                node_priority_way_ids.setdefault(node_id, set()).add(way_id)
                node_priority_highway_types.setdefault(node_id, set()).add(highway)

    reference_lat_rad = projection_reference_lat(points)
    route_xy = project_points(points, reference_lat_rad=reference_lat_rad)
    way_geometries = highway_way_geometries(ways, nodes, reference_lat_rad=reference_lat_rad)
    matched_route_way_ids = matched_route_way_ids_for_route(
        points,
        way_geometries,
        reference_lat_rad=reference_lat_rad,
    )
    junction_candidates: list[dict[str, Any]] = []
    for node_id, way_ids in node_way_ids.items():
        priority_way_ids = node_priority_way_ids.get(node_id, set())
        if len(priority_way_ids) < 2 or node_id not in nodes:
            continue
        if not (priority_way_ids & matched_route_way_ids):
            continue
        node = nodes[node_id]
        distance_to_route_m = point_to_polyline_distance_m(
            node["lat"],
            node["lng"],
            route_xy,
            reference_lat_rad=reference_lat_rad,
        )
        if distance_to_route_m > 35.0:
            continue
        junction_candidates.append(
            {
                "node_id": node_id,
                "lat": node["lat"],
                "lng": node["lng"],
                "way_count": len(priority_way_ids),
                "highway_types": sorted(node_priority_highway_types.get(node_id, set())),
                "connected_ways": [
                    way_summaries[way_id]
                    for way_id in sorted(priority_way_ids)
                    if way_id in way_summaries
                ],
                "distance_to_route_m": round(distance_to_route_m, 1),
            }
        )

    merged = merge_nearby_junctions(junction_candidates, within_m=45.0)
    explicit_yield_situations = yield_situations_near_route(
        nodes,
        node_way_ids,
        matched_route_way_ids,
        route_xy,
        reference_lat_rad=reference_lat_rad,
    )
    inferred_priority_yield_situations = inferred_priority_yield_situations_near_route(
        junction_candidates,
        points,
        route_xy,
        way_geometries,
        reference_lat_rad=reference_lat_rad,
    )
    yield_situations = {
        **explicit_yield_situations,
        "inferred_priority_yield_count": inferred_priority_yield_situations["count"],
        "inferred_priority_yield_per_10km": round(
            inferred_priority_yield_situations["count"] / (total_m / 10_000),
            1,
        ),
        "inferred_priority_yield_situations": inferred_priority_yield_situations,
    }
    count = len(merged)
    return {
        "available": True,
        "source": "osm_overpass",
        "count": count,
        "per_10km": round(count / (total_m / 10_000), 1),
        "method": (
            "OSM highway topology near route: Overpass way(around:60m) along sampled route; "
            "clean/map-match the GPS track to relevant non-service highway ways first, then count "
            "nodes shared by >=2 cleaned ways within 35m of the GPS track, merged within 45m"
        ),
        "limitation": (
            "Map-backed estimate, not turn-by-turn priority. It can count harmless side-road junctions "
            "and misses unmapped/private crossings."
        ),
        "sampled_route_points": len(sampled),
        "osm_fetch_strategy": osm_fetch.get("strategy"),
        "osm_fetch_bbox_area_deg2": osm_fetch.get("bbox_area_deg2"),
        "osm_way_count": len(ways),
        "matched_route_way_count": len(matched_route_way_ids),
        "raw_candidate_count": len(junction_candidates),
        "junctions_preview": merged[:20],
        "yield_situations": yield_situations,
    }


def yield_situations_near_route(
    nodes: dict[int, dict[str, Any]],
    node_way_ids: dict[int, set[int]],
    matched_route_way_ids: set[int],
    route_xy: list[tuple[float, float]],
    *,
    reference_lat_rad: float,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for node_id, node in nodes.items():
        tags = node.get("tags") or {}
        highway = str(tags.get("highway") or "")
        if highway not in TRAFFIC_CONTROL_HIGHWAYS:
            continue
        if not (node_way_ids.get(node_id, set()) & matched_route_way_ids):
            continue
        distance_to_route_m = point_to_polyline_distance_m(
            float(node["lat"]),
            float(node["lng"]),
            route_xy,
            reference_lat_rad=reference_lat_rad,
        )
        if distance_to_route_m > 35.0:
            continue
        candidates.append(
            {
                "node_id": node_id,
                "lat": node["lat"],
                "lng": node["lng"],
                "highway": highway,
                "distance_to_route_m": round(distance_to_route_m, 1),
            }
        )
    merged = merge_nearby_junctions(candidates, within_m=25.0)
    by_type = Counter(str(item.get("highway") or "unknown") for item in merged)
    explicit_yield_or_stop_count = by_type["give_way"] + by_type["stop"]
    return {
        "available": True,
        "source": "osm_overpass",
        "method": (
            "Explicit OSM traffic-control nodes that lie on OSM ways matched to the GPS route, "
            "then checked within 35m of the GPS track and merged within 25m. Vikeplikt count is "
            "highway=give_way + highway=stop."
        ),
        "limitation": (
            "Counts mapped signs/control nodes only. It does not infer legal right-of-way at ordinary "
            "unmapped junctions and does not know whether a traffic signal was green."
        ),
        "explicit_yield_or_stop_count": explicit_yield_or_stop_count,
        "give_way_count": by_type["give_way"],
        "stop_count": by_type["stop"],
        "traffic_signals_count": by_type["traffic_signals"],
        "crossing_count": by_type["crossing"],
        "raw_candidate_count": len(candidates),
        "events_preview": merged[:20],
    }


def inferred_priority_yield_situations_near_route(
    junction_candidates: list[dict[str, Any]],
    points: list[dict[str, float]],
    route_xy: list[tuple[float, float]],
    way_geometries: list[dict[str, Any]],
    *,
    reference_lat_rad: float,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for junction in junction_candidates:
        connected_ways = [
            way
            for way in (junction.get("connected_ways") or [])
            if is_priority_yield_way(way)
        ]
        if not connected_ways:
            continue
        locations = point_to_polyline_locations(
            float(junction["lat"]),
            float(junction["lng"]),
            points,
            route_xy,
            reference_lat_rad=reference_lat_rad,
            max_distance_m=35.0,
        )
        if not locations:
            continue
        for location in locations:
            along_m = location["distance_m"]
            before = route_point_at_distance(points, along_m - 30.0)
            after = route_point_at_distance(points, along_m + 30.0)
            before_match = nearest_highway_at_point(before, way_geometries, reference_lat_rad=reference_lat_rad)
            after_match = nearest_highway_at_point(after, way_geometries, reference_lat_rad=reference_lat_rad)
            route_matches = [match for match in (before_match, after_match) if match is not None]
            if not route_matches:
                continue
            route_way_ids = {int(match["way_id"]) for match in route_matches if match.get("way_id") is not None}
            if before_match is None or before_match.get("rank") is None:
                continue
            before_rank = int(before_match["rank"])
            after_rank = int(after_match["rank"]) if after_match and after_match.get("rank") is not None else before_rank
            junction_xy = project_lat_lng(
                float(junction["lat"]),
                float(junction["lng"]),
                reference_lat_rad=reference_lat_rad,
            )
            route_bearings = route_bearings_through_junction(
                before,
                after,
                float(junction["lat"]),
                float(junction["lng"]),
                reference_lat_rad=reference_lat_rad,
            )
            route_turn_deg = angle_diff_deg(route_bearings[0], route_bearings[1])
            class_upgrade_on_route = before_rank > after_rank
            same_or_higher_connected_way_count = sum(
                1 for way in connected_ways if int(way.get("rank") or 99) <= before_rank
            )
            off_route_ways = [
                way
                for way in connected_ways
                if int(way.get("way_id")) not in route_way_ids
            ]
            priority_side_ways: list[dict[str, Any]] = []
            same_class_right_side_ways: list[dict[str, Any]] = []
            for way in off_route_ways:
                way_rank = int(way.get("rank") or 99)
                if not is_distinct_side_branch(
                    way,
                    way_geometries,
                    junction_xy,
                    route_bearings,
                ):
                    continue
                if way_rank < before_rank:
                    priority_side_ways.append(way)
                    continue
                if way_rank == before_rank and branch_is_on_right(
                    way,
                    way_geometries,
                    junction_xy,
                    incoming_bearing=route_bearings[0],
                ):
                    same_class_right_side_ways.append(way)
            if not class_upgrade_on_route and not priority_side_ways and not same_class_right_side_ways:
                continue
            reason_parts = []
            if class_upgrade_on_route:
                reason_parts.append("route enters a higher-priority OSM highway class")
            if priority_side_ways:
                reason_parts.append("a geometrically distinct side branch has a higher OSM highway class than the incoming route")
            if same_class_right_side_ways:
                reason_parts.append("a geometrically distinct same-class side branch is on the rider's right")
            reason = "; ".join(reason_parts)
            side_ways = priority_side_ways + same_class_right_side_ways
            candidates.append(
                {
                    "node_id": junction.get("node_id"),
                    "lat": junction.get("lat"),
                    "lng": junction.get("lng"),
                    "route_distance_km": round((along_m - points[0]["distance"]) / 1000, 2),
                    "distance_to_route_m": round(float(location["distance_to_route_m"]), 1),
                    "connected_highway_types": sorted(
                        {str(way.get("highway")) for way in connected_ways}
                    ),
                    "highest_priority_highway": highway_type_with_best_rank(
                        [str(way.get("highway")) for way in connected_ways]
                    ),
                    "same_or_higher_priority_side_ways": [
                        compact_highway_match_with_bearing(
                            way,
                            way_geometries,
                            junction_xy,
                            incoming_bearing=route_bearings[0],
                        )
                        for way in side_ways
                    ],
                    "route_turn_deg": round(route_turn_deg, 1),
                    "same_or_higher_connected_way_count": same_or_higher_connected_way_count,
                    "route_before": compact_highway_match(before_match),
                    "route_after": compact_highway_match(after_match),
                    "reason": reason,
                }
            )
    merged = merge_nearby_route_events(candidates, within_m=80.0, within_route_km=0.15)
    return {
        "available": True,
        "source": "osm_overpass",
        "count": len(merged),
        "method": (
            "Infer likely priority/yield situations from OSM highway class changes near the GPS track: "
            "count when the route enters a higher-priority road class, when a geometrically distinct "
            "side branch has a higher road class than the incoming route, or when a geometrically "
            "distinct same-class side branch is on the rider's right by the route direction."
        ),
        "limitation": (
            "Heuristic only. It does not read Norwegian right-of-way law, signs not mapped in OSM, "
            "lane geometry, or whether the rider is on carriageway versus an adjacent cycle/footway."
        ),
        "raw_candidate_count": len(candidates),
        "events_preview": merged[:20],
    }


def route_gps_points(streams_path: Path) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    if not streams_path.exists():
        return points
    with streams_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            lat = value(row, "lat")
            lng = value(row, "lng")
            distance_m = value(row, "distance")
            if lat is None or lng is None or distance_m is None:
                continue
            points.append({"lat": float(lat), "lng": float(lng), "distance": float(distance_m)})
    return points


def sample_points_by_distance(points: list[dict[str, float]], *, step_m: float) -> list[dict[str, float]]:
    if not points:
        return []
    sampled = [points[0]]
    next_distance = points[0]["distance"] + step_m
    for point in points[1:]:
        if point["distance"] >= next_distance:
            sampled.append(point)
            next_distance = point["distance"] + step_m
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def fetch_osm_highways_for_route(
    points: list[dict[str, float]],
    *,
    sampled_points: list[dict[str, float]],
    radius_m: float,
) -> dict[str, Any]:
    south = min(point["lat"] for point in points)
    north = max(point["lat"] for point in points)
    west = min(point["lng"] for point in points)
    east = max(point["lng"] for point in points)
    lat_pad = radius_m / 111_320
    lng_pad = radius_m / (111_320 * max(0.2, math.cos(math.radians((south + north) / 2))))
    padded = (south - lat_pad, west - lng_pad, north + lat_pad, east + lng_pad)
    bbox_area = (padded[2] - padded[0]) * (padded[3] - padded[1])
    if bbox_area <= OSM_ROUTE_BBOX_MAX_AREA_DEG2:
        try:
            return {
                "strategy": "bbox",
                "bbox_area_deg2": round(bbox_area, 5),
                "elements": fetch_osm_highways_bbox(padded),
            }
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            elements = fetch_osm_highways_around_points(sampled_points, radius_m=radius_m)
            return {
                "strategy": "around_points_after_bbox_error",
                "bbox_area_deg2": round(bbox_area, 5),
                "elements": elements,
            }
    return {
        "strategy": "around_points_large_bbox",
        "bbox_area_deg2": round(bbox_area, 5),
        "elements": fetch_osm_highways_around_points(sampled_points, radius_m=radius_m),
    }


def fetch_osm_highways_bbox(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    south, west, north, east = bbox
    query = "\n".join(
        [
            "[out:json][timeout:45];",
            "(",
            f'  way["highway"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});',
            f'  node["highway"~"^(give_way|stop|traffic_signals|crossing)$"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});',
            ");",
            "out body;",
            ">;",
            "out skel qt;",
        ]
    )
    data = fetch_overpass_json(urllib.parse.urlencode({"data": query}).encode("utf-8"))
    return dedupe_osm_elements(data.get("elements", []))


def fetch_osm_highways_around_points(points: list[dict[str, float]], *, radius_m: float) -> list[dict[str, Any]]:
    all_elements: dict[tuple[str, int], dict[str, Any]] = {}
    chunk_size = 20
    for start in range(0, len(points), chunk_size):
        chunk = points[start : start + chunk_size]
        query_lines = ["[out:json][timeout:30];", "("]
        for point in chunk:
            query_lines.append(
                f'  way(around:{radius_m:.0f},{point["lat"]:.7f},{point["lng"]:.7f})["highway"];'
            )
            query_lines.append(
                f'  node(around:{radius_m:.0f},{point["lat"]:.7f},{point["lng"]:.7f})["highway"~"^(give_way|stop|traffic_signals|crossing)$"];'
            )
        query_lines.extend([");", "out body;", ">;", "out skel qt;"])
        payload = urllib.parse.urlencode({"data": "\n".join(query_lines)}).encode("utf-8")
        data = fetch_overpass_json(payload)
        for element in data.get("elements", []):
            if isinstance(element, dict) and "type" in element and "id" in element:
                key = (str(element["type"]), int(element["id"]))
                all_elements[key] = merge_osm_element(all_elements.get(key), element)
    return list(all_elements.values())


def dedupe_osm_elements(elements: Any) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for element in elements or []:
        if not isinstance(element, dict) or "type" not in element or "id" not in element:
            continue
        key = (str(element["type"]), int(element["id"]))
        merged[key] = merge_osm_element(merged.get(key), element)
    return list(merged.values())


def merge_osm_element(existing: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return new
    if existing.get("tags") and not new.get("tags"):
        return existing
    if new.get("tags") and not existing.get("tags"):
        return new
    return new


def fetch_overpass_json(payload: bytes) -> dict[str, Any]:
    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"User-Agent": "training-ai-route-recommendations/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("no Overpass endpoints configured")


def projection_reference_lat(points: list[dict[str, float]]) -> float:
    if not points:
        return 0.0
    return math.radians(sum(point["lat"] for point in points) / len(points))


def project_points(points: list[dict[str, float]], *, reference_lat_rad: float) -> list[tuple[float, float]]:
    if not points:
        return []
    return [
        project_lat_lng(point["lat"], point["lng"], reference_lat_rad=reference_lat_rad)
        for point in points
    ]


def project_lat_lng(lat: float, lng: float, *, reference_lat_rad: float) -> tuple[float, float]:
    return (
        math.radians(lng) * math.cos(reference_lat_rad) * 6_371_000,
        math.radians(lat) * 6_371_000,
    )


def highway_priority_rank(highway: str) -> int | None:
    return HIGHWAY_PRIORITY_RANK.get(highway)


def is_priority_yield_way(way: dict[str, Any]) -> bool:
    highway = str(way.get("highway") or "")
    if highway not in PRIORITY_YIELD_HIGHWAYS:
        return False
    if highway == "service":
        return False
    return way.get("rank") is not None


def highway_type_with_best_rank(highways: list[str]) -> str | None:
    ranked = [
        (rank, highway)
        for highway in highways
        if (rank := highway_priority_rank(str(highway))) is not None
    ]
    if not ranked:
        return None
    return min(ranked)[1]


def highway_way_geometries(
    ways: list[dict[str, Any]],
    nodes: dict[int, dict[str, Any]],
    *,
    reference_lat_rad: float,
) -> list[dict[str, Any]]:
    geometries: list[dict[str, Any]] = []
    for way in ways:
        tags = way.get("tags") or {}
        highway = str(tags.get("highway") or "")
        rank = highway_priority_rank(highway)
        way_summary = {
            "highway": highway,
            "service": tags.get("service"),
            "rank": rank,
        }
        if rank is None or not is_priority_yield_way(way_summary):
            continue
        points: list[tuple[float, float]] = []
        for node_id_raw in way.get("nodes") or []:
            node = nodes.get(int(node_id_raw))
            if not node:
                continue
            points.append(
                project_lat_lng(
                    float(node["lat"]),
                    float(node["lng"]),
                    reference_lat_rad=reference_lat_rad,
                )
            )
        if len(points) < 2:
            continue
        geometries.append(
            {
                "id": int(way["id"]),
                "name": tags.get("name"),
                "highway": highway,
                "service": tags.get("service"),
                "rank": rank,
                "points": points,
            }
        )
    return geometries


def route_point_at_distance(points: list[dict[str, float]], distance_m: float) -> dict[str, float]:
    if not points:
        return {"lat": 0.0, "lng": 0.0, "distance": 0.0}
    if distance_m <= points[0]["distance"]:
        return points[0]
    if distance_m >= points[-1]["distance"]:
        return points[-1]
    for start, end in zip(points, points[1:]):
        if start["distance"] <= distance_m <= end["distance"]:
            span = end["distance"] - start["distance"]
            if span <= 0:
                return start
            t = (distance_m - start["distance"]) / span
            return {
                "lat": start["lat"] + t * (end["lat"] - start["lat"]),
                "lng": start["lng"] + t * (end["lng"] - start["lng"]),
                "distance": distance_m,
            }
    return points[-1]


def nearest_highway_at_point(
    point: dict[str, float],
    way_geometries: list[dict[str, Any]],
    *,
    reference_lat_rad: float,
    max_distance_m: float = 35.0,
) -> dict[str, Any] | None:
    if not way_geometries:
        return None
    point_xy = project_lat_lng(point["lat"], point["lng"], reference_lat_rad=reference_lat_rad)
    best: dict[str, Any] | None = None
    for way in way_geometries:
        distance_m = polyline_xy_distance_m(point_xy, way["points"])
        if distance_m > max_distance_m:
            continue
        if best is None or distance_m < best["distance_to_way_m"]:
            best = {
                "way_id": way["id"],
                "name": way.get("name"),
                "highway": way["highway"],
                "service": way.get("service"),
                "rank": way["rank"],
                "distance_to_way_m": round(distance_m, 1),
            }
    return best


def matched_route_way_ids_for_route(
    points: list[dict[str, float]],
    way_geometries: list[dict[str, Any]],
    *,
    reference_lat_rad: float,
    step_m: float = 25.0,
    max_distance_m: float = 25.0,
) -> set[int]:
    matched: set[int] = set()
    for point in sample_points_by_distance(points, step_m=step_m):
        match = nearest_highway_at_point(
            point,
            way_geometries,
            reference_lat_rad=reference_lat_rad,
            max_distance_m=max_distance_m,
        )
        if match and match.get("way_id") is not None:
            matched.add(int(match["way_id"]))
    return matched


def compact_highway_match(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {
        "way_id": match.get("way_id"),
        "name": match.get("name"),
        "highway": match.get("highway"),
        "service": match.get("service"),
        "rank": match.get("rank"),
        "distance_to_way_m": match.get("distance_to_way_m"),
    }


def compact_highway_match_with_bearing(
    way: dict[str, Any],
    way_geometries: list[dict[str, Any]],
    junction_xy: tuple[float, float],
    *,
    incoming_bearing: float | None = None,
) -> dict[str, Any]:
    result = compact_highway_match(way) or {}
    bearing = way_bearing_away_from_junction(way, way_geometries, junction_xy)
    if bearing is not None:
        result["bearing_deg"] = round(bearing, 1)
        if incoming_bearing is not None:
            right_angle = clockwise_angle_diff_deg(incoming_bearing, bearing)
            result["right_side_angle_deg"] = round(right_angle, 1)
            result["right_hand_rule_hit"] = branch_bearing_is_on_right(bearing, incoming_bearing)
    return result


def route_bearings_through_junction(
    before: dict[str, float],
    after: dict[str, float],
    junction_lat: float,
    junction_lng: float,
    *,
    reference_lat_rad: float,
) -> list[float]:
    junction_xy = project_lat_lng(junction_lat, junction_lng, reference_lat_rad=reference_lat_rad)
    before_xy = project_lat_lng(before["lat"], before["lng"], reference_lat_rad=reference_lat_rad)
    after_xy = project_lat_lng(after["lat"], after["lng"], reference_lat_rad=reference_lat_rad)
    return [
        bearing_xy(before_xy, junction_xy),
        bearing_xy(junction_xy, after_xy),
    ]


def is_distinct_side_branch(
    way: dict[str, Any],
    way_geometries: list[dict[str, Any]],
    junction_xy: tuple[float, float],
    route_bearings: list[float],
    *,
    min_angle_deg: float = 30.0,
) -> bool:
    bearing = way_bearing_away_from_junction(way, way_geometries, junction_xy)
    if bearing is None:
        return False
    return all(undirected_angle_diff_deg(bearing, route_bearing) >= min_angle_deg for route_bearing in route_bearings)


def branch_is_on_right(
    way: dict[str, Any],
    way_geometries: list[dict[str, Any]],
    junction_xy: tuple[float, float],
    *,
    incoming_bearing: float,
) -> bool:
    bearing = way_bearing_away_from_junction(way, way_geometries, junction_xy)
    if bearing is None:
        return False
    return branch_bearing_is_on_right(bearing, incoming_bearing)


def branch_bearing_is_on_right(
    branch_bearing: float,
    incoming_bearing: float,
    *,
    min_right_angle_deg: float = 30.0,
    max_right_angle_deg: float = 150.0,
) -> bool:
    right_angle = clockwise_angle_diff_deg(incoming_bearing, branch_bearing)
    return min_right_angle_deg <= right_angle <= max_right_angle_deg


def way_bearing_near_junction(
    way: dict[str, Any],
    way_geometries: list[dict[str, Any]],
    junction_xy: tuple[float, float],
) -> float | None:
    way_id = int(way.get("way_id") or way.get("id") or 0)
    for geometry in way_geometries:
        if int(geometry["id"]) != way_id:
            continue
        return nearest_segment_bearing_xy(junction_xy, geometry["points"])
    return None


def way_bearing_away_from_junction(
    way: dict[str, Any],
    way_geometries: list[dict[str, Any]],
    junction_xy: tuple[float, float],
) -> float | None:
    way_id = int(way.get("way_id") or way.get("id") or 0)
    for geometry in way_geometries:
        if int(geometry["id"]) != way_id:
            continue
        return nearest_segment_bearing_away_from_point(junction_xy, geometry["points"])
    return None


def nearest_segment_bearing_xy(
    point_xy: tuple[float, float],
    polyline_xy: list[tuple[float, float]],
) -> float | None:
    if len(polyline_xy) < 2:
        return None
    best_distance = float("inf")
    best_bearing: float | None = None
    for start, end in zip(polyline_xy, polyline_xy[1:]):
        distance = point_to_segment_distance(point_xy, start, end)
        if distance < best_distance:
            best_distance = distance
            best_bearing = bearing_xy(start, end)
    return best_bearing


def nearest_segment_bearing_away_from_point(
    point_xy: tuple[float, float],
    polyline_xy: list[tuple[float, float]],
) -> float | None:
    if len(polyline_xy) < 2:
        return None
    best_distance = float("inf")
    best_bearing: float | None = None
    px, py = point_xy
    for start, end in zip(polyline_xy, polyline_xy[1:]):
        distance = point_to_segment_distance(point_xy, start, end)
        if distance >= best_distance:
            continue
        best_distance = distance
        sx, sy = start
        ex, ey = end
        if math.hypot(px - sx, py - sy) <= math.hypot(px - ex, py - ey):
            best_bearing = bearing_xy(start, end)
        else:
            best_bearing = bearing_xy(end, start)
    return best_bearing


def bearing_xy(start: tuple[float, float], end: tuple[float, float]) -> float:
    sx, sy = start
    ex, ey = end
    return (math.degrees(math.atan2(ex - sx, ey - sy)) + 360.0) % 360.0


def clockwise_angle_diff_deg(a: float, b: float) -> float:
    return (b - a + 360.0) % 360.0


def undirected_angle_diff_deg(a: float, b: float) -> float:
    diff = abs((a - b + 180.0) % 360.0 - 180.0)
    return min(diff, 180.0 - diff)


def angle_diff_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def point_to_polyline_distance_m(
    lat: float,
    lng: float,
    route_xy: list[tuple[float, float]],
    *,
    reference_lat_rad: float,
) -> float:
    if len(route_xy) < 2:
        return float("inf")
    point_xy = project_lat_lng(lat, lng, reference_lat_rad=reference_lat_rad)
    best = float("inf")
    for start, end in zip(route_xy, route_xy[1:]):
        best = min(best, point_to_segment_distance(point_xy, start, end))
    return best


def point_to_polyline_location(
    lat: float,
    lng: float,
    points: list[dict[str, float]],
    route_xy: list[tuple[float, float]],
    *,
    reference_lat_rad: float,
) -> dict[str, float] | None:
    if len(points) < 2 or len(route_xy) < 2:
        return None
    point_xy = project_lat_lng(lat, lng, reference_lat_rad=reference_lat_rad)
    best: dict[str, float] | None = None
    for index, (start_xy, end_xy) in enumerate(zip(route_xy, route_xy[1:])):
        px, py = point_xy
        sx, sy = start_xy
        ex, ey = end_xy
        dx = ex - sx
        dy = ey - sy
        if dx == 0 and dy == 0:
            t = 0.0
            distance_to_route_m = math.hypot(px - sx, py - sy)
        else:
            t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
            closest_x = sx + t * dx
            closest_y = sy + t * dy
            distance_to_route_m = math.hypot(px - closest_x, py - closest_y)
        distance_m = points[index]["distance"] + t * (points[index + 1]["distance"] - points[index]["distance"])
        if best is None or distance_to_route_m < best["distance_to_route_m"]:
            best = {
                "distance_to_route_m": distance_to_route_m,
                "distance_m": distance_m,
            }
    return best


def point_to_polyline_locations(
    lat: float,
    lng: float,
    points: list[dict[str, float]],
    route_xy: list[tuple[float, float]],
    *,
    reference_lat_rad: float,
    max_distance_m: float,
    merge_within_m: float = 50.0,
) -> list[dict[str, float]]:
    if len(points) < 2 or len(route_xy) < 2:
        return []
    point_xy = project_lat_lng(lat, lng, reference_lat_rad=reference_lat_rad)
    locations: list[dict[str, float]] = []
    for index, (start_xy, end_xy) in enumerate(zip(route_xy, route_xy[1:])):
        px, py = point_xy
        sx, sy = start_xy
        ex, ey = end_xy
        dx = ex - sx
        dy = ey - sy
        if dx == 0 and dy == 0:
            t = 0.0
            distance_to_route_m = math.hypot(px - sx, py - sy)
        else:
            t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
            closest_x = sx + t * dx
            closest_y = sy + t * dy
            distance_to_route_m = math.hypot(px - closest_x, py - closest_y)
        if distance_to_route_m > max_distance_m:
            continue
        distance_m = points[index]["distance"] + t * (points[index + 1]["distance"] - points[index]["distance"])
        locations.append(
            {
                "distance_to_route_m": distance_to_route_m,
                "distance_m": distance_m,
            }
        )
    locations.sort(key=lambda item: item["distance_m"])
    merged: list[dict[str, float]] = []
    for location in locations:
        if not merged or abs(location["distance_m"] - merged[-1]["distance_m"]) > merge_within_m:
            merged.append(location)
            continue
        if location["distance_to_route_m"] < merged[-1]["distance_to_route_m"]:
            merged[-1] = location
    return merged


def polyline_xy_distance_m(point_xy: tuple[float, float], polyline_xy: list[tuple[float, float]]) -> float:
    if len(polyline_xy) < 2:
        return float("inf")
    return min(
        point_to_segment_distance(point_xy, start, end)
        for start, end in zip(polyline_xy, polyline_xy[1:])
    )


def point_to_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
    closest_x = sx + t * dx
    closest_y = sy + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def merge_nearby_junctions(junctions: list[dict[str, Any]], *, within_m: float) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for junction in sorted(junctions, key=lambda item: (item["lat"], item["lng"])):
        if any(distance_km(junction["lat"], junction["lng"], item["lat"], item["lng"]) * 1000 <= within_m for item in merged):
            continue
        merged.append(junction)
    return merged


def merge_nearby_route_events(
    events: list[dict[str, Any]],
    *,
    within_m: float,
    within_route_km: float,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: number(item.get("route_distance_km")) or 0.0):
        event_route_km = number(event.get("route_distance_km"))
        duplicate = False
        for item in merged:
            item_route_km = number(item.get("route_distance_km"))
            if event_route_km is None or item_route_km is None:
                route_close = True
            else:
                route_close = abs(event_route_km - item_route_km) <= within_route_km
            spatial_close = (
                distance_km(event["lat"], event["lng"], item["lat"], item["lng"]) * 1000 <= within_m
            )
            if spatial_close and route_close:
                duplicate = True
                break
        if not duplicate:
            merged.append(event)
    return merged


def gps_summary(streams_path: Path) -> dict[str, Any]:
    points: list[dict[str, float | None]] = []
    with streams_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for index, row in enumerate(reader):
            lat = value(row, "lat")
            lng = value(row, "lng")
            if lat is None or lng is None:
                continue
            points.append({"index": index, "lat": lat, "lng": lng, "distance": value(row, "distance")})
    if not points:
        return {"has_gps": False}
    lats = [float(point["lat"]) for point in points if point["lat"] is not None]
    lngs = [float(point["lng"]) for point in points if point["lng"] is not None]
    return {
        "has_gps": True,
        "point_count": len(points),
        "start_lat": points[0]["lat"],
        "start_lng": points[0]["lng"],
        "end_lat": points[-1]["lat"],
        "end_lng": points[-1]["lng"],
        "bbox": {
            "min_lat": min(lats),
            "min_lng": min(lngs),
            "max_lat": max(lats),
            "max_lng": max(lngs),
        },
        "route_shape_key": route_shape_key(points),
    }


def route_shape_key(points: list[dict[str, float | None]]) -> str | None:
    usable = [
        point
        for point in points
        if point.get("lat") is not None and point.get("lng") is not None and point.get("distance") is not None
    ]
    if len(usable) < 20:
        return None
    start_distance = float(usable[0]["distance"] or 0.0)
    total_m = float(usable[-1]["distance"] or 0.0) - start_distance
    if total_m <= 0:
        return None
    sampled: list[tuple[float, float]] = []
    index = 0
    for step in range(21):
        target = start_distance + total_m * step / 20
        while index + 1 < len(usable) and float(usable[index + 1]["distance"] or 0.0) < target:
            index += 1
        sampled.append((round(float(usable[index]["lat"]), 3), round(float(usable[index]["lng"]), 3)))
    distance_bucket_km = round((total_m / 1000) / 3) * 3
    shape = "|".join(f"{lat:.3f},{lng:.3f}" for lat, lng in sampled)
    return f"{distance_bucket_km}km:{shape}"


def query_matches(route: dict[str, Any], queries: list[str]) -> bool:
    if not queries:
        return True
    haystack = f"{route['name']} {route['route_key']}".lower()
    return any(query.lower() in haystack for query in queries)


def route_matches_target_distance(route: dict[str, Any], *, target_distance_km: float | None) -> bool:
    if target_distance_km is None:
        return True
    distance_km = number(route.get("distance_km"))
    if distance_km is None:
        return False
    distance_filter = target_distance_filter(target_distance_km)
    return distance_filter["min_km"] <= distance_km <= distance_filter["max_km"]


def preferred_route_display_info_by_group(
    routes: list[dict[str, Any]],
    *,
    registry: dict[str, Any] | None = None,
) -> dict[str, dict[str, str | None]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        group_key = route_group_key(route)
        if not group_key:
            continue
        grouped.setdefault(group_key, []).append(route)
    return {
        group_key: preferred_route_display_info_for_group(
            group_routes,
            reference_routes=routes,
            registry=registry,
        )
        for group_key, group_routes in grouped.items()
    }


def preferred_route_display_info_for_group(
    routes: list[dict[str, Any]],
    *,
    reference_routes: list[dict[str, Any]] | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    override = route_display_name_override(routes, registry)
    if override:
        return override
    for route in routes:
        name = str(route.get("name") or "")
        if is_usable_route_display_name(name):
            display_name = strip_endpoint_places_from_route_name(name, endpoint_place_names(route))
            return {
                "display_name": display_name,
                "display_name_source": "source_activity_name",
                "display_name_reason": (
                    "Start/end anchor was omitted from the source activity name."
                    if display_name != name
                    else None
                ),
            }
    similar = similar_route_display_name(routes, reference_routes or routes)
    if similar:
        return {
            "display_name": similar,
            "display_name_source": "similar_route_geometry",
            "display_name_reason": (
                "All references in this route group had generic or workout-derived activity names; "
                "display name was inferred from a similarly shaped route with a concrete place-based name."
            ),
        }
    inferred = inferred_route_display_name(routes)
    if inferred:
        return {
            "display_name": inferred,
            "display_name_source": "inferred_from_route_context",
            "display_name_reason": (
                "All references in this route group had generic or workout-derived activity names; "
                "display name was inferred from place text."
            ),
        }
    fallback = str((routes[0] if routes else {}).get("name") or "")
    return {
        "display_name": fallback,
        "display_name_source": "source_activity_name",
        "display_name_reason": None,
    }


def route_display_name_override(
    routes: list[dict[str, Any]],
    registry: dict[str, Any] | None,
) -> dict[str, str | None] | None:
    activities = (registry or {}).get("activities") or {}
    for route in routes:
        activity_id = str(route.get("id") or "")
        issue = activities.get(activity_id)
        if not isinstance(issue, dict):
            continue
        display_name = str(issue.get("route_display_name") or "").strip()
        if not display_name:
            continue
        return {
            "display_name": display_name,
            "display_name_source": str(
                issue.get("route_display_name_source") or "route_data_quality_override"
            ),
            "display_name_reason": str(issue.get("reason") or "") or None,
        }
    return None


def is_usable_route_display_name(name: str) -> bool:
    return bool(name and not is_generic_route_name(name) and not is_workout_route_name(name))


def is_generic_route_name(name: str) -> bool:
    key = route_key(name)
    if key in GENERIC_ROUTE_NAMES:
        return True
    return bool(re.fullmatch(r".+\s+landeveissykling", normalize_name(name)))


def is_workout_route_name(name: str) -> bool:
    normalized = normalize_name(name)
    if any(marker in normalized for marker in WORKOUT_ROUTE_NAME_MARKERS):
        return True
    parts = [part.strip() for part in normalized.split(" - ")]
    if len(parts) >= 2 and parts[-1] in KNOWN_WORKOUT_ROUTE_NAME_SUFFIXES:
        return True
    return False


def inferred_route_display_name(routes: list[dict[str, Any]]) -> str | None:
    base_names: Counter[str] = Counter()
    for route in routes:
        base = route_name_base_candidate(str(route.get("name") or ""))
        if base:
            base_names[base] += 1
    if not base_names:
        return None
    return base_names.most_common(1)[0][0]


def similar_route_display_name(routes: list[dict[str, Any]], reference_routes: list[dict[str, Any]]) -> str | None:
    best: tuple[tuple[int, float], str] | None = None
    for route in routes:
        route_samples = route_shape_samples(route)
        route_distance = number(route.get("distance_km"))
        if not route_samples or route_distance is None:
            continue
        for reference in reference_routes:
            if reference is route:
                continue
            reference_name = str(reference.get("display_name") or reference.get("name") or "")
            if not is_usable_route_display_name(reference_name):
                continue
            reference_distance = number(reference.get("distance_km"))
            if reference_distance is None:
                continue
            distance_gap = abs(reference_distance - route_distance)
            if distance_gap > max(12.0, route_distance * 0.25):
                continue
            sample_distance_m = route_shape_average_distance_m(route_samples, route_shape_samples(reference))
            if sample_distance_m > 3000:
                continue
            endpoint_places = endpoint_place_names(route)
            candidate_name = strip_endpoint_places_from_route_name(reference_name, endpoint_places)
            if not candidate_name:
                continue
            score = sample_distance_m + distance_gap * 100
            sort_key = (1 if route_place_name_count(candidate_name) <= 1 else 0, score)
            if best is None or sort_key < best[0]:
                best = (sort_key, candidate_name)
    return best[1] if best else None


def route_place_name_count(name: str) -> int:
    parts = [part for part in re.split(r"\s*(?:-|–|—|\+| og )\s*", name) if part.strip()]
    return len(parts)


def route_shape_samples(route: dict[str, Any]) -> list[tuple[float, float]]:
    key = str(route.get("route_shape_key") or "")
    if ":" not in key:
        return []
    samples: list[tuple[float, float]] = []
    for token in key.split(":", 1)[1].split("|"):
        try:
            lat_text, lng_text = token.split(",", 1)
            samples.append((float(lat_text), float(lng_text)))
        except ValueError:
            continue
    return samples


def route_shape_average_distance_m(
    a_samples: list[tuple[float, float]],
    b_samples: list[tuple[float, float]],
) -> float:
    if not a_samples or not b_samples:
        return float("inf")
    return min(
        route_shape_average_distance_one_direction_m(a_samples, b_samples),
        route_shape_average_distance_one_direction_m(a_samples, list(reversed(b_samples))),
    )


def route_shape_average_distance_one_direction_m(
    a_samples: list[tuple[float, float]],
    b_samples: list[tuple[float, float]],
) -> float:
    count = min(len(a_samples), len(b_samples))
    if count == 0:
        return float("inf")
    distances = []
    for index in range(count):
        a_index = round(index * (len(a_samples) - 1) / (count - 1)) if count > 1 else 0
        b_index = round(index * (len(b_samples) - 1) / (count - 1)) if count > 1 else 0
        a_lat, a_lng = a_samples[a_index]
        b_lat, b_lng = b_samples[b_index]
        distances.append(distance_km(a_lat, a_lng, b_lat, b_lng) * 1000)
    return sum(distances) / len(distances)


def endpoint_place_names(route: dict[str, Any]) -> set[str]:
    names = {"fjällbacka", "fjallbacka"}
    anchor_name = str(route.get("start_anchor_name") or "")
    for token in re.split(r"[\s,/()]+", normalize_name(anchor_name)):
        if len(token) >= 3:
            names.add(token)
    return names


def strip_endpoint_places_from_route_name(name: str, endpoint_places: set[str]) -> str:
    parts = [part.strip() for part in re.split(r"\s*(?:-|–|—|\+| og )\s*", name) if part.strip()]
    if len(parts) <= 1:
        return name.strip()
    while len(parts) > 1 and normalize_name(parts[0]) in endpoint_places:
        parts.pop(0)
    while len(parts) > 1 and normalize_name(parts[-1]) in endpoint_places:
        parts.pop()
    return "-".join(parts).strip()


def route_name_base_candidate(name: str) -> str | None:
    normalized = normalize_name(name)
    if not normalized:
        return None
    if " - " in normalized:
        parts = [part.strip() for part in name.split(" - ")]
        normalized_parts = [normalize_name(part) for part in parts]
        if (
            any(marker in normalized for marker in WORKOUT_ROUTE_NAME_MARKERS)
            or normalized_parts[-1] in KNOWN_WORKOUT_ROUTE_NAME_SUFFIXES
        ):
            return parts[0].strip() or None
    landevei_suffix = " landeveissykling"
    if normalized.endswith(landevei_suffix):
        return name[: -len(landevei_suffix)].strip(" -") or None
    if is_usable_route_display_name(name):
        return name.strip()
    return None


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower()).strip()


def target_distance_filter(target_distance_km: float | None) -> dict[str, float] | None:
    if target_distance_km is None:
        return None
    return {
        "min_km": round(max(8.0, target_distance_km * 0.6), 1),
        "max_km": round(max(target_distance_km + 20.0, target_distance_km * 2.0), 1),
    }


def score_route(
    route: dict[str, Any],
    *,
    target_distance_km: float | None,
    prefer_terrain_steady_endurance: bool,
    surface_preference: str,
) -> float:
    score = 0.0
    if target_distance_km is not None and route.get("distance_km") is not None:
        distance_tolerance_km = max(10.0, target_distance_km * 0.25)
        score += (
            route_closeness_score(
                route,
                "distance_km",
                target_distance_km,
                tolerance=distance_tolerance_km,
            )
            * 16
        )
    if route.get("starts_ends_near_start_anchor"):
        score += 20
    if prefer_terrain_steady_endurance:
        score += terrain_steady_endurance_ranking_adjustment(route)
    score += surface_preference_adjustment(route, surface_preference=surface_preference)
    return round(score, 2)


def terrain_steady_endurance_ranking_adjustment(route: dict[str, Any]) -> float:
    flow = route.get("steady_endurance") or {}
    downhill_disruption_pct = number(flow.get("downhill_disruption_pct"))
    if downhill_disruption_pct is None:
        adjustment = 0.0
    else:
        flow_score = max(0.0, 100.0 - 10.0 * downhill_disruption_pct)
        adjustment = (flow_score - 60.0) * 0.7
        if downhill_disruption_pct is not None and downhill_disruption_pct >= 5.0:
            adjustment -= min(20.0, (downhill_disruption_pct - 5.0) * 5.0)
    return adjustment


def surface_preference_adjustment(route: dict[str, Any], *, surface_preference: str) -> float:
    surface = (route.get("surface") or {}).get("surface")
    if surface_preference == "any":
        return 0.0
    if surface_preference == "unknown-ok" and surface == "unknown":
        return 0.0
    if surface == surface_preference:
        return 0.0
    if surface == "unknown":
        return -8.0
    if surface_preference == "road" and surface == "gravel":
        return -35.0
    if surface_preference == "gravel" and surface == "road":
        return -20.0
    return 0.0


def closeness_score(value_: float, target: float, *, tolerance: float) -> float:
    return max(0.0, 1.0 - abs(value_ - target) / tolerance)


def route_closeness_score(route: dict[str, Any], field: str, target: float, *, tolerance: float) -> float:
    value_ = number(route.get(field))
    if value_ is None:
        return 0.0
    return closeness_score(value_, target, tolerance=tolerance)


def route_reference_note(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "saved_route_reference",
        "text": "Saved activity is used as a route reference; recency and execution are not route-ranking inputs.",
    }


def compact_route_reference(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": route["date"].isoformat(),
        "id": route.get("id"),
        "url": route.get("url"),
        "moving_minutes": route.get("moving_minutes"),
        "distance_km": route.get("distance_km"),
        "xss": route.get("xss"),
        "load_source": route.get("load_source"),
        "training_load": route.get("training_load"),
        "intensity": route.get("intensity"),
        "average_watts": route.get("average_watts"),
        "weighted_average_watts": route.get("weighted_average_watts"),
    }


def format_route(route: dict[str, Any]) -> dict[str, Any]:
    gps = route.get("gps") or {}
    bbox = gps.get("bbox") or {}
    display_name = str(route.get("display_name") or route["name"])
    return {
        "score": route["score"],
        "date": route["date"].isoformat(),
        "id": route["id"],
        "name": display_name,
        "display_name_source": route.get("display_name_source"),
        "display_name_reason": route.get("display_name_reason"),
        "source_activity_name": route["name"],
        "route_key": route["route_key"],
        "route_shape_key": route.get("route_shape_key"),
        "route_group_key": route_group_key(route),
        "route_reference_count": route.get("route_reference_count"),
        "route_reference_count_used_for_ranking": False,
        "moving_minutes": route["moving_minutes"],
        "distance_km": route["distance_km"],
        "elevation_gain_m": route["elevation_gain_m"],
        "xss": route.get("xss"),
        "load_source": route.get("load_source"),
        "training_load": route["training_load"],
        "intensity": route["intensity"],
        "average_watts": route["average_watts"],
        "weighted_average_watts": route["weighted_average_watts"],
        "average_heartrate": route["average_heartrate"],
        "max_heartrate": route["max_heartrate"],
        "gear": route.get("gear"),
        "surface": route.get("surface"),
        "surface_preference": route.get("surface_preference"),
        "start_anchor_name": route.get("start_anchor_name"),
        "starts_ends_near_start_anchor": route.get("starts_ends_near_start_anchor"),
        "start_distance_from_anchor_km": route.get("start_distance_from_anchor_km"),
        "end_distance_from_anchor_km": route.get("end_distance_from_anchor_km"),
        "steady_endurance": route.get("steady_endurance"),
        "map_junctions": route.get("map_junctions"),
        "map_yield_situations": route.get("map_yield_situations"),
        "bbox": bbox,
        "activity_dir": route["activity_dir"],
        "url": route["url"],
        "url_meaning": "Intervals.icu activity URL for the saved route reference; not a map image.",
        "intervals_activity_url": route["url"],
        "route_reference_note": route.get("route_reference_note"),
        "recommendation_text": recommendation_text(route),
    }


def recommendation_text(route: dict[str, Any]) -> str:
    note = route.get("route_reference_note") or {}
    suffix = f" {note['text']}" if note.get("text") else ""
    surface_text = route_surface_text(route)
    steady_endurance_text = route_steady_endurance_text(route)
    display_name = str(route.get("display_name") or route["name"])
    return (
        f"Bruk tidligere rute `{display_name}` ({route['date'].isoformat()}, {route['id']}): "
        f"{route['distance_km']:.1f} km, {route['elevation_gain_m']:.0f} hm. "
        f"{steady_endurance_text} "
        f"{surface_text} "
        f"{route['url']}."
        f"{suffix}"
    )


def route_steady_endurance_text(route: dict[str, Any]) -> str:
    flow = route.get("steady_endurance") or {}
    if flow.get("available") is False:
        return "Jevn endurance: ukjent/svak høydedata."
    downhill_disruption_pct = number(flow.get("downhill_disruption_pct"))
    if downhill_disruption_pct is None:
        return "Jevn endurance: ikke beregnet."
    gt4_pct = number(flow.get("descent_gt4_pct"))
    gt5_pct = number(flow.get("descent_gt5_pct"))
    if gt4_pct is not None and gt5_pct is not None:
        return f"Bratt nedover: {downhill_disruption_pct:.1f}% vektet ({gt4_pct:.1f}% >4%, {gt5_pct:.1f}% >5%)."
    return f"Bratt nedover: {downhill_disruption_pct:.1f}% vektet."


def route_surface_text(route: dict[str, Any]) -> str:
    surface = route.get("surface") or {}
    preference = route.get("surface_preference") or "road"
    kind = surface.get("surface")
    label = surface.get("label") or "ukjent underlag"
    bike = surface.get("bike") or surface.get("gear_name")
    bike_suffix = f" ({bike})" if bike else ""
    if preference == "any":
        if kind in {"road", "gravel"}:
            return f"Underlag: {label}{bike_suffix}; ikke vektet i scoren."
        warning = surface.get("warning") or "Kan ikke bekrefte landevei vs grus fra metadata."
        return f"Underlag: {label}{bike_suffix}; ikke vektet i scoren. {warning}"
    if preference == "unknown-ok" and kind == "unknown":
        warning = surface.get("warning") or "Kan ikke bekrefte landevei vs grus fra metadata."
        return f"Underlag: {label}{bike_suffix}; ukjent underlag er akseptert i denne rangeringen. {warning}"
    if kind == "road":
        suffix = "matcher ønsket landevei." if preference == "road" else "matcher ikke ønsket grus."
        return f"Underlag: {label}{bike_suffix}; {suffix}"
    if kind == "gravel":
        suffix = "matcher ønsket grus." if preference == "gravel" else "matcher ikke ønsket landevei."
        return f"Underlag: {label}{bike_suffix}; {suffix}"
    warning = surface.get("warning") or "Kan ikke bekrefte landevei vs grus fra metadata."
    return f"Underlag: {label}{bike_suffix}. {warning}"


def route_key(name: str) -> str:
    key = name.lower()
    key = re.sub(r"\s+-\s+xert.*$", "", key)
    key = re.sub(r"\s+landeveissykling$", "", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def route_group_key(route: dict[str, Any]) -> str:
    return str(route.get("route_shape_key") or route.get("route_key") or route.get("name") or "")


def intervals_url(activity_id: Any) -> str | None:
    if not activity_id:
        return None
    return f"https://intervals.icu/activities/{activity_id}"


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def minutes(seconds: float | None) -> float | None:
    if seconds is None:
        return None
    return round(seconds / 60, 1)


def number(raw: Any) -> float | None:
    if raw in ("", None):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_date(raw: str) -> date:
    return datetime.fromisoformat(raw).date()


if __name__ == "__main__":
    main()
