#!/usr/bin/env python3
"""Three read-oriented Intervals.icu tools exposed through MCP."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from intervals_icu_api import (  # noqa: E402
    download_activity_streams_csv,
    get_activity,
    list_activities,
    load_intervals_icu_api_key,
)


class ToolFailure(RuntimeError):
    def __init__(self, message: str, code: str = "tool_error") -> None:
        super().__init__(message)
        self.code = code


def _object(description: str) -> dict[str, object]:
    return {"type": "object", "additionalProperties": True, "description": description}


ANNOTATIONS = {
    "list_activities": {
        "title": "List Intervals.icu Activities", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "get_activity": {
        "title": "Get Intervals.icu Activity", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "get_activity_streams": {
        "title": "Get Intervals.icu Activity Streams", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
    },
}


TOOL_DEFINITIONS: dict[str, dict[str, object]] = {
    "list_activities": {
        "name": "list_activities",
        "description": (
            "List all Intervals.icu activities in an inclusive local-date range. "
            "Use the same date for since and until to resolve today's exact activity; "
            "do not substitute a latest-activity lookup."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "format": "date", "description": "Inclusive local start date."},
                "until": {"type": "string", "format": "date", "description": "Inclusive local end date."},
            },
            "required": ["since", "until"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "string"}, "until": {"type": "string"},
                "count": {"type": "integer"},
                "activities": {"type": "array", "items": _object("Intervals.icu activity summary.")},
            },
            "required": ["since", "until", "count", "activities"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["list_activities"],
    },
    "get_activity": {
        "name": "get_activity",
        "description": (
            "Get one Intervals.icu activity by its exact Intervals.icu id, including "
            "Intervals.icu interval summaries by default."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "minLength": 1},
                "include_intervals": {"type": "boolean", "default": True},
            },
            "required": ["activity_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string"},
                "include_intervals": {"type": "boolean"},
                "activity": _object("Source-native Intervals.icu activity."),
            },
            "required": ["activity_id", "include_intervals", "activity"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["get_activity"],
    },
    "get_activity_streams": {
        "name": "get_activity_streams",
        "description": (
            "Download stream samples for one exact Intervals.icu activity to a "
            "private temporary CSV and return its path. Omit stream_types to fetch "
            "all available streams; large samples are never placed in model context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "minLength": 1},
                "stream_types": {
                    "type": "array", "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                    "description": "Optional Intervals.icu stream names. Omit or use [] for all streams.",
                },
            },
            "required": ["activity_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string"},
                "stream_types": {"type": "array", "items": {"type": "string"}},
                "streams_file": {"type": "string"},
                "byte_size": {"type": "integer"},
            },
            "required": ["activity_id", "stream_types", "streams_file", "byte_size"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["get_activity_streams"],
    },
}


class IntervalsIcuToolService:
    def __init__(
        self,
        credential_factory: Callable[[], str] = load_intervals_icu_api_key,
        activity_lister: Callable[..., list[dict[str, Any]]] = list_activities,
        activity_getter: Callable[..., dict[str, Any]] = get_activity,
        streams_downloader: Callable[..., Path] = download_activity_streams_csv,
    ) -> None:
        self._credential_factory = credential_factory
        self._activity_lister = activity_lister
        self._activity_getter = activity_getter
        self._streams_downloader = streams_downloader

    def list_tools(self) -> list[dict[str, object]]:
        return list(TOOL_DEFINITIONS.values())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_DEFINITIONS:
            raise ToolFailure(f"Unknown tool: {name}", "unknown_tool")
        unknown = set(arguments) - set(TOOL_DEFINITIONS[name]["inputSchema"]["properties"])
        if unknown:
            raise ToolFailure(f"Unsupported argument: {sorted(unknown)[0]}", "invalid_arguments")
        try:
            api_key = self._credential_factory()
            if name == "list_activities":
                since = _required_date(arguments, "since")
                until = _required_date(arguments, "until")
                if until < since:
                    raise ToolFailure("until must not be before since", "invalid_arguments")
                activities = self._activity_lister(api_key=api_key, oldest=since, newest=until)
                return {
                    "since": since.isoformat(), "until": until.isoformat(),
                    "count": len(activities), "activities": activities,
                }
            activity_id = _required_string(arguments, "activity_id")
            if name == "get_activity":
                include_intervals = arguments.get("include_intervals", True)
                if not isinstance(include_intervals, bool):
                    raise ToolFailure("include_intervals must be a boolean", "invalid_arguments")
                activity = self._activity_getter(
                    activity_id=activity_id, api_key=api_key,
                    include_intervals=include_intervals,
                )
                return {
                    "activity_id": activity_id,
                    "include_intervals": include_intervals,
                    "activity": activity,
                }
            stream_types = arguments.get("stream_types", [])
            if not isinstance(stream_types, list) or any(
                not isinstance(value, str) or not value for value in stream_types
            ):
                raise ToolFailure("stream_types must be an array of non-empty strings", "invalid_arguments")
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f"intervals-{activity_id}-", suffix="-streams.csv"
            )
            os.close(descriptor)
            os.chmod(raw_path, 0o600)
            try:
                path = self._streams_downloader(
                    activity_id=activity_id, api_key=api_key,
                    stream_types=stream_types or None, output_path=raw_path,
                )
            except Exception:
                Path(raw_path).unlink(missing_ok=True)
                raise
            return {
                "activity_id": activity_id, "stream_types": stream_types,
                "streams_file": str(path), "byte_size": path.stat().st_size,
            }
        except ToolFailure:
            raise
        except (KeyError, ValueError) as exc:
            raise ToolFailure(str(exc), "configuration_error") from exc
        except Exception as exc:
            raise ToolFailure(str(exc), "source_error") from exc


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ToolFailure(f"{key} must be a non-empty string", "invalid_arguments")
    return value


def _required_date(arguments: dict[str, Any], key: str) -> date:
    value = _required_string(arguments, key)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolFailure(f"{key} must use YYYY-MM-DD", "invalid_arguments") from exc


def create_sdk_server(service: IntervalsIcuToolService) -> Any:
    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server(
        "intervals-icu", version="0.1.0",
        instructions=(
            "Resolve a local date to exact Intervals.icu activity ids, fetch one "
            "activity and its interval summaries, and save large stream samples "
            "to a private temporary CSV for downstream analysis."
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
            error_payload = {"error": str(exc), "errorCode": exc.code}
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(exc))],
                structuredContent=error_payload, isError=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(
                type="text", text=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )],
            structuredContent=payload,
        )

    return server


async def serve_async() -> None:
    from mcp.server.stdio import stdio_server

    server = create_sdk_server(IntervalsIcuToolService())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    try:
        import anyio

        anyio.run(serve_async)
    except Exception as exc:
        print(f"Intervals.icu MCP internal error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
