#!/usr/bin/env python3
"""Inspect a GPX route without depending on source-specific XML layout."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


EARTH_RADIUS_M = 6_371_000
SAMPLE_STEP_M = 25.0
ELEVATION_REVERSAL_M = 3.0


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if local_name(child.tag) == name and child.text:
            return child.text.strip()
    return None


def haversine_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = lat2 - lat1
    dlng = math.radians(b["lon"] - a["lon"])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(value))


def parse_gpx(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    metadata = next((node for node in root if local_name(node.tag) == "metadata"), None)
    name = child_text(metadata, "name") if metadata is not None else None
    route_type = child_text(metadata, "type") if metadata is not None else None

    segments: list[list[dict[str, Any]]] = []
    for track in (node for node in root if local_name(node.tag) == "trk"):
        name = name or child_text(track, "name")
        route_type = route_type or child_text(track, "type")
        for segment in (node for node in track if local_name(node.tag) == "trkseg"):
            points = parse_points(segment, "trkpt")
            if points:
                segments.append(points)

    if not segments:
        for route in (node for node in root if local_name(node.tag) == "rte"):
            name = name or child_text(route, "name")
            route_type = route_type or child_text(route, "type")
            points = parse_points(route, "rtept")
            if points:
                segments.append(points)

    if not segments:
        raise ValueError("GPX file contains no track or route points")
    return {"name": name, "type": route_type, "segments": segments}


def parse_points(parent: ET.Element, point_tag: str) -> list[dict[str, Any]]:
    points = []
    for node in parent:
        if local_name(node.tag) != point_tag:
            continue
        try:
            point: dict[str, Any] = {"lat": float(node.attrib["lat"]), "lon": float(node.attrib["lon"])}
        except (KeyError, ValueError):
            continue
        elevation = child_text(node, "ele")
        if elevation is not None:
            try:
                point["ele"] = float(elevation)
            except ValueError:
                pass
        points.append(point)
    return points


def add_distances(segments: list[list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], float]:
    flat: list[dict[str, Any]] = []
    total_m = 0.0
    for segment_index, segment in enumerate(segments):
        previous = None
        for raw in segment:
            if previous is not None:
                total_m += haversine_m(previous, raw)
            point = dict(raw, distance_m=total_m, segment=segment_index)
            flat.append(point)
            previous = raw
    return flat, total_m


def elevation_profile(points: list[dict[str, Any]]) -> list[tuple[float, float]]:
    known = [(point["distance_m"], point["ele"]) for point in points if "ele" in point]
    if len(known) < 2 or known[-1][0] <= known[0][0]:
        return []
    samples = []
    target = known[0][0]
    index = 1
    while target <= known[-1][0]:
        while index < len(known) and known[index][0] < target:
            index += 1
        if index >= len(known):
            break
        left, right = known[index - 1], known[index]
        span = right[0] - left[0]
        if span > 0:
            fraction = (target - left[0]) / span
            samples.append((target, left[1] + fraction * (right[1] - left[1])))
        target += SAMPLE_STEP_M
    elevations = [sample[1] for sample in samples]
    smoothed = [
        statistics.median(elevations[max(0, index - 2) : min(len(elevations), index + 3)])
        for index in range(len(elevations))
    ]
    return [(samples[index][0], smoothed[index]) for index in range(len(samples))]


def elevation_gain(profile: list[tuple[float, float]]) -> float | None:
    if not profile:
        return None
    gain = 0.0
    anchor = extreme = profile[0][1]
    direction = 0
    for _, elevation in profile[1:]:
        if direction == 0:
            if elevation >= anchor + ELEVATION_REVERSAL_M:
                direction = 1
                extreme = elevation
            elif elevation <= anchor - ELEVATION_REVERSAL_M:
                direction = -1
                extreme = elevation
        elif direction > 0:
            extreme = max(extreme, elevation)
            if extreme - elevation >= ELEVATION_REVERSAL_M:
                gain += max(0.0, extreme - anchor)
                anchor = extreme
                extreme = elevation
                direction = -1
        else:
            extreme = min(extreme, elevation)
            if elevation - extreme >= ELEVATION_REVERSAL_M:
                anchor = extreme
                extreme = elevation
                direction = 1
    if direction > 0:
        gain += max(0.0, extreme - anchor)
    return gain


def terrain_sections(profile: list[tuple[float, float]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not profile:
        return [], []
    turning = [profile[0]]
    anchor = extreme = profile[0]
    direction = 0
    for point in profile[1:]:
        if direction == 0:
            if point[1] >= anchor[1] + ELEVATION_REVERSAL_M:
                direction = 1
                extreme = point
            elif point[1] <= anchor[1] - ELEVATION_REVERSAL_M:
                direction = -1
                extreme = point
        elif direction > 0:
            if point[1] >= extreme[1]:
                extreme = point
            elif extreme[1] - point[1] >= ELEVATION_REVERSAL_M:
                turning.append(extreme)
                anchor = extreme
                extreme = point
                direction = -1
        else:
            if point[1] <= extreme[1]:
                extreme = point
            elif point[1] - extreme[1] >= ELEVATION_REVERSAL_M:
                turning.append(extreme)
                anchor = extreme
                extreme = point
                direction = 1
    if turning[-1] != extreme:
        turning.append(extreme)
    if turning[-1] != profile[-1]:
        turning.append(profile[-1])

    climbs, descents = [], []
    for start, end in zip(turning, turning[1:]):
        distance = end[0] - start[0]
        change = end[1] - start[1]
        if distance < 300 or abs(change) < 20:
            continue
        section = {
            "start_km": round(start[0] / 1000, 2),
            "end_km": round(end[0] / 1000, 2),
            "length_km": round(distance / 1000, 2),
            "elevation_change_m": round(change),
            "average_grade_pct": round(100 * change / distance, 1),
        }
        (climbs if change > 0 else descents).append(section)
    climbs.sort(key=lambda item: item["elevation_change_m"], reverse=True)
    descents.sort(key=lambda item: item["elevation_change_m"])
    return climbs, descents


def inspect_gpx(path: Path) -> dict[str, Any]:
    parsed = parse_gpx(path)
    points, distance_m = add_distances(parsed["segments"])
    profile = elevation_profile(points)
    gain = elevation_gain(profile)
    climbs, descents = terrain_sections(profile)
    start, end = points[0], points[-1]
    closure_m = haversine_m(start, end)
    round_trip_threshold_m = max(200.0, distance_m * 0.02)
    elevations = [elevation for _, elevation in profile]
    return {
        "file": str(path),
        "name": parsed["name"],
        "activity_type": parsed["type"],
        "point_count": len(points),
        "track_segment_count": len(parsed["segments"]),
        "distance_km": round(distance_m / 1000, 2),
        "elevation_gain_m": round(gain) if gain is not None else None,
        "elevation_min_m": round(min(elevations), 1) if elevations else None,
        "elevation_max_m": round(max(elevations), 1) if elevations else None,
        "start": {"lat": round(start["lat"], 6), "lon": round(start["lon"], 6)},
        "end": {"lat": round(end["lat"], 6), "lon": round(end["lon"], 6)},
        "closure_distance_m": round(closure_m),
        "is_round_trip": closure_m <= round_trip_threshold_m,
        "elevation_method": {
            "sample_step_m": SAMPLE_STEP_M,
            "median_window_m": SAMPLE_STEP_M * 5,
            "reversal_threshold_m": ELEVATION_REVERSAL_M,
        },
        "major_climbs": climbs,
        "major_descents": descents,
    }


def summary(result: dict[str, Any]) -> str:
    lines = [
        result["name"] or Path(result["file"]).stem,
        f"{result['distance_km']:.2f} km | "
        + (f"{result['elevation_gain_m']} hm" if result["elevation_gain_m"] is not None else "høyde mangler")
        + f" | {'rundtur' if result['is_round_trip'] else 'ikke rundtur'}",
        f"Start/slutt-avstand: {result['closure_distance_m']} m | "
        f"{result['point_count']} punkter i {result['track_segment_count']} segment(er)",
    ]
    if result["elevation_min_m"] is not None:
        lines.append(f"Høyde: {result['elevation_min_m']:.1f}–{result['elevation_max_m']:.1f} moh.")
    if result["major_climbs"]:
        lines.append("Vesentlige stigninger:")
        lines.extend(
            f"  km {item['start_km']:.2f}–{item['end_km']:.2f}: "
            f"{item['length_km']:.2f} km, +{item['elevation_change_m']} m, "
            f"{item['average_grade_pct']:.1f} %"
            for item in result["major_climbs"][:5]
        )
    if result["major_descents"]:
        lines.append("Vesentlige utforkjøringer:")
        lines.extend(
            f"  km {item['start_km']:.2f}–{item['end_km']:.2f}: "
            f"{item['length_km']:.2f} km, {item['elevation_change_m']} m, "
            f"{item['average_grade_pct']:.1f} %"
            for item in result["major_descents"][:5]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpx", type=Path)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of a summary.")
    args = parser.parse_args()
    try:
        result = inspect_gpx(args.gpx)
    except (OSError, ET.ParseError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
