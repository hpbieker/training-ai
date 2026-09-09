import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins' / 'xert'))
import xert_activity_summaries as D
import xert_mcp as MCP


def row(path, day, **extra):
    return dict(path=path, name=path, start_date=f'2026-08-{day:02}T22:30:00Z',
                start_date_local=f'2026-08-{day+1:02}T00:30:00Z', **extra)


def page(number, rows, last=2, total=4):
    return json.dumps(dict(data=rows, current_page=number, last_page=last, total=total))


class DashboardTests(unittest.TestCase):
    def fetch(self, pages, start='2026-08-10', end='2026-08-20', **kwargs):
        with patch.object(D, '_open_text', side_effect=pages) as mock:
            result = D.list_activity_summaries(object(), start, end, **kwargs)
            return result, mock.call_count

    def test_limit_after_end_date_and_duplicate(self):
        result, calls = self.fetch([page(1, [row('new', 22), row('a', 18)]),
                                   page(2, [row('a', 18), row('b', 17), row('c', 16)])], limit=2)
        self.assertEqual([a['path'] for a in result['activities']], ['a', 'b'])
        self.assertFalse(result['period_complete'])
        self.assertEqual(calls, 2)

    def test_local_date_inclusive_and_units_and_zero(self):
        result, _ = self.fetch([page(1, [row('a', 9, duration=0, distance=1.25, xss=0, xlss=0,
                                            xhss=0, xpss=0, signature={'ftp': 300}, map_url='/map/a'), row('old', 8)])],
                              end='2026-08-10', include_fields=('duration_s','distance_m','xss','signature','map_url'))
        a = result['activities'][0]
        self.assertEqual(a['start_local'], '2026-08-10T00:30:00')
        self.assertEqual(a['duration_s'], 0)
        self.assertEqual(a['distance_m'], 1250)
        self.assertEqual(a['xss'], dict(total=0, low=0, high=0, peak=0))
        self.assertEqual(a['signature'], {'ftp': 300})
        self.assertEqual(a['map_url'], 'https://www.xertonline.com/map/a')
        self.assertTrue(result['period_complete'])

    def test_limit_stops_without_requesting_next_page(self):
        result, calls = self.fetch([page(1, [row('a', 18), row('b', 17)])], limit=1)
        self.assertEqual(calls, 1)
        self.assertEqual(result['stop_reason'], 'limit')

    def test_wrong_order_is_error_even_with_limit(self):
        with self.assertRaisesRegex(RuntimeError, 'newest-first'):
            self.fetch([page(1, [row('a', 17), row('b', 18)])], limit=1)

    def test_changed_total_or_failed_page_is_not_partial_success(self):
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.fetch([page(1, [row('a', 18)]), page(2, [row('b', 17)], total=5)])
        with self.assertRaises(OSError):
            self.fetch([page(1, [row('a', 18)]), OSError('network')])

    def test_empty_history(self):
        result, _ = self.fetch([page(1, [], last=1, total=0)])
        self.assertEqual(result['count'], 0)
        self.assertTrue(result['period_complete'])

    def test_schema_and_dispatch_no_sort_or_detail_calls(self):
        from unittest.mock import Mock
        service = Mock()
        service.list_activity_summaries.return_value = {'activities': [], 'count': 0}
        result = MCP.XertToolService._dispatch(service, 'list_activity_summaries', {
            'start_date': '2026-08-01', 'end_date': '2026-08-20', 'includeFields': ['signature'], 'limit': 2})
        service.list_activity_summaries.assert_called_once_with('2026-08-01', '2026-08-20', include_fields=('signature',), limit=2)
        service.get_activity.assert_not_called()
        self.assertEqual(result['includeFields'], ['signature'])
        self.assertNotIn('sort', MCP.TOOL_DEFINITIONS['list_activity_summaries']['inputSchema']['properties'])
        self.assertIn('list_activities', MCP.ALL_TOOL_NAMES)

    def test_invalid_limit(self):
        for limit in [0, -1, True, 1.2]:
            with self.assertRaises(ValueError):
                self.fetch([], limit=limit)
