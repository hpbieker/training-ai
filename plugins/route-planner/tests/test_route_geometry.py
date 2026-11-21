import sys
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import route_geometry as route

def payload(tags='highway=residential surface=asphalt'):
    return {'features': [{'geometry': {'type': 'LineString', 'coordinates': [[10, 60], [10.01, 60]]},
                          'properties': {'messages': [['WayTags'], [tags]]}}]}


class RouteGeometryTests(unittest.TestCase):
    def test_validates_geometry_and_endpoint_distance(self):
        p = payload()
        p['features'][0]['properties'] = {}
        self.assertEqual(route.validate_route(p, [10, 60], [10.01, 60], 100),
                         [[10, 60], [10.01, 60]])
        with self.assertRaises(ValueError):
            route.validate_route(p, [11, 60], [10.01, 60], 100)

    def test_coordinate_validation(self):
        for value in [(float('nan'), 10), (91, 10), (60, 181), (60, float('inf'))]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                route.coordinate(*value)
        self.assertEqual(route.coordinate(60, 10), [10, 60])

    def test_gpx_preserves_track_and_route_name(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'route.gpx'
            route.write_gpx(path, 'A & B', [[10,60,23], [10.01,60]])
            root = ET.parse(path).getroot()
            ns = {'g': 'http://www.topografix.com/GPX/1/1'}
            self.assertEqual(root.findtext('g:metadata/g:name', namespaces=ns), 'A & B')
            self.assertEqual(root.findtext('g:trk/g:name', namespaces=ns), 'A & B')
            points = root.findall('g:trk/g:trkseg/g:trkpt', ns)
            self.assertEqual(len(points), 2)
            self.assertEqual(points[1].get('lon'), '10.01')


if __name__ == '__main__':
    unittest.main()
