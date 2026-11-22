import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from route_data import normalize_route
from route_planner_mcp import SHOW_ROUTE, show_route

LINE = {'type': 'LineString', 'coordinates': [[14, 58], [14.1, 58.1]]}

class RouteTests(unittest.TestCase):
    def test_geometry_is_only_in_map_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'route.geojson'
            path.write_text(json.dumps(LINE))
            result = show_route({'route_file': str(path)})
        summary = {'title': 'Route', 'point_count': 2, 'segment_count': 1}
        self.assertEqual(result.structuredContent, summary)
        self.assertEqual(json.loads(result.content[0].text), summary)
        self.assertEqual(result.meta['route']['geometry']['coordinates'], [LINE['coordinates']])

    def test_gpx_keeps_segment_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'route.gpx'
            path.write_text('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lon="14" lat="58"/><trkpt lon="15" lat="58"/></trkseg><trkseg><trkpt lon="16" lat="58"/><trkpt lon="17" lat="58"/></trkseg></trk></gpx>')
            route = normalize_route({'route_file': str(path)})
            self.assertEqual(len(route['geometry']['coordinates']), 2)
            path.write_text('<broken')
            with self.assertRaisesRegex(ValueError, 'Invalid GPX'):
                normalize_route({'route_file': str(path)})

    def test_rejects_bad_coordinates_and_conflicting_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'route.geojson'
            arguments = {'route_file': str(path)}
            for coordinate in ([float('nan'), 58], [True, 58], [14, 90], [181, 58]):
                path.write_text(json.dumps({'type': 'LineString', 'coordinates': [coordinate, [14, 58]]}))
                with self.subTest(coordinate=coordinate), self.assertRaises(ValueError):
                    normalize_route(arguments)
            path.write_text(json.dumps(LINE))
            with self.assertRaisesRegex(ValueError, 'HTTPS URL without credentials'):
                normalize_route({**arguments, 'source_url': 'https://user:password@example.com'})

        validate = Draft202012Validator(SHOW_ROUTE.inputSchema).is_valid
        route_id = {'route_id': 'a' * 32}
        self.assertTrue(validate(route_id))
        self.assertTrue(validate(arguments))
        for invalid in ({**route_id, **arguments}, {'geojson': LINE}, {**arguments, 'geojson': LINE}):
            with self.subTest(arguments=invalid):
                self.assertFalse(validate(invalid))

    def test_local_artifact_and_independent_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'route.json'
            path.write_text(json.dumps({'points':[{'lng':14,'lat':58},{'lng':15,'lat':59}]}))
            other = Path(tmp) / 'other.geojson'
            other.write_text(json.dumps(LINE))
            first = show_route({'route_file':str(path),'title':'First','distance_km':100})
            second = show_route({'route_file': str(other), 'title': 'Second'})
            self.assertEqual(first.meta['route']['title'], 'First')
            self.assertNotIn('distance_km', second.meta['route'])

if __name__ == '__main__':
    unittest.main()
