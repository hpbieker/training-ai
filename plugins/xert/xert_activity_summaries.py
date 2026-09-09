"""Rich, newest-first activity summaries from Xert's authenticated dashboard."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from urllib.request import Request
from urllib.parse import urljoin

from xert_common import XERT_API_BASE_URL, _open_text

SUMMARY_FIELDS = (
    'duration_s', 'distance_m', 'source', 'map_url', 'signature', 'xss',
    'xep_watts', 'focus', 'specificity', 'difficulty', 'difficulty_rating',
    'avg_power', 'max_power', 'avg_heart_rate', 'max_heart_rate',
    'avg_cadence', 'max_cadence',
)


def _timestamps(row):
    # Xert appends Z to start_date_local even though it is a wall-clock value.
    local = datetime.fromisoformat(row['start_date_local'].replace('Z', '+00:00')).replace(tzinfo=None)
    utc = datetime.fromisoformat(row['start_date'].replace('Z', '+00:00'))
    if utc.tzinfo is None:
        raise RuntimeError('Dashboard start_date has no UTC offset')
    return local, utc.astimezone(timezone.utc)


def normalize_summary(row, fields):
    local, _ = _timestamps(row)
    distance = row.get('distance')
    map_url = row.get('map_url')
    values = {
        **{k: row.get(k) for k in SUMMARY_FIELDS},
        'duration_s': row.get('duration'),
        'distance_m': distance * 1000 if isinstance(distance, (int, float)) else None,
        'source': 'xert_plugin',
        'map_url': urljoin(XERT_API_BASE_URL, map_url) if isinstance(map_url, str) and map_url else None,
        'signature': row.get('signature'),
        'xss': {k: row.get(v) for k, v in [('total', 'xss'), ('low', 'xlss'), ('high', 'xhss'), ('peak', 'xpss')]},
        'xep_watts': row.get('xep'),
        'focus': row.get('focus', row.get('fa')),
        'specificity': row.get('spr'),
        'difficulty_rating': row.get('rating'),
    }
    return {'path': row['path'], 'name': row.get('name'), 'start_local': local.isoformat(),
            **{k: values[k] for k in fields}}


def list_activity_summaries(opener, start_date, end_date, *, include_fields=(), limit=None):
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if start > end:
        raise ValueError('start_date must not be after end_date')
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('limit must be a positive integer')
    if any(f not in SUMMARY_FIELDS for f in include_fields):
        raise ValueError('Unsupported summary field')
    result, seen = [], set()
    previous_utc = previous_local = None
    first_total = None
    for page in range(1, 1001):
        url = f'{XERT_API_BASE_URL}/activities/dashboard?searchFavourites=false&page={page}&perPage=100'
        payload = json.loads(_open_text(opener, Request(url, headers={
            'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
        }), 'Xert activity summaries'))
        rows = payload.get('data')
        if not isinstance(rows, list) or int(payload.get('current_page', 0)) != page:
            raise RuntimeError('Invalid dashboard page response')
        last_page = int(payload['last_page'])
        if page == 1:
            first_total = payload.get('total')
        elif payload.get('total') != first_total:
            raise RuntimeError('Dashboard changed during pagination; retry the request')
        if not rows and page < last_page:
            raise RuntimeError('Unexpected empty dashboard page')
        validated = []
        for row in rows:
            if not isinstance(row, dict) or not row.get('path'):
                raise RuntimeError('Dashboard activity is missing its identity')
            local, utc = _timestamps(row)
            if row['path'] in seen:
                continue
            if previous_utc is not None and (utc > previous_utc or local.date() > previous_local):
                raise RuntimeError('Dashboard is not newest-first; cannot safely apply date boundaries or limit')
            previous_utc, previous_local = utc, local.date()
            seen.add(row['path'])
            validated.append((row, local.date()))
        for row, day in validated:
            if day > end:
                continue
            if day < start:
                return _result(result, page, True, 'start_date')
            if limit is not None and len(result) == limit:
                return _result(result, page, False, 'limit')
            result.append(normalize_summary(row, include_fields))
        if page >= last_page:
            return _result(result, page, True, 'history_end')
        if limit is not None and len(result) == limit:
            return _result(result, page, False, 'limit')
    raise RuntimeError('Dashboard exceeded 1000 pages; no complete result returned')


def _result(rows, pages, complete, reason):
    return {'activities': rows, 'count': len(rows), 'pages_fetched': pages,
            'period_complete': complete, 'stop_reason': reason, 'order': 'newest_first'}
