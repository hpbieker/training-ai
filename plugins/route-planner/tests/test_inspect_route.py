import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from route_planner_mcp import inspect_route


class InspectionRangeTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = str(Path(directory) / "route.geojson")
        points = [[10, 60], [10.001, 60], [10.002, 60], [10.001, 60], [10, 60]]
        tags = ("highway=residential surface=asphalt name=Test Road ref=165", "highway=cycleway surface=gravel")
        messages = [["Longitude", "Latitude", "Distance", "WayTags"]]
        for index, point in enumerate(points[1:]):
            messages.append([round(point[0] * 1e6), 60_000_000, 56, tags[index // 2]])
        Path(self.path).write_text(json.dumps({"features": [{
            "geometry": {"type": "LineString", "coordinates": points},
            "properties": {"messages": messages},
        }]}))
        self.ids = [str(i) * 32 for i in range(1, 4)]
        self.saved = {
            "route_id": "0" * 32,
            "revision": 1,
            "geojson_file": self.path,
            "points": [{}, *[
                {"waypoint_id": key, "on_route": {"lon": point[0], "lat": point[1]}}
                for key, point in zip(self.ids, points[1:-1])
            ], {}],
        }

    def test_distance_range_clips_sections_and_prorates_totals(self):
        full = inspect_route({"route_file": self.path})
        result = inspect_route({"route_file": self.path,
                                "distance_range": {"from_km": 0.100, "to_km": 0.150}})
        self.assertEqual(result.keys(), full.keys())
        self.assertEqual(full["distance_by_tag_m"]["surface"], {"asphalt": 112.0, "gravel": 112.0})
        self.assertEqual(result["distance_by_tag_m"]["surface"], {"asphalt": 11.3, "gravel": 39.1})
        self.assertEqual([section["surface"] for section in result["sections"]], ["asphalt", "gravel"])
        first, last = result["sections"]
        self.assertEqual(first["start_km"], 0.100)
        self.assertEqual(last["end_km"], 0.150)
        self.assertTrue(10.001 < first["start"]["lon"] < 10.002)
        self.assertTrue(10.001 < last["end"]["lon"] < 10.002)

    def test_waypoint_range_uses_the_requested_passage(self):
        with patch("route_planner_mcp.load_route", return_value=self.saved):
            result = inspect_route({
                "route_id": self.saved["route_id"],
                "waypoint_range": {"from_waypoint_id": self.ids[1], "to_waypoint_id": self.ids[2]},
            })
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["distance_by_tag_m"]["surface"], {"gravel": 56.0})
        section, = result["sections"]
        self.assertEqual(section["start"]["lon"], 10.002)
        self.assertEqual(section["end"]["lon"], 10.001)
        self.assertEqual(section["start_km"], 0.1112)
        self.assertEqual(section["end_km"], 0.1668)

    def test_invalid_filters_fail(self):
        distance_range = {"from_km": 0.10, "to_km": 0.05}
        waypoint_range = {"from_waypoint_id": self.ids[2], "to_waypoint_id": self.ids[1]}
        with self.assertRaisesRegex(ValueError, "increasing range"):
            inspect_route({"route_file": self.path, "distance_range": distance_range})
        with self.assertRaisesRegex(ValueError, "Use route_id"):
            inspect_route({"route_file": self.path, "waypoint_range": waypoint_range})
        with self.assertRaisesRegex(ValueError, "either"):
            inspect_route({"route_file": self.path, "distance_range": distance_range,
                           "waypoint_range": waypoint_range})
        with patch("route_planner_mcp.load_route", return_value=self.saved):
            with self.assertRaisesRegex(ValueError, "travel order"):
                inspect_route({"route_id": self.saved["route_id"], "waypoint_range": waypoint_range})
