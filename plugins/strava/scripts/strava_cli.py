#!/usr/bin/env python3
"""MCP-like CLI exposing user-oriented Strava tools."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Callable

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from strava_activity_service import get_activity, list_activities, update_activities, update_activity
from scripts.strava_route_api import StravaError


class ToolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


TOOLS: dict[str, dict[str, Any]] = {
    "list_activities": {
        "description": "List authenticated Strava activities in a date range.",
        "mutating": False,
        "inputSchema": {
            "type": "object",
            "required": ["since"],
            "properties": {
                "since": {"type": "string", "format": "date"},
                "until": {"type": "string", "format": "date"},
                "visibility": {"enum": ["everyone", "followers_only", "only_me"]},
                "max_pages": {"type": "integer", "minimum": 1, "default": 20},
                "per_page": {"type": "integer", "minimum": 1, "default": 100},
            },
            "additionalProperties": False,
        },
        "handler": list_activities,
    },
    "get_activity": {
        "description": "Get one Strava activity with its editable metadata.",
        "mutating": False,
        "inputSchema": {
            "type": "object",
            "required": ["activity_id"],
            "properties": {"activity_id": {"type": ["integer", "string"]}},
            "additionalProperties": False,
        },
        "handler": get_activity,
    },
    "update_activity": {
        "description": "Update editable metadata for one exact Strava activity and read it back.",
        "mutating": True,
        "inputSchema": {
            "type": "object",
            "required": ["activity_id", "patch", "confirm"],
            "properties": {
                "activity_id": {"type": ["integer", "string"]},
                "patch": {"$ref": "#/$defs/activityPatch"},
                "confirm": {"const": True},
            },
            "additionalProperties": False,
        },
        "handler": update_activity,
    },
    "update_activities": {
        "description": "Apply one metadata patch to multiple exact Strava activity IDs with readback.",
        "mutating": True,
        "inputSchema": {
            "type": "object",
            "required": ["activity_ids", "patch", "confirm"],
            "properties": {
                "activity_ids": {"type": "array", "minItems": 1, "items": {"type": ["integer", "string"]}},
                "patch": {"$ref": "#/$defs/activityPatch"},
                "confirm": {"const": True},
            },
            "additionalProperties": False,
        },
        "handler": update_activities,
    },
}

ACTIVITY_PATCH_SCHEMA = {
    "type": "object",
    "minProperties": 1,
    "properties": {
        "name": {"type": "string"},
        "tag": {"type": ["string", "null"]},
        "trainer": {"type": "boolean"},
        "visibility": {"enum": ["everyone", "followers_only", "only_me"]},
        "start_time_hidden": {"type": "boolean"},
        "bike_id": {"type": ["integer", "string", "null"]},
        "bike_name": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}


def public_tool(name: str, definition: dict[str, Any]) -> dict[str, Any]:
    schema = {**definition["inputSchema"]}
    if name in {"update_activity", "update_activities"}:
        schema["$defs"] = {"activityPatch": ACTIVITY_PATCH_SCHEMA}
    return {
        "name": name,
        "description": definition["description"],
        "inputSchema": schema,
        "mutating": definition["mutating"],
    }


def read_arguments(raw: str | None) -> dict[str, Any]:
    text = raw if raw is not None else sys.stdin.read()
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ToolError("invalid_json", f"Tool arguments are not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ToolError("invalid_arguments", "Tool arguments must be a JSON object")
    return payload


def matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_schema(value: Any, schema: dict[str, Any], *, root: dict[str, Any], path: str = "arguments") -> None:
    if "$ref" in schema:
        if schema["$ref"] != "#/$defs/activityPatch":
            raise ToolError("invalid_schema", f"Unsupported schema reference: {schema['$ref']}")
        schema = root["$defs"]["activityPatch"]
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(matches_type(value, item) for item in types):
            raise ToolError("invalid_arguments", f"{path} must have type {' or '.join(types)}")
    if "const" in schema and value != schema["const"]:
        raise ToolError("confirmation_required", f"{path} must be true")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolError("invalid_arguments", f"{path} must be one of: {', '.join(schema['enum'])}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                raise ToolError("invalid_arguments", f"Missing required property: {path}.{required}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ToolError("invalid_arguments", f"Unknown properties at {path}: {', '.join(unknown)}")
        if len(value) < schema.get("minProperties", 0):
            raise ToolError("invalid_arguments", f"{path} must not be empty")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], root=root, path=f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ToolError("invalid_arguments", f"{path} must contain at least {schema['minItems']} item(s)")
        for index, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), root=root, path=f"{path}[{index}]")
    if isinstance(value, int) and not isinstance(value, bool) and value < schema.get("minimum", value):
        raise ToolError("invalid_arguments", f"{path} must be at least {schema['minimum']}")
    if schema.get("format") == "date" and isinstance(value, str):
        try:
            dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ToolError("invalid_arguments", f"{path} must be an ISO date") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tools", help="List available user-oriented tools")
    describe = commands.add_parser("describe", help="Describe one tool")
    describe.add_argument("tool")
    call = commands.add_parser("call", help="Call one tool with JSON arguments")
    call.add_argument("tool")
    call.add_argument("--json", dest="arguments")
    args = parser.parse_args()

    try:
        if args.command == "tools":
            payload = {"tools": [public_tool(name, definition) for name, definition in TOOLS.items()]}
        else:
            if args.tool not in TOOLS:
                raise ValueError(f"Unknown Strava tool: {args.tool}")
            if args.command == "describe":
                payload = public_tool(args.tool, TOOLS[args.tool])
            else:
                arguments = read_arguments(args.arguments)
                schema = public_tool(args.tool, TOOLS[args.tool])["inputSchema"]
                validate_schema(arguments, schema, root=schema)
                handler: Callable[..., dict[str, Any]] = TOOLS[args.tool]["handler"]
                payload = {"tool": args.tool, "result": handler(**arguments)}
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError, StravaError) as exc:
        code = exc.code if isinstance(exc, ToolError) else "operation_failed"
        print(json.dumps({"error": {"code": code, "message": str(exc)}}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
