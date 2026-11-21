"""Route geometry validation and GPX export for the Route Planner MCP."""
import math
import xml.etree.ElementTree as ET

USER_AGENT = "training-ai-route-planner/0.2.0"

LIMITATIONS = [
    "No external traffic counts are fetched; the routing profile may use OSM-derived estimates.",
    "Conditional access and local restrictions are not fully modelled.",
    "Road selection and access handling follow the bundled BRouter profile.",
    "The routing profile can use elevation and OSM-derived estimates for routing.",
    "Importing GPX into another service may recalculate the route; compare the resulting track.",
]


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


def write_gpx(path, name, points):
    ET.register_namespace("", "http://www.topografix.com/GPX/1/1")
    ns = "{http://www.topografix.com/GPX/1/1}"
    root = ET.Element(ns+"gpx", version="1.1", creator=USER_AGENT)
    metadata = ET.SubElement(root, ns+"metadata")
    ET.SubElement(metadata, ns+"name").text = name
    ET.SubElement(metadata, ns+"desc").text = " ".join(LIMITATIONS)
    trk = ET.SubElement(root, ns+"trk")
    ET.SubElement(trk, ns+"name").text = name
    ET.SubElement(trk, ns+"type").text = "cycling"
    seg = ET.SubElement(trk, ns+"trkseg")
    for p in points:
        point = ET.SubElement(seg, ns+"trkpt", lat=str(p[1]), lon=str(p[0]))
        if len(p) > 2 and p[2] is not None and math.isfinite(p[2]):
            ET.SubElement(point, ns+"ele").text = str(p[2])
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
