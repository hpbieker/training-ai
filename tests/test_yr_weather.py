from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError
from zoneinfo import ZoneInfo


YR_SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "yr" / "scripts"
sys.path.insert(0, str(YR_SCRIPTS))

from yr_cli import parse_local_datetime
from yr_weather import compact_hourly_forecast, fetch_locationforecast


class YrWeatherTests(unittest.TestCase):
    def test_compact_rows_use_forecast_location_timezone(self):
        forecast = {
            "properties": {
                "timeseries": [
                    {
                        "time": "2026-07-25T07:00:00Z",
                        "data": {
                            "instant": {"details": {"air_temperature": 20.0}},
                            "next_1_hours": {
                                "details": {"precipitation_amount": 0.2},
                                "summary": {"symbol_code": "lightrain"},
                            },
                        },
                    }
                ]
            }
        }

        rows = compact_hourly_forecast(
            forecast,
            local_timezone=ZoneInfo("Europe/Lisbon"),
        )

        self.assertEqual(rows[0]["time_local"], "2026-07-25T08:00:00+01:00")
        self.assertEqual(rows[0]["time_utc"], "2026-07-25T07:00:00+00:00")
        self.assertEqual(rows[0]["precipitation_amount_next_1h"], 0.2)
        self.assertEqual(rows[0]["symbol_code_next_1h"], "lightrain")
        self.assertIsNone(rows[0]["precipitation_amount_next_6h"])

    def test_naive_filter_bounds_use_selected_timezone(self):
        timezone = ZoneInfo("Europe/Lisbon")
        parsed = parse_local_datetime(
            "2026-07-25T08:00",
            local_timezone=timezone,
        )

        self.assertEqual(parsed, datetime(2026, 7, 25, 8, 0, tzinfo=timezone))

    def test_library_rejects_invalid_coordinates_before_network_access(self):
        with self.assertRaisesRegex(ValueError, "latitude"):
            fetch_locationforecast(latitude=91, longitude=10)
        with self.assertRaisesRegex(ValueError, "longitude"):
            fetch_locationforecast(latitude=60, longitude=181)

    def test_network_failure_is_wrapped_in_source_specific_error(self):
        with patch("yr_weather.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(RuntimeError, "MET/Yr request failed"):
                fetch_locationforecast(latitude=60, longitude=10)


if __name__ == "__main__":
    unittest.main()
