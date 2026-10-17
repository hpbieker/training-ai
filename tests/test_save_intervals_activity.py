import importlib.util
import json
import hashlib
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

            manifest = root / "streams.json"
            manifest.write_text(json.dumps({"activity_id": "i123", "streams_file": str(streams_file),
                                           "sha256": hashlib.sha256(streams_file.read_bytes()).hexdigest()}))
            result = MODULE.save_activity_package(
                activity_json=activity_json,
                streams_manifest=manifest,
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
            manifest = root / "streams.json"
            manifest.write_text(json.dumps({"activity_id": "i123", "streams_file": "missing.csv", "sha256": "invalid"}))
            for activity in (
                {"start_date_local": "2026-08-17T10:00:00"},
                {"id": "i123", "start_date_local": "invalid"},
                {"id": "i123", "start_date_local": "2026-08-17T10:00:00"},
            ):
                activity_json.write_text(json.dumps(activity), encoding="utf-8")
                with self.assertRaises(ValueError):
                    MODULE.save_activity_package(
                        activity_json=activity_json,
                        streams_manifest=manifest,
                        output_dir=root / "intervals",
                    )

    def test_rejects_wrong_identity_or_changed_stream_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activity = root / "activity.json"
            activity.write_text(json.dumps({"id": "i123", "start_date_local": "2026-10-17"}))
            streams = root / "streams.csv"
            streams.write_text("time,watts\n0,200\n")
            manifest = root / "streams.json"
            digest = hashlib.sha256(streams.read_bytes()).hexdigest()
            for identity, checksum in [("i456", digest), ("i123", "changed")]:
                manifest.write_text(json.dumps({"activity_id": identity, "streams_file": str(streams), "sha256": checksum}))
                with self.subTest(identity=identity, checksum=checksum), self.assertRaises(ValueError):
                    MODULE.save_activity_package(activity_json=activity, streams_manifest=manifest, output_dir=root / "out")
                self.assertFalse((root / "out").exists())

    def test_rejects_conflicting_activity_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "activity.json"
            p.write_text(json.dumps({"activity_id": "i456", "activity": {"id": "i123"}}))
            with self.assertRaises(ValueError):
                MODULE.load_activity(p)


if __name__ == "__main__":
    unittest.main()
