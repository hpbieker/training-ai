"""Bounded, station-backed historical observations from MET Norway Frost."""

from __future__ import annotations

import base64
import copy
import json
import math
import re
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SOURCE = "MET Norway Frost"


class ObservationFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def object_schema(properties, required):
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
TIME = {"type": "string", "format": "date-time"}
ELEMENTS = {"type": "array", "items": STRING, "minItems": 1, "maxItems": 10,
            "uniqueItems": True, "description": "Exact Frost element IDs, e.g. air_temperature or sum(precipitation_amount PT1H)."}
POINT = {"latitude": {"type": "number", "minimum": -90, "maximum": 90},
         "longitude": {"type": "number", "minimum": -180, "maximum": 180}}
WINDOW = {"timezone": STRING, "from_local": TIME, "to_local": TIME,
          "elements": ELEMENTS,
          "time_resolution": {"type": "string", "enum": ["PT1H", "PT10M"], "default": "PT1H"}}
RADIUS = {"type": "number", "exclusiveMinimum": 0, "maximum": 200, "default": 50}
OBSERVATION = object_schema({
    "station_id": STRING, "source_id": STRING, "element_id": STRING,
    "reference_time_utc": STRING, "time_utc": STRING, "time_local": STRING,
    "value": {"type": "number"}, "unit": STRING,
    "time_offset": {"type": ["string", "null"]},
    "time_resolution": {"type": ["string", "null"]},
    "level": {"type": ["object", "null"]},
    "quality_code": {"type": ["integer", "null"]},
    "time_series_id": {"type": ["integer", "null"]},
    "performance_category": {"type": ["string", "null"]},
}, ["station_id", "source_id", "element_id", "reference_time_utc", "time_utc",
    "time_local", "value", "unit", "time_offset", "time_resolution", "level",
    "quality_code", "time_series_id", "performance_category"])
STATION = object_schema({
    "station_id": STRING, "name": {"type": ["string", "null"]},
    "latitude": {"type": "number"}, "longitude": {"type": "number"},
    "altitude_m": {"type": ["number", "null"]},
    "distance_km": {"type": ["number", "null"]},
    "valid_from": {"type": ["string", "null"]},
    "valid_to": {"type": ["string", "null"]},
    "available_series": {"type": "array", "items": {"type": "object"}},
}, ["station_id", "name", "latitude", "longitude", "altitude_m", "distance_km",
    "valid_from", "valid_to", "available_series"])
WARNINGS = {"type": "array", "items": {"type": "string"}}
TEMPERATURE = "air_temperature"
PRECIPITATION = "sum(precipitation_amount PT1H)"
SNOW_DEPTH = "surface_snow_thickness"
SUMMARY_ELEMENTS = [TEMPERATURE, PRECIPITATION, SNOW_DEPTH]
SUMMARY_POINT = object_schema({"id": STRING, **POINT}, ["id", *POINT])
SUMMARY_SAMPLE = object_schema({
    "time_local": TIME, "value": {"type": "number"},
    "quality_code": {"type": ["integer", "null"]},
}, ["time_local", "value", "quality_code"])
OPTIONAL_SAMPLE = {"anyOf": [SUMMARY_SAMPLE, {"type": "null"}]}
SUMMARY_METRICS = {
    TEMPERATURE: object_schema({
        "min": SUMMARY_SAMPLE, "max": SUMMARY_SAMPLE,
        "first_at_or_below_zero": OPTIONAL_SAMPLE,
        "last_at_or_below_zero": OPTIONAL_SAMPLE,
    }, ["min", "max", "first_at_or_below_zero", "last_at_or_below_zero"]),
    PRECIPITATION: object_schema({
        "total": {"type": "number"}, "first_wet_hour": OPTIONAL_SAMPLE,
        "last_wet_hour": OPTIONAL_SAMPLE, "wettest_hour": OPTIONAL_SAMPLE,
    }, ["total", "first_wet_hour", "last_wet_hour", "wettest_hour"]),
    SNOW_DEPTH: object_schema({
        "first": SUMMARY_SAMPLE, "last": SUMMARY_SAMPLE,
        "change": {"type": ["number", "null"]},
    }, ["first", "last", "change"]),
}
SUMMARY_ROW = object_schema({
    "station_id": STRING, "element": {"enum": SUMMARY_ELEMENTS},
    "unit": STRING, "sample_count": {"type": "integer"},
    "missing_hours": {"type": "integer"},
    "first_time_local": TIME, "last_time_local": TIME,
    "quality_codes": {"type": "array", "items": {"type": ["integer", "null"]}},
    "metrics": {"oneOf": list(SUMMARY_METRICS.values())},
}, ["station_id", "element", "unit", "sample_count", "missing_hours",
    "first_time_local", "last_time_local", "quality_codes", "metrics"])
SERIES_OUTPUT = object_schema({
    "source": STRING, "timezone": STRING, "from_local": STRING, "to_local": STRING,
    "stations": {"type": "array", "items": STATION},
    "observations": {"type": "array", "items": OBSERVATION},
    "count": {"type": "integer"}, "warnings": WARNINGS,
}, ["source", "timezone", "from_local", "to_local", "stations", "observations", "count", "warnings"])


def definition(name, description, inputs, required, output):
    return {"name": name, "description": description,
            "inputSchema": object_schema(inputs, required), "outputSchema": output,
            "annotations": {"title": name.replace("_", " ").title(), "readOnlyHint": True,
                            "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}}


TOOL_DEFINITIONS = {
    "find_observation_stations": definition(
        "find_observation_stations",
        "Find stations near coordinates, ranked by distance and filtered to all requested "
        "elements and overlapping time-series availability. Coverage metadata does not guarantee every sample exists. "
        "Starts with a small candidate set and expands only for missing coverage, up to 50 candidates; no route interpretation.",
        {**POINT, **WINDOW, "radius_km": RADIUS,
         "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5}},
        [*POINT, "timezone", "from_local", "to_local", "elements"],
        object_schema({"source": STRING, "timezone": STRING,
                       "from_local": STRING, "to_local": STRING,
                       "stations": {"type": "array", "items": STATION},
                       "count": {"type": "integer"}, "warnings": WARNINGS},
                      ["source", "timezone", "from_local", "to_local", "stations", "count", "warnings"])),
    "get_observation_series": definition(
        "get_observation_series",
        "Get historical station observations for an inclusive local window of at most 31 days. "
        "Preserves source time, offset, resolution, measurement level and quality. Uses Frost default "
        "levels/offsets and main time series; never treats missing data as zero or interpolates samples.",
        {**WINDOW, "station_ids": {"type": "array", "items": STRING, "minItems": 1,
                                    "maxItems": 10, "uniqueItems": True}},
        ["station_ids", "timezone", "from_local", "to_local", "elements"], SERIES_OUTPUT),
    "get_observations": definition(
        "get_observations",
        "Get nearest historical observations for 1–25 caller-selected points and local times. "
        "Starts with three candidates and fetches their observations together. Expands only for missing "
        "coverage, up to 50 candidates. Prefers complete element coverage then station distance, "
        "and picks the nearest sample per element within tolerance (earlier wins ties). "
        "Each result uses one station and exposes actual times and missing elements; no interpolation.",
        {"timezone": STRING, "elements": ELEMENTS, "radius_km": RADIUS,
         "tolerance_minutes": {"type": "integer", "minimum": 0, "maximum": 180, "default": 60},
         "requests": {"type": "array", "minItems": 1, "maxItems": 25,
                      "items": object_schema({"id": STRING, **POINT, "at_local": TIME},
                                             ["id", *POINT, "at_local"])}},
        ["timezone", "elements", "requests"],
        object_schema({"source": STRING, "timezone": STRING, "count": {"type": "integer"},
                       "success_count": {"type": "integer"}, "error_count": {"type": "integer"},
                       "results": {"type": "array", "items": object_schema({
                           "id": STRING, "requested_at_local": STRING,
                           **POINT, "station": {"anyOf": [STATION, {"type": "null"}]},
                           "observations": {"type": "array", "items": OBSERVATION},
                           "missing_elements": {"type": "array", "items": STRING},
                           "warnings": WARNINGS, "error": {"type": ["string", "null"]}},
                           ["id", "requested_at_local", *POINT, "station", "observations",
                            "missing_elements", "warnings", "error"])}},
                      ["source", "timezone", "count", "success_count", "error_count", "results"])),
    "get_observations_summary": definition(
        "get_observations_summary",
        "Summarize hourly temperature, precipitation and snow depth near 1–25 points "
        "over a shared inclusive window of at most 31 days. Selects the nearest station "
        "with actual samples per element. Returns each station and summary once, without raw samples.",
        {"timezone": STRING, "from_local": TIME, "to_local": TIME, "radius_km": RADIUS,
         "elements": {**ELEMENTS, "items": {"enum": SUMMARY_ELEMENTS}, "maxItems": 3,
                      "description": "Temperature, hourly precipitation and/or snow depth."},
         "points": {"type": "array", "minItems": 1, "maxItems": 25, "items": SUMMARY_POINT}},
        ["timezone", "from_local", "to_local", "elements", "points"],
        object_schema({
            "source": STRING, "timezone": STRING, "from_local": TIME, "to_local": TIME,
            "stations": {"type": "array", "items": object_schema({
                "station_id": STRING, "name": {"type": ["string", "null"]},
                "altitude_m": {"type": ["number", "null"]},
            }, ["station_id", "name", "altitude_m"])},
            "results": {"type": "array", "items": object_schema({
                "id": STRING,
                "matches": {"type": "array", "items": object_schema({
                    "element": {"enum": SUMMARY_ELEMENTS}, "station_id": STRING,
                    "distance_km": {"type": "number"},
                }, ["element", "station_id", "distance_km"])},
                "missing_elements": {"type": "array", "items": {"enum": SUMMARY_ELEMENTS}},
                "snow_around_precipitation": object_schema({
                    "before_first_wet_hour": OPTIONAL_SAMPLE,
                    "at_or_after_last_wet_hour": OPTIONAL_SAMPLE,
                }, ["before_first_wet_hour", "at_or_after_last_wet_hour"]),
            }, ["id", "matches", "missing_elements"])},
            "summaries": {"type": "array", "items": SUMMARY_ROW},
        }, ["source", "timezone", "from_local", "to_local", "stations", "results", "summaries"])),
}


class FrostClient:
    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or Path.home() / ".yr_mcp.json"

    def get(self, endpoint: str, params: dict) -> dict:
        try:
            config = json.loads(self.config_path.read_text())["frost"]
            client_id = config["client_id"]
            if not isinstance(client_id, str) or not client_id.strip():
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ObservationFailure("configuration_error", "Configure frost.client_id in ~/.yr_mcp.json") from exc
        token = base64.b64encode((client_id + ":").encode()).decode()
        request = Request("https://frost.met.no/" + endpoint + "/v0.jsonld?" + urlencode(params),
                          headers={"Authorization": "Basic " + token,
                                   "User-Agent": "codex-yr-plugin/0.3", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as exc:
            # Frost returns 404 when a valid query has no matching data.
            if exc.code == 404:
                return {"data": []}
            raise ObservationFailure("source_error", f"Frost request failed: HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise ObservationFailure("source_error", "Frost connection failed or timed out") from None
        except (ValueError, UnicodeError):
            raise ObservationFailure("source_error", "Frost returned invalid JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ObservationFailure("source_error", "Frost returned an unexpected response")
        if payload.get("nextLink"):
            raise ObservationFailure("source_error", "Frost response is incomplete; narrow the request")
        return payload


class CachedFrostClient:
    """Bounded process-local metadata cache; observations are always fetched fresh."""

    def __init__(self, client, *, ttl_seconds=900, max_entries=128, clock=time.monotonic):
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries = OrderedDict()
        self._lock = Lock()

    def _read(self, key):
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            expires, value = item
            if self.clock() >= expires:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return copy.deepcopy(value)

    def _write(self, key, value):
        with self._lock:
            self._entries[key] = (self.clock() + self.ttl_seconds, copy.deepcopy(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def get(self, endpoint, params):
        if endpoint not in {"sources", "observations/availableTimeSeries"}:
            return self.client.get(endpoint, params)
        key = (endpoint, json.dumps(params, sort_keys=True))
        cached = self._read(key)
        if cached is not None:
            return cached

        # Reuse metadata from earlier nearest searches for explicit station reads.
        # Scope aliases to the same validity interval; never reuse across dates.
        ids = list(dict.fromkeys(params.get("ids", "").split(",")))
        direct = endpoint == "sources" and params.get("ids") and set(params) <= {"ids", "validtime"}
        if direct:
            records = [self._read(("station", s, params.get("validtime"))) for s in ids]
            if all(s is not None for s in records):
                return {"data": records}

        result = self.client.get(endpoint, params)
        self._write(key, result)
        if endpoint == "sources":
            for station in result["data"]:
                self._write(("station", station["id"], params.get("validtime")), station)
        return result


def validate(name, arguments):
    # jsonschema is a dependency of the MCP SDK. Keep validation before any I/O,
    # including all batch members, and avoid returning configuration values.
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(TOOL_DEFINITIONS[name]["inputSchema"]).iter_errors(arguments))
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "arguments"
        raise ObservationFailure("invalid_arguments", f"Invalid {path}: {error.validator}")
    try:
        tz = ZoneInfo(arguments["timezone"])
    except (ValueError, KeyError):
        raise ObservationFailure("invalid_arguments", "Unknown IANA timezone") from None
    for key in ("latitude", "longitude", "radius_km"):
        if key in arguments and not math.isfinite(arguments[key]):
            raise ObservationFailure("invalid_arguments", f"{key} must be finite")
    for element in arguments["elements"]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_() .-]{0,150}", element):
            raise ObservationFailure("invalid_arguments", "Expected exact Frost element IDs")
    if name in ("get_observations", "get_observations_summary"):
        ids = set()
        for r in arguments["requests" if name == "get_observations" else "points"]:
            if r["id"] in ids:
                raise ObservationFailure("invalid_arguments", "Duplicate request id")
            ids.add(r["id"])
            if "at_local" in r:
                local_time(r["at_local"], tz)
            if not all(math.isfinite(r[k]) for k in POINT):
                raise ObservationFailure("invalid_arguments", "Coordinates must be finite")
    if name != "get_observations":
        start, end = window(arguments, tz)
        if name == "get_observation_series":
            step = 600 if arguments.get("time_resolution") == "PT10M" else 3600
            expected = ((end.astimezone(timezone.utc)-start.astimezone(timezone.utc)).total_seconds()/step+1)
            if expected * len(arguments["station_ids"]) * len(arguments["elements"]) > 50000:
                raise ObservationFailure("invalid_arguments", "Request exceeds 50000 expected samples; narrow the window or selection")
            for station in arguments["station_ids"]:
                if not re.fullmatch(r"SN\d+(?::\d+)?", station):
                    raise ObservationFailure("invalid_arguments", "Expected Frost station IDs such as SN18700")
    return tz


def local_time(value, tz):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if "T" not in value:
            raise ValueError
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
            # Reject ambiguous/nonexistent wall times; explicit offsets resolve them.
            if dt.utcoffset() != dt.replace(fold=1).utcoffset():
                raise ValueError
            if dt.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != dt.replace(tzinfo=None):
                raise ValueError
        return dt.astimezone(tz)
    except (ValueError, TypeError):
        raise ObservationFailure("invalid_arguments", "Use an ISO date-time; include an offset for DST transitions") from None


def window(a, tz):
    start, end = (local_time(a[k], tz) for k in ("from_local", "to_local"))
    span = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    if not timedelta(0) <= span <= timedelta(days=31):
        raise ObservationFailure("invalid_arguments", "Window must be ordered and at most 31 days")
    return start, end


def utc(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def reference_window(start, end):
    # Frost's interval is end-exclusive; expose an inclusive interface.
    return utc(start) + "/" + utc(end + timedelta(seconds=1))


def distance(lat, lon, coords):
    lon2, lat2 = coords[:2]
    a, b = math.radians(lat), math.radians(lat2)
    d = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon)/2)**2
    return round(6371.0088 * 2 * math.asin(min(1, math.sqrt(d))), 3)


def station_row(s, latitude=None, longitude=None, series=None):
    coords = s.get("geometry", {}).get("coordinates", [])
    if len(coords) < 2:
        raise ObservationFailure("source_error", "Station coordinates unavailable")
    return {"station_id": s["id"], "name": s.get("name"), "latitude": coords[1],
            "longitude": coords[0], "altitude_m": s.get("masl"),
            "distance_km": None if latitude is None else distance(latitude, longitude, coords),
            "valid_from": s.get("validFrom"), "valid_to": s.get("validTo"),
            "available_series": series or []}


def filters(a):
    return {"elements": ",".join(a["elements"]),
            "timeresolutions": a.get("time_resolution", "PT1H"),
            "levels": "default", "timeoffsets": "default"}


def candidate_limits(initial=3):
    return sorted({initial, *(n for n in (3, 10, 25, 50) if n >= initial)})


def candidate_stations(client, a, start, end, count):
    latitude, longitude = a["latitude"], a["longitude"]
    sources = client.get("sources", {
        "types": "SensorSystem", "geometry": f"nearest(POINT({longitude} {latitude}))",
        "nearestmaxcount": count, "elements": ",".join(a["elements"]),
        "validtime": start.date().isoformat() + "/" + end.date().isoformat()})["data"]
    rows = [s for s in sources if len((s.get("geometry") or {}).get("coordinates", [])) >= 2
            and distance(latitude, longitude, s["geometry"]["coordinates"]) <= a.get("radius_km", 50)]
    rows.sort(key=lambda s: (distance(latitude, longitude, s["geometry"]["coordinates"]), s["id"]))
    # No more candidates can be inside the radius if this response was short,
    # or the radius already excluded one of the nearest candidates.
    exhausted = len(sources) < count or len(rows) < len(sources)
    return rows, exhausted


def find_stations(client, a, tz):
    start, end = window(a, tz)
    rows, seen = [], set()
    limit = a.get("limit", 5)
    for count in candidate_limits(max(3, limit)):
        sources, exhausted = candidate_stations(client, a, start, end, count)
        new = [s for s in sources if s["id"] not in seen]
        if new:
            series = client.get("observations/availableTimeSeries", {
                "sources": ",".join(s["id"] for s in new),
                "referencetime": reference_window(start, end), **filters(a)})["data"]
            for s in new:
                seen.add(s["id"])
                available = [x for x in series if x["sourceId"].split(":")[0] == s["id"]]
                if set(a["elements"]) <= {x["elementId"] for x in available}:
                    rows.append(station_row(s, a["latitude"], a["longitude"], available))
        rows.sort(key=lambda r: (r["distance_km"], r["station_id"]))
        if len(rows) >= limit or exhausted:
            break
    rows = rows[:limit]
    return {"source": SOURCE, "timezone": str(tz), "from_local": start.isoformat(),
            "to_local": end.isoformat(), "stations": rows, "count": len(rows),
            "warnings": ["Candidate search expands only for missing coverage, up to 50 stations; series availability does not guarantee complete samples."]}


def fetch_observation_rows(client, a, tz):
    start, end = window(a, tz)
    data = client.get("observations", {"sources": ",".join(a["station_ids"]),
                      "referencetime": reference_window(start, end), **filters(a)})["data"]
    return normalize_observations(data, start, end, tz)


def normalize_observations(data, start, end, tz):
    rows = []
    for item in data:
        ref = datetime.fromisoformat(item["referenceTime"].replace("Z", "+00:00"))
        for o in item["observations"]:
            # Subdaily Frost referenceTime is already the observation time.
            # timeOffset describes the series schedule, and must not be added.
            at = ref
            if not start.astimezone(timezone.utc) <= at <= end.astimezone(timezone.utc):
                continue
            rows.append({"station_id": item["sourceId"].split(":")[0],
                         "source_id": item["sourceId"], "element_id": o["elementId"],
                         "reference_time_utc": utc(ref), "time_utc": utc(at),
                         "time_local": at.astimezone(tz).isoformat(), "value": o["value"],
                         "unit": o["unit"], "time_offset": o.get("timeOffset"),
                         "time_resolution": o.get("timeResolution"), "level": o.get("level"),
                         "quality_code": o.get("qualityCode"), "time_series_id": o.get("timeSeriesId"),
                         "performance_category": o.get("performanceCategory")})
    if len(rows) > 50000:
        raise ObservationFailure("source_error", "Response exceeds 50000 samples; narrow the request")
    rows.sort(key=lambda r: (r["time_utc"], r["source_id"], r["element_id"]))
    return rows


def get_series(client, a, tz):
    start, end = window(a, tz)
    ids = a["station_ids"]
    metadata = client.get("sources", {"ids": ",".join(s.split(":")[0] for s in ids),
                                      "validtime": start.date().isoformat()+"/"+end.date().isoformat()})["data"]
    rows = fetch_observation_rows(client, a, tz)
    warnings = []
    for station in ids:
        for element in a["elements"]:
            if not any(r["station_id"] == station.split(":")[0] and r["element_id"] == element for r in rows):
                warnings.append(f"No observations for {station}: {element}")
    if rows:
        warnings.append("Station measurements only; missing samples are not interpolated. Accumulations retain their source element and period.")
    return {"source": SOURCE, "timezone": str(tz), "from_local": start.isoformat(),
            "to_local": end.isoformat(), "stations": [station_row(s) for s in metadata],
            "count": len(rows), "observations": rows, "warnings": warnings}


def get_points(client, a, tz):
    results = []
    tolerance = timedelta(minutes=a.get("tolerance_minutes", 60))
    for request in a["requests"]:
        at = local_time(request["at_local"], tz)
        # Arithmetic in UTC keeps tolerance correct across DST transitions.
        at_utc = at.astimezone(timezone.utc)
        window_args = {"timezone": str(tz), "elements": a["elements"],
                       "from_local": (at_utc-tolerance).isoformat(),
                       "to_local": (at_utc+tolerance).isoformat()}
        result = {"id": request["id"], "requested_at_local": at.isoformat(),
                  **{k: request[k] for k in POINT}, "station": None, "observations": [],
                  "missing_elements": a["elements"][:], "warnings": [], "error": None}
        try:
            best = []
            seen = set()
            point_args = {**window_args, **{k: request[k] for k in POINT},
                          "radius_km": a.get("radius_km", 50)}
            start, end = window(window_args, tz)
            for count in candidate_limits():
                stations, exhausted = candidate_stations(
                    client, point_args, start, end, count)
                new = [s for s in stations if s["id"] not in seen]
                if new:
                    samples = fetch_observation_rows(client, {
                        **window_args, "station_ids": [s["id"] for s in new]}, tz)
                    for station in new:
                        seen.add(station["id"])
                        selected = []
                        for element in a["elements"]:
                            matches = [r for r in samples if r["station_id"] == station["id"]
                                       and r["element_id"] == element]
                            if matches:
                                selected.append(min(matches, key=lambda r: (
                                    abs(datetime.fromisoformat(r["time_utc"].replace("Z", "+00:00"))-at_utc), r["time_utc"])))
                        if len(selected) > len(best):
                            best = selected
                            result["station"] = station_row(station, request["latitude"], request["longitude"])
                            result["observations"] = selected
                if len(best) == len(a["elements"]) or exhausted:
                    break
            result["missing_elements"] = [e for e in a["elements"] if e not in {r["element_id"] for r in best}]
            if result["missing_elements"]:
                result["error"] = "No complete observation set within radius and time tolerance"
            result["warnings"] = ["Actual sample times may differ by element; quality codes are retained without reinterpretation."]
        except ObservationFailure as exc:
            result["error"] = str(exc)
            result["missing_elements"] = [e for e in a["elements"]
                                          if e not in {r["element_id"] for r in result["observations"]}]
        results.append(result)
    success = sum(r["error"] is None for r in results)
    return {"source": SOURCE, "timezone": str(tz), "count": len(results),
            "success_count": success, "error_count": len(results)-success, "results": results}


def summary_sample(row):
    if row is None:
        return None
    return {key: row[key] for key in ("time_local", "value", "quality_code")}


def summarize_series(rows, element, expected_hours):
    first, last = rows[0], rows[-1]
    if element == TEMPERATURE:
        freezing = [row for row in rows if row["value"] <= 0]
        metrics = {
            "min": summary_sample(min(rows, key=lambda row: row["value"])),
            "max": summary_sample(max(rows, key=lambda row: row["value"])),
            "first_at_or_below_zero": summary_sample(freezing[0] if freezing else None),
            "last_at_or_below_zero": summary_sample(freezing[-1] if freezing else None),
        }
    elif element == PRECIPITATION:
        wet = [row for row in rows if row["value"] > 0]
        metrics = {
            "total": math.fsum(row["value"] for row in rows),
            "first_wet_hour": summary_sample(wet[0] if wet else None),
            "last_wet_hour": summary_sample(wet[-1] if wet else None),
            "wettest_hour": summary_sample(max(wet, key=lambda row: row["value"]) if wet else None),
        }
    else:
        metrics = {
            "first": summary_sample(first), "last": summary_sample(last),
            "change": last["value"] - first["value"]
            if len(rows) > 1 and min(first["value"], last["value"]) >= 0 else None,
        }
    return {
        "station_id": first["station_id"], "element": element, "unit": first["unit"],
        "sample_count": len(rows), "missing_hours": max(0, expected_hours - len(rows)),
        "first_time_local": first["time_local"], "last_time_local": last["time_local"],
        "quality_codes": sorted({row["quality_code"] for row in rows},
                                key=lambda code: (code is None, code)),
        "metrics": metrics,
    }


def get_points_summary(client, a, tz):
    start, end = window(a, tz)
    expected_hours = math.floor(end.timestamp() / 3600) - math.ceil(start.timestamp() / 3600) + 1
    stations, summaries, results = {}, {}, []
    series_cache = {}
    for point in a["points"]:
        matches = []
        missing = []
        selected_keys = {}
        for element in a["elements"]:
            args = {**a, **point, "elements": [element]}
            for count in candidate_limits():
                candidates, exhausted = candidate_stations(client, args, start, end, count)
                new_ids = [s["id"] for s in candidates if (s["id"], element) not in series_cache]
                # Bound each Frost response even when expanding to 50 stations.
                for offset in range(0, len(new_ids), 10):
                    ids = new_ids[offset:offset + 10]
                    grouped = {station_id: {} for station_id in ids}
                    for row in fetch_observation_rows(client, {**args, "station_ids": ids}, tz):
                        if (row["station_id"] in grouped and row["element_id"] == element
                                and (element == TEMPERATURE or row["value"] >= 0
                                     or (element == SNOW_DEPTH and row["value"] == -1))):
                            grouped[row["station_id"]].setdefault(row["time_utc"], row)
                    for station_id, samples in grouped.items():
                        series_cache[station_id, element] = list(samples.values())
                selected = next((s for s in candidates if series_cache[s["id"], element]), None)
                if selected or exhausted:
                    break
            if selected is None:
                missing.append(element)
                continue
            station_id = selected["id"]
            station = station_row(selected, point["latitude"], point["longitude"])
            stations[station_id] = {key: station[key] for key in ("station_id", "name", "altitude_m")}
            key = station_id, element
            selected_keys[element] = key
            if key not in summaries:
                summaries[key] = summarize_series(series_cache[key], element, expected_hours)
            matches.append({"element": element, "station_id": station_id,
                            "distance_km": station["distance_km"]})
        result = {"id": point["id"], "matches": matches, "missing_elements": missing}
        if PRECIPITATION in selected_keys and SNOW_DEPTH in selected_keys:
            wet = [row for row in series_cache[selected_keys[PRECIPITATION]] if row["value"] > 0]
            if wet:
                snow = series_cache[selected_keys[SNOW_DEPTH]]
                before = next((row for row in reversed(snow)
                               if row["time_utc"] < wet[0]["time_utc"]), None)
                after = next((row for row in snow if row["time_utc"] >= wet[-1]["time_utc"]), None)
                result["snow_around_precipitation"] = {
                    "before_first_wet_hour": summary_sample(before),
                    "at_or_after_last_wet_hour": summary_sample(after),
                }
        results.append(result)
    return {"source": SOURCE, "timezone": str(tz), "from_local": start.isoformat(),
            "to_local": end.isoformat(), "stations": list(stations.values()),
            "results": results, "summaries": list(summaries.values())}


def call_tool(name, arguments, client):
    tz = validate(name, arguments)
    if name == "find_observation_stations":
        return find_stations(client, arguments, tz)
    if name == "get_observation_series":
        return get_series(client, arguments, tz)
    if name == "get_observations_summary":
        return get_points_summary(client, arguments, tz)
    return get_points(client, arguments, tz)
