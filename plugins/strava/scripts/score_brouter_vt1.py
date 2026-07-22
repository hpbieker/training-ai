#!/usr/bin/env python3
"""Score BRouter GeoJSON route candidates for Hans Petter-style outdoor VT1 flow.

The score is intentionally opinionated: it penalizes G/S shortcuts, footways,
crossing-like nodes, barriers, signals, and traffic calming because these break
steady VT1 pacing.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

BAD_ROAD_TYPES = {"footway", "path", "pedestrian", "track"}
INVALID_FAST_ROAD_TYPES = {"motorway", "motorway_link", "trunk", "trunk_link"}
UNPAVED_SURFACES = {
    "compacted",
    "dirt",
    "earth",
    "fine_gravel",
    "grass",
    "gravel",
    "ground",
    "mud",
    "sand",
    "unpaved",
}


def score(path: Path) -> dict:
    data = json.loads(path.read_text())
    feature = data["features"][0]
    props = feature.get("properties", {})
    messages = props.get("messages", [])[1:]
    by_type: collections.Counter[str] = collections.Counter()
    crossings = signals = uncontrolled = barriers = calming = 0
    unpaved_m = unknown_surface_m = foot_designated_m = 0.0
    total_m = 0.0
    long_bad_segments = []

    for row in messages:
        if len(row) < 11:
            continue
        distance_m = float(row[3])
        total_m += distance_m
        way_tags = row[9] or ""
        node_tags = row[10] or ""
        match = re.search(r"highway=([^ ]+)", way_tags)
        road_type = match.group(1) if match else "unknown"
        by_type[road_type] += distance_m
        surface_match = re.search(r"surface=([^ ]+)", way_tags)
        surface = surface_match.group(1) if surface_match else ""
        is_unpaved = surface in UNPAVED_SURFACES
        is_unknown_surface = not surface
        is_foot_designated = "foot=designated" in way_tags
        if is_unpaved:
            unpaved_m += distance_m
        if is_unknown_surface:
            unknown_surface_m += distance_m
        if is_foot_designated:
            foot_designated_m += distance_m

        if (road_type in BAD_ROAD_TYPES | {"cycleway"} or is_unpaved or is_unknown_surface) and distance_m >= 100:
            long_bad_segments.append(
                {
                    "km": round(total_m / 1000, 1),
                    "meters": round(distance_m),
                    "type": road_type,
                    "surface": surface,
                    "foot_designated": is_foot_designated,
                    "way_tags": way_tags,
                    "node_tags": node_tags,
                }
            )

        crossing_like = (
            "highway=crossing" in node_tags
            or "crossing=" in node_tags
            or "estimated_crossing_class" in node_tags
        )
        if crossing_like:
            crossings += 1
        if "traffic_signals" in node_tags:
            signals += 1
        if "uncontrolled" in node_tags:
            uncontrolled += 1
        if "barrier=" in node_tags:
            barriers += 1
        if "traffic_calming" in node_tags:
            calming += 1

    vt1_score = (
        by_type["footway"] * 7
        + by_type["path"] * 6
        + by_type["pedestrian"] * 6
        + by_type["track"] * 3
        + by_type["cycleway"] * 2.5
        + crossings * 220
        + uncontrolled * 350
        + signals * 400
        + barriers * 250
        + calming * 100
        + unpaved_m * 20
        + unknown_surface_m * 1.5
        + foot_designated_m * 4
    )

    invalid_fast_roads_m = sum(by_type[t] for t in INVALID_FAST_ROAD_TYPES)
    gs_like_m = by_type["cycleway"] + by_type["footway"] + by_type["path"] + by_type["pedestrian"]

    return {
        "path": str(path),
        "length_km": round(total_m / 1000, 2),
        "filtered_ascend_m": props.get("filtered ascend"),
        "brouter_cost": props.get("cost"),
        "vt1_interruption_score": round(vt1_score),
        "gs_like_km": round(gs_like_m / 1000, 2),
        "cycleway_km": round(by_type["cycleway"] / 1000, 2),
        "footway_path_pedestrian_km": round(
            (by_type["footway"] + by_type["path"] + by_type["pedestrian"]) / 1000,
            2,
        ),
        "unpaved_km": round(unpaved_m / 1000, 2),
        "unknown_surface_km": round(unknown_surface_m / 1000, 2),
        "foot_designated_km": round(foot_designated_m / 1000, 2),
        "invalid_fast_roads_km": round(invalid_fast_roads_m / 1000, 2),
        "crossings": crossings,
        "signals": signals,
        "uncontrolled_crossings": uncontrolled,
        "barriers": barriers,
        "traffic_calming": calming,
        "road_class_km": {k: round(v / 1000, 2) for k, v in by_type.most_common()},
        "long_bad_segments": long_bad_segments[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("geojson", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of compact text.")
    args = parser.parse_args()
    results = [score(path) for path in args.geojson]
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    for result in results:
        print(f"\n{result['path']}")
        print(
            "len={length_km} km asc={filtered_ascend_m} vt1_score={vt1_interruption_score} "
            "gs={gs_like_km} km cycle={cycleway_km} km foot/path/ped={footway_path_pedestrian_km} km "
            "unpaved={unpaved_km} km unknown_surface={unknown_surface_km} km foot_designated={foot_designated_km} km "
            "crossings={crossings} signals={signals} uncontrolled={uncontrolled_crossings} "
            "barriers={barriers} calming={traffic_calming} invalid_fast_roads={invalid_fast_roads_km} km".format(
                **result
            )
        )
        print("roads: " + ", ".join(f"{k}:{v}" for k, v in result["road_class_km"].items()))
        if result["long_bad_segments"]:
            print("long bad segments:")
            for seg in result["long_bad_segments"][:8]:
                print(f"  km {seg['km']:>4}: {seg['meters']:>4} m {seg['type']} {seg['way_tags'][:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
