#!/usr/bin/env python3
"""Xert activities and workouts exposed through the stable MCP Python SDK."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from xert_service import XertService


ALL_TOOL_NAMES = (
    "list_activities",
    "get_activity",
    "list_workouts",
    "get_workout",
    "list_notes",
    "get_note",
    "set_note",
    "get_training_state",
    "get_training_advice",
    "create_workout",
    "delete_workout",
    "update_workout",
    "get_training_forecast",
)

TOOL_ANNOTATIONS: dict[str, dict[str, object]] = {
    "list_activities": {
        "title": "List Xert Activities",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_activity": {
        "title": "Get Xert Activity",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "list_workouts": {
        "title": "List Xert Workouts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_workout": {
        "title": "Get Xert Workout",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "list_notes": {
        "title": "List Xert Calendar Notes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_note": {
        "title": "Get Xert Calendar Note",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "set_note": {
        "title": "Set Xert Calendar Note",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_training_state": {
        "title": "Get Xert Training State",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_training_advice": {
        "title": "Get Xert Training Advice",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "create_workout": {
        "title": "Create Xert Workout",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "delete_workout": {
        "title": "Delete Xert Workout",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "update_workout": {
        "title": "Update Xert Workout",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_training_forecast": {
        "title": "Get Xert Training Forecast",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
}


def _object(description: str) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": True,
        "description": description,
    }


_ACTIVITY_LIST_INCLUDE_FIELDS = (
    "map_url", "xss", "xep_watts", "focus", "specificity", "difficulty",
    "difficulty_rating", "freshness", "signature",
)
_ACTIVITY_LIST_DETAIL_FIELDS = frozenset(
    {"xss", "xep_watts", "focus", "specificity", "difficulty",
     "difficulty_rating", "freshness", "signature"}
)
_WORKOUT_LIST_INCLUDE_FIELDS = (
    "work_watts", "xss", "xlss", "xhss", "xpss", "difficulty", "rating",
)


def _array(description: str) -> dict[str, object]:
    return {
        "type": "array",
        "items": _object("Normalized or source-native Xert object."),
        "description": description,
    }


def _workout_rows_schema(description: str) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": 1,
        "description": description,
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Optional row name."},
                "duration_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Work duration for each repetition in seconds.",
                },
                "power": {"type": "number", "description": "Primary power value."},
                "power_type": {
                    "type": "string",
                    "enum": ["absolute", "relative_ftp", "ramp_ftp", "ramp_ltp", "ramp_absolute"],
                    "default": "absolute",
                    "description": "Interpretation of power; relative and ramp values are percentages.",
                },
                "power_second_value": {
                    "type": "number",
                    "description": "Required ending power for ramp power types.",
                },
                "interval_count": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "Number of work repetitions represented by this row.",
                },
                "rib_duration_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Rest-in-between duration after every repetition, including the final one.",
                },
                "rib_power": {
                    "type": "number",
                    "default": 0,
                    "description": "Rest-in-between power value.",
                },
                "rib_power_type": {
                    "type": "string",
                    "enum": ["absolute", "relative_ftp"],
                    "default": "absolute",
                    "description": "Interpretation of rest-in-between power.",
                },
            },
            "required": ["duration_seconds", "power"],
            "additionalProperties": False,
        },
    }


TOOL_DEFINITIONS: dict[str, dict[str, object]] = {
    "list_activities": {
        "name": "list_activities",
        "description": (
            "List compact Xert activity identity summaries for an inclusive local-date "
            "range. Use includeFields for selected details; load and signature fields "
            "trigger the heavier per-activity detail read."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Inclusive local start date in YYYY-MM-DD format.",
                },
                "end_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Inclusive local end date in YYYY-MM-DD format.",
                },
                "includeFields": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_ACTIVITY_LIST_INCLUDE_FIELDS)},
                    "uniqueItems": True,
                    "default": [],
                    "description": "Optional activity detail fields added to every compact summary.",
                },
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Requested inclusive start date."},
                "end_date": {"type": "string", "description": "Requested inclusive end date."},
                "includeFields": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Requested optional fields.",
                },
                "count": {"type": "integer", "description": "Number of returned activities."},
                "activities": _array("Activities in source order."),
            },
            "required": ["start_date", "end_date", "includeFields", "count", "activities"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["list_activities"],
    },
    "get_activity": {
        "name": "get_activity",
        "description": (
            "Get a compact summary of one Xert activity. Set save_full=true to save "
            "the complete activity document, or save_session=true to fetch and save "
            "Xert-specific second-by-second data, in private temporary JSON files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Xert activity path returned by list_activities.",
                },
                "save_full": {
                    "type": "boolean",
                    "default": False,
                    "description": "Save the complete activity document without session series.",
                },
                "save_session": {
                    "type": "boolean",
                    "default": False,
                    "description": "Fetch and save the complete activity including Xert session series.",
                },
            },
            "required": ["activity_path"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_path": {"type": "string", "description": "Requested Xert activity path."},
                "activity": _object("Compact normalized Xert activity summary."),
                "full_activity_file": {
                    "type": "string",
                    "description": "Private complete-activity JSON path; absent unless requested.",
                },
                "full_activity_format": {"type": "string"},
                "full_activity_byte_size": {"type": "integer"},
                "session_file": {
                    "type": "string",
                    "description": "Private session-inclusive JSON path; absent unless requested.",
                },
                "session_format": {"type": "string"},
                "session_byte_size": {"type": "integer"},
            },
            "required": ["activity_path", "activity"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_activity"],
    },
    "list_workouts": {
        "name": "list_workouts",
        "description": (
            "List compact Xert workout identity summaries, optionally requiring "
            "every supplied case-insensitive name keyword. Use includeFields to "
            "add selected load or difficulty fields."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name_keywords": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Optional space-separated keywords that must all occur in the workout name.",
                },
                "includeFields": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_WORKOUT_LIST_INCLUDE_FIELDS)},
                    "uniqueItems": True,
                    "default": [],
                    "description": "Optional workout detail fields added to every compact summary.",
                },
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "includeFields": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Requested optional fields.",
                },
                "name_keywords": {
                    "type": ["string", "null"],
                    "description": "Applied name filter, or null when unfiltered.",
                },
                "count": {"type": "integer", "description": "Number of returned workouts."},
                "workouts": _array("Matching workouts in source order."),
            },
            "required": ["includeFields", "name_keywords", "count", "workouts"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["list_workouts"],
    },
    "get_workout": {
        "name": "get_workout",
        "description": (
            "Get one Xert workout. resolved uses the current Fitness Signature; "
            "editable returns authoritative Workout Designer rows including repeats, "
            "slopes, and rest-in-between fields."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workout_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Xert workout path returned by list_workouts.",
                },
                "view": {
                    "type": "string",
                    "enum": ["resolved", "editable"],
                    "default": "resolved",
                    "description": "resolved returns the calculated workout; editable returns Designer rows.",
                },
            },
            "required": ["workout_path"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "workout_path": {"type": "string", "description": "Requested Xert workout path."},
                "view": {"type": "string", "description": "Returned workout representation."},
                "workout": _object("Resolved workout payload; absent for editable view."),
                "rows": _array("Editable Workout Designer rows; absent for resolved view."),
            },
            "required": ["workout_path", "view"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_workout"],
    },
    "list_notes": {
        "name": "list_notes",
        "description": "List non-empty Xert calendar notes for an inclusive local-date range.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Inclusive local start date in YYYY-MM-DD format.",
                },
                "end_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Inclusive local end date in YYYY-MM-DD format.",
                },
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Requested inclusive start date."},
                "end_date": {"type": "string", "description": "Requested inclusive end date."},
                "count": {"type": "integer", "description": "Number of non-empty notes."},
                "notes": {
                    "type": "array",
                    "description": "Calendar notes sorted by date.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "Local calendar date."},
                            "text": {"type": "string", "description": "Note text."},
                        },
                        "required": ["date", "text"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["start_date", "end_date", "count", "notes"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["list_notes"],
    },
    "get_note": {
        "name": "get_note",
        "description": "Get the Xert calendar note for one local date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "format": "date",
                    "description": "Local calendar date in YYYY-MM-DD format.",
                },
            },
            "required": ["date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Requested local calendar date."},
                "exists": {"type": "boolean", "description": "Whether a non-empty note exists."},
                "text": {
                    "type": ["string", "null"],
                    "description": "Note text, or null when no non-empty note exists.",
                },
            },
            "required": ["date", "exists", "text"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_note"],
    },
    "set_note": {
        "name": "set_note",
        "description": (
            "Set or replace the Xert calendar note for one local date. Pass an empty "
            "text string to clear the note. The saved value is read back and verified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "format": "date",
                    "description": "Local calendar date in YYYY-MM-DD format.",
                },
                "text": {
                    "type": "string",
                    "description": "Desired note text; an empty string clears the note.",
                },
            },
            "required": ["date", "text"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Updated local calendar date."},
                "exists": {"type": "boolean", "description": "Whether a non-empty note now exists."},
                "text": {
                    "type": ["string", "null"],
                    "description": "Verified saved text, or null after clearing.",
                },
                "success": {"type": "boolean", "description": "Whether readback matched the requested text."},
            },
            "required": ["date", "exists", "text", "success"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["set_note"],
    },
    "get_training_state": {
        "name": "get_training_state",
        "description": (
            "Get current Xert Fitness Signature, Training and Recovery Load, form, "
            "recovery hours, training status, and target XSS. This is current state, "
            "not a future projection or activity-specific readiness calculation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "default": "summary",
                    "description": "summary returns normalized state; full returns both source payloads.",
                },
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "description": "Returned state representation."},
                "state": _object("Normalized current state or complete source payloads."),
            },
            "required": ["view", "state"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_training_state"],
    },
    "get_training_advice": {
        "name": "get_training_advice",
        "description": (
            "Get Xert training advice for now or a planned time. Omit at for the "
            "current /my-fitness advice; provide at for /recommended-training advice "
            "resolved immediately before that planned start. This does not include "
            "activity-specific load or cross-source readiness."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "at": {
                    "type": "string",
                    "format": "date-time",
                    "description": (
                        "Optional planned ISO date-time. Naive values use the user's "
                        "local timezone; omit for advice now."
                    ),
                },
                "view": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "default": "summary",
                    "description": "summary returns normalized advice; full returns the selected source payload.",
                },
                "include_recommendations": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Include normalized recommended workouts. This performs the "
                        "additional recommended-training read when advice is for now."
                    ),
                },
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "description": "Returned advice representation."},
                "advice": _object("Normalized advice or selected complete source payload."),
            },
            "required": ["view", "advice"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_training_advice"],
    },
    "get_training_forecast": {
        "name": "get_training_forecast",
        "description": (
            "Get Xert's calendar training forecast for an inclusive local-date range. "
            "This is forecast state, not the mixed activity/Planner calendar feed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Inclusive local start date in YYYY-MM-DD format.",
                },
                "end_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Inclusive local end date in YYYY-MM-DD format.",
                },
                "view": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "default": "summary",
                    "description": "summary returns normalized days; full retains source day fields.",
                },
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Requested inclusive start date."},
                "end_date": {"type": "string", "description": "Requested inclusive end date."},
                "view": {"type": "string", "description": "Returned forecast representation."},
                "forecast": _object("Filtered normalized or source-native forecast."),
            },
            "required": ["start_date", "end_date", "view", "forecast"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["get_training_forecast"],
    },
    "create_workout": {
        "name": "create_workout",
        "description": (
            "Create and save a new Xert workout from complete Workout Designer rows. "
            "The saved metadata and rows are read back and verified. Repeated calls "
            "create additional workouts; use only when creation is explicitly requested."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Name for the new workout.",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional workout description.",
                },
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Complete Workout Designer rows in execution order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Optional row name."},
                            "duration_seconds": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "Work duration for each repetition in seconds.",
                            },
                            "power": {"type": "number", "description": "Primary power value."},
                            "power_type": {
                                "type": "string",
                                "enum": ["absolute", "relative_ftp", "ramp_ftp", "ramp_ltp", "ramp_absolute"],
                                "default": "absolute",
                                "description": "Interpretation of power; relative and ramp values are percentages.",
                            },
                            "power_second_value": {
                                "type": "number",
                                "description": "Required ending power for ramp power types.",
                            },
                            "interval_count": {
                                "type": "integer",
                                "minimum": 1,
                                "default": 1,
                                "description": "Number of work repetitions represented by this row.",
                            },
                            "rib_duration_seconds": {
                                "type": "integer",
                                "minimum": 0,
                                "default": 0,
                                "description": "Rest-in-between duration after every repetition, including the final one.",
                            },
                            "rib_power": {
                                "type": "number",
                                "default": 0,
                                "description": "Rest-in-between power value.",
                            },
                            "rib_power_type": {
                                "type": "string",
                                "enum": ["absolute", "relative_ftp"],
                                "default": "absolute",
                                "description": "Interpretation of rest-in-between power.",
                            },
                        },
                        "required": ["duration_seconds", "power"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["name", "rows"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "workout": _object("Created workout path, verified metadata, and timeline summary."),
            },
            "required": ["workout"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["create_workout"],
    },
    "delete_workout": {
        "name": "delete_workout",
        "description": (
            "Permanently delete one Xert workout. The target metadata is read before "
            "deletion and the workout library is read afterward to verify that the "
            "path is absent. Use only when deletion is explicitly requested."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workout_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Xert workout path returned by list_workouts.",
                },
            },
            "required": ["workout_path"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "deletion": _object("Deleted target metadata and absence verification."),
            },
            "required": ["deletion"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["delete_workout"],
    },
    "update_workout": {
        "name": "update_workout",
        "description": (
            "Update Xert workout metadata and optionally replace all Workout Designer "
            "rows atomically. Omitted metadata is preserved. When rows are supplied, "
            "first read view=editable, modify the complete row set, and submit every "
            "row in final execution order. Saved metadata and rows are read back."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workout_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Xert workout path returned by list_workouts.",
                },
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Optional replacement workout name.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional replacement description; an empty string clears it.",
                },
                "rows": _workout_rows_schema(
                    "Optional complete replacement Designer rows in final execution order."
                ),
            },
            "required": ["workout_path"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "workout": _object("Verified workout update and timeline summary when rows changed."),
            },
            "required": ["workout"],
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS["update_workout"],
    },
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    definition: dict[str, object]


TOOL_SPECS = {
    name: ToolSpec(name=name, definition=TOOL_DEFINITIONS[name]) for name in ALL_TOOL_NAMES
}


class ToolFailure(Exception):
    """Stable tool-facing error with a machine-readable category."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class XertToolService:
    """Transport-independent MCP validation and dispatch."""

    def __init__(self, service_factory: Callable[[], XertService] = XertService) -> None:
        self._service_factory = service_factory
        self._service: XertService | None = None
        self._lock = threading.RLock()

    def list_tools(self) -> list[dict[str, object]]:
        return [TOOL_SPECS[name].definition for name in ALL_TOOL_NAMES]

    def call_tool(self, name: str, arguments: object | None = None) -> dict[str, Any]:
        if name not in TOOL_SPECS:
            raise ToolFailure("unknown_tool", f"Unknown Xert tool: {name}")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ToolFailure("invalid_arguments", "tool arguments must be an object")
        schema = TOOL_SPECS[name].definition["inputSchema"]
        allowed = set(schema["properties"])
        unknown = set(arguments) - allowed
        if unknown:
            raise ToolFailure("invalid_arguments", f"unknown argument: {sorted(unknown)[0]}")
        missing = [field for field in schema.get("required", []) if field not in arguments]
        if missing:
            raise ToolFailure("invalid_arguments", f"missing required argument: {missing[0]}")
        try:
            with self._lock:
                if self._service is None:
                    self._service = self._service_factory()
                return self._dispatch(self._service, name, arguments)
        except ToolFailure:
            raise
        except ValueError as exc:
            code = "authentication_error" if "XERT_" in str(exc) else "invalid_arguments"
            raise ToolFailure(code, str(exc)) from exc
        except Exception as exc:
            raise ToolFailure("xert_error", str(exc)) from exc

    @staticmethod
    def _dispatch(service: XertService, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "list_activities":
            start = arguments["start_date"]
            end = arguments["end_date"]
            include_fields = _validate_include_fields(arguments.get("includeFields", []))
            view = (
                "loads"
                if any(field in _ACTIVITY_LIST_DETAIL_FIELDS for field in include_fields)
                else "summary"
            )
            result = service.list_activities(start, end, view=view)
            activities = result["activities"] if view == "loads" else result
            return {
                "start_date": start,
                "end_date": end,
                "includeFields": list(include_fields),
                "count": len(activities),
                "activities": [
                    _activity_list_summary(activity, include_fields)
                    for activity in activities
                ],
            }
        if name == "get_activity":
            path = arguments["activity_path"]
            save_full = arguments.get("save_full", False)
            save_session = arguments.get("save_session", False)
            if not isinstance(save_full, bool):
                raise ValueError("save_full must be a boolean")
            if not isinstance(save_session, bool):
                raise ValueError("save_session must be a boolean")
            output: dict[str, Any] = {
                "activity_path": path,
                "activity": service.get_activity(path, view="summary"),
            }
            if save_full:
                full = service.get_activity(path, view="full")
                file_path, byte_size = _write_private_activity_file(
                    path, full, kind="activity"
                )
                output.update({
                    "full_activity_file": file_path,
                    "full_activity_format": "xert-activity-v1",
                    "full_activity_byte_size": byte_size,
                })
            if save_session:
                session = service.get_activity(path, view="session")
                file_path, byte_size = _write_private_activity_file(
                    path, session, kind="session"
                )
                output.update({
                    "session_file": file_path,
                    "session_format": "xert-activity-session-v1",
                    "session_byte_size": byte_size,
                })
            return output
        if name == "list_workouts":
            keywords = arguments.get("name_keywords")
            include_fields = _validate_include_fields(
                arguments.get("includeFields", []),
                allowed=_WORKOUT_LIST_INCLUDE_FIELDS,
                parameter="includeFields",
            )
            workouts = service.list_workouts(name_keywords=keywords, view="summary")
            return {
                "includeFields": list(include_fields),
                "name_keywords": keywords,
                "count": len(workouts),
                "workouts": [
                    _workout_list_summary(workout, include_fields)
                    for workout in workouts
                ],
            }
        if name == "list_notes":
            start = arguments["start_date"]
            end = arguments["end_date"]
            notes = service.list_notes(start, end)
            return {"start_date": start, "end_date": end, "count": len(notes), "notes": notes}
        if name == "get_note":
            return service.get_note(arguments["date"])
        if name == "set_note":
            return service.set_note(arguments["date"], arguments["text"])
        if name == "get_training_state":
            view = arguments.get("view", "summary")
            return {"view": view, "state": service.get_training_state(view=view)}
        if name == "get_training_advice":
            view = arguments.get("view", "summary")
            return {
                "view": view,
                "advice": service.get_training_advice(
                    at=arguments.get("at"),
                    view=view,
                    include_recommendations=arguments.get("include_recommendations", False),
                ),
            }
        if name == "get_training_forecast":
            start = arguments["start_date"]
            end = arguments["end_date"]
            view = arguments.get("view", "summary")
            return {
                "start_date": start,
                "end_date": end,
                "view": view,
                "forecast": service.get_training_forecast(start, end, view=view),
            }
        if name == "create_workout":
            return {
                "workout": service.create_workout(
                    name=arguments["name"],
                    description=arguments.get("description", ""),
                    rows=arguments["rows"],
                )
            }
        if name == "delete_workout":
            return {"deletion": service.delete_workout(arguments["workout_path"])}
        if name == "update_workout":
            return {
                "workout": service.update_workout(
                    arguments["workout_path"],
                    name=arguments.get("name"),
                    description=arguments.get("description"),
                    rows=arguments.get("rows"),
                )
            }
        path = arguments["workout_path"]
        view = arguments.get("view", "resolved")
        workout = service.get_workout(path, view=view)
        output = {"workout_path": path, "view": view}
        output["rows" if view == "editable" else "workout"] = workout
        return output


def _write_private_activity_file(
    activity_path: str, payload: dict[str, Any], *, kind: str
) -> tuple[str, int]:
    safe_path = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in activity_path
    ).strip("-") or "activity"
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f"xert-{safe_path}-", suffix=f"-{kind}.json"
    )
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"activity_path": activity_path, "activity": payload},
                stream, ensure_ascii=False, separators=(",", ":"),
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return str(path), path.stat().st_size


def _validate_include_fields(
    value: Any,
    *,
    allowed: tuple[str, ...] = _ACTIVITY_LIST_INCLUDE_FIELDS,
    parameter: str = "includeFields",
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(field, str) for field in value):
        raise ValueError(f"{parameter} must be an array of strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{parameter} must contain unique fields")
    unsupported = [field for field in value if field not in allowed]
    if unsupported:
        raise ValueError(f"Unsupported {parameter} value: {unsupported[0]}")
    return tuple(value)


def _activity_list_summary(
    activity: dict[str, Any], include_fields: tuple[str, ...]
) -> dict[str, Any]:
    elapsed_minutes = activity.get("elapsed_minutes")
    distance_km = activity.get("distance_km")
    summary = {
        "path": activity.get("path"),
        "name": activity.get("name"),
        "start_local": activity.get("start_local"),
        "duration_s": (
            round(float(elapsed_minutes) * 60) if elapsed_minutes is not None else None
        ),
        "distance_m": (
            round(float(distance_km) * 1000) if distance_km is not None else None
        ),
        "source": activity.get("source") or "xert_plugin",
    }
    summary.update({field: activity.get(field) for field in include_fields})
    return summary


def _workout_list_summary(
    workout: dict[str, Any], include_fields: tuple[str, ...]
) -> dict[str, Any]:
    duration_min = workout.get("duration_min")
    summary = {
        "path": workout.get("path"),
        "name": workout.get("name"),
        "duration_s": (
            round(float(duration_min) * 60) if duration_min is not None else None
        ),
    }
    summary.update({field: workout.get(field) for field in include_fields})
    return summary


def create_sdk_server(service: XertToolService) -> Any:
    """Build the stable SDK server used by the stdio entry point."""

    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server(
        "xert",
        version="0.1.0",
        instructions=(
            "Read Xert cycling activities, workouts, calendar notes, current training "
            "state, and current or planned-time training advice, set calendar-note "
            "text, and create verified Workout Designer workouts. Inclusive dates "
            "use the user's local calendar."
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
                structuredContent=error_payload,
                isError=True,
            )
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=text)],
            structuredContent=payload,
        )

    return server


async def serve_async(service_factory: Callable[[], XertService] = XertService) -> None:
    from mcp.server.stdio import stdio_server

    server = create_sdk_server(XertToolService(service_factory))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve(service_factory: Callable[[], XertService] = XertService) -> int:
    try:
        import anyio

        anyio.run(serve_async, service_factory)
    except Exception as exc:
        print(f"Xert MCP internal error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return serve(XertService)


if __name__ == "__main__":
    raise SystemExit(main())
