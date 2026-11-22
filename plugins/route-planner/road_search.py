"""Locate points on carriageways in an OpenStreetMap routing graph."""

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from route_geometry import ATTRIBUTION, LICENSE_URL, USER_AGENT, coordinate

LOCATE_URL = "https://valhalla1.openstreetmap.de/locate"
RADIUS_M = 300
MAX_REPLY = 2 * 1024 * 1024


def road_candidates(edges, road):
    candidates = {}
    for edge in edges:
        info, network = edge["edge_info"], edge["edge"]
        names = info["names"]
        classification = network["classification"]
        if (
            edge["distance"] > RADIUS_M
            or not network["access"]["car"]
            or not network["access"]["bicycle"]
            or network["destination_only"]
            or classification["use"] not in {"road", "ramp", "living_street"}
            or (road and not any(road == name.casefold() for name in names))
        ):
            continue

        way_id = info["way_id"]
        key = tuple(sorted(names)) if names else way_id
        if key in candidates and candidates[key]["distance_from_near_m"] <= edge["distance"]:
            continue
        candidates[key] = {
            "point": {"lat": edge["correlated_lat"], "lon": edge["correlated_lon"]},
            "distance_from_near_m": edge["distance"],
            "names": names,
            "road_class": classification["classification"],
            "road_use": classification["use"],
            "surface": classification["surface"],
            "source_url": f"https://www.openstreetmap.org/way/{way_id}",
        }
    return sorted(candidates.values(), key=lambda match: match["distance_from_near_m"])[:5]


def find_road_points(arguments):
    requests = arguments["locations"]
    locations = []
    for item in requests:
        near = item["near"]
        lon, lat = coordinate(near["lat"], near["lon"])
        locations.append({"lon": lon, "lat": lat, "radius": RADIUS_M})
    params = {"locations": locations, "costing": "auto", "verbose": True}
    query = urlencode({"json": json.dumps(params, separators=(",", ":"))})
    request = Request(
        f"{LOCATE_URL}?{query}",
        headers={"User-Agent": USER_AGENT, "X-Client-Id": "training-ai-route-planner"},
    )
    with urlopen(request, timeout=10) as response:
        body = response.read(MAX_REPLY + 1)
    if len(body) > MAX_REPLY:
        raise ValueError("Road lookup response exceeded the size limit.")
    payload = json.loads(body)
    if not isinstance(payload, list) or len(payload) != len(locations):
        raise ValueError("Road lookup returned an unexpected response.")
    return {
        "locations": [
            {
                "near": item["near"],
                "results": road_candidates(result.get("edges") or [], item.get("road", "").strip().casefold()),
            }
            for item, result in zip(requests, payload)
        ],
        "radius_m": RADIUS_M,
        "attribution": ATTRIBUTION,
        "license_url": LICENSE_URL,
    }
