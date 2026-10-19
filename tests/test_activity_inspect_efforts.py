import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from activity_inspect import rolling_best


class EffortWindowsTests(unittest.TestCase):
    def test_does_not_bridge_paused_recording(self):
        rows = [{'time': t, 'watts': 400} for t in list(range(180)) + list(range(3600, 3780))]
        self.assertIsNone(rolling_best(rows, 'watts', 300, digits=0))

    def test_does_not_stitch_missing_measurements(self):
        rows = [{'time': t, 'watts': 300 if t != 150 else None} for t in range(301)]
        self.assertIsNone(rolling_best(rows, 'watts', 300, digits=0))

    def test_regular_and_two_second_sampling_have_same_duration_and_mean(self):
        for step in (1, 2):
            rows = [{'time': t, 'watts': 200} for t in range(0, 600, step)]
            result = rolling_best(rows, 'watts', 300, digits=0)
            self.assertEqual(result['avg'], 200)
            self.assertEqual(result['end_s_exclusive'] - result['start_s'], 300)

    def test_time_weights_irregular_sampling(self):
        rows = [{'time': t, 'watts': p} for t, p in [(0, 100), (1, 300), (4, 100), (5, 100)]]
        result = rolling_best(rows, 'watts', 4, digits=0)
        self.assertEqual(result['avg'], 250)

    def test_nonmonotonic_clock_is_unavailable(self):
        self.assertIsNone(rolling_best([{'time': t, 'watts': 100} for t in [0, 1, 1]], 'watts', 2, digits=0))


if __name__ == '__main__':
    unittest.main()
