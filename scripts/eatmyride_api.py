"""Cache EatMyRide activity details and recorded food-plan events."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


EATMYRIDE_API_BASE_URL = os.environ.get(
    "EATMYRIDE_API_BASE_URL",
    "https://backend.eatmyride.com/api",
)
EATMYRIDE_API_VERSION = os.environ.get("EATMYRIDE_API_VERSION", "1.03")
DEFAULT_DATA_DIR = Path("data/eatmyride")
LOCAL_TIMEZONE = ZoneInfo("Europe/Oslo")


@dataclass(frozen=True)
class EatMyRideCredentials:
    """Credentials for the EatMyRide personal API."""

    email: str
    password: str

    def login(self) -> str:
        """Return a fresh JWT without persisting it locally."""

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


def list_activities_for_day(day: str | date, *, token: str) -> list[dict[str, Any]]:
    """List activities whose start falls within one local Oslo calendar day."""

    local_day = date.fromisoformat(day) if isinstance(day, str) else day
    start = datetime.combine(local_day, time.min, tzinfo=LOCAL_TIMEZONE)
    end = start + timedelta(days=1)
    payload = _request_json(
        f"/activities/list/{quote(start.isoformat())}/{quote(end.isoformat())}",
        token=token,
    )
    if not isinstance(payload, list):
        raise TypeError("Expected EatMyRide activities endpoint to return a list")
    return [
        activity
        for activity in payload
        if _activity_local_date(activity) == local_day
    ]


def cache_activity(
    activity_id: str | int,
    *,
    token: str,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache one EatMyRide activity and its recorded food-plan events."""

    activity = get_activity(activity_id, token=token)
    foodplan = get_foodplan(activity_id, token=token)

    activity_dir = _activity_cache_dir(Path(output_dir), activity)
    activity_dir.mkdir(parents=True, exist_ok=True)
    activity_path = activity_dir / "activity.json"
    foodplan_path = activity_dir / "foodplan.json"
    _write_json(activity_path, activity)
    _write_json(foodplan_path, foodplan)
    return {
        "activity_dir": activity_dir,
        "activity": activity_path,
        "foodplan": foodplan_path,
    }


def get_activity(activity_id: str | int, *, token: str) -> dict[str, Any]:
    """Return one EatMyRide activity."""

    activity = _request_json(f"/activities/{activity_id}", token=token)
    if not isinstance(activity, dict):
        raise TypeError("Expected EatMyRide activity endpoint to return an object")
    return activity


def get_foodplan(activity_id: str | int, *, token: str) -> list[dict[str, Any]]:
    """Return recorded food-plan events for one EatMyRide activity."""

    foodplan = _request_json(f"/foodplan/{activity_id}", token=token)
    if not isinstance(foodplan, list):
        raise TypeError("Expected EatMyRide foodplan endpoint to return a list")
    return foodplan


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
    """Return intake totals calculated from recorded event quantities.

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
    posted_foodplan = _request_json(
        f"/foodplan/{activity_id}",
        token=token,
        method="POST",
        json_body=foodplan,
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


def cache_day(
    day: str | date,
    *,
    token: str,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> list[dict[str, Path]]:
    """Cache all EatMyRide activities for one local Oslo calendar day."""

    local_day = date.fromisoformat(day) if isinstance(day, str) else day
    activities = list_activities_for_day(local_day, token=token)
    lists_dir = Path(output_dir) / "activity_lists"
    lists_dir.mkdir(parents=True, exist_ok=True)
    _write_json(lists_dir / f"{local_day.isoformat()}.json", activities)
    return [
        cache_activity(activity["id"], token=token, output_dir=output_dir)
        for activity in activities
    ]


def cache_latest_activity(
    *,
    token: str,
    output_dir: str | Path = DEFAULT_DATA_DIR,
    lookback_days: int = 7,
) -> dict[str, Path]:
    """Cache the newest EatMyRide activity in a recent local-day window."""

    today = datetime.now(LOCAL_TIMEZONE).date()
    activities = []
    for offset in range(lookback_days + 1):
        activities.extend(list_activities_for_day(today - timedelta(days=offset), token=token))
    if not activities:
        raise RuntimeError(f"No EatMyRide activities found in the last {lookback_days} days")
    latest = max(activities, key=lambda activity: str(activity.get("date") or ""))
    return cache_activity(latest["id"], token=token, output_dir=output_dir)


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
        "User-Agent": "training-ai/0.1 (+EatMyRide personal cache client)",
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


def _activity_cache_dir(root: Path, activity: dict[str, Any]) -> Path:
    activity_id = activity.get("id")
    if not activity_id:
        raise KeyError(f"EatMyRide activity is missing id: {activity}")
    activity_date = _activity_local_date(activity)
    local_date = activity_date.isoformat() if activity_date else "unknown"
    return root / "activities" / f"{local_date}_{activity_id}"


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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
