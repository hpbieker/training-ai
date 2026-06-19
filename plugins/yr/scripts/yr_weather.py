"""Utilities for downloading weather forecasts from MET Norway / Yr.

Yr uses MET Norway's public Locationforecast API. The API requires a
non-generic User-Agent with contact information.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


MET_LOCATIONFORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
DEFAULT_USER_AGENT = "codex-yr-plugin/0.1 github.com/hanspetterbieker"


def fetch_locationforecast(
    *,
    latitude: float,
    longitude: float,
    altitude: int | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    """Fetch a compact Locationforecast from MET Norway / Yr."""

    params: dict[str, Any] = {
        "lat": f"{latitude:.4f}",
        "lon": f"{longitude:.4f}",
    }
    if altitude is not None:
        params["altitude"] = altitude
    request = Request(
        f"{MET_LOCATIONFORECAST_URL}?{urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"MET/Yr request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    if not isinstance(payload, dict) or "properties" not in payload:
        raise TypeError("Expected MET/Yr locationforecast endpoint to return GeoJSON")
    return payload

