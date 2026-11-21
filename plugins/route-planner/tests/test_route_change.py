import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import route_planner_mcp as planner


def brouter_payload(points):
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": points},
            "properties": {"total-time": 100, "cost": 100},
        }],
    }, "custom_123"


class RouteChangeTests(unittest.TestCase):
    def test_insert_waypoint_between_existing_waypoints(self):
        start, first, second, end = [[10, 60], [10.001, 60], [10.003, 60], [10.004, 60]]
        snapped = [10.002, 60.001]
        drop = {"lon": 10.002, "lat": 60.0013}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"ROUTE_PLANNER_ROUTES": directory}),
            patch.object(planner, "run_brouter", side_effect=[
                brouter_payload([start, first, second, end]),
                brouter_payload([start, first, snapped, second, end]),
            ]) as engine,
        ):
            saved = planner.plan_route({
                "start": {"lon": start[0], "lat": start[1]},
                "end": {"lon": end[0], "lat": end[1]},
                "waypoints": [{"lon": point[0], "lat": point[1]} for point in (first, second)],
            })
            first_id, second_id = [point["waypoint_id"] for point in saved["points"][1:-1]]
            change = {"route_id": saved["route_id"], "expected_revision": 1}
            result = planner.update_route({
                **change, "add_waypoint": {**drop, "after_waypoint_id": first_id, "snap_to_route": True},
            })
            self.assertEqual(result["revision"], 2)
            self.assertEqual(engine.call_args.args[0], [start, first, [drop["lon"], drop["lat"]], second, end])
            points = result["points"][1:-1]
            self.assertEqual(planner.load_route(saved["route_id"])["points"][1:-1], points)
            self.assertEqual([points[0]["waypoint_id"], points[2]["waypoint_id"]], [first_id, second_id])
            self.assertNotIn(points[1]["waypoint_id"], [first_id, second_id])
            self.assertEqual(points[1]["requested"], {"lon": snapped[0], "lat": snapped[1]})

    def test_drag_snap_accepts_nearby_road_and_saves_its_position(self):
        route = [[10, 60], [10.001, 60], [10.002, 60]]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"ROUTE_PLANNER_ROUTES": directory}),
            patch.object(planner, "run_brouter", return_value=brouter_payload(route)) as engine,
        ):
            saved = planner.plan_route({
                "start": {"lon": 10, "lat": 60},
                "end": {"lon": 10.002, "lat": 60},
                "waypoints": [{"lon": 10.001, "lat": 60}],
            })
            waypoint_id = saved["points"][1]["waypoint_id"]
            changes = {"route_id": saved["route_id"], "expected_revision": 1}
            drop = {"waypoint_id": waypoint_id, "lon": 10.001, "lat": 60.0003}
            with self.assertRaisesRegex(ValueError, "limit 15 m"):
                planner.update_route({**changes, "move_waypoint": drop})
            with self.assertRaisesRegex(ValueError, "limit 50 m"):
                planner.update_route({
                    **changes, "move_waypoint": {**drop, "lat": 60.0006, "snap_to_route": True},
                })

            updated = planner.update_route({
                **changes, "move_waypoint": {**drop, "snap_to_route": True},
            })
            self.assertEqual(updated["revision"], 2)
            point = planner.load_route(saved["route_id"])["points"][1]
            self.assertEqual(point["waypoint_id"], waypoint_id)
            self.assertEqual(point["requested"], {"lon": 10.001, "lat": 60})
            self.assertEqual(point["requested"], point["on_route"])
            with self.assertRaisesRegex(ValueError, "revision conflict"):
                planner.update_route({**changes, "end": {"lon": 10.002, "lat": 60}})
            self.assertEqual(planner.load_route(saved["route_id"])["revision"], 2)
            planner.update_route({**changes, "expected_revision": 2, "end": {"lon": 10.002, "lat": 60}})
            self.assertEqual(engine.call_args.args[0][1], route[1])
