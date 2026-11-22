"""Find representative place coordinates with a Nominatim-compatible service."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from route_geometry import ATTRIBUTION, LICENSE_URL, USER_AGENT

PLACE_API = "https://nominatim.openstreetmap.org/search"
RESULT_LIMIT = 5
MAX_REPLY = 1024 * 1024
CACHE_TTL_S = 86400
REQUEST_INTERVAL_S = 1.05
ADDRESS_FIELDS = {
    "road": "street",
    "house_number": "housenumber",
    **{key: key for key in ("postcode", "city", "town", "village", "municipality", "county", "state", "country")},
}


def fetch_places(request):
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read(MAX_REPLY + 1)
    except HTTPError as exc:
        detail = " Try again later." if exc.code == 429 or exc.code >= 500 else ""
        raise ValueError(f"Nominatim place search returned HTTP {exc.code}.{detail}") from None
    except (URLError, TimeoutError):
        raise ValueError("Could not connect to Nominatim place search.") from None
    if len(body) > MAX_REPLY:
        raise ValueError("Place search response exceeded the size limit.")
    results = json.loads(body)
    if not isinstance(results, list):
        raise ValueError("Nominatim returned an unexpected response.")
    return results


def cached_places(request):
    directory = Path(tempfile.gettempdir()) / f"route-planner-search-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    key = hashlib.sha256(request.full_url.encode()).hexdigest()
    with closing(sqlite3.connect(directory / "places.sqlite3", timeout=20)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS places (key TEXT PRIMARY KEY, saved REAL, payload TEXT)")
        # Hold the transaction across the request so parallel MCP processes share the limit.
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM places WHERE key != '' AND saved < ?", (time.time() - CACHE_TTL_S,))
        cached = db.execute("SELECT payload FROM places WHERE key = ?", (key,)).fetchone()
        if cached is not None:
            return json.loads(cached[0])

        previous = db.execute("SELECT saved FROM places WHERE key = ''").fetchone()
        if previous is not None:
            remaining = REQUEST_INTERVAL_S - (time.time() - previous[0])
            time.sleep(max(0, min(remaining, REQUEST_INTERVAL_S)))
        try:
            results = fetch_places(request)
            db.execute("INSERT INTO places VALUES (?, ?, ?)", (key, time.time(), json.dumps(results)))
            return results
        finally:
            db.execute("INSERT OR REPLACE INTO places VALUES ('', ?, NULL)", (time.time(),))
            db.commit()


def find_public_place(query, near, distance):
    endpoint = os.environ.get("ROUTE_PLANNER_GEOCODER_URL") or PLACE_API
    params = urlencode({"q": query, "format": "jsonv2", "addressdetails": 1, "limit": RESULT_LIMIT})
    request = Request(f"{endpoint}?{params}", headers={"User-Agent": USER_AGENT})
    matches = []
    for item in cached_places(request)[:RESULT_LIMIT]:
        osm_type, osm_id = item.get("osm_type"), item.get("osm_id")
        if osm_type not in {"node", "way", "relation"} or not osm_id:
            continue
        lon, lat = float(item["lon"]), float(item["lat"])
        address = {
            ADDRESS_FIELDS[key]: value
            for key, value in item.get("address", {}).items()
            if key in ADDRESS_FIELDS
        }
        candidate = {
            "name": item.get("name") or item.get("display_name") or query,
            "point": {"lat": lat, "lon": lon},
            "address": address,
            "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        }
        if near is not None:
            candidate["distance_from_near_m"] = round(distance((lon, lat), near), 1)
        matches.append(candidate)
    if near is not None:
        matches.sort(key=lambda entry: entry["distance_from_near_m"])
    return {
        "results": matches, "source": "Nominatim / OpenStreetMap",
        "attribution": ATTRIBUTION, "license_url": LICENSE_URL,
        "note": "Place coordinates are representative, not verified road points.",
    }
