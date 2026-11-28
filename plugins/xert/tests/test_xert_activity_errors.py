import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xert_activities as activities


class ActivityErrorsTest(unittest.TestCase):
    def test_v2_detail_normalizes_activity_summary_without_streams(self):
        started = datetime.fromisoformat("2026-10-18T10:00:00").astimezone().isoformat()
        xss = {"total": 12, "low": 8, "high": 4, "peak": 0}
        with patch.object(activities, "_request_json", return_value={
            "name": "Ride", "summary": {
                "start_date": started, "duration": 3004, "distance": 25.25,
                "activity_map": "/map/a1", "xss": xss, "sig": {"hie": 16.25},
                "session": {"avg_power": 205}, "freshness": "Fresh",
            },
        }) as request:
            result = activities.fetch_activity_summary_v2("a1", "token")
        request.assert_called_once_with("/oauth/v2/activity/a1", "token", params=None)
        self.assertEqual(result["start_local"], "2026-10-18T10:00:00")
        self.assertEqual(result["elapsed_minutes"], 50.1)
        self.assertEqual(result["distance_m"], 25250)
        self.assertEqual(result["map_url"], "https://www.xertonline.com/map/a1")
        self.assertEqual(result["signature"]["hie"], 16.25)
        self.assertEqual(result["avg_power"], 205)
        self.assertEqual(result["freshness"], "Fresh")
        self.assertEqual(result["xss"], xss)

    def test_v2_paginates_before_moving_to_the_older_date_window(self):
        def ride(path, start, distance=None, duration=None):
            return {
                "path": path, "name": path,
                "start_date": datetime.fromisoformat(start).astimezone().isoformat(),
                "distance": distance, "summary": {"duration": duration},
                "map_url": "/map.png" if distance else False,
            }

        newest = ride("newest", "2026-11-01T10:00:00", 12.5, 7200)
        with patch.object(activities, "_request_json", side_effect=[
            {"activities": [newest], "next_cursor": "next"},
            {"activities": [newest, ride("second", "2026-10-18T10:00:00")], "next_cursor": None},
            {"activities": [ride("oldest", "2026-10-01T10:00:00")], "next_cursor": None},
        ]) as request:
            result = activities.list_activities_v2(
                date(2026, 10, 1), date(2026, 11, 1), "token", include_details=True,
            )
        self.assertEqual([r["path"] for r in result], ["newest", "second", "oldest"])
        identity = {
            "path": "newest", "name": "newest", "start_local": "2026-11-01T10:00:00",
            "source": "xert_plugin", "duration_s": 7200, "elapsed_minutes": 120,
            "distance_m": 12500, "distance_km": 12.5,
            "map_url": "https://www.xertonline.com/map.png",
        }
        self.assertEqual({key: result[0][key] for key in identity}, identity)
        self.assertIsNone(result[1]["map_url"])
        first, second, third = (call.kwargs["params"] for call in request.call_args_list)
        self.assertEqual(second, {**first, "cursor": "next"})
        self.assertTrue(first["from"].startswith("2026-10-03T00:00:00"))
        self.assertTrue(third["to"].startswith("2026-10-02T23:59:59"))
        self.assertNotIn("cursor", third)

    def test_v2_does_not_return_a_filtered_or_truncated_period_as_complete(self):
        for response, message in (
            ({"activities": [], "data_use_notice": "Filtered", "next_cursor": None}, "filtered"),
            ({"activities": [], "next_cursor": "repeated"}, "cursor"),
            ({"activities": []}, "cursor"),
        ):
            with self.subTest(response=response), patch.object(
                activities, "_request_json", return_value=response,
            ):
                with self.assertRaisesRegex(RuntimeError, message):
                    activities.list_activities_v2(
                        date(2026, 10, 1), date(2026, 10, 1), "token", include_details=False,
                    )

    def test_http_success_with_api_failure_does_not_become_empty_activity(self):
        for view in (False, True):
            with self.subTest(session=view), patch.object(activities, "_request_json", return_value={
                "error": "activity_not_found", "success": "false",
            }):
                with self.assertRaisesRegex(RuntimeError, "list_activities"):
                    activities.fetch_activity_detail("a1", access_token="test", include_session_data=view)

    def test_failed_list_with_empty_rows_is_not_valid_empty_period(self):
        with patch.object(activities, "_request_json", return_value={"success": False, "activities": []}):
            with self.assertRaises(RuntimeError):
                activities.list_activities(oldest="2026-10-18", newest="2026-10-18", access_token="test")

    def test_batch_detail_failure_is_not_compacted(self):
        with patch.object(activities, "_request_json", side_effect=[
            {"success": True, "activities": [{"path": "a1"}]},
            {"error": "activity_not_found", "success": "false"},
        ]):
            with self.assertRaises(RuntimeError):
                activities.list_activity_details(oldest="2026-10-18", newest="2026-10-18", access_token="test")

    def test_success_payload_and_empty_list_are_preserved(self):
        payload = {"success": True, "summary": {"xss": 12}}
        with patch.object(activities, "_request_json", return_value=payload):
            self.assertEqual(activities.fetch_activity_detail("a1", access_token="test"), payload)
        with patch.object(activities, "_request_json", return_value={"success": True, "activities": []}):
            self.assertEqual(activities.list_activities(oldest="2026-10-18", newest="2026-10-18", access_token="test"), [])


if __name__ == "__main__":
    unittest.main()
