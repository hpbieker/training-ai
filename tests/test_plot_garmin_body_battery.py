import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.plot_garmin_body_battery import (
    _activity_window,
    _parse_garmin_local_datetime,
    _time_value_points,
)


class GarminBodyBatteryTimezoneTests(unittest.TestCase):
    def test_epoch_points_are_converted_from_utc_to_requested_timezone(self):
        lisbon = ZoneInfo("Europe/Lisbon")
        timestamp_ms = int(
            datetime.fromisoformat("2026-07-31T09:00:00+00:00").timestamp()
            * 1000
        )

        points = _time_value_points(
            [[timestamp_ms, 75]],
            local_timezone=lisbon,
        )

        self.assertEqual(
            points[0][0].isoformat(),
            "2026-07-31T10:00:00+01:00",
        )

    def test_garmin_local_milliseconds_preserve_local_clock_in_requested_zone(self):
        lisbon = ZoneInfo("Europe/Lisbon")
        local_clock_encoded_as_utc_ms = int(
            datetime.fromisoformat("2026-07-31T07:30:00+00:00").timestamp()
            * 1000
        )

        parsed = _parse_garmin_local_datetime(
            local_clock_encoded_as_utc_ms,
            local_timezone=lisbon,
        )

        self.assertEqual(parsed.isoformat(), "2026-07-31T07:30:00+01:00")

    def test_activity_window_uses_requested_timezone_without_host_conversion(self):
        lisbon = ZoneInfo("Europe/Lisbon")
        with tempfile.TemporaryDirectory() as tmp:
            activity_dir = Path(tmp)
            (activity_dir / "activity.json").write_text(
                json.dumps(
                    {
                        "start_date_local": "2026-07-31T10:15:00",
                        "moving_time": 2700,
                    }
                ),
                encoding="utf-8",
            )

            start, end = _activity_window(
                str(activity_dir),
                local_timezone=lisbon,
            )

        self.assertEqual(start.isoformat(), "2026-07-31T10:15:00+01:00")
        self.assertEqual(end.isoformat(), "2026-07-31T11:00:00+01:00")


if __name__ == "__main__":
    unittest.main()
