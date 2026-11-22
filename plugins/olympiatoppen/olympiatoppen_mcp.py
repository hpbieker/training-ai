#!/usr/bin/env python3
"""Local MCP server for reading Olympiatoppen diary sessions."""
from __future__ import annotations

import json
import sys
from typing import Any

from olympiatoppen_service import OlympiatoppenToolService, ToolFailure


TOOL_DEFINITIONS = {
    "import_session": {
        "name": "import_session",
        "description": (
            "Verify a Cookie header obtained from the authenticated Olympiatoppen browser tab, "
            "replace the locally saved session, and return only verification status. "
            "Do not pass cookies from other sites or include them in any other tool call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cookie_header": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Cookie header read from the authenticated Olympiatoppen site in Nettleser. "
                        "Sensitive session credential; do not include unrelated headers or cURL text."
                    ),
                },
            },
            "required": ["cookie_header"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {"stored": {"type": "boolean"}, "verified": {"type": "boolean"}},
            "required": ["stored", "verified"],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "Save Olympiatoppen Session", "readOnlyHint": False,
            "destructiveHint": True, "idempotentHint": True, "openWorldHint": True,
        },
    },
    "get_session_status": {
        "name": "get_session_status",
        "description": (
            "Check whether the saved diary session exists, has private file permissions, and is currently valid."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "outputSchema": {
            "type": "object",
            "properties": {"stored": {"type": "boolean"}, "verified": {"type": "boolean"}},
            "required": ["stored", "verified"],
            "additionalProperties": False,
        },
        "annotations": {"title": "Check Olympiatoppen Session", "readOnlyHint": True, "openWorldHint": True},
    },
    "list_workouts": {
        "name": "list_workouts",
        "description": (
            "List logged diary sessions in an inclusive date range. Returns dates, names, descriptions, "
            "recorded activity metrics, and sessionMetrics such as perceived load and daily form."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_date": {"type": "string", "format": "date"},
                "to_date": {"type": "string", "format": "date"},
            },
            "required": ["from_date", "to_date"],
            "additionalProperties": False,
        },
        "outputSchema": {"type": "object", "additionalProperties": True},
        "annotations": {"title": "List Olympiatoppen Workouts", "readOnlyHint": True, "openWorldHint": True},
    },
    "get_activity": {
        "name": "get_activity",
        "description": (
            "Retrieve one exact session by its session ID within a required inclusive date range. "
            "Use the logged local date as both bounds when known."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "minLength": 1},
                "from_date": {"type": "string", "format": "date"},
                "to_date": {"type": "string", "format": "date"},
            },
            "required": ["session_id", "from_date", "to_date"],
            "additionalProperties": False,
        },
        "outputSchema": {"type": "object", "additionalProperties": True},
        "annotations": {"title": "Get Olympiatoppen Workout", "readOnlyHint": True, "openWorldHint": True},
    },
    "clear_session": {
        "name": "clear_session",
        "description": "Remove the locally saved diary session cookie.",
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "outputSchema": {
            "type": "object", "properties": {"cleared": {"type": "boolean"}},
            "required": ["cleared"], "additionalProperties": False,
        },
        "annotations": {
            "title": "Clear Olympiatoppen Session", "readOnlyHint": False,
            "destructiveHint": True, "idempotentHint": True, "openWorldHint": False,
        },
    },
}


def create_sdk_server(service: OlympiatoppenToolService | None = None) -> Any:
    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    tool_service = service or OlympiatoppenToolService()
    server = Server(
        "olympiatoppen",
        version="0.1.4",
        instructions=(
            "Read Olympiatoppen diary sessions using the Olympiatoppen skill. "
            "Session authentication is stored locally and never returned by tools. "
            "Use list_workouts or get_activity for bounded reads. If a diary call returns auth_required, "
            "follow the Olympiatoppen skill to import a cookie from Nettleser, then repeat the failed call."
        ),
    )

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [mcp_types.Tool.model_validate(row) for row in TOOL_DEFINITIONS.values()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        try:
            payload = await anyio.to_thread.run_sync(tool_service.call_tool, name, arguments)
        except ToolFailure as exc:
            payload = {"error": str(exc), "errorCode": exc.code}
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                structuredContent=payload,
                isError=True,
            )
        except (OSError, ValueError) as exc:
            payload = {"error": str(exc), "errorCode": "invalid_arguments"}
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                structuredContent=payload,
                isError=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))],
            structuredContent=payload,
        )

    return server


async def serve_async() -> None:
    from mcp.server.stdio import stdio_server

    server = create_sdk_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    import anyio

    try:
        anyio.run(serve_async)
    except Exception as exc:
        print(f"Olympiatoppen MCP internal error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
