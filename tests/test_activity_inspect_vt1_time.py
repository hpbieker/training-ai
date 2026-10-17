from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from activity_inspect import (timed_rows, covered_seconds, indoor_power_control,
    outdoor_pedaling_normalized, outdoor_pedaling_row, rolling_time_over,
    rolling_power_by_time, rolling_bouts_over, indoor_vt1_quality,
    detect_indoor_vt1_power_segment, time_after_moving_seconds,
    best_continuous_vt1_block_for_duration, detect_traffic_stop_segments)


def ride(step):
    return timed_rows([{'time': str(t), 'watts': str(210 if t < 600 else 240 if t < 900 else 0),
                        'cadence': '90'} for t in range(0, 1200, step)])


class Vt1TimeTests(unittest.TestCase):
    def test_uniform_sample_rates_preserve_time_and_power_distribution(self):
        outputs = []
        for step in [1, 5, 10]:
            rows = ride(step)
            pedaling = [r for r in rows if outdoor_pedaling_row(r)]
            self.assertEqual(covered_seconds(rows), 1200)
            self.assertEqual(covered_seconds(pedaling), 900)
            summary = outdoor_pedaling_normalized(rows, pedaling, 210)
            self.assertEqual(summary['coasting_or_soft_pedaling_min'], 5)
            self.assertEqual(summary['pedaling_time_pct_of_moving'], 75)
            self.assertEqual(summary['pedaling_avg_w'], 220)
            outputs.append((summary, indoor_power_control(pedaling, 210)))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_irregular_sampling_and_filtered_rows_keep_source_weights(self):
        rows = timed_rows([{'time': str(t), 'watts': str(w)} for t, w in
                          [(0, 210), (1, 0), (6, 240), (11, 0), (16, 210)]])
        pedaling = [r for r in rows if outdoor_pedaling_row(r)]
        self.assertEqual(covered_seconds(rows), 21)
        self.assertEqual(covered_seconds(pedaling), 11)
        control = indoor_power_control(pedaling, 210)
        self.assertEqual(control['pct_above_vt1_plus_20w'], 45.5)
        series = {int(r['time']): float(r['watts']) for r in rows}
        self.assertEqual(rolling_time_over(series, pedaling, 230)['pct'], 45.5)

    def test_missing_time_is_not_work_and_splits_bouts(self):
        rows = timed_rows([{'time': str(t), 'watts': '240'}
                           for t in list(range(0, 60, 5)) + list(range(120, 180, 5))])
        self.assertEqual(covered_seconds(rows), 120)
        series = {int(r['time']): 240 for r in rows}
        self.assertEqual(rolling_bouts_over(series, rows, 230, []), [(0, 59), (120, 179)])
        self.assertIsNone(detect_indoor_vt1_power_segment(rows, rows, 240, min_duration_seconds=100))

    def test_block_search_and_stops_use_elapsed_time(self):
        for step in [1, 5]:
            rows = timed_rows([{'time': str(t), 'watts': '210'} for t in range(0, 1200, step)])
            rolled = rolling_power_by_time(rows, 60, [])
            result = best_continuous_vt1_block_for_duration(
                rows, moving_rows=rows, rolling_60=rolled, duration_seconds=600,
                step_seconds=60, vt1_watts=210)
            self.assertIsNotNone(result)
            stops = timed_rows([{'time': str(t), 'watts': '0', 'velocity_smooth': '0'}
                                for t in range(0, 30, step)])
            self.assertEqual(detect_traffic_stop_segments(stops, [])[0]['duration_s'], 30)

    def test_rolling_bouts_and_moving_duration_use_seconds(self):
        for step in [1, 5, 10]:
            rows = timed_rows([{'time': str(t), 'watts': '210'} for t in range(0, 1800, step)])
            rolled = rolling_power_by_time(rows, 60, [])
            self.assertEqual(rolled[120], 210)
            series = {int(r['time']): 240 for r in rows}
            self.assertEqual(rolling_time_over(series, rows, 230), {'min': 30, 'pct': 100})
            self.assertEqual(rolling_bouts_over(series, rows, 230, []), [(0, 1799)])
            self.assertEqual(time_after_moving_seconds(rows, 0, 600, []), 600)
            segment = detect_indoor_vt1_power_segment(rows, rows, 210)
            self.assertEqual(segment[1]['duration_min'], 30)
            result = indoor_vt1_quality(rows, vt1_watts=210, pauses=[], auto_triggered=False)
            self.assertEqual(result['power_control']['avg_w'], 210)


if __name__ == '__main__':
    unittest.main()
