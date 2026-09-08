#!/usr/bin/env python3
"""Build and inspect a Strava route candidate with Python HTTP."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from analyze_strava_build import analyze
from strava_route_api import StravaError, StravaSession, default_cookie_file


EARTH_RADIUS_KM = 6371.0088


def destination(lat: float, lng: float, distance_km: float, bearing_deg: float) -> tuple[float, float]:
    angular = distance_km / EARTH_RADIUS_KM
    bearing = math.radians(bearing_deg % 360)
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), ((math.degrees(lng2) + 540) % 360) - 180


def parse_via(raw: str) -> dict[str, Any]:
    parts = [part.strip() for part in raw.split(",", 2)]
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("--via must be LAT,LNG[,NAME]")
    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--via coordinates must be numeric") from exc
    name = parts[2] if len(parts) == 3 and parts[2] else "Via"
    return {"lat": lat, "lng": lng, "name": name}


def point(lat: float, lng: float, name: str) -> dict[str, Any]:
    return {"lat": lat, "lng": lng, "name": name}


def generated_points(args: argparse.Namespace) -> list[dict[str, Any]]:
    start = point(args.start_lat, args.start_lng, args.start_name)
    if args.via:
        return [start, *args.via, start]
    if args.shape == "out-and-back":
        turn_lat, turn_lng = destination(
            args.start_lat,
            args.start_lng,
            args.target_km / 2,
            args.bearing_deg,
        )
        return [start, point(turn_lat, turn_lng, "Turnaround"), start]

    side_km = args.target_km / 3
    first_lat, first_lng = destination(
        args.start_lat,
        args.start_lng,
        side_km,
        args.bearing_deg,
    )
    second_lat, second_lng = destination(
        first_lat,
        first_lng,
        side_km,
        args.bearing_deg + 120,
    )
    return [
        start,
        point(first_lat, first_lng, "Loop anchor 1"),
        point(second_lat, second_lng, "Loop anchor 2"),
        start,
    ]


def element(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "elementType": "Waypoint",
        "waypoint": {
            "point": {"lat": item["lat"], "lng": item["lng"]},
            "metadata": {"title": item["name"]},
        },
    }


def route_preferences(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "routeType": "Ride",
        "surfaceType": args.surface,
        "popularity": args.popularity,
        "elevation": 1 if args.elevation == "hilly" else 0,
        "straightLine": False,
    }


def build_body(points: list[dict[str, Any]], prefs: dict[str, Any]) -> dict[str, Any]:
    elements = [element(item) for item in points]
    requests = [
        {"elements": [elements[idx], elements[idx + 1]], "routePrefs": prefs}
        for idx in range(len(elements) - 1)
    ]
    return {"requests": requests}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def validate_candidate(
    result: dict[str, Any],
    *,
    target_km: float,
    tolerance_pct: float,
    surface: str,
    allow_distance_deviation: bool,
) -> None:
    if not result.get("ok") or result.get("leg_count", 0) < 2:
        raise StravaError("Strava did not return a complete route candidate.")
    actual_km = float(result["total_length_m"]) / 1000
    deviation = abs(actual_km - target_km) / target_km * 100
    if deviation > tolerance_pct and not allow_distance_deviation:
        raise StravaError(
            f"Built route is {actual_km:.1f} km, {deviation:.1f}% from the "
            f"{target_km:.1f} km target; adjust direction or via points."
        )
    if surface == "Paved" and result.get("skeptical_surface_m", 0) > 0:
        raise StravaError(
            "Strava reports Unknown or Unpaved surface on a road-only candidate; "
            "inspect or revise the route before creation."
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--cookie-file",
        type=Path,
        default=default_cookie_file(),
        help="Cookie header file (default: STRAVA_COOKIE_FILE or ~/.strava/session.headers).",
    )
    result.add_argument(
        "--header-file",
        type=Path,
        help="Optional private file of additional non-secret browser headers.",
    )
    result.add_argument("--start-name", required=True)
    result.add_argument("--start-lat", type=float, required=True)
    result.add_argument("--start-lng", type=float, required=True)
    result.add_argument("--target-km", type=float, required=True)
    result.add_argument("--shape", choices=("out-and-back", "loop"), default="loop")
    result.add_argument("--bearing-deg", type=float, default=0)
    result.add_argument("--via", type=parse_via, action="append", default=[])
    result.add_argument("--surface", choices=("Paved", "Any", "Dirt"), default="Paved")
    result.add_argument("--popularity", type=float, choices=(0.0, 0.5, 1.0), default=0.0)
    result.add_argument("--elevation", choices=("flat", "hilly"), default="flat")
    result.add_argument("--distance-tolerance-pct", type=float, default=15)
    result.add_argument("--allow-distance-deviation", action="store_true")
    result.add_argument("--output-dir", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.target_km <= 0:
        raise SystemExit("--target-km must be positive")
    if args.distance_tolerance_pct < 0:
        raise SystemExit("--distance-tolerance-pct cannot be negative")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    points = generated_points(args)
    prefs = route_preferences(args)
    build_request = build_body(points, prefs)
    build_request_path = args.output_dir / "build-request.json"
    build_response_path = args.output_dir / "build-response.json"
    analysis_path = args.output_dir / "analysis.json"
    geojson_path = args.output_dir / "route.geojson"
    write_json(build_request_path, build_request)

    try:
        with StravaSession(args.cookie_file, args.header_file) as session:
            auth = session.authenticate()
            build_response = session.api("build", build_request_path, build_response_path)
            analysis = analyze(build_response_path, geojson_path)
            write_json(analysis_path, analysis)
            validate_candidate(
                analysis,
                target_km=args.target_km,
                tolerance_pct=args.distance_tolerance_pct,
                surface=args.surface,
                allow_distance_deviation=args.allow_distance_deviation,
            )
            output: dict[str, Any] = {
                "action": "build_only",
                "auth": auth,
                "target_km": args.target_km,
                "points": points,
                "analysis": analysis,
                "artifacts": {
                    "build_request": str(build_request_path),
                    "build_response": str(build_response_path),
                    "analysis": str(analysis_path),
                    "geojson": str(geojson_path),
                },
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0
    except StravaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
