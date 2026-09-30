import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from route_data import normalize_route
from training_visuals_mcp import show_route

LINE = {'type': 'LineString', 'coordinates': [[14, 58], [14.1, 58.1]]}

class RouteTests(unittest.TestCase):
    def test_geometry_only_in_view_metadata(self):
        result = show_route({'geojson': LINE})
        self.assertNotIn('geometry', result.structuredContent)
        self.assertEqual(result.structuredContent['point_count'], 2)
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
        for coordinate in ([float('nan'), 58], [True, 58], [14, 90], [181, 58]):
            with self.subTest(coordinate=coordinate), self.assertRaises(ValueError):
                normalize_route({'geojson': {'type':'LineString','coordinates':[coordinate,[14,58]]}})
        with self.assertRaises(ValueError):
            normalize_route({'geojson': LINE, 'route_file':'/tmp/test.gpx'})
        with self.assertRaises(ValueError):
            normalize_route({'geojson': LINE, 'source_url':'https://user:password@example.com'})

    def test_local_artifact_and_independent_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'route.json'
            path.write_text(json.dumps({'points':[{'lng':14,'lat':58},{'lng':15,'lat':59}]}))
            first = show_route({'route_file':str(path),'title':'First','distance_km':100})
            second = show_route({'geojson':LINE,'title':'Second'})
            self.assertEqual(first.meta['route']['title'], 'First')
            self.assertNotIn('distance_km', second.meta['route'])

if __name__ == '__main__':
    unittest.main()
