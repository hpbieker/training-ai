#!/usr/bin/env python3
"""Focused Intervals.icu activity and wellness tools exposed through MCP."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from intervals_icu_api import (  # noqa: E402
    IntervalsIcuCredentials,
    delete_activity,
    download_activity_file,
    download_activity_streams_csv,
    create_event,
    delete_event,
    get_activity,
    get_activities,
    get_wellness,
    list_activities,
    list_activity_power_curves,
    list_events,
    list_wellness,
    discover_intervals_icu_credentials,
    search_activities,
    update_activity,
    update_wellness,
    update_event,
    upload_activity_file,
)
from list_query import apply_list_query, query_fields, query_properties  # noqa: E402


class ToolFailure(RuntimeError):
    def __init__(self, message: str, code: str = "tool_error") -> None:
        super().__init__(message)
        self.code = code


def _object(description: str) -> dict[str, object]:
    return {"type": "object", "additionalProperties": True, "description": description}


_ACTIVITY_LIST_INCLUDE_FIELDS = (
    "type", "duration_s", "distance_m", "source", "external_id", "created",
    "moving_time", "trainer", "strava_id", "device_name", "gear",
    "description", "tags", "sub_type", "icu_color", "carbs_ingested", "kg_lifted",
    "icu_ignore_time",
    "icu_ignore_hr", "icu_ignore_power", "ignore_velocity", "ignore_pace",
    "icu_training_load", "icu_intensity", "icu_average_watts",
    "icu_weighted_avg_watts", "average_heartrate", "max_heartrate",
    "average_cadence", "average_temp", "decoupling", "icu_rpe", "feel",
    "interval_summary", "stream_types",
)
_ACTIVITY_LIST_FILTER_FIELDS = (
    "id", "name", "start_date_local", "type", "duration_s", "distance_m",
    "source", "external_id", *_ACTIVITY_LIST_INCLUDE_FIELDS,
)
_WELLNESS_FILTER_FIELDS = (
    "id", "weight", "restingHR", "resting_hr", "hrv", "hrvSDNN", "ctl", "atl",
    "rampRate", "sleepSecs", "sleep_secs", "sleepQuality", "soreness", "fatigue",
    "stress", "mood", "motivation", "injury", "hydration", "comments", "steps",
    "vo2max", "locked",
)
_EVENT_FILTER_FIELDS = (
    "id", "category", "name", "description", "type", "start_date_local",
    "end_date_local", "icu_training_load", "paired_activity_id", "external_id",
)


ANNOTATIONS = {
    "list_activities": {
        "title": "List Intervals.icu Activities", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "list_activity_power_curves": {
        "title": "List Intervals.icu Activity Power Curves", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "get_activity": {
        "title": "Get Intervals.icu Activity", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
    },
    "get_activities": {
        "title": "Get Intervals.icu Activities", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
    },
    "search_activities": {
        "title": "Search Intervals.icu Activities", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "get_activity_streams": {
        "title": "Get Intervals.icu Activity Streams", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
    },
    "get_activity_file": {
        "title": "Get Intervals.icu Activity File", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
    },
    "update_activity": {
        "title": "Update Intervals.icu Activity", "readOnlyHint": False,
        "destructiveHint": True, "idempotentHint": True, "openWorldHint": True,
    },
    "delete_activity": {
        "title": "Delete Intervals.icu Activity", "readOnlyHint": False,
        "destructiveHint": True, "idempotentHint": False, "openWorldHint": True,
    },
    "delete_activities": {
        "title": "Delete Intervals.icu Activities", "readOnlyHint": False,
        "destructiveHint": True, "idempotentHint": False, "openWorldHint": True,
    },
    "upload_activity": {
        "title": "Upload Intervals.icu Activity", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
    },
    "list_wellness": {
        "title": "List Intervals.icu Wellness", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "update_wellness": {
        "title": "Update Intervals.icu Wellness", "readOnlyHint": False,
        "destructiveHint": True, "idempotentHint": True, "openWorldHint": True,
    },
    "list_events": {
        "title": "List Intervals.icu Calendar Events", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "create_event": {
        "title": "Create Intervals.icu Calendar Event", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "update_event": {
        "title": "Update Intervals.icu Calendar Event", "readOnlyHint": False,
        "destructiveHint": True, "idempotentHint": True, "openWorldHint": True,
    },
    "delete_event": {
        "title": "Delete Intervals.icu Calendar Event", "readOnlyHint": False,
        "destructiveHint": True, "idempotentHint": False, "openWorldHint": True,
    },
}


TOOL_DEFINITIONS: dict[str, dict[str, object]] = {
    "list_activities": {
        "name": "list_activities",
        "description": (
            "List all Intervals.icu activities in an inclusive local-date range. "
            "Use the same start_date and end_date to resolve today's exact activity; "
            "do not substitute a latest-activity lookup."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date", "description": "Inclusive local start date."},
                "end_date": {"type": "string", "format": "date", "description": "Inclusive local end date."},
                "includeFields": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_ACTIVITY_LIST_INCLUDE_FIELDS)},
                    "uniqueItems": True,
                    "default": [],
                    "description": "Optional activity detail fields added to every compact summary.",
                },
                **query_properties(_ACTIVITY_LIST_FILTER_FIELDS),
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "includeFields": {"type": "array", "items": {"type": "string"}},
                "count": {"type": "integer"},
                "activities": {"type": "array", "items": _object("Intervals.icu activity summary.")},
                "source_count": {"type": "integer"},
                "matched_count": {"type": "integer"},
                "filters": {"type": "array", "items": {}},
                "sort": {"type": "array", "items": {}},
                "limit": {"type": ["integer", "null"]},
            },
            "required": ["start_date", "end_date", "includeFields", "count", "activities"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["list_activities"],
    },
    "list_activity_power_curves": {
        "name": "list_activity_power_curves",
        "description": (
            "List per-activity Intervals.icu power-curve values for explicit durations "
            "in an inclusive local-date range. For example, secs=[1] returns each "
            "activity's best one-second average power; this is not raw max-power metadata."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date", "description": "Inclusive local start date."},
                "end_date": {"type": "string", "format": "date", "description": "Inclusive local end date."},
                "secs": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 1,
                    "maxItems": 100,
                    "uniqueItems": True,
                    "description": "Power-curve durations in seconds, for example [1, 5, 60, 300].",
                },
            },
            "required": ["start_date", "end_date", "secs"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "secs": {"type": "array", "items": {"type": "integer"}},
                "count": {"type": "integer"},
                "curves": {"type": "array", "items": _object("Intervals.icu activity power-curve row.")},
            },
            "required": ["start_date", "end_date", "secs", "count", "curves"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["list_activity_power_curves"],
    },
    "search_activities": {
        "name": "search_activities",
        "description": (
            "Search Intervals.icu activities through the source search endpoint. "
            "Returns compact identity summaries with optional includeFields. The result "
            "is limited by Intervals.icu and preserves source order and duplicates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string", "minLength": 1,
                    "description": "Text or tag query passed unchanged to Intervals.icu.",
                },
                "limit": {
                    "type": "integer", "minimum": 1, "default": 10,
                    "description": "Maximum number of source search results.",
                },
                "includeFields": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_ACTIVITY_LIST_INCLUDE_FIELDS)},
                    "uniqueItems": True,
                    "default": [],
                    "description": "Optional activity detail fields added to every compact summary.",
                },
                **query_properties(_ACTIVITY_LIST_FILTER_FIELDS, include_limit=False),
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "includeFields": {"type": "array", "items": {"type": "string"}},
                "count": {"type": "integer"},
                "activities": {"type": "array", "items": _object("Intervals.icu search result.")},
                "source_count": {"type": "integer"},
                "matched_count": {"type": "integer"},
                "filters": {"type": "array", "items": {}},
                "sort": {"type": "array", "items": {}},
                "source_limited": {"type": "boolean"},
            },
            "required": ["query", "limit", "includeFields", "count", "activities"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["search_activities"],
    },
    "get_activity": {
        "name": "get_activity",
        "description": (
            "Get a compact identity summary of one exact Intervals.icu activity, "
            "optionally adding selected includeFields. Set "
            "save_full=true to also save the complete source activity in the "
            "standard activity envelope to a private temporary JSON file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "minLength": 1},
                "includeFields": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_ACTIVITY_LIST_INCLUDE_FIELDS)},
                    "uniqueItems": True,
                    "default": [],
                    "description": "Optional activity detail fields added to the compact summary.",
                },
                "save_full": {
                    "type": "boolean", "default": False,
                    "description": "Save complete activity metadata to a private temporary JSON file.",
                },
            },
            "required": ["activity_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string"},
                "includeFields": {"type": "array", "items": {"type": "string"}},
                "activity": _object("Compact normalized Intervals.icu activity summary."),
                "full_activity_file": {"type": "string"},
                "full_activity_format": {"type": "string"},
                "full_activity_byte_size": {"type": "integer"},
            },
            "required": ["activity_id", "includeFields", "activity"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["get_activity"],
    },
    "get_activities": {
        "name": "get_activities",
        "description": (
            "Get compact identity summaries of several exact Intervals.icu activities "
            "in one source request, optionally adding selected includeFields. Set "
            "save_full=true to also save the complete source "
            "activities in a standard private batch envelope."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "includeFields": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_ACTIVITY_LIST_INCLUDE_FIELDS)},
                    "uniqueItems": True,
                    "default": [],
                    "description": "Optional activity detail fields added to every compact summary.",
                },
                "save_full": {
                    "type": "boolean", "default": False,
                    "description": "Save complete activity metadata to a private temporary JSON file.",
                },
            },
            "required": ["activity_ids"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_ids": {"type": "array", "items": {"type": "string"}},
                "includeFields": {"type": "array", "items": {"type": "string"}},
                "count": {"type": "integer"},
                "activities": {"type": "array", "items": _object("Compact normalized Intervals.icu activity summary.")},
                "full_activities_file": {"type": "string"},
                "full_activities_format": {"type": "string"},
                "full_activities_byte_size": {"type": "integer"},
            },
            "required": ["activity_ids", "includeFields", "count", "activities"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["get_activities"],
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
    "get_activity_file": {
        "name": "get_activity_file",
        "description": (
            "Download the original uploaded activity file or an Intervals.icu-generated "
            "FIT file to a private temporary directory and return its path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["original", "fit"], "default": "original"},
            },
            "required": ["activity_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string"}, "kind": {"type": "string"},
                "file_path": {"type": "string"}, "byte_size": {"type": "integer"},
            },
            "required": ["activity_id", "kind", "file_path", "byte_size"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["get_activity_file"],
    },
    "update_activity": {
        "name": "update_activity",
        "description": (
            "Patch supported fields on one exact activity. Reads first, requires "
            "confirmation before replacing non-empty values, and verifies by readback."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "minLength": 1},
                "updates": {
                    "type": "object", "minProperties": 1, "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "description": {"type": ["string", "null"]},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "uniqueItems": True,
                        },
                        "sub_type": {
                            "type": "string",
                            "enum": ["NONE", "COMMUTE", "WARMUP", "COOLDOWN", "RACE"],
                        },
                        "icu_color": {"type": ["string", "null"]},
                        "carbs_ingested": {"type": "integer", "minimum": 0},
                        "kg_lifted": {"type": "number", "minimum": 0},
                        "icu_ignore_time": {"type": "boolean"},
                        "icu_ignore_hr": {"type": "boolean"},
                        "icu_ignore_power": {"type": "boolean"},
                        "ignore_velocity": {"type": "boolean"},
                        "ignore_pace": {"type": "boolean"},
                        "feel": {
                            "type": ["integer", "null"],
                            "minimum": 1,
                            "maximum": 5,
                            "description": "Subjective feel: 1 is strong and 5 is weak.",
                        },
                        "icu_rpe": {"type": ["number", "null"], "minimum": 0, "maximum": 10},
                    },
                },
                "confirm_overwrite": {"type": "boolean", "default": False},
            },
            "required": ["activity_id", "updates"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string"},
                "updates": _object("Requested activity field changes."),
                "before": _object("Values of the requested fields before the patch."),
                "after": _object("Fresh readback values of the requested fields."),
                "overwritten_fields": {"type": "array", "items": {"type": "string"}},
                "verified": {"type": "boolean"},
            },
            "required": ["activity_id", "updates", "before", "after", "overwritten_fields", "verified"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["update_activity"],
    },
    "delete_activity": {
        "name": "delete_activity",
        "description": (
            "Delete one exact activity after reading it, then verify absence by direct "
            "lookup and from its local-date activity list."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "minLength": 1},
                "confirm": {"type": "string", "description": "Must exactly match activity_id."},
            },
            "required": ["activity_id", "confirm"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string"},
                "before": _object("Activity read immediately before deletion."),
                "deleted_response": _object("Intervals.icu deletion response."),
                "verified_deleted": {"type": "boolean"},
            },
            "required": ["activity_id", "before", "deleted_response", "verified_deleted"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["delete_activity"],
    },
    "delete_activities": {
        "name": "delete_activities",
        "description": (
            "Delete exact activities after one batch read, then verify their collective "
            "absence with one batch read. Each activity is deleted individually because "
            "Intervals.icu has no bulk activity-delete endpoint."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "confirm_activity_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                    "description": "Must exactly match activity_ids, including order.",
                },
            },
            "required": ["activity_ids", "confirm_activity_ids"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_ids": {"type": "array", "items": {"type": "string"}},
                "deleted_count": {"type": "integer"},
                "verified_deleted": {"type": "boolean"},
            },
            "required": ["activity_ids", "deleted_count", "verified_deleted"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["delete_activities"],
    },
    "upload_activity": {
        "name": "upload_activity",
        "description": (
            "Upload one explicit local activity file and verify the canonical returned "
            "activity id with a fresh direct readback and date-bounded list."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "minLength": 1},
                "athlete_id": {"type": ["string", "integer"], "default": 0},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string"},
                "uploaded_activity": _object("Intervals.icu upload response."),
                "verified_activity": _object("Fresh canonical activity readback."),
                "verified": {"type": "boolean"},
            },
            "required": ["activity_id", "uploaded_activity", "verified_activity", "verified"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["upload_activity"],
    },
    "list_wellness": {
        "name": "list_wellness",
        "description": (
            "List Intervals.icu wellness rows for an inclusive local-date range. "
            "Values may originate from connected systems; preserve source caveats."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date", "description": "Inclusive local start date."},
                "end_date": {"type": "string", "format": "date", "description": "Inclusive local end date."},
                **query_properties(_WELLNESS_FILTER_FIELDS),
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "count": {"type": "integer"},
                "wellness": {"type": "array", "items": _object("Intervals.icu wellness row.")},
                "source_count": {"type": "integer"}, "matched_count": {"type": "integer"},
                "filters": {"type": "array", "items": {}},
                "sort": {"type": "array", "items": {}},
                "limit": {"type": ["integer", "null"]},
            },
            "required": ["start_date", "end_date", "count", "wellness"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["list_wellness"],
    },
    "update_wellness": {
        "name": "update_wellness",
        "description": (
            "Update selected supported fields on one Intervals.icu wellness day. Reads "
            "the current row first, refuses conflicting overwrites unless explicitly "
            "confirmed, and verifies every requested field with a fresh readback."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date", "description": "Local wellness date."},
                "updates": {
                    "type": "object", "minProperties": 1, "additionalProperties": False,
                    "description": "Only explicitly supplied wellness fields are changed; null clears a field.",
                    "properties": {
                        "soreness": {
                            "type": ["integer", "null"], "minimum": 0, "maximum": 4,
                            "description": "Muscle soreness: 0 none through 4 extreme; null clears it.",
                        },
                        "fatigue": {
                            "type": ["integer", "null"], "minimum": 0, "maximum": 4,
                            "description": "General fatigue: 0 none through 4 extreme; null clears it.",
                        },
                        "motivation": {
                            "type": ["integer", "null"], "minimum": 1, "maximum": 4,
                            "description": "Motivation: 1 extreme through 4 low; null clears it.",
                        },
                        "comments": {
                            "type": ["string", "null"],
                            "description": "Explicit user-provided wellness comment; null clears it.",
                        },
                    },
                },
                "confirm_overwrite": {
                    "type": "boolean", "default": False,
                    "description": "Required when a requested value differs from an existing non-empty value.",
                },
            },
            "required": ["date", "updates"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "updates": _object("Requested supported field changes."),
                "before": _object("Wellness row before the patch."),
                "after": _object("Freshly read wellness row after the patch."),
                "overwritten_fields": {"type": "array", "items": {"type": "string"}},
                "verified": {"type": "boolean"},
            },
            "required": ["date", "updates", "before", "after", "overwritten_fields", "verified"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["update_wellness"],
    },
    "list_events": {
        "name": "list_events",
        "description": (
            "List all Intervals.icu calendar events for an inclusive local-date range."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date", "description": "Inclusive local start date."},
                "end_date": {"type": "string", "format": "date", "description": "Inclusive local end date."},
                **query_properties(_EVENT_FILTER_FIELDS),
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "count": {"type": "integer"},
                "events": {"type": "array", "items": _object("Intervals.icu calendar event.")},
                "source_count": {"type": "integer"}, "matched_count": {"type": "integer"},
                "filters": {"type": "array", "items": {}},
                "sort": {"type": "array", "items": {}},
                "limit": {"type": ["integer", "null"]},
            },
            "required": ["start_date", "end_date", "count", "events"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["list_events"],
    },
    "create_event": {
        "name": "create_event",
        "description": (
            "Create one all-day Intervals.icu calendar event and verify it. start_date and "
            "end_date are inclusive user dates; Intervals.icu receives an exclusive end "
            "boundary. Record sickness with category SICK, never as a wellness comment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "minLength": 1, "description": "Intervals.icu event category, for example SICK."},
                "name": {"type": "string", "minLength": 1, "description": "Event name, for example Syk."},
                "start_date": {"type": "string", "format": "date", "description": "First event day, inclusive."},
                "end_date": {"type": "string", "format": "date", "description": "Last event day, inclusive."},
            },
            "required": ["category", "name", "start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["created", "unchanged"]},
                "category": {"type": "string"}, "name": {"type": "string"},
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "stored_end_exclusive": {"type": "string"},
                "event": _object("Created or already-existing calendar event."),
                "verified_event": _object("Fresh calendar event readback."),
                "verified": {"type": "boolean"},
            },
            "required": [
                "action", "category", "name", "start_date", "end_date",
                "stored_end_exclusive", "event", "verified_event", "verified",
            ],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["create_event"],
    },
    "update_event": {
        "name": "update_event",
        "description": (
            "Replace the supported all-day state of one Intervals.icu calendar event "
            "and verify it by id. start_date and end_date are inclusive user dates; the stored "
            "end boundary is exclusive. Use list_events to resolve the exact event id first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": ["string", "integer"], "description": "Exact Intervals.icu event id from list_events."},
                "category": {"type": "string", "minLength": 1, "description": "Complete desired event category."},
                "name": {"type": "string", "minLength": 1, "description": "Complete desired event name."},
                "start_date": {"type": "string", "format": "date", "description": "Complete desired first day, inclusive."},
                "end_date": {"type": "string", "format": "date", "description": "Complete desired last day, inclusive."},
            },
            "required": ["event_id", "category", "name", "start_date", "end_date"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["updated"]},
                "event_id": {"type": ["string", "integer"]},
                "category": {"type": "string"}, "name": {"type": "string"},
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "stored_end_exclusive": {"type": "string"},
                "event": _object("Updated calendar event response."),
                "verified_event": _object("Fresh calendar event readback."),
                "verified": {"type": "boolean"},
            },
            "required": [
                "action", "event_id", "category", "name", "start_date", "end_date",
                "stored_end_exclusive", "event", "verified_event", "verified",
            ],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["update_event"],
    },
    "delete_event": {
        "name": "delete_event",
        "description": (
            "Delete one exact Intervals.icu calendar event after reading it from the "
            "supplied inclusive date range, then verify that its id is absent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": ["string", "integer"], "description": "Exact event id returned by list_events."},
                "start_date": {"type": "string", "format": "date", "description": "Inclusive lookup start date containing the event."},
                "end_date": {"type": "string", "format": "date", "description": "Inclusive lookup end date containing the event."},
                "confirm": {"type": ["string", "integer"], "description": "Must exactly match event_id."},
            },
            "required": ["event_id", "start_date", "end_date", "confirm"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": ["string", "integer"]},
                "before": _object("Event read immediately before deletion."),
                "deleted_response": _object("Intervals.icu deletion response."),
                "verified_deleted": {"type": "boolean"},
            },
            "required": ["event_id", "before", "deleted_response", "verified_deleted"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["delete_event"],
    },
}


class IntervalsIcuAuthSession:
    """Immutable authentication state shared by all calls in one MCP process."""

    def __init__(self, credentials: IntervalsIcuCredentials) -> None:
        self.credentials = credentials

    def api_kwargs(self) -> dict[str, str]:
        return self.credentials.api_kwargs()

class IntervalsIcuToolService:
    def __init__(
        self,
        credential_factory: Callable[[], IntervalsIcuCredentials] = discover_intervals_icu_credentials,
        activity_lister: Callable[..., list[dict[str, Any]]] = list_activities,
        activity_power_curve_lister: Callable[..., dict[str, Any]] = list_activity_power_curves,
        activity_searcher: Callable[..., list[dict[str, Any]]] = search_activities,
        activity_getter: Callable[..., dict[str, Any]] = get_activity,
        activities_getter: Callable[..., list[dict[str, Any]]] = get_activities,
        streams_downloader: Callable[..., Path] = download_activity_streams_csv,
        activity_file_downloader: Callable[..., Path] = download_activity_file,
        activity_updater: Callable[..., dict[str, Any]] = update_activity,
        activity_deleter: Callable[..., dict[str, Any]] = delete_activity,
        activity_uploader: Callable[..., dict[str, Any]] = upload_activity_file,
        wellness_lister: Callable[..., list[dict[str, Any]]] = list_wellness,
        wellness_getter: Callable[..., dict[str, Any]] = get_wellness,
        wellness_updater: Callable[..., dict[str, Any]] = update_wellness,
        event_lister: Callable[..., list[dict[str, Any]]] = list_events,
        event_creator: Callable[..., dict[str, Any]] = create_event,
        event_updater: Callable[..., dict[str, Any]] = update_event,
        event_deleter: Callable[..., dict[str, Any]] = delete_event,
    ) -> None:
        self._auth = IntervalsIcuAuthSession(credential_factory())
        self._activity_lister = activity_lister
        self._activity_power_curve_lister = activity_power_curve_lister
        self._activity_searcher = activity_searcher
        self._activity_getter = activity_getter
        self._activities_getter = activities_getter
        self._streams_downloader = streams_downloader
        self._activity_file_downloader = activity_file_downloader
        self._activity_updater = activity_updater
        self._activity_deleter = activity_deleter
        self._activity_uploader = activity_uploader
        self._wellness_lister = wellness_lister
        self._wellness_getter = wellness_getter
        self._wellness_updater = wellness_updater
        self._event_lister = event_lister
        self._event_creator = event_creator
        self._event_updater = event_updater
        self._event_deleter = event_deleter

    def _verified_event(
        self, event_state: dict[str, Any], saved: dict[str, Any],
        *, event_id: str | int | None = None,
    ) -> dict[str, Any]:
        readback = self._event_lister(
            oldest=event_state["start_date"], newest=event_state["end_date"],
            categories=event_state["category"], **self._auth.api_kwargs(),
        )
        expected_id = event_id if event_id is not None else saved.get("id")
        verified_event = next(
            (
                event for event in readback
                if (expected_id is None or str(event.get("id")) == str(expected_id))
                and _event_matches(event, event_state)
            ),
            None,
        )
        if verified_event is None:
            raise ToolFailure("Calendar event did not verify after write", "verification_error")
        return verified_event

    def list_tools(self) -> list[dict[str, object]]:
        return list(TOOL_DEFINITIONS.values())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_DEFINITIONS:
            raise ToolFailure(f"Unknown tool: {name}", "unknown_tool")
        unknown = set(arguments) - set(TOOL_DEFINITIONS[name]["inputSchema"]["properties"])
        if unknown:
            raise ToolFailure(f"Unsupported argument: {sorted(unknown)[0]}", "invalid_arguments")
        try:
            auth = self._auth.api_kwargs()
            if name == "list_activities":
                start_date = _required_date(arguments, "start_date")
                end_date = _required_date(arguments, "end_date")
                if end_date < start_date:
                    raise ToolFailure("end_date must not be before start_date", "invalid_arguments")
                include_fields = _include_fields(
                    arguments.get("includeFields", []), _ACTIVITY_LIST_INCLUDE_FIELDS
                )
                activities = self._activity_lister(oldest=start_date, newest=end_date, **auth)
                query_include = tuple(
                    field for field in query_fields(arguments, _ACTIVITY_LIST_FILTER_FIELDS)
                    if field in _ACTIVITY_LIST_INCLUDE_FIELDS
                )
                effective_fields = tuple(dict.fromkeys((*include_fields, *query_include)))
                summaries = [
                    _activity_list_summary(activity, effective_fields)
                    for activity in activities
                ]
                summaries, query_meta = apply_list_query(
                    summaries, arguments, _ACTIVITY_LIST_FILTER_FIELDS
                )
                return {
                    "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                    "includeFields": list(include_fields),
                    "count": len(summaries), "activities": summaries, **query_meta,
                }
            if name == "list_activity_power_curves":
                start_date = _required_date(arguments, "start_date")
                end_date = _required_date(arguments, "end_date")
                if end_date < start_date:
                    raise ToolFailure("end_date must not be before start_date", "invalid_arguments")
                secs = _required_positive_int_array(arguments, "secs", maximum_items=100)
                result = self._activity_power_curve_lister(
                    oldest=start_date, newest=end_date, secs=secs, **auth,
                )
                curves = result.get("curves")
                returned_secs = result.get("secs")
                if not isinstance(curves, list) or not isinstance(returned_secs, list):
                    raise ToolFailure(
                        "Activity power curves response is missing secs or curves",
                        "source_error",
                    )
                return {
                    "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                    "secs": returned_secs, "count": len(curves), "curves": curves,
                }
            if name == "search_activities":
                query = _required_string(arguments, "query")
                limit = arguments.get("limit", 10)
                if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                    raise ToolFailure("limit must be a positive integer", "invalid_arguments")
                include_fields = _include_fields(
                    arguments.get("includeFields", []), _ACTIVITY_LIST_INCLUDE_FIELDS
                )
                activities = self._activity_searcher(
                    query=query, limit=limit, **auth,
                )
                query_include = tuple(
                    field for field in query_fields(arguments, _ACTIVITY_LIST_FILTER_FIELDS)
                    if field in _ACTIVITY_LIST_INCLUDE_FIELDS
                )
                effective_fields = tuple(dict.fromkeys((*include_fields, *query_include)))
                summaries = [
                    _activity_list_summary(activity, effective_fields)
                    for activity in activities
                ]
                summaries, query_meta = apply_list_query(
                    summaries, arguments, _ACTIVITY_LIST_FILTER_FIELDS,
                    default_limit=limit,
                )
                return {
                    "query": query, "limit": limit,
                    "includeFields": list(include_fields),
                    "count": len(summaries), "activities": summaries,
                    "source_limited": True,
                    **{key: value for key, value in query_meta.items() if key != "limit"},
                }
            if name == "get_activity_file":
                activity_id = _required_string(arguments, "activity_id")
                kind = arguments.get("kind", "original")
                if kind not in {"original", "fit"}:
                    raise ToolFailure("kind must be 'original' or 'fit'", "invalid_arguments")
                temporary_dir = Path(tempfile.mkdtemp(prefix=f"intervals-{activity_id}-file-"))
                os.chmod(temporary_dir, 0o700)
                try:
                    path = self._activity_file_downloader(
                        activity_id=activity_id, kind=kind,
                        output_path=temporary_dir, **auth,
                    )
                    os.chmod(path, 0o600)
                except Exception:
                    for child in temporary_dir.iterdir():
                        child.unlink(missing_ok=True)
                    temporary_dir.rmdir()
                    raise
                return {
                    "activity_id": activity_id, "kind": kind,
                    "file_path": str(path), "byte_size": path.stat().st_size,
                }
            if name == "update_activity":
                activity_id = _required_string(arguments, "activity_id")
                updates = _activity_updates(arguments.get("updates"))
                confirm_overwrite = arguments.get("confirm_overwrite", False)
                if not isinstance(confirm_overwrite, bool):
                    raise ToolFailure("confirm_overwrite must be a boolean", "invalid_arguments")
                before = self._activity_getter(
                    activity_id=activity_id, include_intervals=False, **auth,
                )
                overwritten_fields = [
                    field for field, requested in updates.items()
                    if _has_value(before.get(field)) and before.get(field) != requested
                ]
                if overwritten_fields and not confirm_overwrite:
                    details = {
                        field: {"current": before.get(field), "requested": updates[field]}
                        for field in overwritten_fields
                    }
                    raise ToolFailure(
                        f"Refusing to overwrite existing activity values without confirmation: {details}",
                        "overwrite_confirmation_required",
                    )
                self._activity_updater(activity_id=activity_id, updates=updates, **auth)
                after = self._activity_getter(
                    activity_id=activity_id, include_intervals=False, **auth,
                )
                mismatches = {
                    field: {"requested": requested, "readback": after.get(field)}
                    for field, requested in updates.items() if after.get(field) != requested
                }
                if mismatches:
                    raise ToolFailure(
                        f"Activity update did not verify: {mismatches}", "verification_error"
                    )
                before_values = {field: before.get(field) for field in updates}
                after_values = {field: after.get(field) for field in updates}
                return {
                    "activity_id": activity_id, "updates": updates,
                    "before": before_values, "after": after_values,
                    "overwritten_fields": overwritten_fields, "verified": True,
                }
            if name == "delete_activity":
                activity_id = _required_string(arguments, "activity_id")
                if arguments.get("confirm") != activity_id:
                    raise ToolFailure("confirm must exactly match activity_id", "confirmation_required")
                before = self._activity_getter(
                    activity_id=activity_id, include_intervals=False, **auth,
                )
                activity_day = _activity_local_date(before)
                deleted_response = self._activity_deleter(activity_id=activity_id, **auth)
                direct_absent = False
                try:
                    self._activity_getter(
                        activity_id=activity_id, include_intervals=False, **auth,
                    )
                except RuntimeError as exc:
                    direct_absent = _is_not_found(exc)
                    if not direct_absent:
                        raise
                listed = self._activity_lister(
                    oldest=activity_day, newest=activity_day, **auth,
                )
                list_absent = not any(
                    str(activity.get("id")) == activity_id for activity in listed
                )
                if not direct_absent or not list_absent:
                    raise ToolFailure("Activity did not verify as deleted", "verification_error")
                return {
                    "activity_id": activity_id, "before": before,
                    "deleted_response": deleted_response, "verified_deleted": True,
                }
            if name == "delete_activities":
                activity_ids = _required_unique_string_array(arguments, "activity_ids")
                confirm_activity_ids = _required_unique_string_array(
                    arguments, "confirm_activity_ids"
                )
                if confirm_activity_ids != activity_ids:
                    raise ToolFailure(
                        "confirm_activity_ids must exactly match activity_ids, including order",
                        "confirmation_required",
                    )
                before = self._activities_getter(
                    activity_ids=activity_ids, include_intervals=False, **auth,
                )
                _activities_in_requested_order(activity_ids, before)
                for activity_id in activity_ids:
                    self._activity_deleter(activity_id=activity_id, **auth)
                remaining = self._activities_getter(
                    activity_ids=activity_ids, include_intervals=False, **auth,
                )
                if remaining:
                    remaining_ids = [str(activity.get("id")) for activity in remaining]
                    raise ToolFailure(
                        f"Activities did not verify as deleted: {', '.join(remaining_ids)}",
                        "verification_error",
                    )
                return {
                    "activity_ids": activity_ids,
                    "deleted_count": len(activity_ids),
                    "verified_deleted": True,
                }
            if name == "upload_activity":
                file_path = Path(_required_string(arguments, "file_path")).expanduser()
                if not file_path.is_file():
                    raise ToolFailure("file_path must reference an existing file", "invalid_arguments")
                athlete_id = arguments.get("athlete_id", 0)
                if isinstance(athlete_id, bool) or not isinstance(athlete_id, (str, int)):
                    raise ToolFailure("athlete_id must be a string or integer", "invalid_arguments")
                uploaded = self._activity_uploader(
                    file_path=file_path, athlete_id=athlete_id, **auth,
                )
                uploaded_id = uploaded.get("id")
                if uploaded_id is None or isinstance(uploaded_id, bool):
                    raise ToolFailure("Upload response did not contain an activity id", "verification_error")
                activity_id = str(uploaded_id)
                verified_activity = self._activity_getter(
                    activity_id=activity_id, include_intervals=False, **auth,
                )
                activity_day = _activity_local_date(verified_activity)
                listed = self._activity_lister(
                    oldest=activity_day, newest=activity_day, athlete_id=athlete_id, **auth,
                )
                if not any(str(activity.get("id")) == activity_id for activity in listed):
                    raise ToolFailure("Uploaded activity did not verify in date list", "verification_error")
                return {
                    "activity_id": activity_id, "uploaded_activity": uploaded,
                    "verified_activity": verified_activity, "verified": True,
                }
            if name == "list_wellness":
                start_date = _required_date(arguments, "start_date")
                end_date = _required_date(arguments, "end_date")
                if end_date < start_date:
                    raise ToolFailure("end_date must not be before start_date", "invalid_arguments")
                wellness = self._wellness_lister(
                    oldest=start_date, newest=end_date, **auth,
                )
                wellness, query_meta = apply_list_query(
                    wellness, arguments, _WELLNESS_FILTER_FIELDS
                )
                return {
                    "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                    "count": len(wellness), "wellness": wellness, **query_meta,
                }
            if name == "update_wellness":
                day = _required_date(arguments, "date")
                updates = _wellness_updates(arguments.get("updates"))
                confirm_overwrite = arguments.get("confirm_overwrite", False)
                if not isinstance(confirm_overwrite, bool):
                    raise ToolFailure("confirm_overwrite must be a boolean", "invalid_arguments")
                before = self._wellness_getter(day=day, **auth)
                overwritten_fields = [
                    field for field, requested in updates.items()
                    if _has_value(before.get(field)) and before.get(field) != requested
                ]
                if overwritten_fields and not confirm_overwrite:
                    details = {
                        field: {"current": before.get(field), "requested": updates[field]}
                        for field in overwritten_fields
                    }
                    raise ToolFailure(
                        f"Refusing to overwrite existing wellness values without confirmation: {details}",
                        "overwrite_confirmation_required",
                    )
                self._wellness_updater(day=day, updates=updates, **auth)
                after = self._wellness_getter(day=day, **auth)
                mismatches = {
                    field: {"requested": requested, "readback": after.get(field)}
                    for field, requested in updates.items()
                    if after.get(field) != requested
                }
                if mismatches:
                    raise ToolFailure(
                        f"Wellness update did not verify: {mismatches}", "verification_error"
                    )
                return {
                    "date": day.isoformat(), "updates": updates,
                    "before": before, "after": after,
                    "overwritten_fields": overwritten_fields, "verified": True,
                }
            if name == "list_events":
                start_date = _required_date(arguments, "start_date")
                end_date = _required_date(arguments, "end_date")
                if end_date < start_date:
                    raise ToolFailure("end_date must not be before start_date", "invalid_arguments")
                events = self._event_lister(
                    oldest=start_date, newest=end_date, categories=None, **auth,
                )
                events, query_meta = apply_list_query(
                    events, arguments, _EVENT_FILTER_FIELDS
                )
                return {
                    "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                    "count": len(events), "events": events, **query_meta,
                }
            if name == "create_event":
                event_state = _event_state(arguments)
                existing_events = self._event_lister(
                    oldest=event_state["start_date"], newest=event_state["end_date"],
                    categories=event_state["category"], **auth,
                )
                exact = next(
                    (event for event in existing_events if _event_matches(event, event_state)), None
                )
                if exact is not None:
                    saved = exact
                    action = "unchanged"
                else:
                    saved = self._event_creator(event=event_state["payload"], **auth)
                    action = "created"
                verified_event = self._verified_event(event_state, saved)
                return {
                    "action": action, "category": event_state["category"],
                    "name": event_state["name"],
                    "start_date": event_state["start_date"].isoformat(),
                    "end_date": event_state["end_date"].isoformat(),
                    "stored_end_exclusive": event_state["exclusive_end"].isoformat(),
                    "event": saved, "verified_event": verified_event, "verified": True,
                }
            if name == "update_event":
                event_id = arguments.get("event_id")
                if isinstance(event_id, bool) or not isinstance(event_id, (str, int)) or event_id == "":
                    raise ToolFailure("event_id must be a non-empty string or integer", "invalid_arguments")
                event_state = _event_state(arguments)
                saved = self._event_updater(
                    event_id=event_id, updates=event_state["payload"], **auth,
                )
                verified_event = self._verified_event(event_state, saved, event_id=event_id)
                return {
                    "action": "updated", "event_id": event_id,
                    "category": event_state["category"], "name": event_state["name"],
                    "start_date": event_state["start_date"].isoformat(),
                    "end_date": event_state["end_date"].isoformat(),
                    "stored_end_exclusive": event_state["exclusive_end"].isoformat(),
                    "event": saved, "verified_event": verified_event, "verified": True,
                }
            if name == "delete_event":
                event_id = arguments.get("event_id")
                if isinstance(event_id, bool) or not isinstance(event_id, (str, int)) or event_id == "":
                    raise ToolFailure("event_id must be a non-empty string or integer", "invalid_arguments")
                if str(arguments.get("confirm")) != str(event_id):
                    raise ToolFailure("confirm must exactly match event_id", "confirmation_required")
                start_date = _required_date(arguments, "start_date")
                end_date = _required_date(arguments, "end_date")
                if end_date < start_date:
                    raise ToolFailure("end_date must not be before start_date", "invalid_arguments")
                before_rows = self._event_lister(
                    oldest=start_date, newest=end_date, categories=None, **auth,
                )
                before = next(
                    (event for event in before_rows if str(event.get("id")) == str(event_id)),
                    None,
                )
                if before is None:
                    raise ToolFailure("Event id not found in supplied date range", "not_found")
                deleted_response = self._event_deleter(event_id=event_id, **auth)
                after_rows = self._event_lister(
                    oldest=start_date, newest=end_date, categories=None, **auth,
                )
                verified_deleted = not any(
                    str(event.get("id")) == str(event_id) for event in after_rows
                )
                if not verified_deleted:
                    raise ToolFailure("Calendar event did not verify as deleted", "verification_error")
                return {
                    "event_id": event_id, "before": before,
                    "deleted_response": deleted_response, "verified_deleted": True,
                }
            if name == "get_activities":
                activity_ids = arguments.get("activity_ids")
                if not isinstance(activity_ids, list) or not activity_ids or any(
                    not isinstance(value, str) or not value for value in activity_ids
                ):
                    raise ToolFailure(
                        "activity_ids must be a non-empty array of non-empty strings",
                        "invalid_arguments",
                    )
                if len(set(activity_ids)) != len(activity_ids):
                    raise ToolFailure("activity_ids must contain unique values", "invalid_arguments")
                include_fields = _include_fields(
                    arguments.get("includeFields", []), _ACTIVITY_LIST_INCLUDE_FIELDS
                )
                save_full = arguments.get("save_full", False)
                if not isinstance(save_full, bool):
                    raise ToolFailure("save_full must be a boolean", "invalid_arguments")
                activities = self._activities_getter(
                    activity_ids=activity_ids, include_intervals=True, **auth,
                )
                activities = _activities_in_requested_order(activity_ids, activities)
                result = {
                    "activity_ids": activity_ids,
                    "includeFields": list(include_fields),
                    "count": len(activities),
                    "activities": [
                        _activity_list_summary(activity, include_fields)
                        for activity in activities
                    ],
                }
                if save_full:
                    descriptor, raw_path = tempfile.mkstemp(
                        prefix="intervals-", suffix="-activities.json"
                    )
                    try:
                        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                            json.dump(
                                {"activity_ids": activity_ids, "activities": activities},
                                handle, ensure_ascii=False, separators=(",", ":"),
                            )
                        os.chmod(raw_path, 0o600)
                        result["full_activities_file"] = raw_path
                        result["full_activities_format"] = "intervals-icu-activities-v1"
                        result["full_activities_byte_size"] = Path(raw_path).stat().st_size
                    except Exception:
                        Path(raw_path).unlink(missing_ok=True)
                        raise
                return result
            activity_id = _required_string(arguments, "activity_id")
            if name == "get_activity":
                include_fields = _include_fields(
                    arguments.get("includeFields", []), _ACTIVITY_LIST_INCLUDE_FIELDS
                )
                save_full = arguments.get("save_full", False)
                if not isinstance(save_full, bool):
                    raise ToolFailure("save_full must be a boolean", "invalid_arguments")
                activity = self._activity_getter(
                    activity_id=activity_id, include_intervals=True, **auth,
                )
                result = {
                    "activity_id": activity_id,
                    "includeFields": list(include_fields),
                    "activity": _activity_list_summary(activity, include_fields),
                }
                if save_full:
                    descriptor, raw_path = tempfile.mkstemp(
                        prefix=f"intervals-{activity_id}-", suffix="-activity.json"
                    )
                    try:
                        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                            json.dump(
                                {"activity_id": activity_id, "activity": activity},
                                handle, ensure_ascii=False, separators=(",", ":"),
                            )
                        os.chmod(raw_path, 0o600)
                        result["full_activity_file"] = raw_path
                        result["full_activity_format"] = "intervals-icu-activity-v1"
                        result["full_activity_byte_size"] = Path(raw_path).stat().st_size
                    except Exception:
                        Path(raw_path).unlink(missing_ok=True)
                        raise
                return result
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
                    activity_id=activity_id,
                    stream_types=stream_types or None, output_path=raw_path,
                    **auth,
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


def _required_positive_int_array(
    arguments: dict[str, Any], key: str, *, maximum_items: int
) -> tuple[int, ...]:
    value = arguments.get(key)
    if not isinstance(value, list) or not value or len(value) > maximum_items:
        raise ToolFailure(
            f"{key} must be a non-empty array with at most {maximum_items} items",
            "invalid_arguments",
        )
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        raise ToolFailure(f"{key} values must be positive integers", "invalid_arguments")
    if len(set(value)) != len(value):
        raise ToolFailure(f"{key} values must be unique", "invalid_arguments")
    return tuple(value)


def _required_unique_string_array(arguments: dict[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ToolFailure(
            f"{key} must be a non-empty array of non-empty strings", "invalid_arguments"
        )
    if len(set(value)) != len(value):
        raise ToolFailure(f"{key} must contain unique values", "invalid_arguments")
    return value


def _include_fields(value: Any, allowed: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(field, str) for field in value):
        raise ToolFailure("includeFields must be an array of strings", "invalid_arguments")
    if len(set(value)) != len(value):
        raise ToolFailure("includeFields must contain unique fields", "invalid_arguments")
    unsupported = [field for field in value if field not in allowed]
    if unsupported:
        raise ToolFailure(
            f"Unsupported includeFields value: {unsupported[0]}", "invalid_arguments"
        )
    return tuple(value)


def _activity_list_summary(
    activity: dict[str, Any], include_fields: tuple[str, ...]
) -> dict[str, Any]:
    summary = {
        "id": activity.get("id"),
        "name": activity.get("name"),
        "start_date_local": activity.get("start_date_local"),
    }
    aliases = {
        "duration_s": activity.get("elapsed_time"),
        "distance_m": activity.get("distance"),
    }
    summary.update({
        field: aliases[field] if field in aliases else activity.get(field)
        for field in include_fields
    })
    return summary


def _activities_in_requested_order(
    activity_ids: list[str], activities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate and order a batch response by the caller's activity ids."""
    by_id: dict[str, dict[str, Any]] = {}
    for activity in activities:
        activity_id = activity.get("id")
        if not isinstance(activity_id, str) or not activity_id:
            raise ToolFailure("Batch response activity is missing a valid id", "source_error")
        if activity_id in by_id:
            raise ToolFailure(
                f"Batch response contained duplicate activity id: {activity_id}",
                "source_error",
            )
        by_id[activity_id] = activity

    requested = set(activity_ids)
    missing = [activity_id for activity_id in activity_ids if activity_id not in by_id]
    unexpected = [activity_id for activity_id in by_id if activity_id not in requested]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing ids: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected ids: {', '.join(unexpected)}")
        raise ToolFailure(
            f"Batch response did not match requested activity ids ({'; '.join(details)})",
            "source_error",
        )
    return [by_id[activity_id] for activity_id in activity_ids]


def _required_date(arguments: dict[str, Any], key: str) -> date:
    value = _required_string(arguments, key)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolFailure(f"{key} must use YYYY-MM-DD", "invalid_arguments") from exc


WELLNESS_FIELDS = {"soreness", "fatigue", "motivation", "comments"}
ACTIVITY_FIELDS = {
    "name", "description", "tags", "sub_type", "icu_color", "carbs_ingested",
    "kg_lifted", "feel", "icu_rpe",
    "icu_ignore_time", "icu_ignore_hr", "icu_ignore_power", "ignore_velocity",
    "ignore_pace",
}
ACTIVITY_BOOLEAN_FIELDS = {
    "icu_ignore_time", "icu_ignore_hr", "icu_ignore_power", "ignore_velocity",
    "ignore_pace",
}
ACTIVITY_SUB_TYPES = {"NONE", "COMMUTE", "WARMUP", "COOLDOWN", "RACE"}


def _activity_updates(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ToolFailure("updates must be a non-empty object", "invalid_arguments")
    unknown = set(value) - ACTIVITY_FIELDS
    if unknown:
        raise ToolFailure(f"Unsupported activity field: {sorted(unknown)[0]}", "invalid_arguments")
    updates = dict(value)
    name = updates.get("name")
    if "name" in updates and (not isinstance(name, str) or not name.strip()):
        raise ToolFailure("updates.name must be a non-empty string", "invalid_arguments")
    description = updates.get("description")
    if (
        "description" in updates
        and description is not None
        and not isinstance(description, str)
    ):
        raise ToolFailure("updates.description must be a string or null", "invalid_arguments")
    tags = updates.get("tags")
    if "tags" in updates and (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
        or len(tags) != len(set(tags))
    ):
        raise ToolFailure(
            "updates.tags must be an array of unique non-empty strings", "invalid_arguments"
        )
    sub_type = updates.get("sub_type")
    if "sub_type" in updates and sub_type not in ACTIVITY_SUB_TYPES:
        raise ToolFailure(
            "updates.sub_type must be NONE, COMMUTE, WARMUP, COOLDOWN, or RACE",
            "invalid_arguments",
        )
    color = updates.get("icu_color")
    if "icu_color" in updates and color is not None and (
        not isinstance(color, str) or not color.strip()
    ):
        raise ToolFailure(
            "updates.icu_color must be a non-empty string or null", "invalid_arguments"
        )
    carbs_ingested = updates.get("carbs_ingested")
    if "carbs_ingested" in updates and (
        isinstance(carbs_ingested, bool)
        or not isinstance(carbs_ingested, int)
        or carbs_ingested < 0
    ):
        raise ToolFailure(
            "updates.carbs_ingested must be a non-negative integer", "invalid_arguments"
        )
    kg_lifted = updates.get("kg_lifted")
    if "kg_lifted" in updates and (
        isinstance(kg_lifted, bool)
        or not isinstance(kg_lifted, (int, float))
        or kg_lifted < 0
    ):
        raise ToolFailure(
            "updates.kg_lifted must be a non-negative number", "invalid_arguments"
        )
    for field in ACTIVITY_BOOLEAN_FIELDS:
        if field in updates and not isinstance(updates[field], bool):
            raise ToolFailure(f"updates.{field} must be a boolean", "invalid_arguments")
    feel = updates.get("feel")
    if "feel" in updates and feel is not None and (
        isinstance(feel, bool) or not isinstance(feel, int) or not 1 <= feel <= 5
    ):
        raise ToolFailure("updates.feel must be an integer from 1 to 5 or null", "invalid_arguments")
    rpe = updates.get("icu_rpe")
    if "icu_rpe" in updates and rpe is not None and (
        isinstance(rpe, bool) or not isinstance(rpe, (int, float)) or not 0 <= rpe <= 10
    ):
        raise ToolFailure("updates.icu_rpe must be a number from 0 to 10 or null", "invalid_arguments")
    return updates


def _activity_local_date(activity: dict[str, Any]) -> date:
    value = str(activity.get("start_date_local") or "")[:10]
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolFailure(
            "Activity is missing a valid start_date_local for verification",
            "verification_error",
        ) from exc


def _is_not_found(exc: Exception) -> bool:
    message = str(exc)
    return "HTTP 404" in message or "Not Found" in message


def _wellness_updates(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ToolFailure("updates must be a non-empty object", "invalid_arguments")
    unknown = set(value) - WELLNESS_FIELDS
    if unknown:
        raise ToolFailure(f"Unsupported wellness field: {sorted(unknown)[0]}", "invalid_arguments")
    updates = dict(value)
    for field in ("soreness", "fatigue"):
        field_value = updates.get(field)
        if field in updates and field_value is not None and (
            isinstance(field_value, bool) or not isinstance(field_value, int)
            or not 0 <= field_value <= 4
        ):
            raise ToolFailure(f"updates.{field} must be an integer from 0 to 4 or null", "invalid_arguments")
    motivation = updates.get("motivation")
    if "motivation" in updates and motivation is not None and (
        isinstance(motivation, bool) or not isinstance(motivation, int)
        or not 1 <= motivation <= 4
    ):
        raise ToolFailure("updates.motivation must be an integer from 1 to 4 or null", "invalid_arguments")
    comments = updates.get("comments")
    if "comments" in updates and comments is not None and not isinstance(comments, str):
        raise ToolFailure("updates.comments must be a string or null", "invalid_arguments")
    return updates


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _event_state(arguments: dict[str, Any]) -> dict[str, Any]:
    category = _required_string(arguments, "category")
    name = _required_string(arguments, "name")
    start_date = _required_date(arguments, "start_date")
    end_date = _required_date(arguments, "end_date")
    if end_date < start_date:
        raise ToolFailure("end_date must not be before start_date", "invalid_arguments")
    exclusive_end = end_date + timedelta(days=1)
    return {
        "category": category,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "exclusive_end": exclusive_end,
        "payload": {
            "category": category,
            "name": name,
            "start_date_local": f"{start_date.isoformat()}T00:00:00",
            "end_date_local": f"{exclusive_end.isoformat()}T00:00:00",
        },
    }


def _event_matches(event: dict[str, Any], state: dict[str, Any]) -> bool:
    payload = state["payload"]
    return (
        event.get("category") == payload["category"]
        and event.get("name") == payload["name"]
        and str(event.get("start_date_local") or "")[:19] == payload["start_date_local"]
        and str(event.get("end_date_local") or "")[:19] == payload["end_date_local"]
    )


def create_sdk_server(service: IntervalsIcuToolService) -> Any:
    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server(
        "intervals-icu", version="0.1.0",
        instructions=(
            "List and search activities; fetch activity details, streams, and files; "
            "safely update, delete, and upload activities; manage wellness and "
            "calendar events with verified writes."
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
