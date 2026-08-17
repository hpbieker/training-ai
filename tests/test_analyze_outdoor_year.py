from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_outdoor_year import activity_name_implies_threshold  # noqa: E402


class OutdoorActivityIntentTests(unittest.TestCase):
    def test_explicit_threshold_names_imply_threshold_intent(self):
        for name in ("VT2 3x12 min", "Terskelintervaller", "Threshold session"):
            with self.subTest(name=name):
                self.assertTrue(activity_name_implies_threshold(name))

    def test_route_and_terrain_names_do_not_imply_threshold_intent(self):
        for name in (
            "Tryvannstårnet",
            "Tryvannstårnet+Sørkedalen",
            "Klatring til Frognerseteren",
            "Climb day",
            "Bakkeøkt",
        ):
            with self.subTest(name=name):
                self.assertFalse(activity_name_implies_threshold(name))


if __name__ == "__main__":
    unittest.main()
