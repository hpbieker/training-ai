#!/usr/bin/env python3
"""Local, cookie-backed Strava tools using the official Python MCP SDK."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import strava_activity_service as activities
from strava_route_api import StravaAuthRequired, StravaError


class ToolFailure(RuntimeError):
    def __init__(self, message: str, code: str = "tool_error", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details


ID = {"type": "string", "pattern": "^[0-9]+$", "description": "Exact Strava ID returned by a read tool."}
VISIBILITY = {"type": "string", "enum": ["everyone", "followers_only", "only_me"]}
PATCH = {
    "type": "object", "additionalProperties": False, "minProperties": 1,
    "description": "Only supplied fields change. Use null to clear the primary tag; bike_id='none' clears the bike.",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "tag": {"type": ["string", "null"], "enum": [None, *activities.TAG_ID_TO_NAME.values()]},
        "trainer": {"type": "boolean"},
        "visibility": VISIBILITY,
        "start_time_hidden": {"type": "boolean"},
        "mute": {"type": "boolean"},
        "bike_id": {"type": "string", "pattern": "^(?:[0-9]+|none)$"},
        "bike_name": {"type": "string", "minLength": 1, "description": "Exact edit-form bike name, or 'none' to clear."},
    },
    "not": {"required": ["bike_id", "bike_name"]},
}


def _tool(name: str, description: str, properties: dict, required: list[str], *, write: bool = False) -> dict:
    return {
        "name": name, "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "annotations": {
            "readOnlyHint": not write, "destructiveHint": write,
            "idempotentHint": not write, "openWorldHint": True,
        },
    }


TOOL_DEFINITIONS = {row["name"]: row for row in [
    _tool("list_activities", "Find activities in an inclusive local date range, optionally filtered by visibility.", {
        "since": {"type": "string", "format": "date"},
        "until": {"type": "string", "format": "date", "description": "Defaults to today's local date."},
        "visibility": VISIBILITY,
        "max_pages": {"type": "integer", "minimum": 1, "default": 20},
        "per_page": {"type": "integer", "minimum": 1, "default": 100},
    }, ["since"]),
    _tool("get_activity", "Read one activity and current editable metadata, including bike and start-time privacy.", {"activity_id": ID}, ["activity_id"]),
    _tool("list_gear", "List the account's active and retired bikes and shoes.", {}, []),
    _tool("get_gear", "Read one bike or shoe from the account's gear collections.", {
        "gear_id": ID, "gear_type": {"type": "string", "enum": ["bike", "shoe"]},
    }, ["gear_id"]),
    _tool("update_activity", "Apply an explicitly authorized metadata patch and verify it through fresh readback. On failure, read current state before retrying.", {
        "activity_id": ID, "patch": PATCH, "confirm": {"type": "boolean", "const": True},
    }, ["activity_id", "patch", "confirm"], write=True),
    _tool("update_activities", "Apply one authorized patch to several activities, verifying each. Partial failures include updated, failed, and not_attempted IDs; never blindly retry the whole batch.", {
        "activity_ids": {"type": "array", "items": ID, "minItems": 1, "uniqueItems": True},
        "patch": PATCH, "confirm": {"type": "boolean", "const": True},
    }, ["activity_ids", "patch", "confirm"], write=True),
]}

# The legacy metadata helper has a module-global SESSION. Protect the entire
# operation (including readback), across service instances in this process.
_SESSION_LOCK = threading.Lock()


class StravaToolService:
    def list_tools(self) -> list[dict[str, Any]]:
        return list(TOOL_DEFINITIONS.values())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from jsonschema import Draft202012Validator, FormatChecker

        if name not in TOOL_DEFINITIONS:
            raise ToolFailure(f"Unknown tool: {name}", "unknown_tool")
        validator = Draft202012Validator(TOOL_DEFINITIONS[name]["inputSchema"], format_checker=FormatChecker())
        error = next(validator.iter_errors(arguments), None)
        if error:
            # Validation messages may contain arbitrary user-supplied values.
            raise ToolFailure(f"Invalid arguments for {name}; check the tool schema.", "invalid_arguments")
        try:
            with _SESSION_LOCK:
                # Each service function creates a fresh StravaSession and reads
                # the private cookie file. No browser launch, refresh or retry.
                payload = getattr(activities, name)(**arguments)
            if name == "update_activities" and not payload["complete"]:
                code = "auth_required" if any(row.get("errorCode") == "auth_required" for row in payload["failed"]) else "partial_failure"
                raise ToolFailure("Batch incomplete. Inspect results and read current state before retrying failed activities.", code, payload)
            return payload
        except StravaAuthRequired as exc:
            raise ToolFailure(str(exc), "auth_required") from exc
        except (TypeError, ValueError) as exc:
            raise ToolFailure(str(exc), "invalid_arguments") from exc
        except (OSError, StravaError) as exc:
            raise ToolFailure(str(exc)) from exc


def create_sdk_server(service: StravaToolService) -> Any:
    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server("strava", version="0.1.0", instructions=(
        "Read Strava activities and gear; apply explicitly authorized metadata changes with fresh readback. "
        "auth_required means follow the Strava skill to renew the private browser session, then call again. "
        "For failed writes, read current state before retrying. Never send cookies in tool arguments. "
        "Authentication is external; this server does not open Safari or refresh sessions."
    ))

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [mcp_types.Tool.model_validate(row) for row in service.list_tools()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        try:
            payload = await anyio.to_thread.run_sync(service.call_tool, name, arguments)
        except ToolFailure as exc:
            payload = {"error": str(exc), "errorCode": exc.code}
            if exc.details is not None:
                payload["details"] = exc.details
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                structuredContent=payload, isError=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))],
            structuredContent=payload,
        )

    return server


async def serve_async() -> None:
    from mcp.server.stdio import stdio_server

    server = create_sdk_server(StravaToolService())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    import anyio

    anyio.run(serve_async)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
