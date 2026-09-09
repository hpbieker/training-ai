"""Offline route geometry preparation. Coordinates are (latitude, longitude)."""
import bisect
import copy
import hashlib
import json
import math

from route_geometry import decode_polyline


def fingerprint(route):
    value = {'elements': route['elements'], 'legs': route['legs']}
    # Detail/editor bookkeeping and metadata do not describe route geometry.
    value = {'points': [e['waypoint']['point'] for e in value['elements']],
             'lines': [[p['polyline'] for p in leg['paths']] for leg in value['legs']]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def encode_pairs(points, scales):
    out = []; previous = [0, 0]
    for point in points:
        for axis, value in enumerate(point):
            if not math.isfinite(value): raise ValueError('Non-finite coordinate or elevation')
            integer = math.floor(value * scales[axis] + .5)
            delta = integer - previous[axis]; previous[axis] = integer
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 32:
                out.append(chr((32 | (value & 31)) + 63)); value >>= 5
            out.append(chr(value + 63))
    return ''.join(out)


def distance(a, b):
    return 111195 * math.hypot(b[0] - a[0], (b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2)))


def cumulative(points):
    values = [0.0]
    for a, b in zip(points, points[1:]): values.append(values[-1] + distance(a, b))
    return values


def elevation(path):
    raw = path.get('elevation', {})
    if raw.get('encoding') != 'DrewsBadIdea': raise ValueError('Native path needs a supported elevation profile')
    data = raw.get('data', ''); cursor = 0; current = [0, 0]; result = []
    while cursor < len(data):
        for axis in range(2):
            value = shift = 0
            while True:
                if cursor >= len(data) or shift > 35: raise ValueError('Invalid elevation encoding')
                byte = ord(data[cursor]) - 63; cursor += 1
                if not 0 <= byte <= 63: raise ValueError('Invalid elevation encoding')
                value |= (byte & 31) << shift; shift += 5
                if byte < 32: break
            current[axis] += ~(value >> 1) if value & 1 else value >> 1
        result.append((current[0] / 10, current[1] / 100))
    if not result or result[0][0] < 0 or any(b[0] < a[0] for a, b in zip(result, result[1:])):
        raise ValueError('Elevation profile needs ordered nonnegative distances')
    return result


def interpolate(profile, position):
    i = bisect.bisect_right([p[0] for p in profile], position)
    if i == 0: return profile[0][1]
    if i == len(profile): return profile[-1][1]
    x, a = profile[i - 1]; y, b = profile[i]
    return a + (b - a) * (position - x) / (y - x)


def make_path(points, profile, surfaces=None):
    if len(points) < 2 or any(not all(math.isfinite(v) for v in p) or abs(p[0]) > 90 or abs(p[1]) > 180 for p in points):
        raise ValueError('Invalid route coordinates')
    points = decode_polyline(encode_pairs(points, (1e5, 1e5)))
    length = cumulative(points)[-1]
    if length <= 0: raise ValueError('Replacement has no length')
    if not profile or any(not all(math.isfinite(v) for v in p) for p in profile):
        raise ValueError('A finite elevation profile is required')
    heights = [p[1] for p in profile]
    return {'pathType': 'Normal', 'origin': dict(zip(('lat', 'lng'), points[0])),
            'target': dict(zip(('lat', 'lng'), points[-1])), 'length': length,
            'gradeAdjustedLength': length,
            'elevationGain': sum(max(0, b-a) for a,b in zip(heights, heights[1:])),
            'elevationLoss': sum(max(0, a-b) for a,b in zip(heights, heights[1:])),
            'polyline': {'encoding': 'Google', 'data': encode_pairs(points, (1e5, 1e5))},
            'elevation': {'encoding': 'DrewsBadIdea', 'data': encode_pairs(profile, (10, 100))},
            'directions': [], 'surfaceTypeOffsets': surfaces or [{'distanceOffset': 0, 'surfaceType': 'Unknown'}]}


def slice_path(path, start, end):
    points = decode_polyline(path['polyline']['data']); offsets = cumulative(points)
    if not 0 <= start < end < len(points): raise ValueError('Invalid source point indices')
    scale = float(path['length']) / offsets[-1]
    a, b = offsets[start]*scale, offsets[end]*scale
    profile = elevation(path)
    samples = [(a, interpolate(profile, a)), *[p for p in profile if a < p[0] < b], (b, interpolate(profile, b))]
    surfaces = path.get('surfaceTypeOffsets', [])
    initial = next((s['surfaceType'] for s in reversed(surfaces) if s['distanceOffset'] <= a), 'Unknown')
    return make_path(points[start:end+1], [((d-a)/scale, h) for d,h in samples],
                     [{'distanceOffset': 0, 'surfaceType': initial},
                      *[{'distanceOffset': (s['distanceOffset']-a)/scale, 'surfaceType': s['surfaceType']} for s in surfaces if a < s['distanceOffset'] < b]])


def validate_join_tolerance(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('max_join_gap_m must be a finite nonnegative number')


def adjust_endpoints(path, start=None, end=None, max_join_gap_m=0, adjustments=None, label='replacement'):
    validate_join_tolerance(max_join_gap_m)
    points = decode_polyline(path['polyline']['data'])
    changes = []
    for index, target, side in ((0, start, 'start'), (-1, end, 'end')):
        if target is None or points[index] == target: continue
        gap = distance(points[index], target)
        if gap > max_join_gap_m:
            raise ValueError(f'{label} {side} gap {gap:.3f} m exceeds max_join_gap_m={max_join_gap_m}')
        changes.append({'section': label, 'endpoint': side, 'gap_m': gap,
                        'from_lat_lng': points[index], 'to_lat_lng': target})
        points[index] = target
    if not changes: return copy.deepcopy(path)
    old_length = float(path['length']); new_length = cumulative(points)[-1]
    if old_length <= 0 or new_length <= 0: raise ValueError('Join adjustment collapsed a section')
    scale = new_length / old_length
    result = make_path(points, [(min(d, old_length)*scale, h) for d,h in elevation(path)],
                       [{**s, 'distanceOffset': s['distanceOffset']*scale} for s in path.get('surfaceTypeOffsets', [])])
    if adjustments is not None: adjustments.extend(changes)
    return result


def merge_paths(paths, max_join_gap_m=0, adjustments=None):
    """Explicitly concatenate sequential sections, never Strava alternatives."""
    validate_join_tolerance(max_join_gap_m)
    points = []; profile = []; surfaces = []; offset = 0.0
    for index, path in enumerate(paths):
        if points:
            path = adjust_endpoints(path, start=points[-1], max_join_gap_m=max_join_gap_m, adjustments=adjustments, label=f'native_section_{index}')
        line = decode_polyline(path['polyline']['data'])
        if points and points[-1] != line[0]: raise ValueError('Sections must meet at the same encoded coordinate')
        points.extend(line if not points else line[1:])
        meters = cumulative(line)[-1]; source_length = float(path['length'])
        if source_length <= 0: raise ValueError('Native path length must be positive')
        scale = meters/source_length
        profile.extend((offset+min(d, source_length)*scale, h) for d,h in elevation(path))
        surfaces.extend({**s, 'distanceOffset': offset+s['distanceOffset']*scale} for s in path.get('surfaceTypeOffsets', []))
        offset += meters
    return make_path(points, profile, surfaces)


def replacement_path(value, profile=None, max_join_gap_m=0, adjustments=None):
    if value.get('type') == 'Feature': value = value['geometry']
    if value.get('type') == 'LineString':
        coordinates = value['coordinates']
        if not all(len(p) in (2, 3) for p in coordinates): raise ValueError('GeoJSON needs 2D or 3D coordinates')
        points = [(p[1], p[0]) for p in coordinates]
        distances = cumulative(points)
        if profile is None:
            if not all(len(p) == 3 for p in coordinates): raise ValueError('2D GeoJSON requires --elevation-profile; heights are not invented')
            profile = list(zip(distances, [p[2] for p in coordinates]))
        if len(profile) < 2 or profile[0][0] != 0 or any(b[0] <= a[0] for a,b in zip(profile, profile[1:])) or abs(profile[-1][0]-distances[-1]) > 1:
            raise ValueError('Elevation profile must cover the replacement distance, ordered in metres')
        return make_path(points, profile)
    legs = value.get('legs')
    if 'buildRoute' in value:
        legs = [leg for result in value['buildRoute'] for leg in result['legs']]
    if not legs: raise ValueError('Replacement needs LineString, native legs or buildRoute results')
    if any(len(leg.get('paths', [])) != 1 for leg in legs): raise ValueError('Select exactly one native path per leg; paths can be alternatives')
    return merge_paths([leg['paths'][0] for leg in legs], max_join_gap_m, adjustments)


def replace_batch(route, edits, max_join_gap_m=0):
    """All indices address the original route; rebuild each affected leg once."""
    validate_join_tolerance(max_join_gap_m)
    if not isinstance(edits, list) or not edits: raise ValueError('edits must be a nonempty array')
    groups = {}; reports = []
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict): raise ValueError('Each edit must be an object')
        leg, start, end = (edit.get(k) for k in ('leg', 'from_point', 'to_point'))
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (leg, start, end)):
            raise ValueError('Leg and point indices must be integers')
        if not 0 <= leg < len(route['legs']) or len(route['legs'][leg]['paths']) != 1:
            raise ValueError('Select a source leg with exactly one path')
        points = decode_polyline(route['legs'][leg]['paths'][0]['polyline']['data'])
        if not 0 <= start < end < len(points): raise ValueError('Point indices must be increasing and within the selected leg')
        groups.setdefault(leg, []).append((start, end, index, edit))
    # Validate every interval before processing replacements or writing artifacts.
    for group in groups.values():
        group.sort(key=lambda row: row[0])
        if any(b[0] < a[1] for a,b in zip(group, group[1:])):
            raise ValueError('Overlapping edits on the same source leg')
    result = copy.deepcopy(route['legs'])
    for leg, group in groups.items():
        path = route['legs'][leg]['paths'][0]; points = decode_polyline(path['polyline']['data'])
        pieces = []; cursor = 0
        for start, end, index, edit in group:
            if start > cursor: pieces.append(slice_path(path, cursor, start))
            adjustments = []
            new = replacement_path(edit['replacement'], edit.get('profile'), max_join_gap_m, adjustments)
            new = adjust_endpoints(new, points[start], points[end], max_join_gap_m, adjustments)
            pieces.append(new); cursor = end
            reports.append({'edit_index': index, 'leg': leg, 'from_point': start, 'to_point': end,
                            'join_adjustments': adjustments})
        if cursor < len(points)-1: pieces.append(slice_path(path, cursor, len(points)-1))
        result[leg]['paths'] = [merge_paths(pieces)]
    return result, sorted(reports, key=lambda row: row['edit_index'])


def replace_points(route, leg_index, start, end, replacement, profile=None, max_join_gap_m=0):
    return replace_batch(route, [{'leg': leg_index, 'from_point': start, 'to_point': end,
                                 'replacement': replacement, 'profile': profile}], max_join_gap_m)[0]
