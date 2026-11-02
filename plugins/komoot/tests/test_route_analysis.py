import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from route_analysis import compare_routes, inspect_route

A = {'lat': 59.9, 'lng': 10.7}
B = {'lat': 59.91, 'lng': 10.7}
C = {'lat': 59.91, 'lng': 10.72}

class RouteAnalysisTests(unittest.TestCase):
    def test_shortcut_detected_in_both_directions(self):
        r = compare_routes([A,B,C], [A,C], sample_spacing_m=25)
        self.assertGreater(r['reference_to_candidate']['max_sampled_distance_m'], 400)
        self.assertGreater(r['candidate_to_reference']['max_sampled_distance_m'], 200)
        self.assertLess(r['length_difference_m'], 0)
        self.assertTrue(r['reference_to_candidate']['deviations'])

    def test_reversed_route_spatially_matches(self):
        r = compare_routes([A,B,C], [C,B,A])
        self.assertEqual(r['reference_to_candidate']['samples_outside_tolerance'], 0)
        self.assertIn('ignores traversal order', r['method'])

    def test_repeated_points_and_invalid_extent(self):
        r = compare_routes([A,A,B], [A,B])
        self.assertEqual(r['reference_to_candidate']['max_sampled_distance_m'], 0)
        with self.assertRaises(ValueError):
            compare_routes([A,B], [A,{'lat':0,'lng':0}])

    def test_inspection_chainage_and_warning_positions(self):
        row = {'from': 1, 'to': 2, 'element':'wt#cycleway'}
        route = {'_embedded': {'coordinates': {'items':[A,B,C]},
                 'way_types': {'items':[row]}, 'surfaces': {'items':[]}},
                 'tour_information': [{'type':'BICYCLE_DISMOUNT','segments':[{'from':1,'to':2}]}]}
        r = inspect_route(route)
        warning = r['warnings'][0]
        self.assertEqual(warning['start'], B)
        self.assertGreater(warning['start_m'], 1000)
        self.assertAlmostEqual(warning['length_m'], r['way_types']['totals_m']['wt#cycleway'])
        route['tour_information'][0]['segments'][0]['to'] = 3
        with self.assertRaises(ValueError): inspect_route(route)

if __name__ == '__main__': unittest.main()
