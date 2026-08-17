import argparse
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from activity_inspect_pipeline import (
    build_inspect_args,
    parse_analysis_options_json,
    source_file_metadata,
)


class ActivityInspectPipelineArgumentsTests(unittest.TestCase):
    def test_explicit_analysis_options_are_forwarded(self):
        options = parse_analysis_options_json(
            json.dumps(
                {
                    "max_gap": "30s",
                    "auto_blocks": True,
                    "auto_min_power": 140,
                    "auto_min_block": "10m",
                    "steady_vt1": True,
                    "no_auto_outdoor_vt1": True,
                    "fields": "time,watts,heartrate",
                    "include_intervals": False,
                    "garmin_json": "/tmp/garmin-activity.json",
                }
            )
        )

        inspect_args = build_inspect_args(options)

        self.assertIn("--auto-blocks", inspect_args)
        self.assertEqual(
            inspect_args[inspect_args.index("--auto-min-block") + 1],
            "10m",
        )
        self.assertIn("--steady-vt1", inspect_args)
        self.assertIn("--no-auto-outdoor-vt1", inspect_args)
        self.assertIn("--no-intervals", inspect_args)
        self.assertEqual(
            inspect_args[inspect_args.index("--garmin-json") + 1],
            "/tmp/garmin-activity.json",
        )

    def test_invalid_analysis_options_are_rejected(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "unsupported"):
            parse_analysis_options_json('{"raw_args":[]}')
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "must be boolean"):
            parse_analysis_options_json('{"auto_blocks":"yes"}')

    def test_garmin_input_can_be_tracked_as_a_cache_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "activity.json").write_text("{}", encoding="utf-8")
            (root / "streams.csv").write_text("time,watts\n0,100\n", encoding="utf-8")
            garmin = root / "garmin.json"
            garmin.write_text('{"metrics_summary":{}}', encoding="utf-8")

            sources = source_file_metadata(root)
            sources["garmin_json"] = {
                "path": str(garmin),
                "mtime_ns": garmin.stat().st_mtime_ns,
                "size": garmin.stat().st_size,
            }

            self.assertEqual(sources["garmin_json"]["path"], str(garmin))


if __name__ == "__main__":
    unittest.main()
