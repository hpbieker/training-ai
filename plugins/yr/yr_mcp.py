#!/usr/bin/env python3
"""Expose compact MET Norway Locationforecast point forecasts over MCP."""

from __future__ import annotations

import json
import sys
from bisect import bisect_left
from itertools import accumulate, pairwise
from threading import Lock
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from yr_weather import compact_hourly_forecast, fetch_locationforecast
import yr_observations


ALL_TOOL_NAMES = (
    "get_forecast", "get_forecasts", "get_route_forecasts_summary", "get_route_observations_summary",
    *yr_observations.TOOL_DEFINITIONS,
)

TOOL_ANNOTATIONS = {
    "get_forecast": {
        "title": "Get Yr Forecast",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
    "get_forecasts": {
        "title": "Get Yr Forecasts",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
}
_NULLABLE_NUMBER = {"type": ["number", "null"]}
_NULLABLE_STRING = {"type": ["string", "null"]}
_FORECAST_ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "time_local": {"type": "string"},
        "time_utc": {"type": "string"},
        "air_temperature": _NULLABLE_NUMBER,
        "relative_humidity": _NULLABLE_NUMBER,
        "wind_speed": _NULLABLE_NUMBER,
        "wind_from_direction": _NULLABLE_NUMBER,
        "wind_speed_of_gust": _NULLABLE_NUMBER,
        "cloud_area_fraction": _NULLABLE_NUMBER,
        "precipitation_amount_next_1h": _NULLABLE_NUMBER,
        "symbol_code_next_1h": _NULLABLE_STRING,
        "precipitation_amount_next_6h": _NULLABLE_NUMBER,
        "symbol_code_next_6h": _NULLABLE_STRING,
        "symbol_code_next_12h": _NULLABLE_STRING,
    },
    "required": [
        "time_local",
        "time_utc",
        "air_temperature",
        "relative_humidity",
        "wind_speed",
        "wind_from_direction",
        "wind_speed_of_gust",
        "cloud_area_fraction",
        "precipitation_amount_next_1h",
        "symbol_code_next_1h",
        "precipitation_amount_next_6h",
        "symbol_code_next_6h",
        "symbol_code_next_12h",
    ],
    "additionalProperties": False,
}

TOOL_DEFINITIONS = {
    "get_forecast": {
        "name": "get_forecast",
        "description": (
            "Fetch a compact hourly MET Norway Locationforecast for one geographic "
            "point. Without to_local, return the first forecast timestamp at or after "
            "from_local. With to_local, return the inclusive local-time window. Call "
            "once per materially different route point; the caller owns route "
            "aggregation and decisions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "minimum": -90,
                    "maximum": 90,
                    "description": "Forecast latitude in decimal degrees.",
                },
                "longitude": {
                    "type": "number",
                    "minimum": -180,
                    "maximum": 180,
                    "description": "Forecast longitude in decimal degrees.",
                },
                "altitude": {
                    "type": "integer",
                    "description": "Optional altitude above sea level in metres.",
                },
                "timezone": {
                    "type": "string",
                    "minLength": 1,
                    "description": "IANA timezone for filtering and local timestamps.",
                },
                "from_local": {
                    "type": "string",
                    "format": "date-time",
                    "description": (
                        "Inclusive local start time. A timezone-naive value uses timezone."
                    ),
                },
                "to_local": {
                    "type": "string",
                    "format": "date-time",
                    "description": (
                        "Optional inclusive local end time. When omitted, return one "
                        "forecast at or immediately after from_local. A timezone-naive "
                        "value uses timezone."
                    ),
                },
            },
            "required": [
                "latitude",
                "longitude",
                "timezone",
                "from_local",
            ],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "source_updated_at": {"type": ["string", "null"]},
                "location": {
                    "type": "object",
                    "properties": {
                        "latitude": {"type": "number"},
                        "longitude": {"type": "number"},
                        "altitude": {"type": ["integer", "null"]},
                    },
                    "required": ["latitude", "longitude", "altitude"],
                    "additionalProperties": False,
                },
                "timezone": {"type": "string"},
                "from_local": {"type": "string"},
                "to_local": {"type": ["string", "null"]},
                "count": {"type": "integer"},
                "hourly": {
                    "type": "array",
                    "items": _FORECAST_ROW_SCHEMA,
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "source",
                "source_updated_at",
                "location",
                "timezone",
                "from_local",
                "to_local",
                "count",
                "hourly",
                "warnings",
            ],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_forecast"],
    },
    "get_forecasts": {
        "name": "get_forecasts",
        "description": (
            "Fetch one compact MET Norway forecast for each requested geographic "
            "point and local time. Use this for route corridors after the caller has "
            "chosen the points and estimated arrival times. Results preserve request "
            "order and report source failures per point."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "minLength": 1,
                    "description": "IANA timezone shared by all requested local times.",
                },
                "requests": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 25,
                    "description": "One to 25 point-and-time forecast requests.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "description": "Caller-selected unique result identifier.",
                            },
                            "latitude": {
                                "type": "number",
                                "minimum": -90,
                                "maximum": 90,
                                "description": "Forecast latitude in decimal degrees.",
                            },
                            "longitude": {
                                "type": "number",
                                "minimum": -180,
                                "maximum": 180,
                                "description": "Forecast longitude in decimal degrees.",
                            },
                            "altitude": {
                                "type": "integer",
                                "description": "Optional altitude above sea level in metres.",
                            },
                            "at_local": {
                                "type": "string",
                                "format": "date-time",
                                "description": (
                                    "Requested local time. A timezone-naive value uses "
                                    "the shared timezone."
                                ),
                            },
                        },
                        "required": ["id", "latitude", "longitude", "at_local"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["timezone", "requests"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "timezone": {"type": "string"},
                "count": {"type": "integer"},
                "success_count": {"type": "integer"},
                "error_count": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "requested_at_local": {"type": "string"},
                            "location": {
                                "type": "object",
                                "properties": {
                                    "latitude": {"type": "number"},
                                    "longitude": {"type": "number"},
                                    "altitude": {"type": ["integer", "null"]},
                                },
                                "required": ["latitude", "longitude", "altitude"],
                                "additionalProperties": False,
                            },
                            "source_updated_at": {"type": ["string", "null"]},
                            "forecast": {"anyOf": [_FORECAST_ROW_SCHEMA, {"type": "null"}]},
                            "error": {"type": ["string", "null"]},
                        },
                        "required": [
                            "id",
                            "requested_at_local",
                            "location",
                            "source_updated_at",
                            "forecast",
                            "error",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "source",
                "timezone",
                "count",
                "success_count",
                "error_count",
                "results",
            ],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_forecasts"],
    },
}


_route_properties = {
    "timezone": {"type": "string", "minLength": 1},
    "geometry": yr_observations.object_schema({
        "type": {"const": "LineString"},
        "coordinates": {"type": "array", "minItems": 2, "maxItems": 50000,
                        "items": {"type": "array", "minItems": 2, "maxItems": 3,
                                  "items": {"type": "number"}}},
    }, ["type", "coordinates"]),
    "sample_count": {"type": "integer", "minimum": 2, "maximum": 25, "default": 5},
}
_route_required = ["timezone", "geometry"]
_distance_schema = {"type": "number"}
_forecast_range = yr_observations.object_schema(
    {"min": {"type": "number"}, "max": {"type": "number"}}, ["min", "max"]
)
_forecast_summary_point = {
    "id": {"type": "string"},
    **yr_observations.POINT,
    "distance_km": _distance_schema,
    "requested_at_local": {"type": "string"},
    "from_local": {"type": "string"},
    "to_local": {"type": "string"},
    "covered_from_local": _NULLABLE_STRING,
    "covered_to_local": _NULLABLE_STRING,
    "source_updated_at": _NULLABLE_STRING,
    "missing_hours": {"type": "integer"},
    "temperature_c": {"anyOf": [_forecast_range, {"type": "null"}]},
    "wind_speed_mps": {"anyOf": [_forecast_range, {"type": "null"}]},
    "wind_from_degrees": {"type": "array", "items": {"type": "number"}},
    "precipitation_mm_overlapping_hours": _NULLABLE_NUMBER,
    "error": _NULLABLE_STRING,
}
_forecast_route_output = {
    "source": {"type": "string"},
    "timezone": _route_properties["timezone"],
    "distance_km": _distance_schema,
    "timing_method": {"enum": ["distance", "recorded_elapsed_time"]},
    "results": {"type": "array", "items": yr_observations.object_schema(
        _forecast_summary_point, list(_forecast_summary_point)
    )},
}
TOOL_DEFINITIONS["get_route_forecasts_summary"] = yr_observations.definition(
    "get_route_forecasts_summary",
    "Summarize weather around estimated passage times along a GeoJSON LineString. "
    "Uses distance-proportional timing or scales recorded elapsed times.",
    {
        **_route_properties,
        "start_local": yr_observations.TIME,
        "duration_minutes": {"type": "number", "exclusiveMinimum": 0, "maximum": 1440},
        "elapsed_seconds": {"type": "array", "minItems": 2, "maxItems": 50000,
                            "items": {"type": "number", "minimum": 0}},
        "window_minutes": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30,
                           "description": "Minutes before and after each passage."},
    },
    [*_route_required, "start_local", "duration_minutes"],
    yr_observations.object_schema(_forecast_route_output, list(_forecast_route_output)),
)
_summary_tool = yr_observations.TOOL_DEFINITIONS["get_observations_summary"]
_summary_input = _summary_tool["inputSchema"]["properties"]
_summary_output = _summary_tool["outputSchema"]
_summary_result = _summary_output["properties"]["results"]["items"]
TOOL_DEFINITIONS["get_route_observations_summary"] = yr_observations.definition(
    "get_route_observations_summary",
    "Summarize Frost weather history near sampled route points over one shared window. "
    "Returns station references and compact summaries of temperature, precipitation and snow depth.",
    {
        **_route_properties,
        **{key: _summary_input[key] for key in ("from_local", "to_local", "elements", "radius_km")},
    },
    [*_route_required, "from_local", "to_local", "elements"],
    yr_observations.object_schema({
        **_summary_output["properties"],
        "distance_km": _distance_schema,
        "results": {"type": "array", "items": yr_observations.object_schema({
            **_summary_result["properties"], **yr_observations.POINT,
            "distance_km": _distance_schema,
        }, [*_summary_result["required"], *yr_observations.POINT, "distance_km"])},
    }, [*_summary_output["required"], "distance_km"]),
)
for _name in ("get_route_forecasts_summary", "get_route_observations_summary"):
    TOOL_ANNOTATIONS[_name] = TOOL_DEFINITIONS[_name]["annotations"]

TOOL_DEFINITIONS.update(yr_observations.TOOL_DEFINITIONS)
TOOL_ANNOTATIONS.update({name: tool["annotations"] for name, tool in yr_observations.TOOL_DEFINITIONS.items()})


class ToolFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class YrLiveService:
    def get_forecast(
        self, *, latitude: float, longitude: float, altitude: int | None
    ) -> dict[str, Any]:
        return fetch_locationforecast(
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
        )


class YrToolService:
    def __init__(self, service_factory: Callable[[], Any] = YrLiveService,
                 frost_factory: Callable[[], Any] = yr_observations.FrostClient) -> None:
        self._service_factory = service_factory
        self._frost_factory = frost_factory
        self._frost_client = None
        self._frost_lock = Lock()

    def _frost(self):
        with self._frost_lock:
            if self._frost_client is None:
                self._frost_client = yr_observations.CachedFrostClient(self._frost_factory())
            return self._frost_client

    def list_tools(self) -> list[dict[str, Any]]:
        return [TOOL_DEFINITIONS[name] for name in ALL_TOOL_NAMES]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALL_TOOL_NAMES:
            raise ToolFailure("unknown_tool", f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise ToolFailure("invalid_arguments", "arguments must be an object")

        if name in yr_observations.TOOL_DEFINITIONS:
            try:
                return yr_observations.call_tool(name, arguments, self._frost())
            except yr_observations.ObservationFailure as exc:
                raise ToolFailure(exc.code, str(exc)) from exc

        schema = TOOL_DEFINITIONS[name]["inputSchema"]
        unknown = set(arguments) - set(schema["properties"])
        if unknown:
            raise ToolFailure(
                "invalid_arguments", f"unknown argument: {sorted(unknown)[0]}"
            )
        missing = [key for key in schema["required"] if key not in arguments]
        if missing:
            raise ToolFailure(
                "invalid_arguments", f"missing required argument: {missing[0]}"
            )
        if name == "get_forecasts":
            return self._call_forecasts(arguments)
        if name in ("get_route_forecasts_summary", "get_route_observations_summary"):
            return self._call_route_tool(name, arguments)

        latitude = _number(arguments["latitude"], "latitude", -90, 90)
        longitude = _number(arguments["longitude"], "longitude", -180, 180)
        altitude = arguments.get("altitude")
        if altitude is not None and (
            not isinstance(altitude, int) or isinstance(altitude, bool)
        ):
            raise ToolFailure("invalid_arguments", "altitude must be an integer")

        timezone_name = arguments["timezone"]
        if not isinstance(timezone_name, str) or not timezone_name:
            raise ToolFailure("invalid_arguments", "timezone must be a non-empty string")
        timezone = _timezone(timezone_name)

        from_local = _local_datetime(arguments["from_local"], timezone, "from_local")
        to_local = (
            _local_datetime(arguments["to_local"], timezone, "to_local")
            if "to_local" in arguments
            else None
        )
        if to_local is not None and from_local > to_local:
            raise ToolFailure(
                "invalid_arguments", "from_local must be before or equal to to_local"
            )

        try:
            forecast = self._service_factory().get_forecast(
                latitude=latitude,
                longitude=longitude,
                altitude=altitude,
            )
            if to_local is None:
                available_rows = compact_hourly_forecast(
                    forecast,
                    local_timezone=timezone,
                )
                rows = _first_row_at_or_after(available_rows, from_local)
            else:
                rows = compact_hourly_forecast(
                    forecast,
                    local_timezone=timezone,
                    from_local=from_local,
                    to_local=to_local,
                )
        except (RuntimeError, TypeError, ValueError) as exc:
            raise ToolFailure("source_error", str(exc)) from exc

        warnings = []
        if not rows:
            warnings.append("No forecast hours were available in the requested window.")
        if any(
            row["precipitation_amount_next_1h"] is None
            and row["precipitation_amount_next_6h"] is not None
            for row in rows
        ):
            warnings.append(
                "Hourly precipitation is unavailable for some rows; the 6-hour amount "
                "is a period total and must not be treated as hourly rain."
            )

        properties = forecast.get("properties") or {}
        meta = properties.get("meta") or {}
        return {
            "source": "MET Norway Locationforecast 2.0 compact",
            "source_updated_at": meta.get("updated_at"),
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "altitude": altitude,
            },
            "timezone": timezone_name,
            "from_local": from_local.isoformat(timespec="seconds"),
            "to_local": (
                None if to_local is None else to_local.isoformat(timespec="seconds")
            ),
            "count": len(rows),
            "hourly": rows,
            "warnings": warnings,
        }

    def _call_route_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from jsonschema import Draft202012Validator

        schema = TOOL_DEFINITIONS[name]["inputSchema"]
        error = next(Draft202012Validator(schema).iter_errors(arguments), None)
        if error:
            path = ".".join(map(str, error.absolute_path)) or "arguments"
            raise ToolFailure("invalid_arguments", f"invalid {path}: {error.validator}")

        coordinates = arguments["geometry"]["coordinates"]
        for point in coordinates:
            _number(point[0], "longitude", -180, 180)
            _number(point[1], "latitude", -90, 90)
        distances = list(accumulate(
            (yr_observations.distance(a[1], a[0], b) for a, b in pairwise(coordinates)),
            initial=0.0,
        ))
        total = distances[-1]
        if total <= 0:
            raise ToolFailure("invalid_arguments", "route must have positive distance")
        historical = name == "get_route_observations_summary"
        elapsed = arguments.get("elapsed_seconds")
        if not historical:
            timezone = _timezone(arguments["timezone"])
            try:
                start = yr_observations.local_time(arguments["start_local"], timezone).astimezone(UTC)
            except yr_observations.ObservationFailure as exc:
                raise ToolFailure(exc.code, str(exc)) from exc
            duration = _number(arguments["duration_minutes"], "duration_minutes", 0, 1440)
        if elapsed is not None:
            if (len(elapsed) != len(coordinates) or elapsed[0] != 0
                    or not 0 < elapsed[-1] < float("inf")
                    or not all(0 <= a <= b for a, b in pairwise(elapsed))):
                raise ToolFailure("invalid_arguments",
                                  "elapsed_seconds must start at zero, be finite and ordered, "
                                  "and match the coordinates with a positive final time")

        sample_count = arguments.get("sample_count", 5)
        sample_distances = [total * (i / (sample_count - 1)) for i in range(sample_count)]
        requests = []
        for index, distance in enumerate(sample_distances):
            if index in (0, sample_count - 1):
                longitude, latitude = coordinates[0 if index == 0 else -1][:2]
                progress = 0 if index == 0 else 1
            else:
                right = bisect_left(distances, distance)
                left = right - 1
                fraction = (distance - distances[left]) / (distances[right] - distances[left])
                lon1, lat1 = coordinates[left][:2]
                lon2, lat2 = coordinates[right][:2]
                longitude = (lon1 + fraction * ((lon2 - lon1 + 180) % 360 - 180) + 180) % 360 - 180
                latitude = lat1 + fraction * (lat2 - lat1)
                progress = distance / total
                if elapsed is not None:
                    passage = elapsed[left] + fraction * (elapsed[right] - elapsed[left])
                    progress = passage / elapsed[-1]
            point = {"id": str(index + 1), "latitude": latitude, "longitude": longitude}
            if not historical:
                at = start + timedelta(seconds=round(duration * 60 * progress))
                point["at_local"] = at
            requests.append(point)

        if historical:
            batch = {key: arguments[key] for key in
                     ("timezone", "from_local", "to_local", "elements", "radius_km")
                     if key in arguments}
            result = self.call_tool("get_observations_summary", {**batch, "points": requests})
            for point, request in zip(result["results"], requests, strict=True):
                point.update(request)
        else:
            margin = timedelta(minutes=arguments.get("window_minutes", 30))
            result = {
                "source": "MET Norway Locationforecast 2.0 compact",
                "timezone": arguments["timezone"],
                "timing_method": "distance" if elapsed is None else "recorded_elapsed_time",
                "results": [self._route_forecast_window(point, timezone, margin) for point in requests],
            }
        for point, distance in zip(result["results"], sample_distances, strict=True):
            point["distance_km"] = round(distance, 3)
        result["distance_km"] = round(total, 3)
        return result

    def _route_forecast_window(self, point, timezone, margin):
        passage = point["at_local"]
        start, end = passage - margin, passage + margin
        first_hour = start.replace(minute=0, second=0, microsecond=0)
        hour = timedelta(hours=1)
        last_hour = end.replace(minute=0, second=0, microsecond=0)
        if last_hour == end:
            last_hour -= hour

        def local(dt):
            return dt.astimezone(timezone).isoformat(timespec="seconds")

        result = {
            "id": point["id"], "latitude": point["latitude"], "longitude": point["longitude"],
            "requested_at_local": local(passage), "from_local": local(start), "to_local": local(end),
            "covered_from_local": None, "covered_to_local": None, "source_updated_at": None,
            "missing_hours": (last_hour - first_hour) // hour + 1,
            "temperature_c": None, "wind_speed_mps": None, "wind_from_degrees": [],
            "precipitation_mm_overlapping_hours": None, "error": None,
        }
        try:
            forecast = self.call_tool("get_forecast", {
                "latitude": point["latitude"], "longitude": point["longitude"],
                "timezone": str(timezone), "from_local": first_hour.isoformat(),
                "to_local": last_hour.isoformat(),
            })
        except ToolFailure as exc:
            result["error"] = str(exc)
            return result

        result["source_updated_at"] = forecast["source_updated_at"]
        rows = forecast["hourly"]
        if not rows:
            result["error"] = forecast["warnings"][0]
            return result

        result["missing_hours"] -= len(rows)
        first = datetime.fromisoformat(rows[0]["time_utc"])
        last = datetime.fromisoformat(rows[-1]["time_utc"])
        result["covered_from_local"] = local(max(start, first))
        result["covered_to_local"] = local(min(end, last + hour))
        for field, output in (("air_temperature", "temperature_c"), ("wind_speed", "wind_speed_mps")):
            values = [row[field] for row in rows if row[field] is not None]
            if values:
                result[output] = {"min": min(values), "max": max(values)}
        result["wind_from_degrees"] = sorted({row["wind_from_direction"] for row in rows
                                              if row["wind_from_direction"] is not None})
        rain = [row["precipitation_amount_next_1h"] for row in rows]
        if not result["missing_hours"] and None not in rain:
            result["precipitation_mm_overlapping_hours"] = round(sum(rain), 3)
        return result

    def _call_forecasts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        timezone_name = arguments["timezone"]
        if not isinstance(timezone_name, str) or not timezone_name:
            raise ToolFailure("invalid_arguments", "timezone must be a non-empty string")
        timezone = _timezone(timezone_name)
        requests = arguments["requests"]
        if not isinstance(requests, list) or not 1 <= len(requests) <= 25:
            raise ToolFailure(
                "invalid_arguments", "requests must contain between 1 and 25 items"
            )

        allowed = {"id", "latitude", "longitude", "altitude", "at_local"}
        required = {"id", "latitude", "longitude", "at_local"}
        validated = []
        seen_ids: set[str] = set()
        for index, request in enumerate(requests):
            prefix = f"requests[{index}]"
            if not isinstance(request, dict):
                raise ToolFailure("invalid_arguments", f"{prefix} must be an object")
            unknown = set(request) - allowed
            if unknown:
                raise ToolFailure(
                    "invalid_arguments",
                    f"unknown argument in {prefix}: {sorted(unknown)[0]}",
                )
            missing = sorted(required - set(request))
            if missing:
                raise ToolFailure(
                    "invalid_arguments",
                    f"missing required argument in {prefix}: {missing[0]}",
                )
            request_id = request["id"]
            if not isinstance(request_id, str) or not request_id:
                raise ToolFailure(
                    "invalid_arguments", f"{prefix}.id must be a non-empty string"
                )
            if request_id in seen_ids:
                raise ToolFailure(
                    "invalid_arguments", f"duplicate request id: {request_id}"
                )
            seen_ids.add(request_id)
            latitude = _number(request["latitude"], f"{prefix}.latitude", -90, 90)
            longitude = _number(
                request["longitude"], f"{prefix}.longitude", -180, 180
            )
            altitude = request.get("altitude")
            if altitude is not None and (
                not isinstance(altitude, int) or isinstance(altitude, bool)
            ):
                raise ToolFailure(
                    "invalid_arguments", f"{prefix}.altitude must be an integer"
                )
            at_local = _local_datetime(
                request["at_local"], timezone, f"{prefix}.at_local"
            )
            validated.append(
                {
                    "id": request_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "altitude": altitude,
                    "at_local": at_local,
                }
            )

        results = []
        for request in validated:
            location = {
                "latitude": request["latitude"],
                "longitude": request["longitude"],
                "altitude": request["altitude"],
            }
            requested_at = request["at_local"].isoformat(timespec="seconds")
            try:
                single = self.call_tool(
                    "get_forecast",
                    {
                        **location,
                        "timezone": timezone_name,
                        "from_local": requested_at,
                    },
                )
            except ToolFailure as exc:
                results.append(
                    {
                        "id": request["id"],
                        "requested_at_local": requested_at,
                        "location": location,
                        "source_updated_at": None,
                        "forecast": None,
                        "error": str(exc),
                    }
                )
                continue
            forecast = single["hourly"][0] if single["hourly"] else None
            results.append(
                {
                    "id": request["id"],
                    "requested_at_local": requested_at,
                    "location": location,
                    "source_updated_at": single["source_updated_at"],
                    "forecast": forecast,
                    "error": None if forecast is not None else single["warnings"][0],
                }
            )

        success_count = sum(result["forecast"] is not None for result in results)
        return {
            "source": "MET Norway Locationforecast 2.0 compact",
            "timezone": timezone_name,
            "count": len(results),
            "success_count": success_count,
            "error_count": len(results) - success_count,
            "results": results,
        }


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ToolFailure("invalid_arguments", f"{field} must be a number")
    value = float(value)
    if not minimum <= value <= maximum:
        raise ToolFailure(
            "invalid_arguments", f"{field} must be between {minimum:g} and {maximum:g}"
        )
    return value


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ToolFailure("invalid_arguments", f"unknown IANA timezone: {value}") from exc


def _first_row_at_or_after(
    rows: list[dict[str, Any]],
    requested_at: datetime,
) -> list[dict[str, Any]]:
    for row in rows:
        row_time = datetime.fromisoformat(str(row["time_local"]))
        if row_time >= requested_at:
            return [row]
    return []


def _local_datetime(value: Any, timezone: ZoneInfo, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ToolFailure("invalid_arguments", f"{field} must be a date-time string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ToolFailure("invalid_arguments", f"invalid {field}: {exc}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def create_sdk_server(service: YrToolService) -> Any:
    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server(
        "yr",
        version="0.3.1",
        instructions=(
            "Fetch MET Norway point forecasts and station-backed Frost historical observations. "
            "The caller owns geocoding, route-point and arrival-time selection, route "
            "aggregation, persistence, plotting, and weather-dependent decisions."
        ),
    )

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [mcp_types.Tool.model_validate(item) for item in service.list_tools()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        try:
            payload = await anyio.to_thread.run_sync(service.call_tool, name, arguments)
        except ToolFailure as exc:
            error_payload = {"error": str(exc), "errorCode": exc.code}
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(exc))],
                structuredContent=error_payload,
                isError=True,
            )
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=text)],
            structuredContent=payload,
        )

    return server


async def serve_async(service_factory: Callable[[], Any] = YrLiveService) -> None:
    from mcp.server.stdio import stdio_server

    server = create_sdk_server(YrToolService(service_factory))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve(service_factory: Callable[[], Any] = YrLiveService) -> int:
    try:
        import anyio

        anyio.run(serve_async, service_factory)
    except Exception as exc:
        print(f"Yr MCP internal error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return serve(YrLiveService)


if __name__ == "__main__":
    raise SystemExit(main())
