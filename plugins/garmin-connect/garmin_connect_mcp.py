#!/usr/bin/env python3
"""Expose focused Garmin Connect health and activity reads through MCP."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from garmin_connect_api import (  # noqa: E402
    DAILY_SPEC_CHOICES,
    compact_day_payload,
    compact_recent_payload,
    delete_course,
    fetch_activity,
    fetch_course,
    fetch_courses,
    fetch_day,
    fetch_recent_days,
    garmin_activity_search,
    local_now,
    resolve_gccli,
    upload_course,
)


ALL_TOOL_NAMES = (
    "get_health_day",
    "list_health_days",
    "list_activities",
    "get_activity",
    "list_courses",
    "get_course",
    "create_course",
    "delete_course",
)

ANNOTATIONS: dict[str, dict[str, object]] = {
    name: {
        "title": " ".join(part.capitalize() for part in name.split("_")),
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    for name in ALL_TOOL_NAMES
}
ANNOTATIONS["create_course"].update(readOnlyHint=False, idempotentHint=False)
ANNOTATIONS["delete_course"].update(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
)


def _object(description: str) -> dict[str, object]:
    return {"type": "object", "additionalProperties": True, "description": description}


_SOURCE_ARRAY = {
    "type": "array",
    "items": {"type": "string", "enum": DAILY_SPEC_CHOICES},
    "uniqueItems": True,
    "description": "Optional Garmin daily sources. Omit for the readiness profile.",
}

TOOL_DEFINITIONS: dict[str, dict[str, object]] = {
    "get_health_day": {
        "name": "get_health_day",
        "description": (
            "Get compact normalized Garmin health and readiness data for one local date. "
            "Returns all timestamped Training Readiness observations, its six drivers, "
            "Recovery Time, VO2max context, and the requested supporting daily sources. "
            "For a future training date, request the latest date that has occurred."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "sources": _SOURCE_ARRAY,
                "tolerate_errors": {"type": "boolean", "default": True},
            },
            "required": ["date"],
            "additionalProperties": False,
        },
        "outputSchema": _object("Normalized Garmin health-day payload."),
        "annotations": ANNOTATIONS["get_health_day"],
    },
    "list_health_days": {
        "name": "list_health_days",
        "description": (
            "List compact normalized Garmin health data through an inclusive ending "
            "local date. Use this for HRV, sleep, Body Battery, stress, readiness, or "
            "recovery trends; do not carry same-day observations into future dates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "until": {"type": "string", "format": "date"},
                "days": {"type": "integer", "minimum": 1, "maximum": 31, "default": 7},
                "sources": _SOURCE_ARRAY,
                "tolerate_errors": {"type": "boolean", "default": True},
            },
            "required": ["until"],
            "additionalProperties": False,
        },
        "outputSchema": _object("Normalized Garmin health-day range payload."),
        "annotations": ANNOTATIONS["list_health_days"],
    },
    "list_activities": {
        "name": "list_activities",
        "description": (
            "List Garmin activities in an inclusive local-date range. Use the same "
            "date for since and until when resolving an exact same-day activity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "format": "date"},
                "until": {"type": "string", "format": "date"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
            "required": ["since", "until"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "source_time_local": {"type": "string"},
                "since": {"type": "string"},
                "until": {"type": "string"},
                "count": {"type": "integer"},
                "activities": {"type": "array", "items": _object("Garmin activity summary.")},
            },
            "required": ["source", "source_time_local", "since", "until", "count", "activities"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["list_activities"],
    },
    "get_activity": {
        "name": "get_activity",
        "description": (
            "Get normalized Garmin model context for one activity: Training Effect, "
            "load, Stamina, and Performance Condition. Accepts a Garmin activity ID, "
            "Raw Garmin chart samples are used internally but are not returned."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "minLength": 1},
            },
            "required": ["activity_id"],
            "additionalProperties": False,
        },
        "outputSchema": _object("Normalized Garmin activity model summary."),
        "annotations": ANNOTATIONS["get_activity"],
    },
    "list_courses": {
        "name": "list_courses",
        "description": (
            "List the Garmin Connect user's saved courses (planned routes), including "
            "IDs, names, sport types, distance, elevation, start coordinates, and source."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputSchema": _object("Garmin saved-course list."),
        "annotations": ANNOTATIONS["list_courses"],
    },
    "get_course": {
        "name": "get_course",
        "description": (
            "Get one saved Garmin course with its full geometry and named course points. "
            "Use this immediately before copying or deleting a course."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"course_id": {"type": "string", "minLength": 1}},
            "required": ["course_id"],
            "additionalProperties": False,
        },
        "outputSchema": _object("Full Garmin saved-course payload."),
        "annotations": ANNOTATIONS["get_course"],
    },
    "create_course": {
        "name": "create_course",
        "description": (
            "Create a Garmin course from a raw Garmin course object or the wrapper "
            "returned by get_course. Preserves accepted geometry and course points, "
            "then reads the new course back and reports verification mismatches. "
            "Use a distinct name for a copy unless explicitly requested otherwise."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "course": _object("Raw Garmin course or get_course wrapper."),
                "name": {"type": "string", "minLength": 1},
                "privacy": {"type": "integer", "enum": [1, 2, 4], "default": 2},
            },
            "required": ["course"],
            "additionalProperties": False,
        },
        "outputSchema": _object("Created Garmin course and read-back verification."),
        "annotations": ANNOTATIONS["create_course"],
    },
    "delete_course": {
        "name": "delete_course",
        "description": (
            "Permanently delete exactly one Garmin course. Resolve it with get_course "
            "immediately beforehand and pass the identical ID as confirm_course_id. "
            "Success requires a post-delete course-list verification."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string", "minLength": 1},
                "confirm_course_id": {"type": "string", "minLength": 1},
            },
            "required": ["course_id", "confirm_course_id"],
            "additionalProperties": False,
        },
        "outputSchema": _object("Verified Garmin course-deletion result."),
        "annotations": ANNOTATIONS["delete_course"],
    },
}


class ToolFailure(RuntimeError):
    def __init__(self, message: str, code: str = "tool_error") -> None:
        super().__init__(message)
        self.code = code


class GarminConnectToolService:
    def __init__(self, gccli_factory: Callable[[], str] = resolve_gccli) -> None:
        self._gccli_factory = gccli_factory

    def list_tools(self) -> list[dict[str, object]]:
        return [TOOL_DEFINITIONS[name] for name in ALL_TOOL_NAMES]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_DEFINITIONS:
            raise ToolFailure(f"Unknown Garmin Connect tool: {name}", "unknown_tool")
        try:
            return self._call_tool(name, arguments)
        except (ValueError, TypeError, KeyError) as exc:
            raise ToolFailure(str(exc), "invalid_arguments") from exc
        except SystemExit as exc:
            raise ToolFailure(str(exc), "garmin_access_error") from exc

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        gccli = self._gccli_factory()
        if name == "get_health_day":
            day = _iso_date(arguments["date"], "date")
            payload = fetch_day(
                day,
                gccli=gccli,
                only=_sources(arguments),
                profile="full" if arguments.get("sources") else "readiness",
                tolerate_errors=arguments.get("tolerate_errors", True),
            )
            return compact_day_payload(payload)
        if name == "list_health_days":
            until = _iso_date(arguments["until"], "until")
            days = arguments.get("days", 7)
            if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 31:
                raise ValueError("days must be an integer from 1 to 31")
            payload = fetch_recent_days(
                days=days,
                until=until,
                gccli=gccli,
                only=_sources(arguments),
                profile="full" if arguments.get("sources") else "readiness",
                tolerate_errors=arguments.get("tolerate_errors", True),
            )
            result = compact_recent_payload(payload)
            if "body_battery_range" in payload:
                result["body_battery_range"] = payload["body_battery_range"]
            return result
        if name == "list_activities":
            since = _iso_date(arguments["since"], "since")
            until = _iso_date(arguments["until"], "until")
            if date.fromisoformat(since) > date.fromisoformat(until):
                raise ValueError("since must be on or before until")
            limit = arguments.get("limit", 100)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
                raise ValueError("limit must be an integer from 1 to 500")
            activities = garmin_activity_search(gccli, since, until, limit=limit)
            return {
                "source": "garmin_connect_gccli",
                "source_time_local": local_now(),
                "since": since,
                "until": until,
                "count": len(activities),
                "activities": activities,
            }
        if name == "get_activity":
            activity = _required_id(arguments, "activity_id")
            payload = fetch_activity(activity, gccli=gccli, include_details=True)
            payload.pop("summary", None)
            payload.pop("details", None)
            return payload
        if name == "list_courses":
            return fetch_courses(gccli=gccli)
        if name == "get_course":
            return fetch_course(_required_id(arguments, "course_id"), gccli=gccli)
        if name == "create_course":
            course = arguments["course"]
            if not isinstance(course, dict):
                raise TypeError("course must be an object")
            name_override = arguments.get("name")
            if name_override is not None and (
                not isinstance(name_override, str) or not name_override.strip()
            ):
                raise ValueError("name must be a non-empty string when supplied")
            return upload_course(
                course,
                gccli=gccli,
                course_name=name_override.strip() if name_override else None,
                course_privacy=arguments.get("privacy", 2),
            )
        course_id = _required_id(arguments, "course_id")
        confirmed_course_id = _required_id(arguments, "confirm_course_id")
        if confirmed_course_id != course_id:
            raise ToolFailure(
                "confirm_course_id must exactly match course_id",
                "confirmation_required",
            )
        return delete_course(
            course_id,
            gccli=gccli,
            confirmed_course_id=confirmed_course_id,
        )


def _iso_date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date") from exc


def _required_id(arguments: dict[str, Any], field: str) -> str:
    value = arguments[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _sources(arguments: dict[str, Any]) -> list[str] | None:
    values = arguments.get("sources")
    if values is None:
        return None
    if not isinstance(values, list) or not values:
        raise ValueError("sources must be a non-empty array when supplied")
    if any(value not in DAILY_SPEC_CHOICES for value in values):
        raise ValueError("sources contains an unsupported Garmin daily source")
    return values


def create_sdk_server(service: GarminConnectToolService) -> Any:
    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server(
        "garmin-connect",
        version="0.1.0",
        instructions=(
            "Read compact Garmin Connect health/readiness days, activity model "
            "context, and saved courses; create and permanently delete courses with "
            "read-back verification. Garmin signals are timestamped vendor estimates; "
            "the caller owns persistence, cross-source composition, and training decisions."
        ),
    )

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [mcp_types.Tool.model_validate(definition) for definition in service.list_tools()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        try:
            payload = await anyio.to_thread.run_sync(service.call_tool, name, arguments)
        except ToolFailure as exc:
            error = {"error": str(exc), "errorCode": exc.code}
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(exc))],
                structuredContent=error,
                isError=True,
            )
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=text)],
            structuredContent=payload,
        )

    return server


async def serve_async() -> None:
    from mcp.server.stdio import stdio_server

    server = create_sdk_server(GarminConnectToolService())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    try:
        import anyio

        anyio.run(serve_async)
    except Exception as exc:
        print(f"Garmin Connect MCP internal error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
