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
import strava_route_service as routes
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

ROUTE_PREFS = {
    "type": "object", "additionalProperties": False, "minProperties": 1,
    "properties": {
        "routeType": {"type": "string", "enum": routes.ROUTE_TYPES},
        "surfaceType": {"type": "string", "enum": ["Unknown", "Paved", "Unpaved"]},
        "popularity": {"type": "number", "minimum": -1, "maximum": 1},
        "elevation": {"type": "number", "minimum": -1, "maximum": 1},
        "straightLine": {"type": "boolean"},
    },
}
ROUTE_FIELDS = {
    "name": {"type": "string", "minLength": 1},
    "description": {"type": "string", "description": "Use an empty string to clear."},
    "visibility": {"type": "string", "enum": ["OnlyMe", "Everyone"]},
    "starred": {"type": "boolean"},
    "elements": {"type": "array", "minItems": 2, "items": {
        "type": "object", "required": ["elementType", "waypoint"],
        "properties": {"elementType": {"const": "Waypoint"}, "waypoint": {
            "type": "object", "required": ["point"], "properties": {"point": {
                "type": "object", "required": ["lat", "lng"], "properties": {
                    "lat": {"type": "number", "minimum": -90, "maximum": 90},
                    "lng": {"type": "number", "minimum": -180, "maximum": 180},
                },
            }},
        }},
    }},
    "legs": {"type": "array", "minItems": 1, "items": {
        "type": "object", "required": ["startElement", "paths"],
        "properties": {"startElement": {"type": "integer", "minimum": 0}, "paths": {
            "type": "array", "minItems": 1, "items": {"type": "object", "required": ["polyline"],
                "properties": {"polyline": {"type": "object", "required": ["encoding", "data"],
                    "properties": {"encoding": {"const": "Google"}, "data": {"type": "string", "minLength": 1}}}},
            },
        }},
    }},
    "routePrefs": ROUTE_PREFS,
}
CREATE_ROUTE_PROPS = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "elements", "legs", "routePrefs"],
    "properties": {**ROUTE_FIELDS, "routePrefs": {**ROUTE_PREFS, "required": list(ROUTE_PREFS["properties"])},
                   "visibility": {**ROUTE_FIELDS["visibility"], "default": "OnlyMe"}},
}
UPDATE_ROUTE_PATCH = {
    "type": "object", "additionalProperties": False, "minProperties": 1,
    "properties": ROUTE_FIELDS,
    "dependentRequired": {"elements": ["legs"], "legs": ["elements"]},
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
    _tool("build_route", "Calculate paths between explicit waypoint pairs without saving a route. Accepts Strava's requests array and returns its complete buildRoute response unchanged by default. save_full=true writes that response to a private temporary JSON file and returns only counts and file details. Each result corresponds to a requested leg, not an alternative complete route. Does not accept a target distance or generate waypoints.", {
        "requests": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["elements", "routePrefs"],
            "properties": {
                "elements": {**ROUTE_FIELDS["elements"], "maxItems": 2},
                "routePrefs": CREATE_ROUTE_PROPS["properties"]["routePrefs"],
            },
        }},
        "save_full": {"type": "boolean", "default": False, "description": "Save full build response locally; return counts and file details instead of geometry."},
    }, ["requests"]),
    _tool("delete_route", "Delete one explicitly authorized owned route. Checks ownership before deleting and verifies a not-found response while still authenticated. On failure read current state before retrying.", {
        "route_id": ID, "confirm": {"type": "boolean", "const": True},
    }, ["route_id", "confirm"], write=True),
    _tool("create_route", "Save already built and inspected route geometry using Strava's native write props. Does not build or reroute. Defaults to OnlyMe. Returns the full native source route object after readback. On uncertain failure, inspect existing routes before retrying to avoid duplicates.", {
        "props": CREATE_ROUTE_PROPS, "confirm": {"type": "boolean", "const": True},
    }, ["props", "confirm"], write=True),
    _tool("update_route", "Update an owned route using either inline patch or patch_file (absolute path to a prepare-update envelope). The file route ID must match; its geometry fingerprint is preserved. confirm must be supplied separately. Reads editable state first and preserves omitted fields; routePrefs merges supplied keys. Supply elements and built legs together when replacing geometry, with one complete path per leg. Use base_geometry_sha256 from prepare-update to reject stale geometry. Verification requires two separated matching readbacks. Returns the full native source route object after readback. Read current state before retrying a failed write.", {
        "route_id": ID, "patch": UPDATE_ROUTE_PATCH,
        "patch_file": {"type": "string", "minLength": 1, "description": "Absolute path to prepare-update update.json. Use instead of patch; route_id must match the file."},
        "base_geometry_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "Geometry fingerprint from prepare-update. Rejects stale input before writing."}, "confirm": {"type": "boolean", "const": True},
    }, ["route_id", "confirm"], write=True),
    _tool("get_route", "Read one saved route, retaining all native fields except the fixed arrays elements, legs, segmentsOnRoute, segments, elevation, polyline, distanceStream and routePolylineData.media, regardless of size. omitted_arrays lists removed JSON-pointer paths and sizes. save_full=true saves the complete source route in a private temporary JSON file and returns its path, format and size.", {
        "route_id": {**ID, "description": "Exact route ID returned by list_routes, as a string."},
        "save_full": {"type": "boolean", "default": False, "description": "Save complete source route data to a private temporary JSON file."},
    }, ["route_id"]),
    _tool("list_routes", "List saved routes from My Routes, including routes saved from others. Follows source pagination up to max_pages; if has_more, resume with next_cursor and the same filters. Route IDs are strings.", {
        "query": {"type": "string", "description": "Text search passed to Strava."},
        "created_by": {"type": "string", "enum": ["any", "me", "others"], "default": "any"},
        "only_starred": {"type": "boolean", "default": False},
        "route_types": {"type": "array", "items": {"type": "string", "enum": routes.ROUTE_TYPES}, "minItems": 1, "uniqueItems": True, "description": "Omit for all source route types."},
        "max_pages": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        "cursor": {"type": "string", "minLength": 1, "description": "Exact next_cursor from a previous result; omit to start."},
    }, []),
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
    _tool("list_activity_media", "List photos and videos attached to one activity. Use the returned media_id for downloads.", {
        "activity_id": ID,
    }, ["activity_id"]),
    _tool("download_activity_media", "Download one listed photo or video to an explicit local directory. Returns the saved path. Existing files require overwrite=true.", {
        "activity_id": ID,
        "media_id": {"type": "string", "minLength": 1, "description": "Exact media_id returned by list_activity_media; may be a UUID."},
        "destination_dir": {"type": "string", "pattern": "^/", "description": "Absolute local destination directory."},
        "overwrite": {"type": "boolean", "default": False},
    }, ["activity_id", "media_id", "destination_dir"], write=True),
    _tool("upload_activity_media", "Attach one explicitly authorized local image or video and verify it through fresh media-list readback. List existing media first; after an uncertain failure, list again before retrying to avoid duplicates.", {
        "activity_id": ID,
        "file_path": {"type": "string", "pattern": "^/", "description": "Absolute path to an existing JPG, JPEG, PNG, GIF, MP4, or MOV file."},
        "caption": {"type": "string"},
        "confirm": {"type": "boolean", "const": True},
    }, ["activity_id", "file_path", "confirm"], write=True),
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


TOOL_DEFINITIONS['update_route']['inputSchema']['oneOf'] = [
    {'required': ['patch'], 'not': {'required': ['patch_file']}},
    {'required': ['patch_file'], 'not': {'required': ['patch']}},
]


def resolve_patch_file(arguments):
    path = Path(arguments['patch_file'])
    if not path.is_absolute() or not path.is_file():
        raise ValueError('patch_file must be an absolute path to a regular JSON file')
    def invalid_constant(value): raise ValueError('Non-finite values are not allowed in patch_file')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate keys in patch_file')
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding='utf-8'), parse_constant=invalid_constant, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError('patch_file must contain valid UTF-8 JSON') from exc
    if not isinstance(value, dict) or not {'route_id','patch'}.issubset(value) or set(value)-{'route_id','patch','base_geometry_sha256'}:
        raise ValueError('patch_file must contain the prepare-update envelope: route_id, patch, optional base_geometry_sha256')
    if value['route_id'] != arguments['route_id']:
        raise ValueError('patch_file route_id does not match the requested route')
    if 'base_geometry_sha256' in arguments and 'base_geometry_sha256' in value and arguments['base_geometry_sha256'] != value['base_geometry_sha256']:
        raise ValueError('Conflicting geometry fingerprints in arguments and patch_file')
    return {**{k:v for k,v in arguments.items() if k != 'patch_file'}, **value}


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
            if name == 'update_route' and 'patch_file' in arguments:
                arguments = resolve_patch_file(arguments)
                if next(validator.iter_errors(arguments), None):
                    raise ValueError('Invalid update arguments in patch_file; check the tool schema')
            with _SESSION_LOCK:
                # Each service function creates a fresh StravaSession and reads
                # the private cookie file. No browser launch, refresh or retry.
                service = routes if name in {"list_routes", "get_route", "build_route", "create_route", "update_route", "delete_route"} else activities
                payload = getattr(service, name)(**arguments)
            if name == "update_activities" and not payload["complete"]:
                code = "auth_required" if any(row.get("errorCode") == "auth_required" for row in payload["failed"]) else "partial_failure"
                raise ToolFailure("Batch incomplete. Inspect results and read current state before retrying failed activities.", code, payload)
            return payload
        except routes.RouteWriteError as exc:
            raise ToolFailure(str(exc), "write_unverified", exc.details) from exc
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
        "Read Strava activities, saved routes, gear and media; download media to explicit local paths; "
        "apply authorized metadata changes and media uploads with fresh readback. "
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
            _meta={"route_verification": payload.verification} if isinstance(payload, routes.VerifiedRoute) else None,
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
