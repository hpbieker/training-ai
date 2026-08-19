#!/usr/bin/env python3
"""List and filter authenticated Strava activities with Python HTTP."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

from strava_route_api import StravaError, StravaSession, default_cookie_file


BASE_URL = "https://www.strava.com/athlete/training_activities"


def payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("models", "activities", "results", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise StravaError("Strava returned an unsupported activity-list response.")


def activity_date(row: dict[str, Any]) -> dt.date | None:
    value = row.get("start_time") or row.get("start_date_local") or row.get("start_date_local_raw") or row.get("start_date")
    if not value:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).date()
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def normalized_activity(row: dict[str, Any]) -> dict[str, Any]:
    visibility = row.get("visibility")
    if visibility is None and row.get("private") is not None:
        visibility = "only_me" if row.get("private") else "everyone"
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "start_date_local": row.get("start_time") or row.get("start_date_local"),
        "type": row.get("type") or row.get("sport_type"),
        "visibility": visibility,
        "private": row.get("private"),
        "trainer": row.get("trainer"),
        "bike_id": row.get("bike_id"),
        "selected_tag_type": row.get("selected_tag_type"),
        "elapsed_time_raw": row.get("elapsed_time_raw"),
        "moving_time_raw": row.get("moving_time_raw"),
        "distance_raw": row.get("distance_raw"),
        "elevation_gain_raw": row.get("elevation_gain_raw"),
        "suffer_score": row.get("suffer_score"),
        "commute": row.get("commute"),
        "has_latlng": row.get("has_latlng"),
    }


def fetch_page(session: StravaSession, page: int, per_page: int) -> Any:
    query = urllib.parse.urlencode({
        "keywords": "", "sport_type": "", "tags": "", "commute": "",
        "private_activities": "", "trainer": "", "gear": "",
        "search_session_id": str(uuid.uuid4()), "new_activity_only": "false",
        "page": page, "per_page": per_page,
    })
    try:
        body, _, _ = session.request(
            f"{BASE_URL}?{query}",
            headers=[
                "Accept: application/json, text/javascript, */*; q=0.01",
                "X-Requested-With: XMLHttpRequest",
                "Referer: https://www.strava.com/athlete/training",
            ],
        )
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise StravaError("Strava activity list returned non-JSON content; refresh authentication.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cookie-file", type=Path, default=default_cookie_file())
    parser.add_argument("--header-file", type=Path)
    parser.add_argument("--since", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--visibility", choices=["everyone", "followers_only", "only_me"])
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--per-page", type=int, default=100)
    args = parser.parse_args()
    if args.until < args.since:
        parser.error("--until must be on or after --since")
    try:
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        with StravaSession(args.cookie_file, args.header_file) as session:
            for page in range(1, args.max_pages + 1):
                rows = payload_rows(fetch_page(session, page, args.per_page))
                if not rows:
                    break
                oldest: dt.date | None = None
                for row in rows:
                    row_date = activity_date(row)
                    if row_date is not None:
                        oldest = row_date if oldest is None else min(oldest, row_date)
                    activity = normalized_activity(row)
                    identifier = str(activity["id"])
                    if identifier in seen or row_date is None or not args.since <= row_date <= args.until:
                        continue
                    if args.visibility and activity["visibility"] != args.visibility:
                        continue
                    seen.add(identifier)
                    matches.append(activity)
                if oldest is not None and oldest < args.since:
                    break
        matches.sort(key=lambda row: (row.get("start_date_local") or "", str(row.get("id"))), reverse=True)
        print(json.dumps({"count": len(matches), "activities": matches}, indent=2, ensure_ascii=False))
        return 0
    except (OSError, StravaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
