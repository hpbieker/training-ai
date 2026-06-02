"""Cache EatMyRide activity details and recorded food-plan events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


EATMYRIDE_API_BASE_URL = "https://backend.eatmyride.com/api"
EATMYRIDE_API_VERSION = "1.03"
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
            return json.loads(response.read().decode("utf-8"))
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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
