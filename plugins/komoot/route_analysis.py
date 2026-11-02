"""Service-independent route inspection and sampled spatial comparison.

Coordinates are dictionaries with lat/lng in degrees; distances are metres.
No API, authentication or provider-specific imports.
"""
import math


def positions(points):
    if not isinstance(points, list) or not 2 <= len(points) <= 10000:
        raise ValueError('A route must contain 2–10000 coordinate objects')
    result = []
    for p in points:
        lat, lng = p['lat'], p['lng']
        if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError('Invalid latitude/longitude')
        result.append({'lat': lat, 'lng': lng})
    return result


def distance(a, b):
    lat1, lat2 = map(math.radians, (a['lat'], b['lat']))
    dlat = lat2-lat1
    dlng = math.radians(b['lng']-a['lng'])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
    return 6371008.8*2*math.asin(math.sqrt(min(1, h)))


def chainage(points):
    out = [0.0]
    for a, b in zip(points, points[1:]):
        out.append(out[-1]+distance(a, b))
    return out


def indexed_segment(segment, points, distances):
    a, b = segment.get('from'), segment.get('to')
    if not isinstance(a, int) or not isinstance(b, int) or not 0 <= a <= b < len(points):
        raise ValueError('Invalid route segment indices')
    return {'from_index': a, 'to_index': b, 'start_m': round(distances[a], 1),
            'end_m': round(distances[b], 1), 'length_m': round(distances[b]-distances[a], 1),
            'start': points[a], 'end': points[b]}


def inspect_route(route):
    embedded = route['_embedded']
    points = positions(embedded['coordinates']['items'])
    distances = chainage(points)
    groups = {}
    for kind in ('way_types', 'surfaces'):
        segments = []
        totals = {}
        for row in embedded[kind]['items']:
            segment = {'type': row['element'], **indexed_segment(row, points, distances)}
            segments.append(segment)
            totals[row['element']] = totals.get(row['element'], 0)+segment['length_m']
        groups[kind] = {'totals_m': {k: round(v, 1) for k, v in totals.items()}, 'segments': segments}
    warnings = []
    for warning in route.get('tour_information', []):
        for row in warning.get('segments', []):
            warnings.append({'type': warning['type'], **indexed_segment(row, points, distances)})
    return {'name': route.get('name'), 'geometry_distance_m': round(distances[-1], 1),
            'komoot_distance_m': route.get('distance'), 'distance_method': 'cumulative haversine; approximate',
            'warnings': warnings, **groups}


def compare_routes(reference, candidate, tolerance_m=25, sample_spacing_m=100):
    """Bidirectional sampled distance to polyline segments, without order matching.

    Regular arc-length samples include both endpoints. Deviations shorter than
    the sampling interval may be missed. Local equirectangular projection is
    bounded to 3 degrees and latitudes below 80 degrees. Work is capped.
    """
    reference, candidate = positions(reference), positions(candidate)
    if not 1 <= tolerance_m <= 1000 or not 10 <= sample_spacing_m <= 1000:
        raise ValueError('Invalid tolerance or sampling interval')
    origin = reference[0]
    lat0, lng0 = origin['lat'], origin['lng']
    scale = math.cos(math.radians(lat0))
    def project(line):
        if any(abs(p['lat']) >= 80 or abs(p['lat']-lat0)>3 or abs(p['lng']-lng0)>3 for p in line):
            raise ValueError('Comparison supports local routes within 3 degrees and below 80 degrees latitude')
        return [((p['lng']-lng0)*111195.08*scale, (p['lat']-lat0)*111195.08) for p in line]
    a, b = project(reference), project(candidate)
    def samples(line):
        out = [(0.0, line[0])]; total = 0.0; next_at = sample_spacing_m
        for p, q in zip(line, line[1:]):
            length = math.dist(p, q)
            while length and next_at <= total+length:
                t = (next_at-total)/length
                out.append((next_at, (p[0]+t*(q[0]-p[0]), p[1]+t*(q[1]-p[1]))))
                next_at += sample_spacing_m
                if len(out)>10000: raise ValueError('Sampling limit exceeded')
            total += length
        if out[-1][0] < total: out.append((total, line[-1]))
        return out, total
    sa, la = samples(a); sb, lb = samples(b)
    if len(sa)*(len(b)-1)+len(sb)*(len(a)-1)>20000000:
        raise ValueError('Comparison work limit exceeded; increase sample_spacing_m')
    def directed(sampled, other):
        intervals = []; active = None; worst = 0.0; outside = 0
        for at, p in sampled:
            nearest = math.inf
            for q, r in zip(other, other[1:]):
                dx, dy = r[0]-q[0], r[1]-q[1]; norm = dx*dx+dy*dy
                t = max(0, min(1, ((p[0]-q[0])*dx+(p[1]-q[1])*dy)/norm)) if norm else 0
                gap = math.hypot(p[0]-q[0]-t*dx, p[1]-q[1]-t*dy)
                nearest = min(nearest, gap)
            worst = max(worst, nearest)
            if nearest > tolerance_m:
                outside += 1
                if active is None:
                    active = {'first_sample_m': round(at, 1), 'last_sample_m': round(at, 1), 'start': {'lat': lat0+p[1]/111195.08, 'lng': lng0+p[0]/(111195.08*scale)}, 'max_distance_m': 0.0}; intervals.append(active)
                active['last_sample_m'] = round(at, 1)
                active['end'] = {'lat': lat0+p[1]/111195.08, 'lng': lng0+p[0]/(111195.08*scale)}
                active['max_distance_m'] = round(max(active['max_distance_m'], nearest), 1)
            else: active = None
        return {'max_sampled_distance_m': round(worst, 1), 'samples_outside_tolerance': outside, 'sample_count': len(sampled), 'deviations': intervals}
    return {'method': 'bidirectional sampled point-to-segment distance; ignores traversal order',
            'tolerance_m': tolerance_m, 'sample_spacing_m': sample_spacing_m,
            'reference_length_m': round(la, 1), 'candidate_length_m': round(lb, 1),
            'length_difference_m': round(lb-la, 1),
            'reference_to_candidate': directed(sa, b), 'candidate_to_reference': directed(sb, a)}
