import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "save_intervals_activity.py"
SPEC = importlib.util.spec_from_file_location("save_intervals_activity_under_test", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SaveIntervalsActivityTests(unittest.TestCase):
    def test_saves_mcp_envelope_and_streams_in_canonical_activity_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            activity_json = root / "activity-source.json"
            streams_file = root / "source-streams.csv"
            activity = {
                "id": "i123",
                "name": "Test ride",
                "start_date_local": "2026-08-17T10:00:00",
            }
            activity_json.write_text(
                json.dumps({"activity_id": "i123", "activity": activity}),
                encoding="utf-8",
            )
            streams_file.write_text("secs,watts\n0,200\n", encoding="utf-8")

            result = MODULE.save_activity_package(
                activity_json=activity_json,
                streams_file=streams_file,
                output_dir=root / "intervals",
            )

            self.assertEqual(result["activity_dir"].name, "2026-08-17_i123")
            self.assertEqual(
                json.loads(result["activity_metadata"].read_text(encoding="utf-8")),
                activity,
            )
            self.assertEqual(
                result["streams_csv"].read_text(encoding="utf-8"),
                "secs,watts\n0,200\n",
            )

    def test_rejects_missing_identity_date_or_streams(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            activity_json = root / "activity.json"
            missing_streams = root / "missing.csv"
            for activity in (
                {"start_date_local": "2026-08-17T10:00:00"},
                {"id": "i123", "start_date_local": "invalid"},
                {"id": "i123", "start_date_local": "2026-08-17T10:00:00"},
            ):
                activity_json.write_text(json.dumps(activity), encoding="utf-8")
                with self.assertRaises(ValueError):
                    MODULE.save_activity_package(
                        activity_json=activity_json,
                        streams_file=missing_streams,
                        output_dir=root / "intervals",
                    )


if __name__ == "__main__":
    unittest.main()
