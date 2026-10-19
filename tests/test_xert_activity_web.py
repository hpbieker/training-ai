"""Authenticated web details must not depend on OAuth/Garmin visibility."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/xert'))
import xert_activities as activities


class WebActivityTests(unittest.TestCase):
    def page(self, url='https://www.xertonline.com/activities/ride/mpa/default?forUser=test'):
        return ('const activity = ' + json.dumps({'name': 'Ride', 'start_date_local': '2026-10-18T09:47:52Z', 'duration': 60})
                + '; Xert.Activity.Analytics.MPA._chartURL = ' + json.dumps(url) + ';')

    def chart(self, **changes):
        return json.dumps({'result': True, 'summary': {'xss': 0, 'xep': 200, 'fa': 'Endurance', 'spr': 'Pure'},
                           'sig': {'ftp': 300}, 'data': [{'time': 0, 'power': 0, 'mpa': 800}], **changes})

    def test_details_and_series_without_oauth(self):
        for include in (False, True):
            with self.subTest(include=include), patch.object(activities, '_open_text', side_effect=[self.page(), self.chart()]), patch.object(activities, '_request_json') as oauth:
                result = activities.fetch_activity_web(object(), 'ride', include_session_data=include)
                self.assertEqual(result['summary']['xss'], 0)
                self.assertEqual(result['path'], 'ride')
                self.assertEqual(result['source'], 'xert_authenticated_web')
                self.assertEqual('session_data' in result, include)
                oauth.assert_not_called()

    def test_wrong_activity_and_external_urls_rejected(self):
        for url in ['https://example.com/activities/ride/mpa/default', 'https://www.xertonline.com/activities/other/mpa/default']:
            with self.subTest(url=url), patch.object(activities, '_open_text', return_value=self.page(url)) as read:
                with self.assertRaises(RuntimeError):
                    activities.fetch_activity_web(object(), 'ride')
                self.assertEqual(read.call_count, 1)

    def test_invalid_page_or_chart_is_not_empty_success(self):
        with patch.object(activities, '_open_text', return_value='<html>Login</html>'):
            with self.assertRaises(RuntimeError):
                activities.fetch_activity_web(object(), 'ride')
        for changes in [{'result': False}, {'data': []}, {'summary': None}, {'data': [None]}]:
            with self.subTest(changes=changes), patch.object(activities, '_open_text', side_effect=[self.page(), self.chart(**changes)]):
                with self.assertRaises(RuntimeError):
                    activities.fetch_activity_web(object(), 'ride')

    def test_path_cannot_inject_url(self):
        with self.assertRaises(ValueError):
            activities.fetch_activity_web(object(), '../other')
