"""Utilities for downloading weather forecasts from MET Norway / Yr.

Yr uses MET Norway's public Locationforecast API. The API requires a
non-generic User-Agent with contact information.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


MET_LOCATIONFORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
DEFAULT_DATA_DIR = Path("data")
DEFAULT_USER_AGENT = "training-ai/0.1 github.com/hanspetterbieker/training-ai"


def cache_locationforecast(
    *,
    latitude: float,
    longitude: float,
    altitude: int | None = None,
    label: str = "location",
    output_dir: str | Path = DEFAULT_DATA_DIR,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Path]:
    """Cache a Yr/MET Locationforecast response for one coordinate."""

    forecast = fetch_locationforecast(
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        user_agent=user_agent,
    )
    weather_dir = Path(output_dir) / "weather" / _safe_label(label)
    weather_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = weather_dir / f"yr_locationforecast_{timestamp}.json"
    csv_path = weather_dir / f"yr_locationforecast_{timestamp}.csv"
    _write_json(json_path, forecast)
    _write_csv(csv_path, flatten_timeseries(forecast))
    return {
        "forecast_json": json_path,
        "forecast_csv": csv_path,
    }


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


def flatten_timeseries(forecast: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the Locationforecast timeseries into CSV-friendly rows."""

    rows = []
    for entry in forecast.get("properties", {}).get("timeseries", []):
        data = entry.get("data", {})
        instant = data.get("instant", {}).get("details", {})
        next_1h = data.get("next_1_hours", {})
        next_6h = data.get("next_6_hours", {})
        next_12h = data.get("next_12_hours", {})
        rows.append(
            {
                "time": entry.get("time"),
                "air_temperature": instant.get("air_temperature"),
                "relative_humidity": instant.get("relative_humidity"),
                "wind_speed": instant.get("wind_speed"),
                "wind_from_direction": instant.get("wind_from_direction"),
                "wind_speed_of_gust": instant.get("wind_speed_of_gust"),
                "cloud_area_fraction": instant.get("cloud_area_fraction"),
                "fog_area_fraction": instant.get("fog_area_fraction"),
                "precipitation_amount_1h": _details(next_1h).get("precipitation_amount"),
                "symbol_code_1h": _summary(next_1h).get("symbol_code"),
                "precipitation_amount_6h": _details(next_6h).get("precipitation_amount"),
                "symbol_code_6h": _summary(next_6h).get("symbol_code"),
                "precipitation_amount_12h": _details(next_12h).get("precipitation_amount"),
                "symbol_code_12h": _summary(next_12h).get("symbol_code"),
            }
        )
    return rows


def _details(block: dict[str, Any]) -> dict[str, Any]:
    details = block.get("details", {})
    return details if isinstance(details, dict) else {}


def _summary(block: dict[str, Any]) -> dict[str, Any]:
    summary = block.get("summary", {})
    return summary if isinstance(summary, dict) else {}


def _safe_label(label: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in label)
    return safe.strip("_") or "location"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
