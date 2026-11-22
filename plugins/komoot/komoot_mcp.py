#!/usr/bin/env python3
"""Expose Komoot tour reads, exports, and verified renames over the Python MCP SDK."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_ROOT))

from komoot_service import (
    KomootError,
    KomootWriteUnverified,
    download_tour_fit,
    download_tour_gpx,
    get_tour_metadata,
    get_tour_route,
    get_tour_line,
    list_tours,
    rename_tour,
    get_tour_waypoints,
    inspect_tour,
    compare_tours,
)


_COMMON_RESULT = {"type": "object", "additionalProperties": True}
_OUTPUT_FIELDS = {
    "tour_id": {"type": "string"},
    "file_path": {"type": "string"},
    "byte_size": {"type": "integer"},
    "format": {"const": "FIT"},
}
_EXPORT_OUTPUT = {
    "type": "object",
    "properties": {
        "tour_id": {"type": "string"},
        "file_path": {"type": "string"},
        "byte_size": {"type": "integer"},
        "format": {"const": "GPX"},
    },
    "required": ["tour_id", "file_path", "byte_size", "format"],
    "additionalProperties": False,
}

TOOL_DEFINITIONS = {
    "download_tour_fit": {
        "name": "download_tour_fit",
        "description": (
            "Download one planned Komoot tour as a FIT file using the existing Safari login. "
            "Reads matching cookies from curl-safari's local Unix socket. Cookies are never "
            "accepted as arguments or returned. Saves to <tour-id>.fit in the training-ai "
            "workspace unless output_path is supplied. Existing files require overwrite=true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tour": {"type": "string", "minLength": 1, "description": "Numeric Komoot tour ID or full tour URL."},
                "output_path": {"type": "string", "pattern": "^/", "description": "Optional absolute destination path. Defaults to <tour-id>.fit in the training-ai workspace."},
                "overwrite": {"type": "boolean", "default": False, "description": "Replace an existing output file. Defaults to false."},
            },
            "required": ["tour"],
            "additionalProperties": False,
        },
        "outputSchema": {"type": "object", "properties": _OUTPUT_FIELDS, "required": list(_OUTPUT_FIELDS), "additionalProperties": False},
        "annotations": {"title": "Download Komoot Tour as FIT", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
    },
    "download_tour_gpx": {
        "name": "download_tour_gpx",
        "description": (
            "Download one Komoot tour as a validated GPX file using the existing Safari login. "
            "Cookies are read from curl-safari's local Unix socket and never accepted as arguments. "
            "Saves to <tour-id>.gpx in the training-ai workspace unless output_path is supplied."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tour": {"type": "string", "minLength": 1, "description": "Numeric Komoot tour ID or full tour URL."},
                "output_path": {"type": "string", "pattern": "^/", "description": "Optional absolute destination path."},
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["tour"],
            "additionalProperties": False,
        },
        "outputSchema": _EXPORT_OUTPUT,
        "annotations": {"title": "Download Komoot Tour as GPX", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
    },
    "list_tours": {
        "name": "list_tours",
        "description": (
            "List tours belonging to the currently signed-in Komoot account. Defaults to planned tours. "
            "Returns compact metadata and pagination; use next_page to continue, and get_tour_metadata "
            "or get_tour_route for a selected tour."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tour_type": {"type": "string", "enum": ["planned", "recorded", "all"], "default": "planned"},
                "query": {"type": "string", "minLength": 1, "description": "Optional name search."},
                "page": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "tours": {"type": "array", "items": _COMMON_RESULT},
                "page": {"type": "integer"}, "limit": {"type": "integer"},
                "total_elements": {"type": ["integer", "null"]},
                "total_pages": {"type": ["integer", "null"]},
                "next_page": {"type": ["integer", "null"]},
            },
            "required": ["tours", "page", "limit", "total_elements", "total_pages", "next_page"],
            "additionalProperties": False,
        },
        "annotations": {"title": "List Komoot Tours", "readOnlyHint": True, "openWorldHint": True},
    },
    "get_tour_metadata": {
        "name": "get_tour_metadata",
        "description": "Get one Komoot tour's metadata without route geometry. Accepts a numeric tour ID or full tour URL.",
        "inputSchema": {
            "type": "object", "properties": {"tour": {"type": "string", "minLength": 1}},
            "required": ["tour"], "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object", "properties": {"tour_id": {"type": "string"}, "metadata": _COMMON_RESULT},
            "required": ["tour_id", "metadata"], "additionalProperties": False,
        },
        "annotations": {"title": "Get Komoot Tour Details", "readOnlyHint": True, "openWorldHint": True},
    },
    "get_tour_route": {
        "name": "get_tour_route",
        "description": (
            "Get a Komoot tour's full route payload, including coordinates, directions, way types, and surfaces. "
            "Accepts a numeric tour ID or full tour URL. Returns the route geometry and associated metadata."
        ),
        "inputSchema": {
            "type": "object", "properties": {"tour": {"type": "string", "minLength": 1}},
            "required": ["tour"], "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object", "properties": {"tour_id": {"type": "string"}, "route": _COMMON_RESULT},
            "required": ["tour_id", "route"], "additionalProperties": False,
        },
        "annotations": {"title": "Get Full Komoot Route", "readOnlyHint": True, "openWorldHint": True},
    },
    "get_tour_line": {
        "name": "get_tour_line",
        "description": "Get Komoot's native tour-line geometry from the /tour_line web API endpoint. Use get_tour_route for full coordinates, directions, way types and surfaces.",
        "inputSchema": {
            "type": "object", "properties": {"tour": {"type": "string", "minLength": 1}},
            "required": ["tour"], "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object", "properties": {"tour_id": {"type": "string"}, "tour_line": _COMMON_RESULT},
            "required": ["tour_id", "tour_line"], "additionalProperties": False,
        },
        "annotations": {"title": "Get Komoot Tour Line", "readOnlyHint": True, "openWorldHint": True},
    },
    "rename_tour": {
        "name": "rename_tour",
        "description": (
            "Rename a planned tour in the signed-in Komoot account. Ownership is checked against the account's "
            "planned-tour list, folder separators are rejected, and the new name is verified by readback. "
            "This uses Komoot's undocumented web API; set confirm=true only for an explicitly intended rename."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tour": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "confirm": {"type": "boolean", "const": True},
            },
            "required": ["tour", "name", "confirm"], "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object", "properties": {
                "tour_id": {"type": "string"}, "old_name": {"type": ["string", "null"]},
                "name": {"type": "string"}, "verified": {"const": True},
            }, "required": ["tour_id", "old_name", "name", "verified"], "additionalProperties": False,
        },
        "annotations": {"title": "Rename Komoot Tour", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
    },
}


for _name, _title, _description in (
    ("get_tour_waypoints", "Get Komoot Tour Waypoints", "Read the planned path waypoints in Komoot order, including locations and geometry indices. Never substitutes route geometry for planning points."),
    ("inspect_tour", "Inspect Komoot Tour", "Inspect way types, surfaces and Komoot warnings with approximate start/end distances and locations along the route. Preserves Komoot category codes; cycleway does not by itself establish whether pedestrians share it."),
    ("compare_tours", "Compare Komoot Tours", "Compare a Komoot route with another Komoot tour or external lat/lng coordinate objects, e.g. Strava geometry. Returns bidirectional sampled spatial deviations along each route. Ignores traversal order and may miss deviations shorter than sample_spacing_m; does not verify road identity."),
):
    _properties = {"tour": {"type": "string", "minLength": 1}}
    _schema = {"type": "object", "properties": _properties, "required": ["tour"], "additionalProperties": False}
    if _name == "compare_tours":
        _properties.update({
            "other_tour": {"type": "string", "minLength": 1},
            "coordinates": {"type": "array", "minItems": 2, "maxItems": 10000, "items": {
                "type": "object", "properties": {"lat": {"type": "number", "minimum": -90, "maximum": 90}, "lng": {"type": "number", "minimum": -180, "maximum": 180}},
                "required": ["lat", "lng"], "additionalProperties": False}},
            "tolerance_m": {"type": "number", "minimum": 1, "maximum": 1000, "default": 25},
            "sample_spacing_m": {"type": "number", "minimum": 10, "maximum": 1000, "default": 100},
        })
        _schema["oneOf"] = [{"required": ["other_tour"], "not": {"required": ["coordinates"]}}, {"required": ["coordinates"], "not": {"required": ["other_tour"]}}]
    TOOL_DEFINITIONS[_name] = {
        "name": _name, "description": _description, "inputSchema": _schema,
        "outputSchema": _COMMON_RESULT,
        "annotations": {"title": _title, "readOnlyHint": True, "openWorldHint": True},
    }


class ToolFailure(RuntimeError):
    pass


class KomootToolService:
    def list_tools(self) -> list[dict[str, Any]]:
        return list(TOOL_DEFINITIONS.values())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from jsonschema import Draft202012Validator

        if name not in TOOL_DEFINITIONS:
            raise ToolFailure(f"Unknown tool: {name}")
        definition = TOOL_DEFINITIONS[name]
        if next(Draft202012Validator(definition["inputSchema"]).iter_errors(arguments), None):
            raise ToolFailure(f"Invalid arguments; check the {name} tool schema")
        try:
            if name == "download_tour_fit":
                return download_tour_fit(**arguments)
            if name == "download_tour_gpx":
                return download_tour_gpx(**arguments)
            if name == "list_tours":
                return list_tours(**arguments)
            if name == "get_tour_metadata":
                return get_tour_metadata(**arguments)
            if name == "get_tour_route":
                return get_tour_route(**arguments)
            if name == "get_tour_line":
                return get_tour_line(**arguments)
            if name == "get_tour_waypoints":
                return get_tour_waypoints(**arguments)
            if name == "inspect_tour":
                return inspect_tour(**arguments)
            if name == "compare_tours":
                return compare_tours(**arguments)
            if name == "rename_tour":
                return rename_tour(**arguments)
        except KomootWriteUnverified:
            raise
        except (KomootError, FileExistsError, OSError, ValueError) as exc:
            raise ToolFailure(str(exc)) from exc
        raise ToolFailure(f"Tool is not implemented: {name}")


def create_sdk_server(service: KomootToolService) -> Any:
    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server("komoot", version="0.1.5", instructions=(
        "List Komoot tours, read metadata, full route geometry or native tour-line geometry, download GPX or FIT exports, "
        "inspect waypoints, surfaces and warnings, compare route geometry, or rename an owned planned tour with explicit confirmation. "
        "The server reads cookies from curl-safari's Unix socket and never accepts or returns cookie values. "
        "It does not open a browser or prompt for Komoot credentials."
    ))

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [mcp_types.Tool.model_validate(item) for item in service.list_tools()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        try:
            payload = await anyio.to_thread.run_sync(service.call_tool, name, arguments)
        except KomootWriteUnverified as exc:
            payload = {"error": str(exc), "errorCode": "komoot_write_unverified"}
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(exc))],
                structuredContent=payload,
                isError=True,
            )
        except ToolFailure as exc:
            payload = {"error": str(exc), "errorCode": "komoot_error"}
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(exc))],
                structuredContent=payload,
                isError=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))],
            structuredContent=payload,
        )

    return server


async def serve_async() -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    server = create_sdk_server(KomootToolService())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    import anyio

    try:
        anyio.run(serve_async)
    except Exception as exc:
        print(f"Komoot MCP internal error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
