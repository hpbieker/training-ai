import argparse
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1] / "plugins" / "intervals-icu" / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))
SPEC = importlib.util.spec_from_file_location(
    "intervals_icu_cli_under_test",
    SCRIPTS_DIR / "intervals_icu_cli.py",
)
assert SPEC is not None and SPEC.loader is not None
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class SearchHelpersTests(unittest.TestCase):
    def test_date_filter_only_filters_intervals_search_results(self) -> None:
        activities = [
            {"id": "i1", "start_date_local": "2025-12-31T12:00:00"},
            {"id": "i2", "start_date_local": "2026-01-01T12:00:00"},
            {"id": "i3", "start_date_local": "2026-07-22T12:00:00Z"},
            {"id": "i4", "start_date_local": "2026-07-23T12:00:00"},
            {"id": "i5", "start_date_local": "2026-07-22T12:00:00Z"},
        ]

        matches = CLI._filter_activity_dates(
            activities,
            since=date(2026, 1, 1),
            until=date(2026, 7, 22),
        )

        self.assertEqual([activity["id"] for activity in matches], ["i2", "i3", "i5"])

    def test_positive_int_rejects_zero_and_negative_values(self) -> None:
        self.assertEqual(CLI._positive_int("3"), 3)
        for value in ("0", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    CLI._positive_int(value)

    def test_iso_date_returns_date_and_rejects_invalid_values(self) -> None:
        self.assertEqual(CLI._iso_date("2026-07-22"), date(2026, 7, 22))
        for value in ("bad-date", "2026-02-30", "22-07-2026"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    argparse.ArgumentTypeError,
                    "must use YYYY-MM-DD",
                ):
                    CLI._iso_date(value)


if __name__ == "__main__":
    unittest.main()
