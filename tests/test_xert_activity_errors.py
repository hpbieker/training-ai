import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "xert"))
import xert_activities as activities


class ActivityErrorsTest(unittest.TestCase):
    def test_http_success_with_api_failure_does_not_become_empty_activity(self):
        for view in (False, True):
            with self.subTest(session=view), patch.object(activities, "_request_json", return_value={
                "error": "activity_not_found", "success": "false",
            }):
                with self.assertRaisesRegex(RuntimeError, "list_activity_summaries"):
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
