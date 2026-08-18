"""Access EatMyRide activity details and food-plan events."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


EATMYRIDE_API_BASE_URL = os.environ.get(
    "EATMYRIDE_API_BASE_URL",
    "https://backend.eatmyride.com/api",
)
EATMYRIDE_API_VERSION = os.environ.get("EATMYRIDE_API_VERSION", "1.03")
LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo
DEFAULT_CONFIG_PATH = Path.home() / ".eatmyride_mcp.json"


@dataclass(frozen=True)
class EatMyRideCredentials:
    """Credentials for the EatMyRide personal API."""

    username: str
    password: str

    def login(self) -> str:
        """Return a session JWT without persisting it locally."""

        payload = _request_json(
            "/auth/login",
            method="POST",
            json_body={"email": self.username, "password": self.password},
        )
        if not isinstance(payload, dict) or not payload.get("token"):
            raise TypeError("Expected EatMyRide login endpoint to return a token")
        return str(payload["token"])


def discover_eatmyride_credentials() -> EatMyRideCredentials:
    """Find credentials for the MCP server without exposing secrets."""

    config_path = DEFAULT_CONFIG_PATH
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid EatMyRide config JSON: {config_path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"EatMyRide config must contain one JSON object: {config_path}"
            )
        config = payload

    username = _config_string(config, "username")
    password = _config_string(config, "password")
    if not username or not password:
        raise KeyError(f"Set username and password in {DEFAULT_CONFIG_PATH}")
    return EatMyRideCredentials(username=username, password=password)


def _config_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value if isinstance(value, str) and value else None


def list_activities(
    start_day: str | date,
    end_day: str | date | None = None,
    *,
    token: str,
) -> list[dict[str, Any]]:
    """List activities whose start falls within an inclusive local date range."""

    local_start = date.fromisoformat(start_day) if isinstance(start_day, str) else start_day
    local_end = (
        local_start
        if end_day is None
        else date.fromisoformat(end_day) if isinstance(end_day, str) else end_day
    )
    if local_end < local_start:
        raise ValueError("end_day must be on or after start_day")
    start = datetime.combine(local_start, time.min, tzinfo=LOCAL_TIMEZONE)
    end = datetime.combine(local_end + timedelta(days=1), time.min, tzinfo=LOCAL_TIMEZONE)
    payload = _request_json(
        f"/activities/list/{quote(start.isoformat())}/{quote(end.isoformat())}",
        token=token,
    )
    if not isinstance(payload, list):
        raise TypeError("Expected EatMyRide activities endpoint to return a list")
    return [
        activity
        for activity in payload
        if (activity_date := _activity_local_date(activity)) is not None
        and local_start <= activity_date <= local_end
    ]


def get_activity(activity_id: str | int, *, token: str) -> dict[str, Any]:
    """Return one EatMyRide activity."""

    activity = _request_json(f"/activities/{activity_id}", token=token)
    if not isinstance(activity, dict):
        raise TypeError("Expected EatMyRide activity endpoint to return an object")
    return activity


def summarize_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Return compact fueling-relevant activity fields."""

    glycogen = _energy_series(activity, "glycogen")
    return {
        "id": activity.get("id"),
        "label": activity.get("label") or activity.get("name"),
        "date": activity.get("date"),
        "sport": activity.get("sport"),
        "type": activity.get("type"),
        "tracker": activity.get("tracker"),
        "duration_s": activity.get("duration"),
        "distance_m": activity.get("distance"),
        "elevation_m": activity.get("elevation"),
        "average_heart_rate": activity.get("avgHeartRate"),
        "normalized_power": activity.get("normalizedPower"),
        "average_temperature": activity.get("averageTemperature"),
        "calories_start": activity.get("caloriesStart"),
        "calories_threshold": activity.get("caloriesThreshold"),
        "calories_needed": activity.get("caloriesNeeded"),
        "energy_needed": activity.get("energyNeeded"),
        "estimated_fat_consumption": activity.get("estimatedFatConsumption"),
        "carbohydrates_from_food_kcal_observed": activity.get("carbohydratesFromFood"),
        "glycogen": glycogen,
        "warning": activity.get("warning"),
        "is_evaluated": activity.get("isEvaluated"),
        "evaluated_at": activity.get("evaluatedAt"),
        "preparation_meal": activity.get("preparationMeal"),
        "recovery_meal": activity.get("recoveryMeal"),
        "ride_type": activity.get("rideType"),
        "profile": activity.get("profile"),
        "goal": activity.get("goal"),
    }


def summarize_fueling(
    activity: dict[str, Any],
    foodplan: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return compact activity energy state plus aggregated planned intake."""

    activity_summary = summarize_activity(activity)
    totals = summarize_foodplan(foodplan)
    duration_s = float(activity_summary.get("duration_s") or 0)
    duration_h = duration_s / 3600 if duration_s > 0 else None

    return {
        "activity": activity_summary,
        "products": summarize_foodplan_products(foodplan),
        "summary": {
            **totals,
            "carbohydrates_per_hour": (
                totals["carbohydrates_grams"] / duration_h if duration_h else None
            ),
            "fluids_per_hour": totals["fluids_ml"] / duration_h if duration_h else None,
            "event_count": len(foodplan),
            "product_count": len({_foodplan_event_product_id(row) for row in foodplan}),
        },
        "intake_evidence": "recorded_food_plan_not_confirmed_consumption",
    }


def get_foodplan(activity_id: str | int, *, token: str) -> list[dict[str, Any]]:
    """Return food-plan events for one EatMyRide activity."""

    foodplan = _request_json(f"/foodplan/{activity_id}", token=token)
    if not isinstance(foodplan, list):
        raise TypeError("Expected EatMyRide foodplan endpoint to return a list")
    return foodplan


def _energy_series(activity: dict[str, Any], key: str) -> dict[str, Any] | None:
    energy = activity.get("energyGraph", {}).get("energy", {})
    values = energy.get(key)
    times = energy.get("time")
    if not isinstance(values, list) or not values:
        return None
    numeric = [value for value in values if isinstance(value, (int, float))]
    if not numeric:
        return None
    min_value = min(numeric)
    min_index = values.index(min_value)
    time_at_min = times[min_index] if isinstance(times, list) and min_index < len(times) else None
    return {
        "start": values[0],
        "end": values[-1],
        "min": min_value,
        "time_at_min_s": time_at_min,
        "delta": values[-1] - values[0] if isinstance(values[-1], (int, float)) and isinstance(values[0], (int, float)) else None,
        "points": len(values),
    }


def search_products(
    query: str,
    *,
    token: str,
    product_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Search EatMyRide products using the same endpoint as the mobile app."""

    body: dict[str, Any] = {"q": query}
    if product_filter is not None:
        body["filter"] = product_filter
    payload = _request_json(
        "/products/search",
        token=token,
        method="POST",
        json_body=body,
    )
    if isinstance(payload, dict) and isinstance(payload.get("searchResults"), list):
        return payload["searchResults"]
    if not isinstance(payload, list):
        raise TypeError("Expected EatMyRide product search endpoint to return a list")
    return payload


def list_products(*, token: str) -> list[dict[str, Any]]:
    """Return the user's custom EatMyRide products."""

    payload = _request_json("/products", token=token)
    if not isinstance(payload, list):
        raise TypeError("Expected EatMyRide product list endpoint to return a list")
    return payload


def get_suggested_products(
    activity_id: str | int,
    kind: str,
    *,
    token: str,
) -> list[dict[str, Any]]:
    """Return EatMyRide suggested food or drink products for an activity."""

    if kind not in {"food", "drinks"}:
        raise ValueError("kind must be 'food' or 'drinks'")
    payload = _request_json(f"/products/suggested/{activity_id}/{kind}", token=token)
    if not isinstance(payload, list):
        raise TypeError("Expected EatMyRide suggested products endpoint to return a list")
    return payload


def get_product(product_id: str | int, *, token: str) -> dict[str, Any]:
    """Return one EatMyRide product by id."""

    payload = _request_json(f"/products/{product_id}", token=token)
    if not isinstance(payload, dict):
        raise TypeError("Expected EatMyRide product endpoint to return an object")
    return payload


def create_product(
    product: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """Create a custom EatMyRide product and return the server object."""

    payload = _request_json(
        "/products",
        token=token,
        method="POST",
        json_body=product,
    )
    if not isinstance(payload, dict):
        raise TypeError("Expected EatMyRide product create endpoint to return an object")
    return payload


def update_product(
    product_id: str | int,
    product: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """Update one custom EatMyRide product and return the server object."""

    payload = _request_json(
        f"/products/{product_id}",
        token=token,
        method="PUT",
        json_body=product,
    )
    if not isinstance(payload, dict):
        raise TypeError("Expected EatMyRide product update endpoint to return an object")
    return payload


def delete_product(
    product_id: str | int,
    *,
    token: str,
) -> str:
    """Delete one custom EatMyRide product and return the server response."""

    return _request_text(f"/products/{product_id}", token=token, method="DELETE")


def build_custom_product_payload(
    *,
    label: str,
    weight_grams: float | None = None,
    volume_ml: float | None = None,
    calories_kcal: float = 0,
    carbohydrates_grams: float = 0,
    fat_grams: float = 0,
    protein_grams: float = 0,
    ingredients_qty: float = 1,
    ingredients_qty_unit: str = "piece",
    tags: str | None = None,
    salt_grams: float = 0,
    sugars_grams: float = 0,
    saturated_fat_grams: float = 0,
    fibers_grams: float = 0,
    caffeine_mg: float = 0,
    per_minute_ms: int = 4000,
) -> dict[str, Any]:
    """Return the mobile-app-shaped payload for a custom EatMyRide product.

    EatMyRide stores weight, macros, salt and most micronutrients as integer
    milligrams. The public UI presents most of these as grams.
    """

    return {
        "weight": _optional_grams_to_milligrams(weight_grams),
        "volume": None if volume_ml is None else _round_int(volume_ml),
        "calories": _round_int(calories_kcal),
        "carbohydrates": _grams_to_milligrams(carbohydrates_grams),
        "fat": _grams_to_milligrams(fat_grams),
        "protein": _grams_to_milligrams(protein_grams),
        "ingredientsQty": ingredients_qty,
        "ingredientsQtyUnit": ingredients_qty_unit,
        "label": label,
        "tags": tags,
        "salt": _grams_to_milligrams(salt_grams),
        "sugars": _grams_to_milligrams(sugars_grams),
        "ofWhichSaturated": _grams_to_milligrams(saturated_fat_grams),
        "fibers": _grams_to_milligrams(fibers_grams),
        "iron": 0,
        "caffeine": _round_int(caffeine_mg),
        "vitaminB6": 0,
        "vitaminB12": 0,
        "calcium": 0,
        "folate": 0,
        "zinc": 0,
        "omega3": 0,
        "omega6": 0,
        "sodium": 0,
        "potassium": 0,
        "phosphorus": 0,
        "magnesium": 0,
        "copper": 0,
        "selenium": 0,
        "iodine": 0,
        "vitaminD": 0,
        "vitaminE": 0,
        "vitaminK": 0,
        "vitaminK1": 0,
        "vitaminK2": 0,
        "vitaminC": 0,
        "per_minute": per_minute_ms,
    }


def summarize_foodplan(foodplan: list[dict[str, Any]]) -> dict[str, float]:
    """Return intake totals calculated from food-plan event quantities.

    EatMyRide product carbohydrate values are stored in milligrams per product
    serving. The activity-level ``carbohydratesFromFood`` field is actually a
    rounded energy total in kcal, despite its name.
    """

    carbohydrates_grams = 0.0
    fluids_ml = 0.0
    for event in foodplan:
        product = event.get("product") or {}
        serving_quantity = float(product.get("ingredientsQty") or 1)
        serving_unit = product.get("ingredientsQtyUnit")
        if serving_unit == "gram" and event.get("gram") is not None:
            serving_count = float(event["gram"]) / serving_quantity
        else:
            serving_count = 1.0
        carbohydrates_grams += float(product.get("carbohydrates") or 0) * serving_count / 1000
        fluids_ml += float(event.get("ml") or 0)
    return {
        "carbohydrates_grams": carbohydrates_grams,
        "fluids_ml": fluids_ml,
    }


def summarize_foodplan_events(foodplan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact item-level food-plan rows for analysis output."""

    return [summarize_foodplan_event(event) for event in foodplan]


def summarize_foodplan_products(foodplan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate food-plan events by product for normal fueling analysis."""

    grouped: dict[int | str | None, dict[str, Any]] = {}
    for event in foodplan:
        product = event.get("product") or {}
        product_id = event.get("productId") or product.get("id")
        key = product_id if product_id is not None else product.get("label")
        row = grouped.setdefault(
            key,
            {
                "product_id": product_id,
                "label": product.get("label"),
                "occurrences": 0,
                "pieces": 0,
                "gram": 0.0,
                "ml": 0.0,
                "carbohydrates_grams": 0.0,
                "calories_kcal": 0.0,
                "times_s": [],
            },
        )
        compact = summarize_foodplan_event(event)
        row["occurrences"] += 1
        if product.get("ingredientsQtyUnit") == "gram":
            row["gram"] += float(event.get("gram") or 0)
        else:
            row["pieces"] += 1
        row["ml"] += float(event.get("ml") or 0)
        row["carbohydrates_grams"] += compact["carbohydrates_grams"]
        row["calories_kcal"] += compact["calories_kcal"]
        if event.get("time") is not None:
            row["times_s"].append(event["time"])

    result = []
    for row in grouped.values():
        times = sorted(set(row.pop("times_s")))
        row["first_time_s"] = times[0] if times else None
        row["last_time_s"] = times[-1] if times else None
        row["time_count"] = len(times)
        if not row["pieces"]:
            row.pop("pieces")
        if not row["gram"]:
            row.pop("gram")
        if not row["ml"]:
            row.pop("ml")
        result.append(row)
    return result


def summarize_foodplan_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return one compact food-plan event with calculated intake values."""

    product = event.get("product") or {}
    serving_quantity = float(product.get("ingredientsQty") or 1)
    serving_unit = product.get("ingredientsQtyUnit")
    if serving_unit == "gram" and event.get("gram") is not None:
        serving_count = float(event["gram"]) / serving_quantity
    else:
        serving_count = 1.0
    carbohydrates_grams = float(product.get("carbohydrates") or 0) * serving_count / 1000
    return {
        "id": event.get("id"),
        "activity_id": event.get("activityId"),
        "time_s": event.get("time"),
        "distance_m": event.get("distance"),
        "product_id": event.get("productId") or product.get("id"),
        "label": product.get("label"),
        "category": product.get("category"),
        "subcategory": product.get("subcategory"),
        "gram": event.get("gram"),
        "ml": event.get("ml"),
        "carbohydrates_grams": carbohydrates_grams,
        "calories_kcal": float(product.get("calories") or 0) * serving_count,
    }


def replace_foodplan(
    activity_id: str | int,
    foodplan: list[dict[str, Any]],
    *,
    token: str,
) -> dict[str, Any]:
    """Replace an activity food plan and return server-verified state.

    EatMyRide's mobile app posts the complete food plan, then puts the activity
    document back to trigger recalculation of its aggregate nutrition fields.
    """

    activity = get_activity(activity_id, token=token)
    post_foodplan(activity_id, foodplan, token=token)
    put_activity(activity_id, activity, token=token)
    return {
        "activity": get_activity(activity_id, token=token),
        "foodplan": get_foodplan(activity_id, token=token),
    }


def post_foodplan(
    activity_id: str | int,
    foodplan: list[dict[str, Any]],
    *,
    token: str,
) -> list[dict[str, Any]]:
    """Replace one activity's food-plan document."""

    normalized_foodplan = normalize_foodplan_for_replace(activity_id, foodplan)
    posted_foodplan = _request_json(
        f"/foodplan/{activity_id}",
        token=token,
        method="POST",
        json_body=normalized_foodplan,
    )
    if not isinstance(posted_foodplan, list):
        raise TypeError("Expected EatMyRide foodplan update endpoint to return a list")
    return posted_foodplan


def put_activity(
    activity_id: str | int,
    activity: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """Put one activity document back to trigger aggregate recalculation."""

    updated_activity = _request_json(
        f"/activities/{activity_id}",
        token=token,
        method="PUT",
        json_body=activity,
    )
    if not isinstance(updated_activity, dict):
        raise TypeError("Expected EatMyRide activity update endpoint to return an object")
    return updated_activity


def build_foodplan_with_set_products(
    activity_id: str | int,
    current_foodplan: list[dict[str, Any]],
    items: list[dict[str, Any]],
    products: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace quantities for selected products while preserving other events.

    Piece quantities are expanded to one event per piece because that is the
    representation EatMyRide uses when calculating and reading food plans.
    """

    mentioned_ids = {_coerce_int(item["product_id"]) for item in items}
    updated = [
        event
        for event in current_foodplan
        if _foodplan_event_product_id(event) not in mentioned_ids
    ]
    for item in items:
        product_id = _coerce_int(item["product_id"])
        product = products.get(product_id)
        if not isinstance(product, dict):
            raise KeyError(f"Product {product_id} was not resolved")
        pieces = item.get("pieces")
        copies = _coerce_positive_piece_count(pieces) if pieces is not None else 1
        event_times = _foodplan_item_times(item, copies)
        for event_time in event_times:
            event: dict[str, Any] = {
                "activityId": _coerce_int(activity_id),
                "distance": 0,
                "product": product,
                "productId": product_id,
                "source": item.get("source"),
                "time": event_time,
            }
            if pieces is not None:
                event["gram"] = 1
            if item.get("gram") is not None:
                event["gram"] = item["gram"]
            if item.get("ml") is not None:
                event["ml"] = item["ml"]
            updated.append(event)
    return updated


def _foodplan_item_times(item: dict[str, Any], count: int) -> list[int]:
    """Return one event time per occurrence, evenly spaced inside a period."""

    if item.get("start") is None:
        return [_elapsed_second(item.get("time", 0))] * count
    start = float(item["start"])
    end = float(item["end"])
    duration = end - start
    times = [start + duration * (index + 0.5) / count for index in range(count)]
    return [_elapsed_second(value) for value in times]


def _elapsed_second(value: int | float) -> int:
    """Round a non-negative elapsed time to the nearest whole second."""

    return int(float(value) + 0.5)


def summarize_foodplan_change(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    product_ids: list[int],
) -> dict[str, Any]:
    """Return a compact before/after summary for selected products."""

    return {
        "event_count_before": len(before),
        "event_count_after": len(after),
        "products": [
            {
                "product_id": product_id,
                "events_before": _count_product_events(before, product_id),
                "events_after": _count_product_events(after, product_id),
                "times_before_s": _product_event_times(before, product_id),
                "times_after_s": _product_event_times(after, product_id),
            }
            for product_id in product_ids
        ],
        "totals_before": summarize_foodplan(before),
        "totals_after": summarize_foodplan(after),
    }


def normalize_foodplan_for_replace(
    activity_id: str | int,
    foodplan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return EatMyRide's narrow food-plan replacement shape.

    Product search/suggested endpoints include extra fields and string-typed
    quantities that the food-plan endpoint may reject. Existing food-plan
    readbacks show the smaller mobile-app shape used here.
    """

    return [
        _normalize_foodplan_event(activity_id, event, user_order=index)
        for index, event in enumerate(foodplan)
    ]


def _normalize_foodplan_event(
    activity_id: str | int,
    event: dict[str, Any],
    *,
    user_order: int,
) -> dict[str, Any]:
    product = event.get("product")
    if not isinstance(product, dict):
        raise TypeError("Each food-plan event must include a product object")

    product_id = event.get("productId") or product.get("id")
    if product_id is None:
        raise ValueError("Each food-plan event must include productId or product.id")

    normalized: dict[str, Any] = {
        "activityId": _coerce_int(activity_id),
        "distance": event.get("distance", 0),
        "product": _normalize_foodplan_product(product),
        "productId": _coerce_int(product_id),
        "source": event.get("source"),
        "time": event.get("time", 0),
        "userOrder": event.get("userOrder", user_order),
    }
    if event.get("id") is not None:
        normalized["id"] = _coerce_int(event["id"])
    if "gram" in event:
        normalized["gram"] = event["gram"]
    if "ml" in event:
        normalized["ml"] = event["ml"]
    return normalized


def _foodplan_event_product_id(event: dict[str, Any]) -> int | None:
    product = event.get("product")
    product_id = event.get("productId")
    if product_id is None and isinstance(product, dict):
        product_id = product.get("id")
    return None if product_id is None else _coerce_int(product_id)


def _count_product_events(foodplan: list[dict[str, Any]], product_id: int) -> int:
    return sum(
        1 for event in foodplan if _foodplan_event_product_id(event) == product_id
    )


def _product_event_times(
    foodplan: list[dict[str, Any]],
    product_id: int,
) -> list[int | float]:
    return [
        event.get("time", 0)
        for event in foodplan
        if _foodplan_event_product_id(event) == product_id
    ]


def _coerce_positive_piece_count(value: Any) -> int:
    numeric = float(value)
    if not numeric.is_integer() or numeric <= 0:
        raise ValueError("pieces must be a positive integer")
    return int(numeric)


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 3)


def _normalize_foodplan_product(product: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = [
        "caffeine",
        "calcium",
        "calories",
        "carbohydrates",
        "category",
        "copper",
        "description",
        "fat",
        "fibers",
        "flavour",
        "folate",
        "id",
        "image",
        "ingredientsQty",
        "ingredientsQtyUnit",
        "iodine",
        "iron",
        "label",
        "magnesium",
        "ofWhichSaturated",
        "omega3",
        "omega6",
        "per_minute",
        "phosphorus",
        "potassium",
        "protein",
        "salt",
        "selenium",
        "shopId",
        "sodium",
        "subcategory",
        "sugars",
        "tags",
        "userId",
        "vitaminB12",
        "vitaminB6",
        "vitaminC",
        "vitaminD",
        "vitaminE",
        "vitaminK",
        "vitaminK1",
        "vitaminK2",
        "volume",
        "weight",
        "zinc",
    ]
    normalized = {key: product.get(key) for key in allowed_keys}
    if normalized["id"] is None:
        raise ValueError("Food-plan product must include id")
    normalized["id"] = _coerce_int(normalized["id"])
    normalized["ingredientsQty"] = _coerce_number(normalized["ingredientsQty"])
    return normalized


def _request_json(
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    json_body: Any = None,
) -> Any:
    return json.loads(
        _request_text(path, token=token, method=method, json_body=json_body)
    )


def _request_text(
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    json_body: Any = None,
) -> str:
    body = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    headers = {
        "Accept": "application/json",
        "accept-version": EATMYRIDE_API_VERSION,
        "User-Agent": "training-ai/0.1 (+EatMyRide personal API client)",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{EATMYRIDE_API_BASE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except HTTPError:
        raise
    except URLError as exc:
        raise RuntimeError(f"EatMyRide request failed: {exc.reason}") from exc


def _activity_local_date(activity: dict[str, Any]) -> date | None:
    raw_date = str(activity.get("date") or "")
    if not raw_date:
        return None
    activity_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    return activity_date.astimezone(LOCAL_TIMEZONE).date()


def _optional_grams_to_milligrams(value: float | None) -> int | None:
    if value is None:
        return None
    return _grams_to_milligrams(value)


def _grams_to_milligrams(value: float) -> int:
    return _round_int(value * 1000)


def _round_int(value: float) -> int:
    return int(round(value))


def _coerce_int(value: Any) -> int:
    return int(value)


def _coerce_number(value: Any) -> int | float | None:
    if value is None:
        return None
    numeric = float(value)
    if numeric.is_integer():
        return int(numeric)
    return numeric
