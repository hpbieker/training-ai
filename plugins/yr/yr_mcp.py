#!/usr/bin/env python3
"""Expose compact MET Norway Locationforecast point forecasts over MCP."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from yr_weather import compact_hourly_forecast, fetch_locationforecast


ALL_TOOL_NAMES = ("get_forecast", "get_forecasts")

TOOL_ANNOTATIONS = {
    "get_forecast": {
        "title": "Get Yr Forecast",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_forecasts": {
        "title": "Get Yr Forecasts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
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
    def __init__(self, service_factory: Callable[[], Any] = YrLiveService) -> None:
        self._service_factory = service_factory

    def list_tools(self) -> list[dict[str, Any]]:
        return [TOOL_DEFINITIONS[name] for name in ALL_TOOL_NAMES]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALL_TOOL_NAMES:
            raise ToolFailure("unknown_tool", f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise ToolFailure("invalid_arguments", "arguments must be an object")

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
        version="0.2.0",
        instructions=(
            "Fetch compact MET Norway point forecasts singly or in a bounded batch. "
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
