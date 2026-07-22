#!/usr/bin/env python3
"""Summarize Strava build-route responses and export their actual polylines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SKEPTICAL_SURFACES = {"Unknown", "Unpaved"}


def decode_polyline(encoded: str) -> list[list[float]]:
    index = lat = lng = 0
    coords: list[list[float]] = []
    while index < len(encoded):
        result = shift = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lat += ~(result >> 1) if result & 1 else result >> 1

        result = shift = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lng += ~(result >> 1) if result & 1 else result >> 1
        coords.append([lng * 1e-5, lat * 1e-5])
    return coords


def iter_paths(data: dict):
    for route_idx, route in enumerate(data.get("buildRoute", [])):
        for leg_idx, leg in enumerate(route.get("legs", [])):
            for path_idx, path in enumerate(leg.get("paths", [])):
                yield route_idx, leg_idx, path_idx, path


def surface_lengths(offsets: list[dict], total_length: float | None) -> dict[str, float]:
    if not offsets or not total_length:
        return {}
    lengths: dict[str, float] = {}
    sorted_offsets = sorted(offsets, key=lambda item: item.get("distanceOffset") or 0)
    for idx, item in enumerate(sorted_offsets):
        start = float(item.get("distanceOffset") or 0)
        end = (
            float(sorted_offsets[idx + 1].get("distanceOffset") or total_length)
            if idx + 1 < len(sorted_offsets)
            else float(total_length)
        )
        surface = item.get("surfaceType") or "Unknown"
        lengths[surface] = lengths.get(surface, 0.0) + max(0.0, end - start)
    return lengths


def analyze(path: Path, geojson_out: Path | None) -> dict:
    data = json.loads(path.read_text())
    features = []
    summaries = []
    for route_idx, leg_idx, path_idx, route_path in iter_paths(data):
        polyline = route_path.get("polyline") or {}
        coords = []
        if polyline.get("encoding") == "Google" and polyline.get("data"):
            coords = decode_polyline(polyline["data"])
        directions = route_path.get("directions") or []
        surfaces = route_path.get("surfaceTypeOffsets") or []
        surface_m = surface_lengths(surfaces, route_path.get("length"))
        summary = {
            "route_index": route_idx,
            "leg_index": leg_idx,
            "path_index": path_idx,
            "length_m": route_path.get("length"),
            "elevation_gain_m": route_path.get("elevationGain"),
            "elevation_loss_m": route_path.get("elevationLoss"),
            "grade_adjusted_length_m": route_path.get("gradeAdjustedLength"),
            "polyline_points": len(coords),
            "surface_type_offsets": surfaces,
            "surface_lengths_m": surface_m,
            "skeptical_surface_m": sum(surface_m.get(s, 0.0) for s in SKEPTICAL_SURFACES),
            "direction_count": len(directions),
            "directions": [
                {
                    "distance": d.get("distance"),
                    "action": d.get("action"),
                    "name": d.get("name"),
                }
                for d in directions
            ],
        }
        summaries.append(summary)
        if coords:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "route_index": route_idx,
                        "leg_index": leg_idx,
                        "path_index": path_idx,
                        "length_m": route_path.get("length"),
                    },
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )

    result = {
        "ok": "buildRoute" in data,
        "route_count": len(data.get("buildRoute", [])),
        "leg_count": len(summaries),
        "total_length_m": sum((s["length_m"] or 0) for s in summaries),
        "total_elevation_gain_m": sum((s["elevation_gain_m"] or 0) for s in summaries),
        "surface_lengths_m": {
            surface: sum(s["surface_lengths_m"].get(surface, 0.0) for s in summaries)
            for surface in sorted({surface for s in summaries for surface in s["surface_lengths_m"]})
        },
        "skeptical_surface_m": sum(s["skeptical_surface_m"] for s in summaries),
        "legs": summaries,
    }
    if geojson_out:
        geojson_out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return result


def compact_print(result: dict) -> None:
    print(
        "routes={route_count} legs={leg_count} len={length:.2f} km elev={elev:.0f} m".format(
            route_count=result["route_count"],
            leg_count=result["leg_count"],
            length=result["total_length_m"] / 1000,
            elev=result["total_elevation_gain_m"],
        )
    )
    for leg in result["legs"]:
        print(
            "leg {leg_index}: {length:.0f} m elev={elev:.0f} pts={pts} skeptical_surface={skeptical:.0f} m surfaces={surfaces}".format(
                leg_index=leg["leg_index"],
                length=leg["length_m"] or 0,
                elev=leg["elevation_gain_m"] or 0,
                pts=leg["polyline_points"],
                skeptical=leg["skeptical_surface_m"],
                surfaces=leg["surface_type_offsets"],
            )
        )
        for direction in leg["directions"][:12]:
            name = direction["name"] or "null"
            print(f"  {direction['distance']:>8.1f} m {direction['action']} {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("response", type=Path)
    parser.add_argument("--geojson-out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = analyze(args.response, args.geojson_out)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        compact_print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
