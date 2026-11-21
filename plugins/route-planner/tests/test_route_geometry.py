import sys
import unittest
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
