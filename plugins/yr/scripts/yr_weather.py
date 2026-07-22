"""Utilities for downloading weather forecasts from MET Norway / Yr.

Yr uses MET Norway's public Locationforecast API. The API requires a
non-generic User-Agent with contact information.
"""

from __future__ import annotations

import json
from datetime import datetime, tzinfo
from typing import Any
from urllib.error import HTTPError, URLError
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

    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")

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
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"MET/Yr request failed: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("MET/Yr returned an invalid JSON response") from exc
    if not isinstance(payload, dict) or "properties" not in payload:
        raise TypeError("Expected MET/Yr locationforecast endpoint to return GeoJSON")
    return payload


def compact_hourly_forecast(
    forecast: dict[str, Any],
    *,
    local_timezone: tzinfo,
    from_local: datetime | None = None,
    to_local: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return compact forecast rows in the caller-selected local timezone."""

    rows = []
    seen_hours: set[str] = set()
    for item in (forecast.get("properties") or {}).get("timeseries") or []:
        if not isinstance(item, dict) or not item.get("time"):
            continue
        timestamp = datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00"))
        local = timestamp.astimezone(local_timezone)
        if from_local and local < from_local:
            continue
        if to_local and local > to_local:
            continue
        hour_key = local.replace(minute=0, second=0, microsecond=0).isoformat()
        if hour_key in seen_hours:
            continue
        seen_hours.add(hour_key)
        data = item.get("data") or {}
        instant = data.get("instant") or {}
        details = instant.get("details") or {}
        next_1_hours = data.get("next_1_hours") or {}
        next_1_details = next_1_hours.get("details") or {}
        next_1_summary = next_1_hours.get("summary") or {}
        next_6_hours = data.get("next_6_hours") or {}
        next_6_details = next_6_hours.get("details") or {}
        next_6_summary = next_6_hours.get("summary") or {}
        next_12_hours = data.get("next_12_hours") or {}
        next_12_summary = next_12_hours.get("summary") or {}
        rows.append(
            {
                "time_local": local.isoformat(timespec="seconds"),
                "time_utc": timestamp.isoformat(timespec="seconds"),
                "air_temperature": details.get("air_temperature"),
                "relative_humidity": details.get("relative_humidity"),
                "wind_speed": details.get("wind_speed"),
                "wind_from_direction": details.get("wind_from_direction"),
                "wind_speed_of_gust": details.get("wind_speed_of_gust"),
                "cloud_area_fraction": details.get("cloud_area_fraction"),
                "precipitation_amount_next_1h": next_1_details.get("precipitation_amount"),
                "symbol_code_next_1h": next_1_summary.get("symbol_code"),
                "precipitation_amount_next_6h": next_6_details.get("precipitation_amount"),
                "symbol_code_next_6h": next_6_summary.get("symbol_code"),
                "symbol_code_next_12h": next_12_summary.get("symbol_code"),
            }
        )
    return rows
