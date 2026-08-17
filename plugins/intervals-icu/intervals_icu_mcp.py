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
    download_activity_streams_csv,
    create_event,
    delete_event,
    get_activity,
    get_wellness,
    list_activities,
    list_events,
    list_wellness,
    discover_intervals_icu_credentials,
    search_activities,
    update_wellness,
    update_event,
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
    "search_activities": {
        "title": "Search Intervals.icu Activities", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    "get_activity_streams": {
        "title": "Get Intervals.icu Activity Streams", "readOnlyHint": False,
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
    "search_activities": {
        "name": "search_activities",
        "description": (
            "Search Intervals.icu activities through the source search endpoint. "
            "The result is limited by Intervals.icu and preserves source order and duplicates."
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
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "count": {"type": "integer"},
                "activities": {"type": "array", "items": _object("Intervals.icu search result.")},
            },
            "required": ["query", "limit", "count", "activities"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["search_activities"],
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
    "list_wellness": {
        "name": "list_wellness",
        "description": (
            "List Intervals.icu wellness rows for an inclusive local-date range. "
            "Values may originate from connected systems; preserve source caveats."
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
                "wellness": {"type": "array", "items": _object("Intervals.icu wellness row.")},
            },
            "required": ["since", "until", "count", "wellness"],
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
                "events": {"type": "array", "items": _object("Intervals.icu calendar event.")},
            },
            "required": ["since", "until", "count", "events"],
            "additionalProperties": False,
        },
        "annotations": ANNOTATIONS["list_events"],
    },
    "create_event": {
        "name": "create_event",
        "description": (
            "Create one all-day Intervals.icu calendar event and verify it. since and "
            "until are inclusive user dates; Intervals.icu receives an exclusive end "
            "boundary. Record sickness with category SICK, never as a wellness comment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "minLength": 1, "description": "Intervals.icu event category, for example SICK."},
                "name": {"type": "string", "minLength": 1, "description": "Event name, for example Syk."},
                "since": {"type": "string", "format": "date", "description": "First event day, inclusive."},
                "until": {"type": "string", "format": "date", "description": "Last event day, inclusive."},
            },
            "required": ["category", "name", "since", "until"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["created", "unchanged"]},
                "category": {"type": "string"}, "name": {"type": "string"},
                "since": {"type": "string"}, "until": {"type": "string"},
                "stored_end_exclusive": {"type": "string"},
                "event": _object("Created or already-existing calendar event."),
                "verified_event": _object("Fresh calendar event readback."),
                "verified": {"type": "boolean"},
            },
            "required": [
                "action", "category", "name", "since", "until",
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
            "and verify it by id. since and until are inclusive user dates; the stored "
            "end boundary is exclusive. Use list_events to resolve the exact event id first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": ["string", "integer"], "description": "Exact Intervals.icu event id from list_events."},
                "category": {"type": "string", "minLength": 1, "description": "Complete desired event category."},
                "name": {"type": "string", "minLength": 1, "description": "Complete desired event name."},
                "since": {"type": "string", "format": "date", "description": "Complete desired first day, inclusive."},
                "until": {"type": "string", "format": "date", "description": "Complete desired last day, inclusive."},
            },
            "required": ["event_id", "category", "name", "since", "until"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["updated"]},
                "event_id": {"type": ["string", "integer"]},
                "category": {"type": "string"}, "name": {"type": "string"},
                "since": {"type": "string"}, "until": {"type": "string"},
                "stored_end_exclusive": {"type": "string"},
                "event": _object("Updated calendar event response."),
                "verified_event": _object("Fresh calendar event readback."),
                "verified": {"type": "boolean"},
            },
            "required": [
                "action", "event_id", "category", "name", "since", "until",
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
                "since": {"type": "string", "format": "date", "description": "Inclusive lookup start date containing the event."},
                "until": {"type": "string", "format": "date", "description": "Inclusive lookup end date containing the event."},
                "confirm": {"type": ["string", "integer"], "description": "Must exactly match event_id."},
            },
            "required": ["event_id", "since", "until", "confirm"],
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

    @property
    def cookie(self) -> str | None:
        return self.credentials.cookie


class IntervalsIcuToolService:
    def __init__(
        self,
        credential_factory: Callable[[], IntervalsIcuCredentials] = discover_intervals_icu_credentials,
        activity_lister: Callable[..., list[dict[str, Any]]] = list_activities,
        activity_searcher: Callable[..., list[dict[str, Any]]] = search_activities,
        activity_getter: Callable[..., dict[str, Any]] = get_activity,
        streams_downloader: Callable[..., Path] = download_activity_streams_csv,
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
        self._activity_searcher = activity_searcher
        self._activity_getter = activity_getter
        self._streams_downloader = streams_downloader
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
            oldest=event_state["since"], newest=event_state["until"],
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
                since = _required_date(arguments, "since")
                until = _required_date(arguments, "until")
                if until < since:
                    raise ToolFailure("until must not be before since", "invalid_arguments")
                activities = self._activity_lister(oldest=since, newest=until, **auth)
                return {
                    "since": since.isoformat(), "until": until.isoformat(),
                    "count": len(activities), "activities": activities,
                }
            if name == "search_activities":
                query = _required_string(arguments, "query")
                limit = arguments.get("limit", 10)
                if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                    raise ToolFailure("limit must be a positive integer", "invalid_arguments")
                activities = self._activity_searcher(
                    query=query, limit=limit, **auth,
                )
                return {
                    "query": query, "limit": limit,
                    "count": len(activities), "activities": activities,
                }
            if name == "list_wellness":
                since = _required_date(arguments, "since")
                until = _required_date(arguments, "until")
                if until < since:
                    raise ToolFailure("until must not be before since", "invalid_arguments")
                wellness = self._wellness_lister(
                    oldest=since, newest=until, **auth,
                )
                return {
                    "since": since.isoformat(), "until": until.isoformat(),
                    "count": len(wellness), "wellness": wellness,
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
                since = _required_date(arguments, "since")
                until = _required_date(arguments, "until")
                if until < since:
                    raise ToolFailure("until must not be before since", "invalid_arguments")
                events = self._event_lister(
                    oldest=since, newest=until, categories=None, **auth,
                )
                return {
                    "since": since.isoformat(), "until": until.isoformat(),
                    "count": len(events), "events": events,
                }
            if name == "create_event":
                event_state = _event_state(arguments)
                existing_events = self._event_lister(
                    oldest=event_state["since"], newest=event_state["until"],
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
                    "name": event_state["name"], "since": event_state["since"].isoformat(),
                    "until": event_state["until"].isoformat(),
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
                    "since": event_state["since"].isoformat(),
                    "until": event_state["until"].isoformat(),
                    "stored_end_exclusive": event_state["exclusive_end"].isoformat(),
                    "event": saved, "verified_event": verified_event, "verified": True,
                }
            if name == "delete_event":
                event_id = arguments.get("event_id")
                if isinstance(event_id, bool) or not isinstance(event_id, (str, int)) or event_id == "":
                    raise ToolFailure("event_id must be a non-empty string or integer", "invalid_arguments")
                if str(arguments.get("confirm")) != str(event_id):
                    raise ToolFailure("confirm must exactly match event_id", "confirmation_required")
                since = _required_date(arguments, "since")
                until = _required_date(arguments, "until")
                if until < since:
                    raise ToolFailure("until must not be before since", "invalid_arguments")
                before_rows = self._event_lister(
                    oldest=since, newest=until, categories=None, **auth,
                )
                before = next(
                    (event for event in before_rows if str(event.get("id")) == str(event_id)),
                    None,
                )
                if before is None:
                    raise ToolFailure("Event id not found in supplied date range", "not_found")
                deleted_response = self._event_deleter(event_id=event_id, **auth)
                after_rows = self._event_lister(
                    oldest=since, newest=until, categories=None, **auth,
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
            activity_id = _required_string(arguments, "activity_id")
            if name == "get_activity":
                include_intervals = arguments.get("include_intervals", True)
                if not isinstance(include_intervals, bool):
                    raise ToolFailure("include_intervals must be a boolean", "invalid_arguments")
                activity = self._activity_getter(
                    activity_id=activity_id, include_intervals=include_intervals, **auth,
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


def _required_date(arguments: dict[str, Any], key: str) -> date:
    value = _required_string(arguments, key)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolFailure(f"{key} must use YYYY-MM-DD", "invalid_arguments") from exc


WELLNESS_FIELDS = {"soreness", "fatigue", "motivation", "comments"}


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
    since = _required_date(arguments, "since")
    until = _required_date(arguments, "until")
    if until < since:
        raise ToolFailure("until must not be before since", "invalid_arguments")
    exclusive_end = until + timedelta(days=1)
    return {
        "category": category,
        "name": name,
        "since": since,
        "until": until,
        "exclusive_end": exclusive_end,
        "payload": {
            "category": category,
            "name": name,
            "start_date_local": f"{since.isoformat()}T00:00:00",
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
            "List and search activities, fetch one activity and its streams, list "
            "and update wellness, list calendar events, and safely record sickness "
            "as a verified SICK calendar event."
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
