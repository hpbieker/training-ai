"""Closed, declarative filtering and sorting for MCP list results."""

from __future__ import annotations

from functools import cmp_to_key
from typing import Any


OPERATORS = ("eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "exists")
DIRECTIONS = ("asc", "desc")


def query_properties(fields: tuple[str, ...], *, include_limit: bool = True) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "filters": {
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(fields)},
                    "op": {"type": "string", "enum": list(OPERATORS)},
                    "value": {},
                },
                "required": ["field", "op", "value"],
                "additionalProperties": False,
            },
            "description": "All typed filters are combined with AND.",
        },
        "sort": {
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(fields)},
                    "direction": {"type": "string", "enum": list(DIRECTIONS)},
                },
                "required": ["field", "direction"],
                "additionalProperties": False,
            },
            "description": "Stable ordered sort keys applied before the result limit.",
        },
    }
    if include_limit:
        properties["limit"] = {
            "type": "integer", "minimum": 1, "maximum": 500,
            "description": "Maximum rows returned after filtering and sorting.",
        }
    return properties


def query_fields(arguments: dict[str, Any], allowed_fields: tuple[str, ...]) -> tuple[str, ...]:
    allowed = set(allowed_fields)
    fields: list[str] = []
    for item in arguments.get("filters", []):
        if isinstance(item, dict) and item.get("field") in allowed:
            fields.append(item["field"])
    for item in arguments.get("sort", []):
        if isinstance(item, dict) and item.get("field") in allowed:
            fields.append(item["field"])
    return tuple(dict.fromkeys(fields))


def apply_list_query(
    rows: list[dict[str, Any]],
    arguments: dict[str, Any],
    allowed_fields: tuple[str, ...],
    *,
    default_limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filters = arguments.get("filters", [])
    sort = arguments.get("sort", [])
    limit = arguments.get("limit", default_limit)
    if not isinstance(filters, list):
        raise ValueError("filters must be an array")
    if not isinstance(sort, list):
        raise ValueError("sort must be an array")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500
    ):
        raise ValueError("limit must be an integer from 1 to 500")
    allowed = set(allowed_fields)
    parsed_filters = [_validate_filter(item, allowed) for item in filters]
    parsed_sort = [_validate_sort(item, allowed) for item in sort]
    matched = [row for row in rows if all(_matches(row, *item) for item in parsed_filters)]
    if parsed_sort:
        matched = sorted(matched, key=cmp_to_key(lambda a, b: _compare_rows(a, b, parsed_sort)))
    returned = matched[:limit] if limit is not None else matched
    return returned, {
        "source_count": len(rows),
        "matched_count": len(matched),
        "filters": filters,
        "sort": sort,
        "limit": limit,
    }


def _validate_filter(item: Any, allowed: set[str]) -> tuple[str, str, Any]:
    if not isinstance(item, dict) or set(item) != {"field", "op", "value"}:
        raise ValueError("each filter must contain only field, op, and value")
    field, op, value = item["field"], item["op"], item["value"]
    if field not in allowed:
        raise ValueError(f"unsupported filter field: {field}")
    if op not in OPERATORS:
        raise ValueError(f"unsupported filter operator: {op}")
    if op in {"in", "not_in"} and not isinstance(value, list):
        raise ValueError(f"filter operator {op} requires an array value")
    if op == "exists" and not isinstance(value, bool):
        raise ValueError("filter operator exists requires a boolean value")
    return field, op, value


def _validate_sort(item: Any, allowed: set[str]) -> tuple[str, str]:
    if not isinstance(item, dict) or set(item) != {"field", "direction"}:
        raise ValueError("each sort item must contain only field and direction")
    field, direction = item["field"], item["direction"]
    if field not in allowed:
        raise ValueError(f"unsupported sort field: {field}")
    if direction not in DIRECTIONS:
        raise ValueError(f"unsupported sort direction: {direction}")
    return field, direction


def _matches(row: dict[str, Any], field: str, op: str, expected: Any) -> bool:
    present, actual = _get(row, field)
    if op == "exists":
        return present is expected
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if op == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected.casefold() in actual.casefold()
        if isinstance(actual, list):
            return expected in actual
        return False
    if not present:
        return False
    try:
        return {
            "gt": actual > expected,
            "gte": actual >= expected,
            "lt": actual < expected,
            "lte": actual <= expected,
        }[op]
    except (TypeError, KeyError):
        return False


def _compare_rows(
    left: dict[str, Any], right: dict[str, Any], sort: list[tuple[str, str]]
) -> int:
    for field, direction in sort:
        _, a = _get(left, field)
        _, b = _get(right, field)
        if a == b:
            continue
        if a is None:
            return 1
        if b is None:
            return -1
        try:
            result = -1 if a < b else 1
        except TypeError:
            result = -1 if str(a) < str(b) else 1
        return result if direction == "asc" else -result
    return 0


def _get(row: dict[str, Any], field: str) -> tuple[bool, Any]:
    value: Any = row
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return value is not None, value
