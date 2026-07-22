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


@dataclass(frozen=True)
class EatMyRideCredentials:
    """Credentials for the EatMyRide personal API."""

    email: str
    password: str

    def login(self) -> str:
        """Return a session JWT without persisting it locally."""

        payload = _request_json(
            "/auth/login",
            method="POST",
            json_body={"email": self.email, "password": self.password},
        )
        if not isinstance(payload, dict) or not payload.get("token"):
            raise TypeError("Expected EatMyRide login endpoint to return a token")
        return str(payload["token"])


def load_eatmyride_credentials(env_path: str | Path = ".env") -> EatMyRideCredentials:
    """Load EatMyRide credentials from a local dotenv-style file."""

    values = _load_env_values(env_path)
    email = values.get("EATMYRIDE_EMAIL")
    password = values.get("EATMYRIDE_PASSWORD")
    if not email or not password:
        raise KeyError("Set EATMYRIDE_EMAIL and EATMYRIDE_PASSWORD in .env")
    return EatMyRideCredentials(email=email, password=password)


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
    """Return compact activity energy state plus item-level intake."""

    return {
        "activity": summarize_activity(activity),
        "foodplan": summarize_foodplan_events(foodplan),
        "summary": summarize_foodplan(foodplan),
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
    normalized_foodplan = normalize_foodplan_for_replace(activity_id, foodplan)
    posted_foodplan = _request_json(
        f"/foodplan/{activity_id}",
        token=token,
        method="POST",
        json_body=normalized_foodplan,
    )
    if not isinstance(posted_foodplan, list):
        raise TypeError("Expected EatMyRide foodplan update endpoint to return a list")
    updated_activity = _request_json(
        f"/activities/{activity_id}",
        token=token,
        method="PUT",
        json_body=activity,
    )
    if not isinstance(updated_activity, dict):
        raise TypeError("Expected EatMyRide activity update endpoint to return an object")
    return {
        "activity": get_activity(activity_id, token=token),
        "foodplan": get_foodplan(activity_id, token=token),
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
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"EatMyRide request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"EatMyRide request failed: {exc.reason}") from exc


def _activity_local_date(activity: dict[str, Any]) -> date | None:
    raw_date = str(activity.get("date") or "")
    if not raw_date:
        return None
    activity_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    return activity_date.astimezone(LOCAL_TIMEZONE).date()


def _load_env_values(env_path: str | Path) -> dict[str, str]:
    path = Path(env_path)
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


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
