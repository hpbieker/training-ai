import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "inspect_gpx.py"
SPEC = importlib.util.spec_from_file_location("inspect_gpx", SCRIPT)
inspect_gpx = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(inspect_gpx)


def write_gpx(body: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".gpx", delete=False)
    handle.write(body)
    handle.close()
    return Path(handle.name)


class InspectGpxTests(unittest.TestCase):
    def test_namespaced_track_and_round_trip(self):
        path = write_gpx(
            """<?xml version="1.0"?>
            <gpx xmlns="http://www.topografix.com/GPX/1/1">
              <metadata><name>Testtur</name></metadata>
              <trk><type>racebike</type><trkseg>
                <trkpt lat="60.0000" lon="10.0000"><ele>100</ele></trkpt>
                <trkpt lat="60.0000" lon="10.0100"><ele>120</ele></trkpt>
                <trkpt lat="60.0000" lon="10.0000"><ele>100</ele></trkpt>
              </trkseg></trk>
            </gpx>"""
        )
        result = inspect_gpx.inspect_gpx(path)
        self.assertEqual(result["name"], "Testtur")
        self.assertEqual(result["activity_type"], "racebike")
        self.assertTrue(result["is_round_trip"])
        self.assertGreater(result["distance_km"], 1)

    def test_route_points_without_elevation(self):
        path = write_gpx(
            """<gpx><rte><name>Flat</name>
              <rtept lat="60.0" lon="10.0"/>
              <rtept lat="60.0" lon="10.01"/>
            </rte></gpx>"""
        )
        result = inspect_gpx.inspect_gpx(path)
        self.assertIsNone(result["elevation_gain_m"])
        self.assertEqual(result["major_climbs"], [])
        self.assertFalse(result["is_round_trip"])

    def test_separate_track_segments_are_not_connected(self):
        path = write_gpx(
            """<gpx><trk>
              <trkseg>
                <trkpt lat="60.0" lon="10.0"/><trkpt lat="60.0" lon="10.01"/>
              </trkseg>
              <trkseg>
                <trkpt lat="61.0" lon="11.0"/><trkpt lat="61.0" lon="11.01"/>
              </trkseg>
            </trk></gpx>"""
        )
        result = inspect_gpx.inspect_gpx(path)
        self.assertEqual(result["track_segment_count"], 2)
        self.assertLess(result["distance_km"], 2)

    def test_elevation_hysteresis_ignores_small_noise(self):
        profile = [(index * 25.0, 100 + (1 if index % 2 else 0)) for index in range(20)]
        self.assertEqual(inspect_gpx.elevation_gain(profile), 0)

    def test_significant_climb_is_reported(self):
        profile = [(index * 25.0, 100 + index * 2.0) for index in range(21)]
        climbs, descents = inspect_gpx.terrain_sections(profile)
        self.assertEqual(len(climbs), 1)
        self.assertEqual(climbs[0]["length_km"], 0.5)
        self.assertEqual(climbs[0]["elevation_change_m"], 40)
        self.assertEqual(descents, [])


if __name__ == "__main__":
    unittest.main()
