"""Route geometry validation for the Route Planner MCP."""
import math

def coordinate(lat, lon):
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinates outside valid latitude/longitude range")
    return [lon, lat]


def distance(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def validate_route(payload, start, end, max_snap):
    features = payload.get("features", [])
    if len(features) != 1 or features[0].get("geometry", {}).get("type") != "LineString":
        raise ValueError("Expected exactly one BRouter LineString")
    feature = features[0]
    points = feature["geometry"]["coordinates"]
    if len(points) < 2:
        raise ValueError("Empty route")
    for p in points:
        coordinate(p[1], p[0])
    snaps = [distance(start, points[0]), distance(end, points[-1])]
    if max(snaps) > max_snap:
        raise ValueError(f"Endpoint moved too far from requested location: {snaps} metres")
    return points
