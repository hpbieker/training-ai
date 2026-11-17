from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from activity_inspect import (timed_rows, covered_seconds, indoor_power_control,
    outdoor_pedaling_normalized, outdoor_pedaling_row, outdoor_vt1_pacing, rolling_time_over,
    rolling_power_by_time, rolling_bouts_over, indoor_vt1_quality,
    detect_indoor_vt1_power_segment, time_after_moving_seconds,
    best_continuous_vt1_block_for_duration, detect_traffic_stop_segments)


def ride(step):
    return timed_rows([{'time': str(t), 'watts': str(210 if t < 600 else 240 if t < 900 else 0),
                        'cadence': '90'} for t in range(0, 1200, step)])


class Vt1TimeTests(unittest.TestCase):
    def test_outdoor_pacing_requires_usable_power(self):
        for valid_samples, ignored, expected_pct, reason in (
            (0, False, 0, "no_valid_values"),
            (30, False, 50, "insufficient_time_coverage"),
            (60, True, 100, "source_ignored_power"),
            (60, False, 100, None),
        ):
            with self.subTest(valid_samples=valid_samples, ignored=ignored):
                rows = [{"time": i * 5, "watts": 200 if i < valid_samples else None}
                        for i in range(60)]
                result = outdoor_vt1_pacing(rows, vt1_watts=210, pauses=[],
                                            auto_triggered=True, ignore_power=ignored)
                self.assertEqual(result["power_coverage"]["valid_pct"], expected_pct)
                if reason:
                    self.assertIn(reason, result["power_coverage"]["reasons"])
                    self.assertEqual(result["assessment"]["verdict"], "power_pacing_unavailable")
                    self.assertNotIn("quality_scores", result)
                    self.assertNotIn("training_characterization", result)
                else:
                    self.assertEqual(result["assessment"]["verdict"], "controlled_outdoor_vt1")
                    self.assertEqual(result["quality_scores"]["execution_score"], 100)

    def test_complete_excerpt_cannot_grade_a_longer_ride(self):
        rows = [{"time": i, "watts": 200} for i in range(300)]
        result = outdoor_vt1_pacing(rows, vt1_watts=210, pauses=[], auto_triggered=True,
                                    activity_moving_seconds=1200)
        self.assertEqual(result["power_coverage"]["valid_pct"], 25)
        self.assertIn("incomplete_activity_coverage", result["power_coverage"]["reasons"])
        self.assertNotIn("quality_scores", result)

    def test_off_target_riding_has_no_stability_exposure(self):
        for watts, expected_minutes in ((150, 0), (None, None)):
            with self.subTest(watts=watts):
                rows = [{"time": t, "watts": watts, "heartrate": 120} for t in range(0, 1800, 5)]
                result = indoor_vt1_quality(rows, vt1_watts=215, pauses=[], auto_triggered=False)
                self.assertEqual(result["duration"]["session_moving_min"], 30)
                self.assertEqual(result["duration"]["vt1_stability_min"], expected_minutes)
                self.assertEqual(result["duration"]["session_minutes_near_working_power"], expected_minutes)
                self.assertEqual(result["drift"]["comparison"]["status"], "unavailable")

    def test_only_matching_work_intervals_contribute_to_work_metrics(self):
        rows = [{"time": t, "watts": 300 if 900 <= t < 1500 else 215,
                 "heartrate": 120 if t < 900 else 140} for t in range(0, 2400, 5)]
        blocks = [{"start_index": a, "end_index": b, "duration_seconds": (b-a)*5,
                   "summary": {"watts": {"avg": w}}}
                  for a, b, w in [(0, 180, 215), (180, 300, 300), (300, 480, 215)]]
        result = indoor_vt1_quality(rows, work_blocks=blocks, vt1_watts=215,
                                    pauses=[], auto_triggered=False)
        self.assertEqual(result["duration"]["session_moving_min"], 40)
        self.assertEqual(result["analysis_window"]["duration_min"], 30)
        self.assertEqual(result["duration"]["vt1_stability_min"], 30)
        self.assertEqual(result["power_control"]["avg_w"], 215)
        parts = result["work_interval_response"]
        self.assertEqual([(p["start_s"], p["duration_min"]) for p in parts], [(0, 15), (1500, 15)])
        for part in parts:
            self.assertEqual(part["minutes_near_working_power"], 15)
            response = part["response"]["comparison"]
            self.assertEqual(response["status"], "matched")
            self.assertGreaterEqual(response["early"]["start_s"], part["start_s"])
            self.assertLessEqual(response["late"]["end_s"], part["start_s"] + 900)

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

    def test_rolling_windows_require_full_uninterrupted_coverage(self):
        for seconds in (30, 60):
            for step in (1, 5, 10):
                rows = [{"time": t, "watts": 200 if t < seconds else 260}
                        for t in range(0, 2 * seconds, step)]
                rolled = rolling_power_by_time(rows, seconds, [])
                self.assertTrue(all(rolled[t] is None for t in range(0, seconds-step, step)))
                self.assertEqual(rolled[seconds-step], 200)
                self.assertAlmostEqual(rolled[seconds], 200 + 60*step/seconds)
                self.assertEqual(rolled[2*seconds-step], 260)

    def test_gap_pause_or_invalid_power_restarts_the_rolling_window(self):
        rows = [{"time": t, "watts": 240} for t in range(180)]
        for interrupted, pauses, restart in (
            ([row for row in rows if not 60 <= row["time"] < 90], [], 90),
            ([row for row in rows if row["time"] != 60], [], 61),
            ([dict(row, watts="nan") if row["time"] == 60 else row for row in rows], [], 61),
            (rows, [(60, 69)], 70),
        ):
            rolled = rolling_power_by_time(interrupted, 60, pauses)
            self.assertEqual(rolled[59], 240)
            self.assertIsNone(rolled[restart+58])
            self.assertEqual(rolled[restart+59], 240)
        short = outdoor_vt1_pacing(rows[:30], vt1_watts=240, pauses=[], auto_triggered=False)
        self.assertEqual(short["assessment"]["verdict"], "power_pacing_unavailable")
        self.assertNotIn("quality_scores", short)
        self.assertIsNone(rolling_time_over(rolling_power_by_time(rows[:30], 60, []),
                                            rows[:30], 230)["min"])

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
