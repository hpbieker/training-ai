from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugins/strava'))
from route_geometry import compare_lines, compare_route_geometry


class GeometryVerificationTests(unittest.TestCase):
    def test_collinear_simplification(self):
        a=[(60,10),(60,10.0005),(60,10.001)]
        self.assertEqual(compare_lines(a,[a[0],a[-1]])['status'],'equivalent_within_tolerance')
    def test_shifted_parallel_road(self):
        a=[(60,10),(60,10.001)]
        b=[(60.0001,10),(60.0001,10.001)]
        r=compare_lines(a,b)
        self.assertEqual(r['status'],'changed');self.assertIn('deviation',r)
    def test_reversed_order_not_equivalent(self):
        a=[(60,10),(60,10.001)]
        self.assertNotIn(compare_lines(a,a[::-1])['status'],['exact','equivalent_within_tolerance'])
    def test_extra_roundabout_lap_not_equivalent(self):
        a=[(60,10),(60,10.001),(60.001,10.001),(60.001,10),(60,10),(60,9.999)]
        b=a[:5]+a[1:]
        self.assertNotIn(compare_lines(a,b)['status'],['exact','equivalent_within_tolerance'])
    def test_same_places_different_order_not_equivalent(self):
        a=[(60,10),(60,10.001),(60,10),(60.001,10),(60,10)]
        b=[a[0],a[3],a[0],a[1],a[0]]
        self.assertNotIn(compare_lines(a,b)['status'],['exact','equivalent_within_tolerance'])
    def test_bad_geometry_unresolved(self):
        r=compare_route_geometry({'legs':[{'paths':[{'polyline':{'encoding':'Google','data':'?'}}]}]}, {'legs':[{'paths':[{'polyline':{'encoding':'Google','data':'bad'}}]}]})
        self.assertEqual(r['status'],'unresolved')
    def test_work_limit(self):
        from unittest.mock import patch
        with patch('route_geometry.MAX_POINTS',10):
            r=compare_lines([(60,10),(60,10.001)],[(60,10),(60,10.0005),(60,10.001)])
        self.assertEqual(r['status'],'unresolved')

if __name__=='__main__':unittest.main()
