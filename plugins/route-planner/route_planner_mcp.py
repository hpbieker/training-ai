#!/usr/bin/env python3
"""Stdio MCP entry point for the Route Planner plugin."""
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

from route_geometry import coordinate, distance, validate_route

PLUGIN = Path(__file__).resolve().parent
PROFILE = PLUGIN / "assets/profiles/fastbike-road-flow.brf"
BROUTER_URL = "https://brouter.de/brouter"
MAX_ROUTING_REPLY = 20 * 1024 * 1024
MAX_ENDPOINT_SNAP_M = 100
MAX_VIA_SNAP_M = 15
POINT = {
    "type": "object",
    "properties": {
        "lat": {"type": "number", "minimum": -90, "maximum": 90},
        "lon": {"type": "number", "minimum": -180, "maximum": 180},
    },
    "required": ["lat", "lon"],
    "additionalProperties": False,
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


def route_directory():
    return Path(os.environ.get("ROUTE_PLANNER_ROUTES", tempfile.gettempdir())).resolve()


def route_folder(route_id):
    if not re.fullmatch(r"[0-9a-f]{32}", route_id):
        raise ValueError("Invalid route_id")
    return route_directory() / f"route-planner-{route_id}"


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


def verify_matches(requested, geometry):
    matches = []
    previous = -1
    for i, point in enumerate(requested):
        role = "start" if i == 0 else "end" if i == len(requested) - 1 else "waypoint"
        limit = MAX_VIA_SNAP_M if role == "waypoint" else MAX_ENDPOINT_SNAP_M
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
                    f" Verify the routing guide near lat {point[1]:.6f}, lon {point[0]:.6f}."
                )
            raise ValueError(detail)
        previous = j
        matches.append((j, {
            "index": i, "role": role, "requested": {"lat": point[1], "lon": point[0]},
            "on_route": {"lat": snap[1], "lon": snap[0]}, "offset_m": round(gap, 2),
        }))
    return matches


def route_point(point):
    return coordinate(point["lat"], point["lon"])


def calculate_route(arguments, route_id):
    waypoints = arguments.get("waypoints", [])
    requested = [
        route_point(arguments["start"]),
        *(route_point(point) for point in waypoints),
        route_point(arguments["end"]),
    ]
    profile = PROFILE.read_bytes()
    payload, profile_id = run_brouter(requested, profile)
    geometry = validate_route(payload, requested[0], requested[-1], MAX_ENDPOINT_SNAP_M)
    matches = verify_matches(requested, geometry)
    for _, point in matches[1:-1]:
        point["waypoint_id"] = uuid4().hex
    props = payload["features"][0]["properties"]
    summary = {
        "route_id": route_id,
        "revision": 1,
        "title": "Route",
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


def save_route(summary, payload):
    folder = route_folder(summary["route_id"])
    folder.mkdir(mode=0o700, parents=True)
    try:
        output = Path(tempfile.mkdtemp(prefix="revision-", dir=folder))
        geojson = output / "route.geojson"
        geojson.write_text(json.dumps(payload), encoding="utf-8")
        saved = {**summary, "geojson_file": str(geojson)}
        pending = output / "current.json"
        pending.write_text(json.dumps(saved), encoding="utf-8")
        pending.replace(folder / "current.json")
    except Exception:
        shutil.rmtree(folder)
        raise
    return summary


def plan_route(arguments):
    summary, payload = calculate_route(arguments, uuid4().hex)
    return save_route(summary, payload)


def create_server():
    server = Server("route-planner", version="0.2.13")

    @server.list_tools()
    async def list_tools():
        return [TOOL]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            if name != TOOL.name:
                raise ValueError(f"Unknown tool: {name}")
            result = await anyio.to_thread.run_sync(plan_route, arguments)
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
