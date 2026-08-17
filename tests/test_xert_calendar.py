import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "plugins" / "xert" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
SPEC = importlib.util.spec_from_file_location(
    "xert_calendar_under_test",
    SCRIPTS_DIR / "xert_calendar.py",
)
assert SPEC is not None and SPEC.loader is not None
CALENDAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALENDAR)


class CalendarEventTests(unittest.TestCase):
    def test_flattens_calendar_day_groups(self) -> None:
        source = {
            "activities": [
                [{"path": "one", "start_date_local": "2026-08-01T09:00:00"}],
                [{"path": "other", "start_date_local": "2026-08-02T09:00:00"}],
                [{"path": "two", "start_date_local": "2026-08-01T11:00:00"}],
            ]
        }
        with patch.object(CALENDAR, "_open_text", return_value=json.dumps(source)):
            result = CALENDAR.fetch_calendar_events_with_opener(object(), "2026-08-01")

        self.assertEqual(result["date"], "2026-08-01")
        self.assertEqual([event["path"] for event in result["events"]], ["one", "two"])

    def test_matches_equal_instants_across_timezones(self) -> None:
        expected = datetime.fromisoformat("2026-08-01T09:00:00+02:00")
        self.assertTrue(CALENDAR._same_instant("2026-08-01T07:00:00Z", expected))
        self.assertFalse(CALENDAR._same_instant("2026-08-01T07:00:01Z", expected))

    def test_event_lookup_uses_path(self) -> None:
        with patch.object(
            CALENDAR,
            "fetch_calendar_events_with_opener",
            return_value={
                "date": "2026-08-01",
                "events": [{"path": "wanted", "start_date_local": "2026-08-01T09:00:00"}],
            },
        ):
            result = CALENDAR.fetch_calendar_event_with_opener(
                object(), "2026-08-01", "wanted"
            )

        self.assertEqual(
            result,
            {"path": "wanted", "start_date_local": "2026-08-01T09:00:00"},
        )


if __name__ == "__main__":
    unittest.main()
