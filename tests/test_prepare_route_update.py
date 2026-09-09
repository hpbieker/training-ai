import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('prepare_route_update', Path(__file__).resolve().parents[1]/'plugins/strava/scripts/prepare_route_update.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def element(x):
    return {'waypoint': {'point': {'lat': 59, 'lng': x}, 'metadata': {'name': str(x)}}}


def leg(label):
    return {'paths': [{'polyline': {'encoding': 'Google', 'data': '??AA'}, 'custom': label, 'length': 1.5, 'elevation': {'encoding': 'DrewsBadIdea', 'data': '??]?' }}]}


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.route = {'id': '3532440438889330932', 'title': 'Keep',
                      'elements': [element(x) for x in range(5)], 'legs': [leg(str(x)) for x in range(4)]}
        self.replacement = {'elements': [element(1), element(1.5), element(2), element(3)],
                            'legs': [leg('a'), leg('b'), leg('c')]}

    def test_splice_preserves_other_data_and_renumbers(self):
        before = copy.deepcopy(self.route)
        update, report = module.prepare({'route_id': self.route['id'], 'route': self.route}, self.replacement, 1, 3)
        patch = update['patch']
        self.assertEqual([e['waypoint']['point']['lng'] for e in patch['elements']], [0, 1, 1.5, 2, 3, 4])
        self.assertEqual([l['paths'][0]['custom'] for l in patch['legs']], ['0', 'a', 'b', 'c', '3'])
        self.assertEqual([l['startElement'] for l in patch['legs']], list(range(5)))
        self.assertEqual(self.route, before)
        self.assertEqual(set(patch), {'elements', 'legs'})
        self.assertNotIn('confirm', update)
        self.assertTrue(report['outside_geometry_preserved'])

    def test_endpoints_must_match_selected_occurrence(self):
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            module.prepare(self.route, self.replacement, 0, 3)

    def test_compact_route_rejected(self):
        with self.assertRaisesRegex(ValueError, 'save_full'):
            module.prepare({'id': '12'}, self.replacement, 0, 1)

    def test_leg_count_and_id_and_selection(self):
        bad = copy.deepcopy(self.replacement); bad['legs'].pop()
        with self.assertRaisesRegex(ValueError, 'one leg'):
            module.prepare(self.route, bad, 1, 3)
        with self.assertRaises(ValueError):
            module.prepare({'route_id': '99', 'route': self.route}, self.replacement, 1, 3)
        for start, end in [(-1, 3), (3, 1), (1, 5)]:
            with self.assertRaises(ValueError):
                module.prepare(self.route, self.replacement, start, end)


if __name__ == '__main__':
    unittest.main()
