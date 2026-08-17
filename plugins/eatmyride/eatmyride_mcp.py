#!/usr/bin/env python3
"""EatMyRide tools exposed through the stable MCP Python SDK."""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError


SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from eatmyride_api import (  # noqa: E402
    EatMyRideCredentials,
    build_custom_product_payload,
    build_foodplan_with_set_products,
    create_product as api_create_product,
    delete_product as api_delete_product,
    get_activity,
    get_foodplan,
    get_product,
    get_suggested_products,
    list_activities,
    list_products as api_list_products,
    post_foodplan,
    put_activity,
    discover_eatmyride_credentials,
    search_products,
    summarize_activity,
    summarize_foodplan,
    summarize_foodplan_change,
    summarize_fueling,
    update_product as api_update_product,
)


ALL_TOOL_NAMES = (
    "list_activities",
    "get_fueling",
    "search_products",
    "list_products",
    "get_product",
    "create_product",
    "update_product",
    "delete_product",
    "set_foodplan_products",
)

TOOL_ANNOTATIONS: dict[str, dict[str, object]] = {
    "list_activities": {
        "title": "List EatMyRide Activities",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_fueling": {
        "title": "Get EatMyRide Fueling",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "search_products": {
        "title": "Search EatMyRide Products",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "list_products": {
        "title": "List EatMyRide Products",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "get_product": {
        "title": "Get EatMyRide Product",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "create_product": {
        "title": "Create Custom EatMyRide Product",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "update_product": {
        "title": "Update Custom EatMyRide Product",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "delete_product": {
        "title": "Delete Custom EatMyRide Product",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "set_foodplan_products": {
        "title": "Set EatMyRide Food-Plan Products",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
}


def _open_object(description: str) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": True,
        "description": description,
    }


def _array_of_open_objects(description: str) -> dict[str, object]:
    return {
        "type": "array",
        "items": _open_object("Normalized or source-native EatMyRide object."),
        "description": description,
    }


def _tool_definition(
    *,
    name: str,
    description: str,
    properties: dict[str, object],
    required: list[str],
    output_properties: dict[str, object],
    output_required: list[str],
) -> dict[str, object]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": output_properties,
            "required": output_required,
            "additionalProperties": False,
        },
        "annotations": TOOL_ANNOTATIONS[name],
    }


_LIMIT_SCHEMA = {
    "type": "integer",
    "minimum": 1,
    "maximum": 200,
    "default": 50,
    "description": "Maximum number of rows returned; total_count remains untruncated.",
}

TOOL_DEFINITIONS: dict[str, dict[str, object]] = {
    "list_activities": _tool_definition(
        name="list_activities",
        description=(
            "List EatMyRide activity candidates in an inclusive local-date range. "
            "Use get_fueling for evaluated intake and glycogen details."
        ),
        properties={
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
            "limit": _LIMIT_SCHEMA,
        },
        required=["start_date", "end_date"],
        output_properties={
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "total_count": {"type": "integer"},
            "count": {"type": "integer"},
            "activities": _array_of_open_objects("Bounded activity candidate rows."),
        },
        output_required=["start_date", "end_date", "total_count", "count", "activities"],
    ),
    "get_fueling": _tool_definition(
        name="get_fueling",
        description=(
            "Get compact EatMyRide activity energy and glycogen state together with "
            "food-plan events and calculated intake totals. A food plan is recorded "
            "planning data and is not proof that every item was consumed."
        ),
        properties={
            "activity_id": {
                "type": "string",
                "minLength": 1,
                "description": "EatMyRide activity identifier from list_activities.",
            }
        },
        required=["activity_id"],
        output_properties={
            "activity": _open_object("Compact activity and glycogen summary."),
            "foodplan": _array_of_open_objects("Compact recorded food-plan events."),
            "summary": _open_object("Calculated carbohydrate and fluid totals."),
        },
        output_required=["activity", "foodplan", "summary"],
    ),
    "search_products": _tool_definition(
        name="search_products",
        description=(
            "Search EatMyRide products for read-only product identification. Results "
            "do not establish food-plan intake totals."
        ),
        properties={
            "query": {
                "type": "string",
                "minLength": 1,
                "description": "Product label or search text.",
            },
            "product_filter": {
                "type": "string",
                "minLength": 1,
                "description": "Optional EatMyRide product-search filter value.",
            },
            "limit": _LIMIT_SCHEMA,
        },
        required=["query"],
        output_properties={
            "query": {"type": "string"},
            "total_count": {"type": "integer"},
            "count": {"type": "integer"},
            "products": _array_of_open_objects("Bounded matching product rows."),
        },
        output_required=["query", "total_count", "count", "products"],
    ),
    "list_products": _tool_definition(
        name="list_products",
        description=(
            "List custom products or activity-specific suggested products, optionally "
            "filtered by label or description. Suggested products require activity_id "
            "and kind and are candidates, not recorded intake."
        ),
        properties={
            "source": {
                "type": "string",
                "enum": ["custom", "suggested"],
                "description": "Product collection to list.",
            },
            "activity_id": {
                "type": "string",
                "minLength": 1,
                "description": "Required when source is suggested.",
            },
            "kind": {
                "type": "string",
                "enum": ["food", "drinks"],
                "description": "Required suggestion category when source is suggested.",
            },
            "contains": {
                "type": "string",
                "minLength": 1,
                "description": "Optional case-insensitive label or description substring.",
            },
            "limit": _LIMIT_SCHEMA,
        },
        required=["source"],
        output_properties={
            "source": {"type": "string"},
            "activity_id": {"type": "string"},
            "kind": {"type": "string"},
            "total_count": {"type": "integer"},
            "count": {"type": "integer"},
            "products": _array_of_open_objects("Bounded product rows."),
        },
        output_required=["source", "total_count", "count", "products"],
    ),
    "get_product": _tool_definition(
        name="get_product",
        description="Get one EatMyRide product by its exact identifier.",
        properties={
            "product_id": {
                "type": "integer",
                "minimum": 1,
                "description": "EatMyRide product identifier.",
            }
        },
        required=["product_id"],
        output_properties={"product": _open_object("Exact EatMyRide product object.")},
        output_required=["product"],
    ),
    "create_product": _tool_definition(
        name="create_product",
        description=(
            "Preview or create a custom EatMyRide product using user-facing kcal, "
            "gram, millilitre, and caffeine values. Preview is the default."
        ),
        properties={
            "label": {"type": "string", "minLength": 1, "description": "Product name."},
            "weight_grams": {"type": "number", "minimum": 0, "description": "Serving weight in grams."},
            "volume_ml": {"type": "number", "minimum": 0, "description": "Serving volume in millilitres."},
            "calories_kcal": {"type": "number", "minimum": 0, "default": 0, "description": "Energy per serving in kcal."},
            "carbohydrates_grams": {"type": "number", "minimum": 0, "default": 0, "description": "Carbohydrate per serving in grams."},
            "fat_grams": {"type": "number", "minimum": 0, "default": 0, "description": "Fat per serving in grams."},
            "protein_grams": {"type": "number", "minimum": 0, "default": 0, "description": "Protein per serving in grams."},
            "serving_quantity": {"type": "number", "exclusiveMinimum": 0, "default": 1, "description": "Quantity represented by one serving."},
            "serving_unit": {"type": "string", "enum": ["piece", "gram", "ml"], "default": "piece", "description": "Unit represented by serving_quantity."},
            "tags": {"type": "string", "description": "Optional EatMyRide tag string."},
            "salt_grams": {"type": "number", "minimum": 0, "default": 0, "description": "Salt per serving in grams."},
            "sugars_grams": {"type": "number", "minimum": 0, "default": 0, "description": "Sugars per serving in grams."},
            "saturated_fat_grams": {"type": "number", "minimum": 0, "default": 0, "description": "Saturated fat per serving in grams."},
            "fibers_grams": {"type": "number", "minimum": 0, "default": 0, "description": "Fibre per serving in grams."},
            "caffeine_mg": {"type": "number", "minimum": 0, "default": 0, "description": "Caffeine per serving in milligrams."},
            "confirm": {"type": "boolean", "default": False, "description": "False previews only; true creates and reads back the product."},
        },
        required=["label"],
        output_properties={
            "confirmed": {"type": "boolean"},
            "verified": {"type": "boolean"},
            "product": _open_object("Previewed or verified product object."),
        },
        output_required=["confirmed", "verified", "product"],
    ),
    "update_product": _tool_definition(
        name="update_product",
        description=(
            "Preview or partially update one custom EatMyRide product using the same "
            "user-facing kcal, gram, millilitre, and caffeine fields as create_product. "
            "Only explicitly supplied fields change."
        ),
        properties={
            "product_id": {"type": "integer", "minimum": 1, "description": "Custom EatMyRide product identifier."},
            "label": {"type": "string", "minLength": 1, "description": "Replacement product name."},
            "weight_grams": {"type": "number", "minimum": 0, "description": "Replacement serving weight in grams."},
            "volume_ml": {"type": "number", "minimum": 0, "description": "Replacement serving volume in millilitres."},
            "calories_kcal": {"type": "number", "minimum": 0, "description": "Replacement energy per serving in kcal."},
            "carbohydrates_grams": {"type": "number", "minimum": 0, "description": "Replacement carbohydrate per serving in grams."},
            "fat_grams": {"type": "number", "minimum": 0, "description": "Replacement fat per serving in grams."},
            "protein_grams": {"type": "number", "minimum": 0, "description": "Replacement protein per serving in grams."},
            "serving_quantity": {"type": "number", "exclusiveMinimum": 0, "description": "Replacement quantity represented by one serving."},
            "serving_unit": {"type": "string", "enum": ["piece", "gram", "ml"], "description": "Replacement serving unit."},
            "tags": {"type": "string", "description": "Replacement EatMyRide tag string."},
            "salt_grams": {"type": "number", "minimum": 0, "description": "Replacement salt per serving in grams."},
            "sugars_grams": {"type": "number", "minimum": 0, "description": "Replacement sugars per serving in grams."},
            "saturated_fat_grams": {"type": "number", "minimum": 0, "description": "Replacement saturated fat per serving in grams."},
            "fibers_grams": {"type": "number", "minimum": 0, "description": "Replacement fibre per serving in grams."},
            "caffeine_mg": {"type": "number", "minimum": 0, "description": "Replacement caffeine per serving in milligrams."},
            "confirm": {"type": "boolean", "default": False, "description": "False previews only; true updates and reads back the product."},
        },
        required=["product_id"],
        output_properties={
            "product_id": {"type": "integer"},
            "confirmed": {"type": "boolean"},
            "verified": {"type": "boolean"},
            "before": _open_object("Exact product before the proposed update."),
            "product": _open_object("Previewed or verified product object."),
        },
        output_required=["product_id", "confirmed", "verified", "before", "product"],
    ),
    "delete_product": _tool_definition(
        name="delete_product",
        description=(
            "Preview or delete one custom EatMyRide product. confirm=true deletes the "
            "resolved exact product and verifies that it is absent."
        ),
        properties={
            "product_id": {"type": "integer", "minimum": 1, "description": "Custom EatMyRide product identifier."},
            "confirm": {"type": "boolean", "default": False, "description": "False previews only; true deletes and verifies absence."},
        },
        required=["product_id"],
        output_properties={
            "product_id": {"type": "integer"},
            "confirmed": {"type": "boolean"},
            "verified_absent": {"type": "boolean"},
            "product": _open_object("Exact custom product resolved before deletion."),
        },
        output_required=["product_id", "confirmed", "verified_absent", "product"],
    ),
    "set_foodplan_products": _tool_definition(
        name="set_foodplan_products",
        description=(
            "Preview or set exact quantities and elapsed times for products recorded "
            "in one activity food plan while preserving unrelated products. Preview "
            "is the default; confirm=true replaces the server plan and reads it back."
        ),
        properties={
            "activity_id": {
                "type": "string",
                "minLength": 1,
                "description": "EatMyRide activity identifier.",
            },
            "items": {
                "type": "array",
                "minItems": 1,
                "description": "Exact product quantities; repeat a product for separate periods.",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "EatMyRide product identifier.",
                        },
                        "pieces": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Number of piece events to record.",
                        },
                        "gram": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "description": "Reported product mass in grams.",
                        },
                        "ml": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Reported fluid volume in millilitres.",
                        },
                        "time_s": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Exact elapsed activity time in seconds.",
                        },
                        "start_s": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Start of an elapsed-time distribution period.",
                        },
                        "end_s": {
                            "type": "number",
                            "minimum": 0,
                            "description": "End of an elapsed-time distribution period.",
                        },
                    },
                    "required": ["product_id"],
                    "additionalProperties": False,
                },
            },
            "confirm": {
                "type": "boolean",
                "default": False,
                "description": "False previews only; true performs and verifies the replacement.",
            },
        },
        required=["activity_id", "items"],
        output_properties={
            "activity_id": {"type": "string"},
            "confirmed": {"type": "boolean"},
            "verified": {"type": "boolean"},
            "change": _open_object("Compact before-and-after change summary."),
            "activity": _open_object("Verified compact activity state after a write."),
            "summary": _open_object("Verified food-plan intake totals after a write."),
        },
        output_required=["activity_id", "confirmed", "verified", "change"],
    ),
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


class EatMyRideAuthSession:
    """Authentication state owned by one MCP service instance."""

    def __init__(self, credentials: EatMyRideCredentials) -> None:
        self.credentials = credentials
        self._lock = threading.Lock()
        self._token: str | None = None

    def bearer_token(self) -> str:
        with self._lock:
            if self._token is None:
                self._token = self.credentials.login()
            return self._token

    def invalidate_token(self, rejected_token: str) -> None:
        with self._lock:
            if self._token == rejected_token:
                self._token = None


class EatMyRideLiveService:
    """Stable session-scoped call boundary over the EatMyRide API module."""

    def __init__(
        self,
        credentials_factory: Callable[[], EatMyRideCredentials] | None = None,
    ) -> None:
        factory = credentials_factory or discover_eatmyride_credentials
        self._auth = EatMyRideAuthSession(factory())

    def _run(self, operation: Callable[[str], Any]) -> Any:
        token = self._auth.bearer_token()
        try:
            return operation(token)
        except HTTPError as exc:
            if exc.code not in {401, 403}:
                raise
            self._auth.invalidate_token(token)
            return operation(self._auth.bearer_token())

    def list_activities(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self._run(lambda token: list_activities(start_date, end_date, token=token))

    def get_fueling(self, activity_id: str) -> dict[str, Any]:
        activity = self._run(lambda token: get_activity(activity_id, token=token))
        foodplan = self._run(lambda token: get_foodplan(activity_id, token=token))
        return summarize_fueling(activity, foodplan)

    def search_products(
        self, query: str, *, product_filter: str | None = None
    ) -> list[dict[str, Any]]:
        return self._run(
            lambda token: search_products(query, token=token, product_filter=product_filter)
        )

    def list_products(
        self,
        source: str,
        *,
        activity_id: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        if source == "custom":
            return self._run(lambda token: api_list_products(token=token))
        return self._run(
            lambda token: get_suggested_products(activity_id or "", kind or "", token=token)
        )

    def get_product(self, product_id: int) -> dict[str, Any]:
        return self._run(lambda token: get_product(product_id, token=token))

    def create_product(
        self, values: dict[str, Any], *, confirm: bool
    ) -> dict[str, Any]:
        payload = build_custom_product_payload(
            label=values["label"],
            weight_grams=values.get("weight_grams"),
            volume_ml=values.get("volume_ml"),
            calories_kcal=values.get("calories_kcal", 0),
            carbohydrates_grams=values.get("carbohydrates_grams", 0),
            fat_grams=values.get("fat_grams", 0),
            protein_grams=values.get("protein_grams", 0),
            ingredients_qty=values.get("serving_quantity", 1),
            ingredients_qty_unit=values.get("serving_unit", "piece"),
            tags=values.get("tags"),
            salt_grams=values.get("salt_grams", 0),
            sugars_grams=values.get("sugars_grams", 0),
            saturated_fat_grams=values.get("saturated_fat_grams", 0),
            fibers_grams=values.get("fibers_grams", 0),
            caffeine_mg=values.get("caffeine_mg", 0),
        )
        if not confirm:
            return {"confirmed": False, "verified": False, "product": payload}

        created = self._run(lambda token: api_create_product(payload, token=token))
        product_id = created.get("id")
        if product_id is None:
            raise TypeError("Created EatMyRide product did not include an id")
        verified = self._run(lambda token: get_product(product_id, token=token))
        return {"confirmed": True, "verified": True, "product": verified}

    def update_product(
        self,
        product_id: int,
        values: dict[str, Any],
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        current = self._run(lambda token: get_product(product_id, token=token))
        proposed = {**current, **_custom_product_updates(values)}
        if not confirm:
            return {
                "product_id": product_id,
                "confirmed": False,
                "verified": False,
                "before": current,
                "product": proposed,
            }
        self._run(
            lambda token: api_update_product(product_id, proposed, token=token)
        )
        verified = self._run(lambda token: get_product(product_id, token=token))
        return {
            "product_id": product_id,
            "confirmed": True,
            "verified": True,
            "before": current,
            "product": verified,
        }

    def delete_product(self, product_id: int, *, confirm: bool) -> dict[str, Any]:
        product = self._run(lambda token: get_product(product_id, token=token))
        if not confirm:
            return {
                "product_id": product_id,
                "confirmed": False,
                "verified_absent": False,
                "product": product,
            }
        self._run(lambda token: api_delete_product(product_id, token=token))
        try:
            self._run(lambda token: get_product(product_id, token=token))
        except HTTPError as exc:
            if exc.code == 404:
                return {
                    "product_id": product_id,
                    "confirmed": True,
                    "verified_absent": True,
                    "product": product,
                }
            raise
        raise RuntimeError("EatMyRide product remained present after deletion")

    def set_foodplan_products(
        self,
        activity_id: str,
        items: list[dict[str, Any]],
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        current = self._run(lambda token: get_foodplan(activity_id, token=token))
        product_ids = list(dict.fromkeys(int(item["product_id"]) for item in items))
        products = {
            product_id: self._run(
                lambda token, current_id=product_id: get_product(current_id, token=token)
            )
            for product_id in product_ids
        }
        api_items = [_foodplan_api_item(item) for item in items]
        updated = build_foodplan_with_set_products(
            activity_id, current, api_items, products
        )
        change = summarize_foodplan_change(current, updated, product_ids)
        if not confirm:
            return {
                "activity_id": activity_id,
                "confirmed": False,
                "verified": False,
                "change": change,
            }
        activity = self._run(lambda token: get_activity(activity_id, token=token))
        self._run(lambda token: post_foodplan(activity_id, updated, token=token))
        self._run(lambda token: put_activity(activity_id, activity, token=token))
        verified_activity = self._run(
            lambda token: get_activity(activity_id, token=token)
        )
        verified_foodplan = self._run(
            lambda token: get_foodplan(activity_id, token=token)
        )
        return {
            "activity_id": activity_id,
            "confirmed": True,
            "verified": True,
            "change": summarize_foodplan_change(
                current, verified_foodplan, product_ids
            ),
            "activity": summarize_activity(verified_activity),
            "summary": summarize_foodplan(verified_foodplan),
        }


class EatMyRideToolService:
    """Transport-independent MCP validation and dispatch."""

    def __init__(
        self,
        service_factory: Callable[[], EatMyRideLiveService] = EatMyRideLiveService,
    ) -> None:
        self._service_factory = service_factory
        self._service: EatMyRideLiveService | None = None
        self._lock = threading.RLock()

    def list_tools(self) -> list[dict[str, object]]:
        return [TOOL_SPECS[name].definition for name in ALL_TOOL_NAMES]

    def call_tool(self, name: str, arguments: object | None = None) -> dict[str, Any]:
        if name not in TOOL_SPECS:
            raise ToolFailure("unknown_tool", f"Unknown EatMyRide tool: {name}")
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
        _validate_arguments(name, arguments)
        try:
            with self._lock:
                if self._service is None:
                    self._service = self._service_factory()
                return self._dispatch(self._service, name, arguments)
        except ToolFailure:
            raise
        except KeyError as exc:
            raise ToolFailure("authentication_error", str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise ToolFailure("invalid_arguments", str(exc)) from exc
        except Exception as exc:
            raise ToolFailure("eatmyride_error", str(exc)) from exc

    @staticmethod
    def _dispatch(
        service: EatMyRideLiveService,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if name == "list_activities":
            start = arguments["start_date"]
            end = arguments["end_date"]
            activities = service.list_activities(start, end)
            limit = arguments.get("limit", 50)
            selected = activities[:limit]
            return {
                "start_date": start,
                "end_date": end,
                "total_count": len(activities),
                "count": len(selected),
                "activities": selected,
            }
        if name == "get_fueling":
            return service.get_fueling(arguments["activity_id"])
        if name == "search_products":
            products = service.search_products(
                arguments["query"], product_filter=arguments.get("product_filter")
            )
            limit = arguments.get("limit", 50)
            selected = products[:limit]
            return {
                "query": arguments["query"],
                "total_count": len(products),
                "count": len(selected),
                "products": selected,
            }
        if name == "get_product":
            return {"product": service.get_product(arguments["product_id"])}
        if name == "create_product":
            values = {key: value for key, value in arguments.items() if key != "confirm"}
            return service.create_product(
                values, confirm=arguments.get("confirm", False)
            )
        if name == "update_product":
            values = {
                key: value
                for key, value in arguments.items()
                if key not in {"product_id", "confirm"}
            }
            return service.update_product(
                arguments["product_id"],
                values,
                confirm=arguments.get("confirm", False),
            )
        if name == "delete_product":
            return service.delete_product(
                arguments["product_id"], confirm=arguments.get("confirm", False)
            )
        if name == "set_foodplan_products":
            return service.set_foodplan_products(
                arguments["activity_id"],
                arguments["items"],
                confirm=arguments.get("confirm", False),
            )
        products = service.list_products(
            arguments["source"],
            activity_id=arguments.get("activity_id"),
            kind=arguments.get("kind"),
        )
        contains = arguments.get("contains")
        if contains:
            needle = contains.casefold()
            products = [
                product
                for product in products
                if needle
                in f"{product.get('label', '')} {product.get('description', '')}".casefold()
            ]
        limit = arguments.get("limit", 50)
        selected = products[:limit]
        return {
            "source": arguments["source"],
            **({"activity_id": arguments["activity_id"]} if "activity_id" in arguments else {}),
            **({"kind": arguments["kind"]} if "kind" in arguments else {}),
            "total_count": len(products),
            "count": len(selected),
            "products": selected,
        }


def _validate_arguments(name: str, arguments: dict[str, Any]) -> None:
    for key, value in arguments.items():
        if key == "limit" and (not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 200):
            raise ToolFailure("invalid_arguments", "limit must be an integer from 1 to 200")
        if key in {"start_date", "end_date", "activity_id", "query", "product_filter", "contains", "label"}:
            if not isinstance(value, str) or not value.strip():
                raise ToolFailure("invalid_arguments", f"{key} must be a non-empty string")
    if name == "list_products":
        source = arguments.get("source")
        if source not in {"custom", "suggested"}:
            raise ToolFailure("invalid_arguments", "source must be 'custom' or 'suggested'")
        if source == "suggested":
            if not arguments.get("activity_id"):
                raise ToolFailure("invalid_arguments", "activity_id is required for suggested products")
            if arguments.get("kind") not in {"food", "drinks"}:
                raise ToolFailure("invalid_arguments", "kind must be 'food' or 'drinks'")
        elif "activity_id" in arguments or "kind" in arguments:
            raise ToolFailure("invalid_arguments", "activity_id and kind apply only to suggested products")
    if name in {"get_product", "update_product", "delete_product"}:
        product_id = arguments.get("product_id")
        if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id < 1:
            raise ToolFailure("invalid_arguments", "product_id must be a positive integer")
    if name in {"create_product", "update_product", "delete_product"}:
        if "confirm" in arguments and not isinstance(arguments["confirm"], bool):
            raise ToolFailure("invalid_arguments", "confirm must be a boolean")
    if name in {"create_product", "update_product"}:
        _validate_create_product(arguments)
    if name == "update_product" and not (
        set(arguments) - {"product_id", "confirm"}
    ):
        raise ToolFailure("invalid_arguments", "update_product requires at least one field to change")
    if name == "set_foodplan_products":
        _validate_foodplan_items(arguments.get("items"))
        if "confirm" in arguments and not isinstance(arguments["confirm"], bool):
            raise ToolFailure("invalid_arguments", "confirm must be a boolean")


def _validate_create_product(arguments: dict[str, Any]) -> None:
    non_negative = {
        "weight_grams",
        "volume_ml",
        "calories_kcal",
        "carbohydrates_grams",
        "fat_grams",
        "protein_grams",
        "salt_grams",
        "sugars_grams",
        "saturated_fat_grams",
        "fibers_grams",
        "caffeine_mg",
    }
    for field in non_negative:
        if field in arguments and (
            not isinstance(arguments[field], (int, float))
            or isinstance(arguments[field], bool)
            or arguments[field] < 0
        ):
            raise ToolFailure("invalid_arguments", f"{field} must be a non-negative number")
    if "serving_quantity" in arguments and (
        not isinstance(arguments["serving_quantity"], (int, float))
        or isinstance(arguments["serving_quantity"], bool)
        or arguments["serving_quantity"] <= 0
    ):
        raise ToolFailure("invalid_arguments", "serving_quantity must be greater than zero")
    if arguments.get("serving_unit", "piece") not in {"piece", "gram", "ml"}:
        raise ToolFailure("invalid_arguments", "serving_unit must be piece, gram, or ml")


def _custom_product_updates(values: dict[str, Any]) -> dict[str, Any]:
    built = build_custom_product_payload(
        label=values.get("label", ""),
        weight_grams=values.get("weight_grams"),
        volume_ml=values.get("volume_ml"),
        calories_kcal=values.get("calories_kcal", 0),
        carbohydrates_grams=values.get("carbohydrates_grams", 0),
        fat_grams=values.get("fat_grams", 0),
        protein_grams=values.get("protein_grams", 0),
        ingredients_qty=values.get("serving_quantity", 1),
        ingredients_qty_unit=values.get("serving_unit", "piece"),
        tags=values.get("tags"),
        salt_grams=values.get("salt_grams", 0),
        sugars_grams=values.get("sugars_grams", 0),
        saturated_fat_grams=values.get("saturated_fat_grams", 0),
        fibers_grams=values.get("fibers_grams", 0),
        caffeine_mg=values.get("caffeine_mg", 0),
    )
    field_map = {
        "label": "label",
        "weight_grams": "weight",
        "volume_ml": "volume",
        "calories_kcal": "calories",
        "carbohydrates_grams": "carbohydrates",
        "fat_grams": "fat",
        "protein_grams": "protein",
        "serving_quantity": "ingredientsQty",
        "serving_unit": "ingredientsQtyUnit",
        "tags": "tags",
        "salt_grams": "salt",
        "sugars_grams": "sugars",
        "saturated_fat_grams": "ofWhichSaturated",
        "fibers_grams": "fibers",
        "caffeine_mg": "caffeine",
    }
    return {
        payload_field: built[payload_field]
        for input_field, payload_field in field_map.items()
        if input_field in values
    }


def _validate_foodplan_items(items: Any) -> None:
    if not isinstance(items, list) or not items:
        raise ToolFailure("invalid_arguments", "items must be a non-empty array")
    allowed = {"product_id", "pieces", "gram", "ml", "time_s", "start_s", "end_s"}
    for item in items:
        if not isinstance(item, dict):
            raise ToolFailure("invalid_arguments", "each item must be an object")
        unknown = set(item) - allowed
        if unknown:
            raise ToolFailure("invalid_arguments", f"unknown item argument: {sorted(unknown)[0]}")
        product_id = item.get("product_id")
        if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id < 1:
            raise ToolFailure("invalid_arguments", "product_id must be a positive integer")
        has_pieces = "pieces" in item
        has_gram = "gram" in item
        if has_pieces == has_gram:
            raise ToolFailure("invalid_arguments", "each item requires exactly one of pieces or gram")
        if has_pieces and (
            not isinstance(item["pieces"], int)
            or isinstance(item["pieces"], bool)
            or item["pieces"] < 1
        ):
            raise ToolFailure("invalid_arguments", "pieces must be a positive integer")
        for field in ("gram", "ml", "time_s", "start_s", "end_s"):
            if field in item and (
                not isinstance(item[field], (int, float))
                or isinstance(item[field], bool)
                or item[field] < 0
            ):
                raise ToolFailure("invalid_arguments", f"{field} must be a non-negative number")
        if has_gram and item["gram"] <= 0:
            raise ToolFailure("invalid_arguments", "gram must be greater than zero")
        has_time = "time_s" in item
        has_period = "start_s" in item or "end_s" in item
        if has_time and has_period:
            raise ToolFailure("invalid_arguments", "time_s cannot be combined with start_s or end_s")
        if has_period and not {"start_s", "end_s"}.issubset(item):
            raise ToolFailure("invalid_arguments", "start_s and end_s must be provided together")
        if has_period and item["end_s"] < item["start_s"]:
            raise ToolFailure("invalid_arguments", "end_s must be on or after start_s")


def _foodplan_api_item(item: dict[str, Any]) -> dict[str, Any]:
    mapped = {key: value for key, value in item.items() if key not in {"time_s", "start_s", "end_s"}}
    for source, target in (("time_s", "time"), ("start_s", "start"), ("end_s", "end")):
        if source in item:
            mapped[target] = item[source]
    return mapped


def create_sdk_server(service: EatMyRideToolService) -> Any:
    """Build the stable SDK server used by the stdio entry point."""

    import anyio
    import mcp.types as mcp_types
    from mcp.server import Server

    server = Server(
        "eatmyride",
        version="0.1.0",
        instructions=(
            "Read EatMyRide activities, fueling, glycogen state, and products. Preview "
            "custom-product and food-plan changes by default; remote writes require "
            "confirm=true and are verified afterward. Dates are inclusive local calendar "
            "dates. Food plans are recorded planning data, not proof of consumption."
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


async def serve_async(
    service_factory: Callable[[], EatMyRideLiveService] = EatMyRideLiveService,
) -> None:
    from mcp.server.stdio import stdio_server

    server = create_sdk_server(EatMyRideToolService(service_factory))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve(
    service_factory: Callable[[], EatMyRideLiveService] = EatMyRideLiveService,
) -> int:
    try:
        import anyio

        anyio.run(serve_async, service_factory)
    except Exception as exc:
        print(f"EatMyRide MCP internal error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return serve(EatMyRideLiveService)


if __name__ == "__main__":
    raise SystemExit(main())
