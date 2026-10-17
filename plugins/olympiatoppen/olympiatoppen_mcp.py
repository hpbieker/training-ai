#!/usr/bin/env python3
"""Local MCP server for reading Olympiatoppen diary sessions."""
from __future__ import annotations

import json
import sys
from typing import Any

from olympiatoppen_service import OlympiatoppenToolService, ToolFailure


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
        return [mcp_types.Tool.model_validate(row) for row in tool_service.list_tools()]

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
