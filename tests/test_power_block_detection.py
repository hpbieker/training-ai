import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analysis import detect_power_blocks, detect_stable_power_blocks, summarize_block


class PowerBlockDetectionTests(unittest.TestCase):
    def test_cli_finds_ten_minutes_at_each_recording_rate(self):
        # Include a sample at the transition so the full recording defines the
        # final work sample's width, even when the last few intervals vary.
        irregular = [t + offset for t in range(0, 600, 10) for offset in (0, 1, 3)]
        for times in (list(range(600)), list(range(0, 600, 5)), irregular):
            with self.subTest(samples=len(times)), TemporaryDirectory() as directory:
                path = Path(directory)
                (path / "activity.json").write_text('{"type": "VirtualRide"}')
                (path / "streams.csv").write_text("time,watts\n" + "".join(
                    f"{t},300\n" for t in times) + "600,\n")
                result = json.loads(subprocess.check_output([
                    sys.executable, "-B", str(ROOT / "scripts/activity_inspect.py"),
                    directory, "--auto-blocks", "--target", "300", "--compact", "--stdout",
                ]))
                for key in ("auto_power_blocks", "detected_power_blocks"):
                    block, = result[key]
                    self.assertEqual(block["start_time"], 0)
                    self.assertEqual(block["duration_minutes"], 10)

    def test_target_and_threshold_bridge_only_allowed_elapsed_gap(self):
        for criteria in ({"target": 300}, {"threshold": 290}):
            for gap, lengths in [(20, [220]), (25, [100, 100])]:
                with self.subTest(criteria=criteria, gap=gap):
                    rows = [dict(time=t, watts=150 if 100 <= t < 100 + gap else 300)
                            for t in range(0, 200 + gap, 5)]
                    blocks = detect_power_blocks(rows, **criteria, min_seconds=100,
                                                 max_gap_seconds=20, smoothing_seconds=1)
                    self.assertEqual([b.detection["duration_seconds"] for b in blocks], lengths)

    def test_recording_gap_breaks_both_detectors_and_invalid_clock_has_no_blocks(self):
        times = [*range(0, 300, 5), *range(330, 630, 5)]
        rows = [dict(time=t, watts=300) for t in times]
        for detector, options in [(detect_power_blocks, {"target": 300}),
                                  (detect_stable_power_blocks, {})]:
            with self.subTest(detector=detector.__name__):
                self.assertEqual(detector(rows, min_seconds=480, **options), [])
                blocks = detector(rows, min_seconds=300, max_gap_seconds=60, **options)
                self.assertEqual([(b.start_index, b.end_index) for b in blocks], [(0, 60), (60, 120)])
                self.assertEqual(detector([rows[0], rows[0]], min_seconds=1, **options), [])

    def test_smoothing_clips_the_oldest_sample_to_the_time_window(self):
        rows = [dict(time=t, watts=p) for t, p in [(0, 100), (4, 300), (6, 300), (11, 300)]]
        # At t=6, the last five seconds averaged (3*100 + 2*300)/5 = 180 W.
        block, = detect_power_blocks(rows, threshold=190, min_seconds=1, smoothing_seconds=5)
        self.assertEqual(block.start_index, 2)

    def test_smoothing_restarts_after_recording_hole_or_missing_power(self):
        for restart, separator in [(25, []), (11, [dict(time=10, watts=None)])]:
            with self.subTest(restart=restart):
                rows = ([dict(time=t, watts=400) for t in range(10)] + separator
                        + [dict(time=t, watts=100) for t in range(restart, restart + 10)])
                block, = detect_power_blocks(rows, threshold=300, min_seconds=10,
                                             max_gap_seconds=60, smoothing_seconds=30)
                self.assertEqual((block.start_index, block.end_index), (0, 10))

    def test_candidate_ranking_and_stability_are_time_weighted(self):
        rows = ([dict(time=t, watts=300) for t in range(0, 600, 5)]
                + [dict(time=t, watts=200) for t in range(600, 1000)])
        block, = detect_stable_power_blocks(rows, min_seconds=120, smoothing_seconds=0, max_targets=1)
        self.assertEqual(block.detection["auto_target"], 300)
        self.assertEqual(block.detection["duration_seconds"], 600)

        rows = ([dict(time=t, watts=300) for t in range(0, 250, 5)]
                + [dict(time=t, watts=350) for t in range(250, 350)]
                + [dict(time=t, watts=300) for t in range(350, 600, 5)]
                + [dict(time=600, watts=0)])
        block, = detect_stable_power_blocks(rows, min_seconds=400, smoothing_seconds=0,
                                            max_gap_seconds=100, max_power_stddev=22)
        summary = summarize_block(rows, start_index=block.start_index, end_index=block.end_index,
                                  label=block.label, detection=block.detection)
        self.assertEqual(summary["duration_seconds"], 600)
