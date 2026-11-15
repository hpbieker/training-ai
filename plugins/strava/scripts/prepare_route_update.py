#!/usr/bin/env python3
"""Prepare a Strava geometry update locally; never build or save a route."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strava_mcp import UPDATE_ROUTE_PATCH
from route_editing import fingerprint, replace_points, replace_batch, elevation, decode_polyline
from jsonschema import validate


def geometry(value):
    if not isinstance(value, dict):
        raise ValueError('Expected an object containing elements and legs')
    patch = {key: copy.deepcopy(value[key]) for key in ('elements', 'legs') if key in value}
    if set(patch) != {'elements', 'legs'}:
        raise ValueError('Complete elements and legs are required; use save_full=true')
    for element in patch['elements']:
        element.setdefault('elementType', 'Waypoint')
    for index, leg in enumerate(patch['legs']):
        leg['startElement'] = index
    for leg in patch['legs']:
        if len(leg.get('paths', [])) != 1:
            raise ValueError('Select one path per leg; native paths can be alternatives')
        path = leg['paths'][0]
        points = decode_polyline(path['polyline']['data'])
        heights = [h for _, h in elevation(path)]
        path.setdefault('origin', dict(zip(('lat', 'lng'), points[0])))
        path.setdefault('target', dict(zip(('lat', 'lng'), points[-1])))
        path.setdefault('pathType', 'Normal')
        path.setdefault('directions', [])
        path.setdefault('gradeAdjustedLength', path['length'])
        path.setdefault('elevationGain', sum(max(0,b-a) for a,b in zip(heights, heights[1:])))
        path.setdefault('elevationLoss', sum(max(0,a-b) for a,b in zip(heights, heights[1:])))
        path.setdefault('surfaceTypeOffsets', [{'distanceOffset': 0, 'surfaceType': 'Unknown'}])
    validate(patch, UPDATE_ROUTE_PATCH)
    if len(patch['legs']) != len(patch['elements']) - 1:
        raise ValueError('Expected exactly one leg between each pair of elements')
    return patch


def prepare(source, replacement, start, end):
    route = source.get('route', source)
    route_id = route.get('id')
    if not isinstance(route_id, str) or not route_id.isascii() or not route_id.isdigit():
        raise ValueError('Route ID must be a decimal string')
    if 'route_id' in source and source['route_id'] != route_id:
        raise ValueError('Envelope and source route IDs differ')
    original = geometry(route)
    new = geometry(replacement)
    if not 0 <= start < end < len(original['elements']):
        raise ValueError('Require 0 <= from-element < to-element < element count')
    for actual, expected in ((new['elements'][0], original['elements'][start]),
                             (new['elements'][-1], original['elements'][end])):
        if actual['waypoint']['point'] != expected['waypoint']['point']:
            raise ValueError('Replacement endpoint coordinates must match selected waypoints exactly')
    patch = {
        'elements': original['elements'][:start + 1] + new['elements'][1:-1] + original['elements'][end:],
        'legs': original['legs'][:start] + new['legs'] + original['legs'][end:],
    }
    for index, leg in enumerate(patch['legs']):
        leg['startElement'] = index
    validate(patch, UPDATE_ROUTE_PATCH)
    report = {'route_id': route_id, 'from_element': start, 'to_element': end,
              'old_element_count': len(original['elements']), 'new_element_count': len(patch['elements']),
              'replaced_leg_count': end - start, 'replacement_leg_count': len(new['legs']),
              'outside_geometry_preserved': True,
              'limitations': ['Prepared locally; no network request or route write.',
                             'Built geometry must be inspected separately; this does not verify road choice.',
                             'Source may be stale; check current route before submitting.']}
    return {'route_id': route_id, 'patch': patch, 'base_geometry_sha256': fingerprint(route)}, report


def prepare_manifest(source, manifest, directory):
    if not isinstance(manifest, dict) or set(manifest)-{'max_join_gap_m', 'edits'}:
        raise ValueError('Manifest permits only max_join_gap_m and edits')
    rows = manifest.get('edits')
    if not isinstance(rows, list) or not rows: raise ValueError('edits must be a nonempty array')
    edits = []; inputs = []
    for row in rows:
        required = {'leg', 'from_point', 'to_point', 'replacement_file'}
        if not isinstance(row, dict) or not required.issubset(row) or set(row)-required-{'elevation_profile_file'}:
            raise ValueError('Each edit requires leg, from_point, to_point, replacement_file; optional elevation_profile_file')
        edit = {key: row[key] for key in ('leg', 'from_point', 'to_point')}
        files = {}
        for key, target in [('replacement_file', 'replacement'), ('elevation_profile_file', 'profile')]:
            if key not in row: continue
            if not isinstance(row[key], str) or not row[key]: raise ValueError('Manifest file paths must be nonempty strings')
            path = (directory/row[key]).resolve(); data = path.read_bytes()
            edit[target] = json.loads(data)
            files[key] = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()}
        edits.append(edit); inputs.append(files)
    route = source.get('route', source)
    tolerance = manifest.get('max_join_gap_m', 0)
    legs, reports = replace_batch(route, edits, tolerance)
    update, report = prepare(source, {'elements': route['elements'], 'legs': legs}, 0, len(route['elements'])-1)
    for row, files in zip(reports, inputs): row['inputs'] = files
    report.update(edits=reports, max_join_gap_m=tolerance, outside_geometry_preserved=True,
                  grade_adjusted_length='geometric length; not a Strava grade model')
    return update, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', type=Path, required=True, help='Full get_route save_full JSON file')
    parser.add_argument('--replacement', type=Path, help='Native geometry, buildRoute response, or GeoJSON LineString')
    parser.add_argument('--from-element', type=int, help='Zero-based source waypoint index, inclusive')
    parser.add_argument('--to-element', type=int, help='Zero-based source waypoint index, inclusive')
    parser.add_argument('--edits', type=Path, help='Batch manifest; relative file paths resolve from its directory')
    parser.add_argument('--max-join-gap-m', type=float, help='Explicit point-mode join tolerance; default zero')
    parser.add_argument('--leg', type=int, help='Zero-based source leg for a point-level replacement')
    parser.add_argument('--from-point', type=int, help='Inclusive zero-based polyline vertex within --leg')
    parser.add_argument('--to-point', type=int, help='Inclusive zero-based polyline vertex within --leg')
    parser.add_argument('--elevation-profile', type=Path, help='JSON [distance_m, elevation_m] pairs for 2D GeoJSON')
    parser.add_argument('--output-dir', type=Path, required=True, help='New private output directory')
    args = parser.parse_args()
    try:
        source_bytes = args.route.read_bytes()
        source = json.loads(source_bytes)
        if args.edits:
            if any(x is not None for x in (args.replacement, args.leg, args.from_point, args.to_point,
                                           args.from_element, args.to_element, args.elevation_profile, args.max_join_gap_m)):
                raise ValueError('--edits cannot be combined with single-edit options')
            replacement_bytes = args.edits.read_bytes()
            update, report = prepare_manifest(source, json.loads(replacement_bytes), args.edits.resolve().parent)
        else:
            if args.replacement is None: raise ValueError('Use --edits or --replacement')
            replacement_bytes = args.replacement.read_bytes()
            replacement = json.loads(replacement_bytes)
            point_mode = any(x is not None for x in (args.leg, args.from_point, args.to_point))
            if point_mode:
                if any(x is None for x in (args.leg, args.from_point, args.to_point)) or args.from_element is not None or args.to_element is not None:
                    raise ValueError('Use either leg/from-point/to-point or from-element/to-element')
                route = source.get('route', source)
                profile = json.loads(args.elevation_profile.read_text()) if args.elevation_profile else None
                legs, edits_report = replace_batch(route, [{'leg': args.leg, 'from_point': args.from_point, 'to_point': args.to_point, 'replacement': replacement, 'profile': profile}], args.max_join_gap_m or 0)
                update, report = prepare(source, {'elements': route['elements'][args.leg:args.leg+2],
                                                 'legs': [legs[args.leg]]}, args.leg, args.leg+1)
                report.update(edits=edits_report, max_join_gap_m=args.max_join_gap_m or 0, leg=args.leg, from_point=args.from_point, to_point=args.to_point,
                              prefix_preserved_exactly=True, suffix_preserved_exactly=True,
                              grade_adjusted_length='geometric length; not a Strava grade model')
            else:
                if args.from_element is None or args.to_element is None or args.elevation_profile or args.max_join_gap_m is not None:
                    raise ValueError('Native replacement needs from-element/to-element; elevation-profile is only for point mode')
                update, report = prepare(source, replacement, args.from_element, args.to_element)
        report['source_sha256'] = hashlib.sha256(source_bytes).hexdigest()
        report['manifest_sha256' if args.edits else 'replacement_sha256'] = hashlib.sha256(replacement_bytes).hexdigest()
        args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        for name, value in (('update.json', update), ('report.json', report)):
            path = args.output_dir / name
            with path.open('x', encoding='utf-8') as file:
                os.chmod(path, 0o600)
                json.dump(value, file, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        result={'route_id': update['route_id'], 'update_file': str((args.output_dir/'update.json').resolve()),
                'report_file': str((args.output_dir/'report.json').resolve()),
                'new_element_count': report['new_element_count']}
        print(json.dumps(result))

    except Exception as exc:
        parser.exit(1, f'prepare-update: {exc}\n')


if __name__ == '__main__':
    main()
