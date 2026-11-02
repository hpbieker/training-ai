import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from komoot_service import get_tour_waypoints
from komoot_mcp import KomootToolService, ToolFailure

class ToolTests(unittest.TestCase):
    def test_preserves_all_planning_points_including_duplicates(self):
        path = [{'location': {'lat':59.9,'lng':10.7},'index':i} for i in range(107)]
        with patch('komoot_service._get_json',return_value={'path':path}):
            r=get_tour_waypoints('123')
        self.assertEqual(r['count'],107)
        self.assertEqual([p['position'] for p in r['waypoints']], list(range(1,108)))
        self.assertEqual([p['index'] for p in r['waypoints']],list(range(107)))

    def test_comparison_requires_one_candidate_source(self):
        s=KomootToolService()
        for args in [{'tour':'123'}, {'tour':'123','other_tour':'456','coordinates':[{'lat':0,'lng':0}]*2}]:
            with self.assertRaises(ToolFailure): s.call_tool('compare_tours',args)

if __name__=='__main__': unittest.main()
