"""Normalize route geometry without contacting a source service."""
import json
import math
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

MAX_POINTS = 100_000
MAX_FILE_BYTES = 20_000_000
WEB_MERCATOR_LIMIT = 85.05112878


def point(value):
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        raise ValueError('Coordinates must be [longitude, latitude] or [longitude, latitude, elevation].')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('Coordinates must contain finite numbers.')
    lon, lat = value[:2]
    if not -180 <= lon <= 180 or not -WEB_MERCATOR_LIMIT <= lat <= WEB_MERCATOR_LIMIT:
        raise ValueError('Coordinate outside the supported Web Mercator map bounds.')
    return [lon, lat]


def lines_from_geojson(value):
    if not isinstance(value, dict):
        raise ValueError('geojson must be an object.')
    kind = value.get('type')
    if kind == 'Feature':
        return lines_from_geojson(value.get('geometry'))
    if kind == 'FeatureCollection':
        features = value.get('features')
        if not isinstance(features, list):
            raise ValueError('FeatureCollection requires features.')
        return [line for f in features for line in lines_from_geojson(f)]
    if kind == 'LineString':
        return [value.get('coordinates')]
    if kind == 'MultiLineString':
        return value.get('coordinates')
    raise ValueError('Use GeoJSON LineString, MultiLineString, or line Features.')


def read_route_file(filename):
    path = Path(filename).expanduser()
    if not path.is_absolute():
        raise ValueError('route_file must be an absolute local file path.')
    if path.suffix.lower() not in ('.gpx', '.json', '.geojson'):
        raise ValueError('Supported route files: .gpx, .geojson, .json.')
    with path.open('rb') as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('Route file exceeds 20 MB.')
    if path.suffix.lower() == '.gpx':
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('GPX document types and entities are not supported.')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError(f'Invalid GPX: {exc}') from exc
        segments = root.findall('.//{*}trkseg') + root.findall('.//{*}rte')
        lines = []
        for segment in segments:
            nodes = [n for n in segment if n.tag.rsplit('}', 1)[-1] in ('trkpt', 'rtept')]
            if nodes:
                lines.append([[float(n.attrib['lon']), float(n.attrib['lat'])] for n in nodes])
        return lines
    obj = json.loads(raw)
    # Local training-ai route artifacts, as well as portable GeoJSON.
    if isinstance(obj, dict) and isinstance(obj.get('points'), list):
        return [[[p['lng'], p['lat']] for p in obj['points']]]
    return lines_from_geojson(obj)


def normalize_route(arguments):
    if not isinstance(arguments, dict):
        raise ValueError('Arguments must be an object.')
    allowed = {'geojson', 'route_file', 'title', 'date', 'status', 'distance_km', 'moving_time_s', 'elevation_gain_m', 'source_url', 'source_label'}
    if set(arguments) - allowed:
        raise ValueError('Unknown route arguments: ' + ', '.join(sorted(set(arguments) - allowed)))
    if ('geojson' in arguments) == ('route_file' in arguments):
        raise ValueError('Provide exactly one of geojson or route_file.')
    if 'route_file' in arguments:
        if not isinstance(arguments['route_file'], str):
            raise ValueError('route_file must be a string.')
        lines = read_route_file(arguments['route_file'])
    else:
        lines = lines_from_geojson(arguments['geojson'])
    if not isinstance(lines, list) or not lines:
        raise ValueError('Route has no line segments.')
    if any(not isinstance(line, list) or len(line) < 2 for line in lines):
        raise ValueError('Every line segment needs at least two points.')
    if sum(map(len, lines)) > MAX_POINTS:
        raise ValueError('Route exceeds 100,000 points; simplify it before rendering.')
    normalized = [[point(p) for p in line] for line in lines]
    # Preserve breaks: a MultiLineString must not invent connecting roads.
    # Cross-dateline routes need longitude unwrapping, outside this first version.
    if any(abs(b[0] - a[0]) > 180 for line in normalized for a, b in zip(line, line[1:])):
        raise ValueError('Routes crossing the antimeridian are not yet supported.')
    result = {'title': 'Cycling route', 'geometry': {'type': 'MultiLineString', 'coordinates': normalized}}
    for key in ('title', 'date', 'source_label'):
        if key in arguments:
            v = arguments[key]
            if not isinstance(v, str) or not v.strip() or len(v) > 300:
                raise ValueError(f'{key} must be a nonempty string of at most 300 characters.')
            result[key] = v
    for key in ('distance_km', 'moving_time_s', 'elevation_gain_m'):
        if key in arguments:
            v = arguments[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise ValueError(f'{key} must be a finite nonnegative number.')
            result[key] = v
    if 'status' in arguments:
        if arguments['status'] not in ('planned', 'completed'):
            raise ValueError('status must be planned or completed.')
        result['status'] = arguments['status']
    if 'source_url' in arguments:
        url = arguments['source_url']
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError('source_url must be an HTTPS URL.')
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password:
            raise ValueError('source_url must be an HTTPS URL without credentials.')
        result['source_url'] = url
    return result
