"""Locate and summarize road metadata from a BRouter GeoJSON result."""
from bisect import bisect_left
from collections import Counter, defaultdict
from itertools import accumulate, pairwise
import json
import math
from pathlib import Path
import re

from route_geometry import distance

MAX_BYTES = 20 * 1024 * 1024
TOTAL_KEYS = ("road_type", "surface", "bicycle", "access", "motorroad")
SECTION_TAGS = (
    "highway", "route", "name", "ref", "surface", "bicycle", "foot", "access",
    "vehicle", "motor_vehicle", "motorroad", "segregated", "oneway",
    "oneway:bicycle", "reversedirection",
    "access:conditional", "bicycle:conditional", "foot:conditional",
    "vehicle:conditional", "oneway:conditional", "oneway:bicycle:conditional",
)
TAG = re.compile(r"(?:^|\s)([\w:.-]+)=(.*?)(?=\s[\w:.-]+=|$)")


def section_metadata(tags):
    road_type = tags.get("highway") or tags.get("route") or "unknown"
    if (
        road_type == "cycleway" and tags.get("foot") in {"yes", "designated"}
        and tags.get("bicycle") not in {"no", "private", "dismount", "use_sidepath"}
    ) or (
        road_type == "path" and tags.get("foot") in {"yes", "designated"}
        and tags.get("bicycle") in {"yes", "designated"}
    ):
        road_type = "shared_path"
    return {
        "road_type": road_type,
        "surface": tags.get("surface") or "unknown",
        "tags": {key: tags[key] for key in SECTION_TAGS if key in tags},
    }


def route_offsets(points):
    return list(accumulate((distance(a, b) for a, b in pairwise(points)), initial=0.0))


def locate_rows(points, offsets, rows, *, has_locations):
    if not has_locations:
        yield 0, len(points) - 1, sum(length for length, _, _ in rows), {}
        return

    vertices = defaultdict(list)
    for index, point in enumerate(points):
        key = tuple(round(value * 1_000_000) for value in point[:2])
        vertices[key].append(index)

    start = 0
    pending_distance = 0.0
    skipped_row = False
    for length, tags, position in rows:
        pending_distance += length
        candidates = vertices.get(position, [])
        first = bisect_left(candidates, start)
        if first == len(candidates):
            skipped_row = True
            continue
        # A loop may pass the same coordinate again. BRouter's row
        # distance helps distinguish visits at and after the current index.
        expected = offsets[start] + pending_distance
        end = min(candidates[first:], key=lambda index: abs(offsets[index] - expected))
        if end == start and pending_distance > 0:
            skipped_row = True
            continue
        yield start, end, pending_distance, {} if skipped_row else tags
        start = end
        pending_distance = 0.0
        skipped_row = False
    yield start, len(points) - 1, pending_distance, {}


def merge_spans(offsets, located_rows):
    spans = []
    for start, end, _, tags in located_rows:
        if offsets[end] <= offsets[start]:
            continue
        metadata = section_metadata(tags)
        if spans and spans[-1][1] == start and spans[-1][2] == metadata:
            spans[-1] = (spans[-1][0], end, metadata)
        else:
            spans.append((start, end, metadata))
    return spans


def point_at_offset(points, offsets, metres):
    end = bisect_left(offsets, metres)
    if offsets[end] == metres:
        lon, lat = points[end][:2]
    else:
        fraction = (metres - offsets[end - 1]) / (offsets[end] - offsets[end - 1])
        a, b = points[end - 1], points[end]
        lon, lat = (a[i] + (b[i] - a[i]) * fraction for i in range(2))
    return {"lon": lon, "lat": lat}


def describe_sections(points, offsets, spans, lower, upper):
    sections = []
    for start, end, metadata in spans:
        start_m, end_m = max(lower, offsets[start]), min(upper, offsets[end])
        if end_m <= start_m:
            continue
        sections.append({
            "start_km": round(start_m / 1000, 4),
            "end_km": round(end_m / 1000, 4),
            "length_m": round(end_m - start_m, 1),
            "start": point_at_offset(points, offsets, start_m),
            "end": point_at_offset(points, offsets, end_m),
            **metadata,
        })
    return sections


def waypoint_interval(points, offsets, waypoints, waypoint_range):
    order = {waypoint["waypoint_id"]: i for i, waypoint in enumerate(waypoints)}
    try:
        first = order[waypoint_range["from_waypoint_id"]]
        last = order[waypoint_range["to_waypoint_id"]]
    except KeyError as exc:
        raise ValueError(f"Unknown waypoint_id for this route: {exc.args[0]}") from None
    if first >= last:
        raise ValueError("Choose two different waypoints in travel order.")

    coordinates = [tuple(point[:2]) for point in points]
    vertex = 0
    matches = []
    for waypoint in waypoints[:last + 1]:
        snap = waypoint["on_route"]
        try:
            vertex = coordinates.index((snap["lon"], snap["lat"]), vertex + 1, len(points) - 1)
        except ValueError:
            raise ValueError(f"Cannot locate waypoint {waypoint['waypoint_id']} on the saved route.") from None
        matches.append(offsets[vertex])
    return matches[first], matches[last]


def brouter_rows(messages):
    if not messages or not {"WayTags", "Distance"} <= set(messages[0]):
        return
    for row in messages[1:]:
        values = dict(zip(messages[0], row))
        length = float(values["Distance"])
        if not math.isfinite(length) or length < 0:
            raise ValueError("Invalid distance in BRouter metadata")
        tags = dict(TAG.findall(values["WayTags"]))
        try:
            position = (int(values["Longitude"]), int(values["Latitude"]))
        except (KeyError, TypeError, ValueError):
            position = None
        yield length, tags, position


def read_route_feature(route_file):
    path = Path(route_file)
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".geojson":
        raise ValueError("route_file must be an absolute path to plan_route's GeoJSON file")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("route_file exceeds the 20 MiB inspection limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    if len(features) != 1 or features[0].get("geometry", {}).get("type") != "LineString":
        raise ValueError("Expected one BRouter LineString")
    if len(features[0]["geometry"]["coordinates"]) < 2:
        raise ValueError("Expected at least two route coordinates")
    return features[0]


def inspect_route_file(route_file, *, distance_range=None, waypoint_range=None, waypoints=()):
    feature = read_route_feature(route_file)
    points = feature["geometry"]["coordinates"]
    messages = feature.get("properties", {}).get("messages") or []
    header = set(messages[0]) if messages else set()
    has_locations = {"Longitude", "Latitude"} <= header
    rows = list(brouter_rows(messages))
    offsets = route_offsets(points)
    located = list(locate_rows(points, offsets, rows, has_locations=has_locations))
    lower, upper = 0.0, offsets[-1]
    filtered = distance_range is not None or waypoint_range is not None
    if distance_range is not None:
        lower, upper = distance_range["from_km"] * 1000, distance_range["to_km"] * 1000
    elif waypoint_range is not None:
        lower, upper = waypoint_interval(points, offsets, waypoints, waypoint_range)
    if filtered and not 0 <= lower < upper <= offsets[-1]:
        raise ValueError(f"Choose an increasing range within the route (0–{offsets[-1] / 1000:.4f} km).")

    totals = {key: Counter() for key in TOTAL_KEYS}
    if filtered:
        rows = []
        for start, end, length, tags in located:
            overlap = min(upper, offsets[end]) - max(lower, offsets[start])
            if overlap > 0 and length > 0:
                rows.append((length * overlap / (offsets[end] - offsets[start]), tags, None))
    for length, tags, _ in rows:
        for key, counts in totals.items():
            value = (tags.get("highway") or tags.get("route")) if key == "road_type" else tags.get(key)
            counts[value or "not_tagged"] += length
    return {
        "distance_by_tag_m": {key: {tag: round(length, 1) for tag, length in sorted(counts.items())}
                              for key, counts in totals.items()},
        "sections": describe_sections(points, offsets, merge_spans(offsets, located), lower, upper),
        "note": (
            "Tag totals use BRouter distances. Section distances and offsets follow the route geometry. "
            "Unlocated metadata is reported as unknown. Missing access tags do not establish a cycling prohibition."
        ),
    }
