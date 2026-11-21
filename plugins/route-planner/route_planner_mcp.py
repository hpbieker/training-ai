#!/usr/bin/env python3
"""Stdio MCP entry point for the Route Planner plugin."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from place_search import find_public_place
from road_search import find_road_points
from route_geometry import compare_route_geometry, coordinate, distance, validate_route, write_gpx
from route_inspection import inspect_route_file, locate_passages

PLUGIN = Path(__file__).resolve().parent
PROFILE = PLUGIN / "assets/profiles/fastbike-road-flow.brf"
BROUTER_URL = "https://brouter.de/brouter"
MAX_ROUTING_REPLY = 20 * 1024 * 1024
MAX_ENDPOINT_SNAP_M = 100
MAX_VIA_SNAP_M = 15
MAX_EDITED_WAYPOINT_SNAP_M = 50
DEFAULT_ROUTE_LOOKUP_RADIUS_M = 100
MAX_ROUTE_LOOKUP_RADIUS_M = 1000
POINT = {
    "type": "object",
    "properties": {
        "lat": {"type": "number", "minimum": -90, "maximum": 90},
        "lon": {"type": "number", "minimum": -180, "maximum": 180},
    },
    "required": ["lat", "lon"],
    "additionalProperties": False,
}
ID = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
SNAP_TO_ROUTE = {
    "type": "boolean",
    "description": "Save the routed position up to 50 m from the requested point.",
}
WAYPOINT = {
    **POINT,
    "properties": {**POINT["properties"], "waypoint_id": ID},
    "anyOf": [{"required": ["lat", "lon"]}, {"required": ["waypoint_id"]}],
    "required": [],
    "dependentRequired": {"lat": ["lon"], "lon": ["lat"]},
}
TOOL = types.Tool(
    name="plan_route",
    description=(
        "Calculate and save a cycling route through the supplied waypoints in order. "
        "Route coordinates are sent to an external routing service. "
        "Returns route and waypoint IDs, distance, estimated time and verified points. "
        "Endpoints may move up to 100 m and intermediate points up to 15 m."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "start": POINT,
            "end": POINT,
            "waypoints": {"type": "array", "items": POINT, "maxItems": 500},
        },
        "required": ["start", "end"],
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)

UPDATE_ROUTE = types.Tool(
    name="update_route",
    description=(
        "Update a saved route using its ID and the revision you last read. "
        "Route coordinates are sent to an external routing service. "
        "Use move_waypoint with waypoint_id, lat and lon to move one point in place, "
        "or remove_waypoint_id to remove it. Use add_waypoint to insert a point after a waypoint "
        "or after the start. Use waypoints to replace or reorder the full list. "
        "You can also change the start or end. Omitted fields are kept. "
        "Returns the new revision and verified points."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "route_id": ID,
            "expected_revision": {"type": "integer", "minimum": 1},
            "remove_waypoint_id": ID,
            "move_waypoint": {
                **WAYPOINT,
                "properties": {
                    **WAYPOINT["properties"],
                    "snap_to_route": SNAP_TO_ROUTE,
                },
                "required": ["waypoint_id", "lat", "lon"],
            },
            "add_waypoint": {
                **POINT,
                "properties": {
                    **POINT["properties"],
                    "after_waypoint_id": {**ID, "description": "Omit to insert after the start."},
                    "snap_to_route": SNAP_TO_ROUTE,
                },
            },
            "waypoints": {"type": "array", "items": WAYPOINT, "maxItems": 500},
            "start": POINT,
            "end": POINT,
        },
        "required": ["route_id", "expected_revision"],
        "anyOf": [{"required": [key]} for key in (
            "add_waypoint", "remove_waypoint_id", "move_waypoint", "waypoints", "start", "end",
        )],
        "not": {"anyOf": [
            {"required": ["remove_waypoint_id", "waypoints"]},
            {"required": ["move_waypoint", "waypoints"]},
            {"required": ["move_waypoint", "remove_waypoint_id"]},
            {"required": ["add_waypoint", "waypoints"]},
            {"required": ["add_waypoint", "move_waypoint"]},
            {"required": ["add_waypoint", "remove_waypoint_id"]},
        ]},
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)

EVALUATE_ROUTE_CHANGE = types.Tool(
    name="evaluate_route_change",
    description=(
        "Calculate the effect of a proposed update against a saved route revision without saving it. "
        "Accepts the same changes as update_route. Reports the distance difference and where the "
        "route geometry changes. Sends the full proposed route coordinates and bundled profile to BRouter."
    ),
    inputSchema=UPDATE_ROUTE.inputSchema,
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)

GET_ROUTE = types.Tool(
    name="get_route",
    description="Read a saved route summary and its ordered waypoint IDs without recalculating or opening an export file.",
    inputSchema={
        "type": "object",
        "properties": {"route_id": ID},
        "required": ["route_id"],
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)

EXPORT_ROUTE = types.Tool(
    name="export_route",
    description="Export the latest saved route by route_id. Returns a local file path. Defaults to GPX.",
    inputSchema={
        "type": "object",
        "properties": {"route_id": ID, "format": {"enum": ["gpx", "geojson"]}},
        "required": ["route_id"],
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
)

INSPECT_ROUTE = types.Tool(
    name="inspect_route",
    description=(
        "Report where road types, surfaces and access tags occur along the route, plus distance totals. "
        "Pass route_id or a GeoJSON route_file. Optionally filter by distance_range (from_km, to_km) "
        "or, for a saved route, by waypoint_range (from_waypoint_id, to_waypoint_id) in travel order. "
        "The two filters are mutually exclusive. Section offsets are relative to the original route start. "
        "This reads local metadata without network requests."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "route_id": ID,
            "route_file": {"type": "string", "minLength": 1},
            "distance_range": {
                "type": "object",
                "properties": {
                    "from_km": {"type": "number", "minimum": 0},
                    "to_km": {"type": "number", "minimum": 0},
                },
                "required": ["from_km", "to_km"],
                "additionalProperties": False,
            },
            "waypoint_range": {
                "type": "object",
                "properties": {"from_waypoint_id": ID, "to_waypoint_id": ID},
                "required": ["from_waypoint_id", "to_waypoint_id"],
                "additionalProperties": False,
            },
        },
        "oneOf": [{"required": ["route_id"]}, {"required": ["route_file"]}],
        "dependentRequired": {"waypoint_range": ["route_id"]},
        "not": {"required": ["distance_range", "waypoint_range"]},
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)

LOCATE_ON_ROUTE = types.Tool(
    name="locate_on_route",
    description=(
        "Find where a saved route passes near a coordinate. Use search_places first for a named place. "
        "Returns the closest point for each separate visit within the search radius, in travel order, "
        "with kilometres from the route start, offset in metres, compass bearing in degrees clockwise "
        "from true north, and road name or reference when available in saved metadata. "
        "Use a smaller radius to distinguish closely spaced passages. Reads the saved route locally."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "route_id": ID,
            "near": POINT,
            "radius_m": {
                "type": "number", "exclusiveMinimum": 0, "maximum": MAX_ROUTE_LOOKUP_RADIUS_M,
                "default": DEFAULT_ROUTE_LOOKUP_RADIUS_M,
            },
        },
        "required": ["route_id", "near"],
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)

SEARCH_PLACES = types.Tool(
    name="search_places",
    description=(
        "Look up a public place named in a user-requested cycling route using OpenStreetMap data. "
        "Queries go to an external service. Keep personal or confidential information out of queries. "
        "Pass query and optional near to rank the results locally. "
        "Returned point coordinates are representative place locations, not verified road points."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 200},
            "near": POINT,
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)

FIND_ROAD_POINTS = types.Tool(
    name="find_road_points",
    description=(
        "Find points on mapped carriageways within 300 m of each approximate location in one lookup. "
        "Use for routing guides, especially when a parallel cycleway is nearby or a waypoint misses the route. "
        "Optional road matches an exact OpenStreetMap street name or road reference. "
        "Returns up to five candidates with coordinates, road class and OSM links per location, in input order. "
        "Coordinates are sent to an external OpenStreetMap-based service."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "locations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "near": POINT,
                        "road": {"type": "string", "minLength": 1, "maxLength": 200},
                    },
                    "required": ["near"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["locations"],
        "additionalProperties": False,
    },
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)


def route_directory():
    return Path(os.environ.get("ROUTE_PLANNER_ROUTES", tempfile.gettempdir())).resolve()


def route_folder(route_id):
    if not re.fullmatch(r"[0-9a-f]{32}", route_id):
        raise ValueError("Invalid route_id")
    return route_directory() / f"route-planner-{route_id}"


def load_route(route_id):
    try:
        saved = json.loads((route_folder(route_id) / "current.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Unknown or expired route_id: {route_id}") from None
    saved.pop("experimental", None)
    return saved


def get_route(arguments):
    return {key: value for key, value in load_route(arguments["route_id"]).items() if key != "geojson_file"}


def export_route(arguments):
    saved = load_route(arguments["route_id"])
    geojson = Path(saved["geojson_file"])
    if arguments.get("format", "gpx") == "geojson":
        output = geojson
    else:
        coordinates = json.loads(geojson.read_text(encoding="utf-8"))["features"][0]["geometry"]["coordinates"]
        output = geojson.with_suffix(".gpx")
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as file:
            temporary = Path(file.name)
        try:
            write_gpx(temporary, saved["title"], coordinates)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return {"route_id": saved["route_id"], "revision": saved["revision"], "route_file": str(output)}


def inspect_route(arguments):
    distance_range = arguments.get("distance_range")
    waypoint_range = arguments.get("waypoint_range")
    if distance_range is not None and waypoint_range is not None:
        raise ValueError("Choose either distance_range or waypoint_range.")
    if "route_id" in arguments:
        saved = load_route(arguments["route_id"])
        return {
            "route_id": saved["route_id"],
            "revision": saved["revision"],
            **inspect_route_file(
                saved["geojson_file"], distance_range=distance_range,
                waypoint_range=waypoint_range, waypoints=saved["points"][1:-1] if waypoint_range else (),
            ),
        }
    if waypoint_range is not None:
        raise ValueError("Use route_id with waypoint_range.")
    return inspect_route_file(arguments["route_file"], distance_range=distance_range)


def locate_on_route(arguments):
    near = route_point(arguments["near"])
    radius = arguments.get("radius_m", DEFAULT_ROUTE_LOOKUP_RADIUS_M)
    if not 0 < radius <= MAX_ROUTE_LOOKUP_RADIUS_M:
        raise ValueError(f"radius_m must be greater than 0 and at most {MAX_ROUTE_LOOKUP_RADIUS_M}")
    saved = load_route(arguments["route_id"])
    return {
        "route_id": saved["route_id"],
        "revision": saved["revision"],
        "radius_m": radius,
        "passages": locate_passages(saved["geojson_file"], near, radius),
    }


def search_places(arguments):
    near = arguments.get("near")
    reference = coordinate(near["lat"], near["lon"]) if near is not None else None
    query = arguments["query"].strip()
    if not query:
        raise ValueError("query cannot be blank")
    return find_public_place(query, reference, distance)


def brouter_json(url, data=None):
    request = Request(url, data=data, headers={
        "User-Agent": "training-ai-route-planner/0.2",
        "Content-Type": "text/plain; charset=UTF-8",
    })
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read(MAX_ROUTING_REPLY + 1)
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace").strip()
        raise ValueError(f"BRouter service returned HTTP {exc.code}: {detail}") from exc
    if len(body) > MAX_ROUTING_REPLY:
        raise ValueError("BRouter service response exceeded the size limit")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("BRouter service returned an invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise ValueError("BRouter service returned an unexpected response")
    if payload.get("error"):
        raise ValueError(f"BRouter service: {payload['error']}")
    return payload


def run_brouter(requested, profile):
    uploaded = brouter_json(BROUTER_URL + "/profile", profile)
    profile_id = uploaded.get("profileid")
    if not isinstance(profile_id, str) or not re.fullmatch(r"custom_[0-9]+", profile_id):
        raise ValueError("BRouter service did not return a valid uploaded profile ID")
    query = urlencode({
        "lonlats": "|".join(f"{lon},{lat}" for lon, lat in requested),
        "profile": profile_id,
        "format": "geojson",
        "alternativeidx": 0,
    })
    return brouter_json(BROUTER_URL + "?" + query), profile_id


def verify_matches(requested, geometry, snap_waypoint_index=None):
    matches = []
    previous = -1
    for i, point in enumerate(requested):
        role = "start" if i == 0 else "end" if i == len(requested) - 1 else "waypoint"
        snap_waypoint = i == snap_waypoint_index
        limit = MAX_VIA_SNAP_M if role == "waypoint" else MAX_ENDPOINT_SNAP_M
        if snap_waypoint:
            limit = MAX_EDITED_WAYPOINT_SNAP_M
        if role == "start":
            j = 0
        elif role == "end":
            j = len(geometry) - 1
        else:
            if previous + 1 >= len(geometry) - 1:
                raise ValueError(f"No track point remains for waypoint at index {i}")
            j = min(range(previous + 1, len(geometry) - 1),
                    key=lambda index: distance(point, geometry[index]))
        snap = geometry[j]
        gap = distance(point, snap)
        if j <= previous or gap > limit:
            detail = (f"Route misses {role} at index {i} (start is index 0) in order "
                      f"(nearest eligible point {gap:.1f} m away, limit {limit} m).")
            if role == "waypoint":
                detail += (
                    f" Use find_road_points near lat {point[1]:.6f}, lon {point[0]:.6f} "
                    "to locate a routing guide on the intended road."
                )
            raise ValueError(detail)
        previous = j
        if snap_waypoint:
            point, gap = snap, 0
        matches.append((j, {
            "index": i, "role": role, "requested": {"lat": point[1], "lon": point[0]},
            "on_route": {"lat": snap[1], "lon": snap[0]}, "offset_m": round(gap, 2),
        }))
    return matches


def route_point(point):
    return coordinate(point["lat"], point["lon"])


def route_inputs(arguments, saved):
    old = saved["points"] if saved else []
    waypoint_map = {point["waypoint_id"]: point["requested"] for point in old[1:-1]}
    removed = arguments.get("remove_waypoint_id")
    if removed is not None:
        if removed not in waypoint_map:
            raise ValueError(f"Unknown waypoint_id for this route: {removed}")
        del waypoint_map[removed]
    moved = arguments.get("move_waypoint")
    if moved is not None:
        key = moved["waypoint_id"]
        if key not in waypoint_map:
            raise ValueError(f"Unknown waypoint_id for this route: {key}")
        waypoint_map[key] = {"lat": moved["lat"], "lon": moved["lon"]}
    start = arguments["start"] if "start" in arguments else old[0]["requested"]
    end = arguments["end"] if "end" in arguments else old[-1]["requested"]
    via = arguments.get("waypoints", [{"waypoint_id": key} for key in waypoint_map])
    snap_index = None
    added = arguments.get("add_waypoint")
    if added is not None:
        prior = added.get("after_waypoint_id")
        if prior is not None and prior not in waypoint_map:
            raise ValueError(f"Unknown after_waypoint_id for this route: {prior}")
        if len(via) >= 500:
            raise ValueError("Routes support up to 500 waypoints.")
        index = list(waypoint_map).index(prior) + 1 if prior is not None else 0
        via.insert(index, added)
        if added.get("snap_to_route"):
            snap_index = index + 1
    coords, ids = [route_point(start)], []
    for point in via:
        key = point.get("waypoint_id")
        if key is None:
            key = uuid4().hex
        elif key not in waypoint_map:
            raise ValueError(f"Unknown waypoint_id for this route: {key}")
        ids.append(key)
        coords.append(route_point(point if "lat" in point else waypoint_map[key]))
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate waypoint_id")
    if moved and moved.get("snap_to_route"):
        snap_index = ids.index(moved["waypoint_id"]) + 1
    return [*coords, route_point(end)], ids, snap_index


def calculate_route(arguments, route_id, saved):
    requested, waypoint_ids, snap_index = route_inputs(arguments, saved)
    profile = PROFILE.read_bytes()
    payload, profile_id = run_brouter(requested, profile)
    geometry = validate_route(payload, requested[0], requested[-1], MAX_ENDPOINT_SNAP_M)
    matches = verify_matches(requested, geometry, snap_waypoint_index=snap_index)
    for (_, point), waypoint_id in zip(matches[1:-1], waypoint_ids):
        point["waypoint_id"] = waypoint_id
    props = payload["features"][0]["properties"]
    summary = {
        "route_id": route_id,
        "revision": saved["revision"] + 1 if saved else 1,
        "title": saved.get("title", "Route") if saved else "Route",
        "profile": PROFILE.stem,
        "profile_sha256": hashlib.sha256(profile).hexdigest(),
        "distance_km": round(sum(distance(a, b) for a, b in zip(geometry, geometry[1:])) / 1000, 2),
        "estimated_time_s": int(props["total-time"]),
        "brouter_cost": int(props["cost"]),
        "points": [point for _, point in matches],
    }
    provenance = {
        "profile": summary["profile"], "profile_sha256": summary["profile_sha256"],
        "server": BROUTER_URL, "remote_profile_id": profile_id,
        "engine": payload["features"][0]["properties"].get("creator"),
    }
    payload["routing"] = {**provenance, "route_id": route_id, "revision": summary["revision"]}
    return summary, payload


def save_route(summary, payload, previous_revision):
    route_id = summary["route_id"]
    folder = route_folder(route_id)
    if previous_revision is None:
        folder.mkdir(mode=0o700, parents=True)
    output = None
    try:
        output = Path(tempfile.mkdtemp(prefix="revision-", dir=folder))
        geojson = output / "route.geojson"
        geojson.write_text(json.dumps(payload), encoding="utf-8")
        stored = {**summary, "geojson_file": str(geojson)}
        pending = output / "current.json"
        pending.write_text(json.dumps(stored), encoding="utf-8")
        with (folder / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if previous_revision is not None:
                check_revision(previous_revision, load_route(route_id))
            pending.replace(folder / "current.json")
    except Exception:
        if previous_revision is None:
            shutil.rmtree(folder)
        elif output is not None:
            shutil.rmtree(output)
        raise
    return summary


def plan_route(arguments):
    summary, payload = calculate_route(arguments, uuid4().hex, saved=None)
    return save_route(summary, payload, previous_revision=None)


def check_revision(expected, saved):
    current = saved["revision"]
    if current != expected:
        raise ValueError(
            f"Route revision conflict: expected {expected}, current revision is {current}. "
            "Use get_route to read the latest route before retrying."
        )


def update_route(arguments):
    route_id = arguments["route_id"]
    saved = load_route(route_id)
    check_revision(arguments["expected_revision"], saved)
    summary, payload = calculate_route(arguments, route_id, saved)
    result = save_route(summary, payload, saved["revision"])
    return {key: result[key] for key in (
        "route_id", "revision", "distance_km", "estimated_time_s", "points",
    )}


def evaluate_route_change(arguments):
    route_id = arguments["route_id"]
    saved = load_route(route_id)
    check_revision(arguments["expected_revision"], saved)
    baseline = json.loads(Path(saved["geojson_file"]).read_text(encoding="utf-8"))
    candidate, payload = calculate_route(arguments, route_id, saved)
    previous_profile = saved.get("profile_sha256")
    return {
        "route_id": route_id,
        "base_revision": saved["revision"],
        "before_distance_km": saved["distance_km"],
        "after_distance_km": candidate["distance_km"],
        "same_profile": previous_profile == candidate["profile_sha256"] if previous_profile else None,
        **compare_route_geometry(
            baseline["features"][0]["geometry"]["coordinates"],
            payload["features"][0]["geometry"]["coordinates"],
        ),
    }


def create_server():
    server = Server("route-planner", version="0.2.13")

    @server.list_tools()
    async def list_tools():
        return [
            TOOL, UPDATE_ROUTE, GET_ROUTE, EXPORT_ROUTE, INSPECT_ROUTE, LOCATE_ON_ROUTE,
            EVALUATE_ROUTE_CHANGE, SEARCH_PLACES, FIND_ROAD_POINTS,
        ]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            handler = {
                TOOL.name: plan_route,
                UPDATE_ROUTE.name: update_route,
                GET_ROUTE.name: get_route,
                EXPORT_ROUTE.name: export_route,
                INSPECT_ROUTE.name: inspect_route,
                LOCATE_ON_ROUTE.name: locate_on_route,
                EVALUATE_ROUTE_CHANGE.name: evaluate_route_change,
                SEARCH_PLACES.name: search_places,
                FIND_ROAD_POINTS.name: find_road_points,
            }.get(name)
            if handler is None:
                raise ValueError(f"Unknown tool: {name}")
            result = await anyio.to_thread.run_sync(handler, arguments)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result))],
                structuredContent=result,
            )
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            return types.CallToolResult(
                isError=True, content=[types.TextContent(type="text", text=str(exc))]
            )

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
