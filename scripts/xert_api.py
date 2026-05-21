"""Utilities for downloading Xert training summaries.

Xert uses OAuth password credentials with the public ``xert_public`` client for
personal scripts. Keep credentials in ``.env`` and cache only the returned
training/activity metadata under ``data/xert``.
"""

from __future__ import annotations

import csv
import base64
import http.cookiejar
import html
import json
import math
import re
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from zoneinfo import ZoneInfo


XERT_API_BASE_URL = "https://www.xertonline.com"
XERT_FORECAST_PATH = "/calendar/training-forecast"
DEFAULT_DATA_DIR = Path("data")
LOCAL_TIMEZONE = ZoneInfo("Europe/Oslo")
DEFAULT_XERT_OAUTH_CLIENT_ID = "xert_public"
DEFAULT_XERT_OAUTH_CLIENT_SECRET = "xert_public"

RECOVERY_COMPONENTS = {
    "lo": {
        "training_load_key": "ftp",
        "tired_training_divisor": 5.0,
        "tired_base": 35.0,
        "tired_recovery_scale": 10.0,
    },
    "hi": {
        "training_load_key": "hie",
        "tired_training_divisor": 25.0,
        "tired_base": 0.6,
        "tired_recovery_scale": 0.5,
    },
    "pk": {
        "training_load_key": "pp",
        "tired_training_divisor": 25.0,
        "tired_base": 0.12,
        "tired_recovery_scale": 0.1,
    },
}


class CsrfTokenParser(HTMLParser):
    """Extract the Laravel CSRF token from Xert's login form."""

    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    @classmethod
    def from_html(cls, html: str) -> str | None:
        parser = cls()
        parser.feed(html)
        return parser.token

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        values = dict(attrs)
        if values.get("name") == "_token":
            self.token = values.get("value")


class ScriptTextParser(HTMLParser):
    """Collect script bodies from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._in_script = False
        self._current: list[str] = []

    @classmethod
    def from_html(cls, html: str) -> list[str]:
        parser = cls()
        parser.feed(html)
        return parser.scripts

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self.scripts.append("".join(self._current))
            self._in_script = False
            self._current = []


@dataclass(frozen=True)
class XertCredentials:
    """Credentials for Xert API calls."""

    access_token: str | None = None
    username: str | None = None
    password: str | None = None
    cookie: str | None = None
    oauth_client_id: str = DEFAULT_XERT_OAUTH_CLIENT_ID
    oauth_client_secret: str = DEFAULT_XERT_OAUTH_CLIENT_SECRET

    def bearer_token(self) -> str:
        if self.access_token:
            return self.access_token
        if self.username and self.password:
            token = request_xert_token(
                self.username,
                self.password,
                client_id=self.oauth_client_id,
                client_secret=self.oauth_client_secret,
            )
            return token["access_token"]
        raise ValueError("Set XERT_ACCESS_TOKEN or XERT_USERNAME and XERT_PASSWORD")


def request_xert_token(
    username: str,
    password: str,
    *,
    client_id: str = DEFAULT_XERT_OAUTH_CLIENT_ID,
    client_secret: str = DEFAULT_XERT_OAUTH_CLIENT_SECRET,
) -> dict[str, Any]:
    """Request an OAuth token from Xert."""

    client_auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode(
        "ascii"
    )
    body = urlencode(
        {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
    ).encode("utf-8")
    request = Request(
        f"{XERT_API_BASE_URL}/oauth/token",
        data=body,
        headers={
            "Authorization": f"Basic {client_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "training-ai/0.1 (+https://www.xertonline.com/API.html)",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert token request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise TypeError("Expected Xert token endpoint to return an access_token")
    return payload


def cache_training_info(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache Xert training, fitness and status information."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    training_info = _request_json("/oauth/training_info", credentials.bearer_token())
    if not isinstance(training_info, dict):
        raise TypeError("Expected Xert training_info endpoint to return an object")

    xert_dir = Path(output_dir) / "xert"
    xert_dir.mkdir(parents=True, exist_ok=True)
    path = xert_dir / f"training_info_{date.today().isoformat()}.json"
    _write_json(path, training_info)
    return {"training_info_json": path}


def cache_recovery_model(
    *,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache locally calculated Xert recovery days from direct web endpoints."""

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    model = fetch_recovery_model_with_login(username=username, password=password)
    xert_dir = Path(output_dir) / "xert"
    xert_dir.mkdir(parents=True, exist_ok=True)
    path = xert_dir / f"recovery_model_{date.today().isoformat()}.json"
    _write_json(path, model)
    return {"recovery_model_json": path}


def fetch_recovery_model_with_login(*, username: str, password: str) -> dict[str, Any]:
    """Fetch Xert model inputs directly and calculate recovery days locally."""

    opener = xert_web_login(username=username, password=password)
    training_advice, training_plan = fetch_my_fitness_model(opener)
    ir_params = fetch_ir_params(opener)
    forecast = fetch_training_forecast_with_opener(opener)
    recovery_offset = _nested_float(training_plan, "settings", "recovery")
    at_state = training_advice.get("at_state") if isinstance(training_advice, dict) else None
    if not isinstance(at_state, dict):
        raise TypeError("Expected Xert trainingAdvice to include at_state")
    if recovery_offset is None:
        raise TypeError("Expected Xert trainingPlan.settings.recovery")

    recovery_days = calculate_recovery_days(
        ir_params=ir_params,
        recovery_offset=recovery_offset,
        at_state=at_state,
    )
    next_workout_days = infer_next_workout_days(
        at_state_start=str(at_state.get("start_date")),
        forecast=forecast,
    )
    workout_capacity = calculate_workout_capacity(
        next_workout_days=next_workout_days,
        ir_params=ir_params,
        recovery_offset=recovery_offset,
        at_state=at_state,
    )
    return {
        "source": "xert_web_direct",
        "recovery_offset": recovery_offset,
        "next_workout_days": next_workout_days,
        "ir_params": ir_params,
        "at_state": at_state,
        "training_status": training_advice.get("training_status"),
        "targetXSS": training_advice.get("targetXSS"),
        "recovery_days": recovery_days,
        "recovery_hours": {
            key: round(value * 24, 3) if value is not None else None
            for key, value in recovery_days.items()
        },
        "workout_capacity": workout_capacity,
    }


def cache_training_forecast(
    *,
    cookie: str | None = None,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache Xert web calendar training forecast.

    This web endpoint requires an authenticated Xert web session.
    """

    if cookie:
        forecast = fetch_training_forecast(cookie=cookie)
    elif username and password:
        forecast = fetch_training_forecast_with_login(username=username, password=password)
    else:
        raise ValueError("Set XERT_COOKIE or XERT_USERNAME and XERT_PASSWORD")
    if not isinstance(forecast, dict):
        raise TypeError("Expected Xert forecast endpoint to return an object")

    xert_dir = Path(output_dir) / "xert"
    xert_dir.mkdir(parents=True, exist_ok=True)
    path = xert_dir / f"training_forecast_{date.today().isoformat()}.json"
    _write_json(path, forecast)
    return {"training_forecast_json": path}


def cache_recommended_training(
    *,
    date_value: str | date,
    recent: bool = True,
    additional: bool = False,
    sport: str | None = None,
    cookie: str | None = None,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache Xert recommended workouts for a date."""

    if cookie:
        recommendations = fetch_recommended_training(
            date_value=date_value,
            recent=recent,
            additional=additional,
            sport=sport,
            cookie=cookie,
        )
    elif username and password:
        recommendations = fetch_recommended_training_with_login(
            date_value=date_value,
            recent=recent,
            additional=additional,
            sport=sport,
            username=username,
            password=password,
        )
    else:
        raise ValueError("Set XERT_COOKIE or XERT_USERNAME and XERT_PASSWORD")

    xert_dir = Path(output_dir) / "xert" / "recommended_training"
    xert_dir.mkdir(parents=True, exist_ok=True)
    path = xert_dir / f"{_date_to_string(date_value)}.json"
    _write_json(path, recommendations)
    return {"recommended_training_json": path}


def fetch_recommended_training_with_login(
    *,
    date_value: str | date,
    recent: bool,
    additional: bool,
    sport: str | None,
    username: str,
    password: str,
) -> dict[str, Any]:
    """Fetch Xert recommendations by creating a web login session."""

    opener = xert_web_login(username=username, password=password)
    request = Request(
        recommended_training_url(
            date_value=date_value,
            recent=recent,
            additional=additional,
            sport=sport,
        ),
        headers={
            "Accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "training-ai/0.1 (+Xert recommended training cache)",
        },
    )
    try:
        with opener.open(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert recommended training request failed: "
            f"HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return json.loads(body)


def fetch_recommended_training(
    *,
    date_value: str | date,
    recent: bool,
    additional: bool,
    sport: str | None,
    cookie: str,
) -> dict[str, Any]:
    """Fetch Xert recommendations using a web session cookie."""

    request = Request(
        recommended_training_url(
            date_value=date_value,
            recent=recent,
            additional=additional,
            sport=sport,
        ),
        headers={
            "Cookie": cookie,
            "Accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "training-ai/0.1 (+Xert recommended training cache)",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert recommended training request failed: "
            f"HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return json.loads(body)


def recommended_training_url(
    *,
    date_value: str | date,
    recent: bool,
    additional: bool,
    sport: str | None,
) -> str:
    from datetime import datetime, time, timezone

    value_date = date.fromisoformat(date_value) if isinstance(date_value, str) else date_value
    timestamp = datetime.combine(value_date, time.min, tzinfo=timezone.utc).isoformat()
    params = {
        "recent": str(recent).lower(),
        "date": timestamp,
        "additional": str(additional).lower(),
        "sport": sport if sport else "null",
    }
    return f"{XERT_API_BASE_URL}/recommended-training?{urlencode(params)}"


def fetch_training_forecast_with_login(*, username: str, password: str) -> dict[str, Any]:
    """Fetch Xert calendar training forecast by creating a web login session."""

    opener = xert_web_login(username=username, password=password)
    return fetch_training_forecast_with_opener(opener)


def fetch_training_forecast_with_opener(opener) -> dict[str, Any]:
    """Fetch Xert calendar training forecast with an authenticated opener."""

    request = Request(
        f"{XERT_API_BASE_URL}{XERT_FORECAST_PATH}?duration=-1&includePlaceholders=true",
        headers={
            "Accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "training-ai/0.1 (+Xert calendar forecast cache)",
        },
    )
    try:
        with opener.open(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert forecast request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return json.loads(body)


def fetch_training_forecast(*, cookie: str) -> dict[str, Any]:
    """Fetch Xert calendar training forecast using a web session cookie."""

    request = Request(
        f"{XERT_API_BASE_URL}{XERT_FORECAST_PATH}?duration=-1&includePlaceholders=true",
        headers={
            "Cookie": cookie,
            "Accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "training-ai/0.1 (+Xert calendar forecast cache)",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert forecast request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return json.loads(body)


def fetch_my_fitness_model(opener) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch embedded trainingAdvice and trainingPlan from Xert my-fitness."""

    html = _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}/my-fitness",
            headers={"User-Agent": "training-ai/0.1 (+Xert my-fitness model)"},
        ),
        "Xert my-fitness",
    )
    training_advice = _extract_script_json(html, "trainingAdvice")
    training_plan = _extract_script_json(html, "trainingPlan")
    if not isinstance(training_advice, dict):
        raise TypeError("Expected trainingAdvice JSON object in Xert my-fitness")
    if not isinstance(training_plan, dict):
        raise TypeError("Expected trainingPlan JSON object in Xert my-fitness")
    return training_advice, training_plan


def fetch_ir_params(opener) -> dict[str, Any]:
    """Fetch Xert IR time constants from profile settings."""

    html = _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}/profile/settings",
            headers={"User-Agent": "training-ai/0.1 (+Xert profile settings model)"},
        ),
        "Xert profile settings",
    )
    ir_params = _extract_script_json(html, "ir_params", additional_key="window.user_params =")
    if not isinstance(ir_params, dict):
        raise TypeError("Expected ir_params JSON object in Xert profile settings")
    return ir_params


def xert_web_login(*, username: str, password: str):
    """Return an opener with an authenticated xertonline.com web session."""

    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    auth_request = Request(
        f"{XERT_API_BASE_URL}/auth",
        headers={
            "User-Agent": "training-ai/0.1 (+Xert web login)",
        },
    )
    try:
        with opener.open(auth_request, timeout=60) as response:
            auth_html = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert auth page request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc

    token = CsrfTokenParser.from_html(auth_html)
    if not token:
        raise RuntimeError("Could not find Xert CSRF token on auth page")

    body = urlencode(
        {
            "_token": token,
            "username": username,
            "password": password,
        }
    ).encode("utf-8")
    login_request = Request(
        f"{XERT_API_BASE_URL}/auth/login",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "training-ai/0.1 (+Xert web login)",
        },
        method="POST",
    )
    try:
        with opener.open(login_request, timeout=60) as response:
            response.read()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert web login failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return opener


def calculate_recovery_days(
    *,
    ir_params: dict[str, Any],
    recovery_offset: float,
    at_state: dict[str, Any],
) -> dict[str, float | None]:
    """Calculate Xert low/high/peak recovery days from model inputs."""

    training_load = at_state.get("tl")
    recovery_load = at_state.get("rl")
    if not isinstance(training_load, dict) or not isinstance(recovery_load, dict):
        raise TypeError("Expected at_state with tl and rl objects")

    result: dict[str, float | None] = {}
    for component, config in RECOVERY_COMPONENTS.items():
        key = str(config["training_load_key"])
        params = ir_params.get(key)
        if not isinstance(params, dict):
            raise TypeError(f"Expected ir_params.{key}")
        result[component] = calc_recovery_days_component(
            training_load=_required_float(training_load, key),
            recovery_load=_required_float(recovery_load, key),
            training_load_tau=_required_float(params, "tau1"),
            recovery_load_tau=_required_float(params, "tau2"),
            tired_training_divisor=float(config["tired_training_divisor"]),
            tired_base=float(config["tired_base"]),
            tired_recovery_scale=float(config["tired_recovery_scale"]),
            recovery_offset=recovery_offset,
        )
    return result


def calc_recovery_days_component(
    *,
    training_load: float,
    recovery_load: float,
    training_load_tau: float,
    recovery_load_tau: float,
    tired_training_divisor: float,
    tired_base: float,
    tired_recovery_scale: float,
    recovery_offset: float,
) -> float | None:
    """Python port of Xert recovery-days component calculation."""

    tired_value = (
        training_load / tired_training_divisor
        - tired_base
        + recovery_offset * tired_recovery_scale
    )
    recovery_days = math.nan

    if (training_load - tired_value) > 0 and recovery_load != 0:
        recovery_days = -recovery_load_tau * math.log(
            (training_load - tired_value) / recovery_load
        )

    threshold = 0.001
    max_iterations = 50
    for _ in range(max_iterations + 1):
        if math.isnan(recovery_days) or recovery_load == 0:
            break
        tired_value = (
            training_load
            * math.exp(-recovery_days / training_load_tau)
            / tired_training_divisor
            - tired_base
            + recovery_offset * tired_recovery_scale
        )
        numerator = (
            training_load * math.exp(-recovery_days / training_load_tau)
            - tired_value
        )
        if numerator <= 0:
            recovery_days = math.nan
            break
        next_recovery_days = -recovery_load_tau * math.log(numerator / recovery_load)
        if recovery_days == 0 or abs(next_recovery_days / recovery_days - 1.0) < threshold:
            break
        recovery_days = next_recovery_days

    return None if math.isnan(recovery_days) else recovery_days


def calculate_workout_capacity(
    *,
    next_workout_days: float,
    ir_params: dict[str, Any],
    recovery_offset: float,
    at_state: dict[str, Any],
) -> dict[str, float]:
    """Calculate Xert low/high/peak workout capacity from model inputs."""

    training_load = at_state.get("tl")
    recovery_load = at_state.get("rl")
    if not isinstance(training_load, dict) or not isinstance(recovery_load, dict):
        raise TypeError("Expected at_state with tl and rl objects")

    result: dict[str, float] = {}
    for component, config in RECOVERY_COMPONENTS.items():
        key = str(config["training_load_key"])
        params = ir_params.get(key)
        if not isinstance(params, dict):
            raise TypeError(f"Expected ir_params.{key}")
        result[component] = calc_activity_max(
            next_workout_days=next_workout_days,
            recovery_offset=recovery_offset,
            training_load=_required_float(training_load, key),
            recovery_load=_required_float(recovery_load, key),
            training_load_tau=_required_float(params, "tau1"),
            recovery_load_tau=_required_float(params, "tau2"),
            tired_training_divisor=float(config["tired_training_divisor"]),
            tired_base=float(config["tired_base"]),
            tired_recovery_scale=float(config["tired_recovery_scale"]),
        )
    return result


def infer_next_workout_days(
    *,
    at_state_start: str,
    forecast: dict[str, Any],
) -> float:
    """Infer Xert's next-workout horizon from calendar forecast data.

    Xert workout capacity is calculated against the next planned workout after
    the current local calendar day, not against the activity being considered
    today. Falling back to 1 day preserves the historical daily-horizon behavior.
    """

    at_time = _parse_xert_datetime(at_state_start)
    if at_time is None:
        return 1.0
    at_local = at_time.astimezone(LOCAL_TIMEZONE)
    days = forecast.get("days")
    if not isinstance(days, list):
        return 1.0

    future_times = []
    for day in days:
        if not isinstance(day, dict) or not isinstance(day.get("t"), int | float):
            continue
        activity_time = datetime.fromtimestamp(float(day["t"]), tz=timezone.utc)
        activity_local = activity_time.astimezone(LOCAL_TIMEZONE)
        if activity_time <= at_time:
            continue
        if activity_local.date() <= at_local.date():
            continue
        future_times.append(activity_time)

    if not future_times:
        return 1.0
    next_time = min(future_times)
    return (next_time - at_time).total_seconds() / 86400


def calc_activity_max(
    *,
    next_workout_days: float,
    recovery_offset: float,
    training_load: float,
    recovery_load: float,
    training_load_tau: float,
    recovery_load_tau: float,
    tired_training_divisor: float,
    tired_base: float,
    tired_recovery_scale: float,
) -> float:
    """Python port of Xert workout-capacity/activity-max calculation."""

    training_decay = math.exp(-next_workout_days / training_load_tau)
    recovery_decay = math.exp(-next_workout_days / recovery_load_tau)

    training_load_projected = training_load * training_decay
    recovery_load_projected = recovery_load * recovery_decay

    gain_training = 1.0 - math.exp(-1.0 / training_load_tau)
    gain_recovery = 1.0 - math.exp(-1.0 / recovery_load_tau)

    numerator = (
        recovery_load_projected
        - training_load_projected * (1.0 - 1.0 / tired_training_divisor)
        - tired_base
        + tired_recovery_scale * recovery_offset
    )
    denominator = (
        gain_training
        * training_decay
        * (1.0 - 1.0 / tired_training_divisor)
        - gain_recovery * recovery_decay
    )
    return numerator / denominator


def _parse_xert_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _open_text(opener, request: Request, label: str) -> str:
    try:
        with opener.open(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{label} request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc


def _extract_script_json(
    html: str,
    key: str,
    *,
    additional_key: str | None = None,
) -> Any:
    for script in ScriptTextParser.from_html(html):
        if key not in script:
            continue
        if additional_key and additional_key not in script:
            continue
        json_text = _find_json_object(script, key)
        if json_text:
            return json.loads(json_text)
    return None


def _find_json_object(text: str, key: str) -> str | None:
    key_index = text.find(key)
    if key_index < 0:
        return None
    start = text.find("{", key_index)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _nested_float(payload: dict[str, Any], *keys: str) -> float | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, int | float):
        return float(current)
    return None


def _required_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"Expected numeric value for {key}")


def list_activities(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    oldest: str | date,
    newest: str | date,
) -> list[dict[str, Any]]:
    """List Xert activities for a date range."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    activities = _request_json(
        "/oauth/activity",
        credentials.bearer_token(),
        params={
            "from": _date_to_unix(oldest),
            "to": _date_to_unix(newest, end_of_day=True),
        },
    )
    if not isinstance(activities, dict) or not isinstance(activities.get("activities"), list):
        raise TypeError("Expected Xert activity endpoint to return an activities list")
    return activities["activities"]


def cache_activity_summaries(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    oldest: str | date,
    newest: str | date,
    output_dir: str | Path = DEFAULT_DATA_DIR,
    include_details: bool = True,
    include_session_data: bool = False,
) -> dict[str, Path]:
    """Cache Xert activity list and per-activity summary details."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    token = credentials.bearer_token()
    oldest_value = _date_to_string(oldest)
    newest_value = _date_to_string(newest)
    xert_dir = Path(output_dir) / "xert"
    summary_dir = xert_dir / "activity_summaries"
    activities_dir = xert_dir / "activities"
    summary_dir.mkdir(parents=True, exist_ok=True)
    activities_dir.mkdir(parents=True, exist_ok=True)

    activity_list = _request_json(
        "/oauth/activity",
        token,
        params={
            "from": _date_to_unix(oldest),
            "to": _date_to_unix(newest, end_of_day=True),
        },
    )
    if not isinstance(activity_list, dict) or not isinstance(activity_list.get("activities"), list):
        raise TypeError("Expected Xert activity endpoint to return an activities list")
    activities = activity_list["activities"]

    list_json = summary_dir / f"{oldest_value}_{newest_value}.json"
    list_csv = summary_dir / f"{oldest_value}_{newest_value}.csv"
    _write_json(list_json, activities)
    _write_csv(list_csv, activities)

    artifacts = {
        "activities_json": list_json,
        "activities_csv": list_csv,
    }
    if include_details:
        for activity in activities:
            path = _activity_path(activity)
            detail = fetch_activity_detail(
                path,
                access_token=token,
                include_session_data=include_session_data,
            )
            activity_dir = _activity_cache_dir(activities_dir, activity)
            activity_dir.mkdir(parents=True, exist_ok=True)
            _write_json(activity_dir / "activity.json", detail)
        artifacts["activities_dir"] = activities_dir
    return artifacts


def fetch_activity_detail(
    path: str,
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    include_session_data: bool = False,
) -> dict[str, Any]:
    """Fetch one Xert activity detail document."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    detail = _request_json(
        f"/oauth/activity/{path}",
        credentials.bearer_token(),
        params={"include_session_data": 1 if include_session_data else 0},
    )
    if not isinstance(detail, dict):
        raise TypeError("Expected Xert activity detail endpoint to return an object")
    return detail


def list_workouts(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> list[dict[str, Any]]:
    """List the user's Xert workout library."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    payload = _request_json("/oauth/workouts", credentials.bearer_token())
    if not isinstance(payload, dict) or not isinstance(payload.get("workouts"), list):
        raise TypeError("Expected Xert workouts endpoint to return a workouts list")
    return payload["workouts"]


def cache_workouts(
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache the user's Xert workout library."""

    workouts = list_workouts(
        access_token=access_token,
        username=username,
        password=password,
    )
    workouts_dir = Path(output_dir) / "xert" / "workouts"
    workouts_dir.mkdir(parents=True, exist_ok=True)
    list_json = workouts_dir / "workouts.json"
    list_csv = workouts_dir / "workouts.csv"
    _write_json(list_json, workouts)
    _write_csv(list_csv, workouts)
    return {"workouts_json": list_json, "workouts_csv": list_csv}


def summarize_workout_library(
    workouts: Iterable[dict[str, Any]],
    *,
    name_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return compact workout-library rows for chat/table output."""

    rows = []
    for workout in workouts:
        name = str(workout.get("name") or "")
        if name_filter and name_filter.lower() not in name.lower():
            continue
        rows.append(
            {
                "name": name,
                "path": workout.get("path"),
                "duration_min": _round_optional(_numeric_or_none(workout.get("duration")), 1, scale=60),
                "work_watts": parse_work_watts_from_name(name),
                "xss": _round_optional(_numeric_or_none(workout.get("xss")), 1),
                "xlss": _round_optional(_numeric_or_none(workout.get("xlss")), 1),
                "xhss": _round_optional(_numeric_or_none(workout.get("xhss")), 1),
                "xpss": _round_optional(_numeric_or_none(workout.get("xpss")), 1),
                "difficulty": _round_optional(_numeric_or_none(workout.get("difficulty")), 1),
                "rating": workout.get("rating"),
            }
        )
    return rows


def fetch_workout(
    path: str,
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Fetch one resolved Xert workout using the user's fitness signature."""

    credentials = XertCredentials(
        access_token=access_token,
        username=username,
        password=password,
    )
    payload = _request_json(f"/oauth/workout/{path}", credentials.bearer_token())
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert workout endpoint to return an object")
    return payload


def cache_workout(
    path: str,
    *,
    access_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    output_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Cache one resolved Xert workout."""

    workout = fetch_workout(
        path,
        access_token=access_token,
        username=username,
        password=password,
    )
    workouts_dir = Path(output_dir) / "xert" / "workouts" / _safe_path_part(path)
    workouts_dir.mkdir(parents=True, exist_ok=True)
    workout_json = workouts_dir / "workout.json"
    _write_json(workout_json, workout)
    return {"workout_json": workout_json}


def fetch_workout_designer_rows(opener, path: str) -> list[dict[str, Any]]:
    """Fetch editable Xert Workout Designer rows for a workout."""

    request = Request(
        f"{XERT_API_BASE_URL}/workout/{path}/intervals",
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "training-ai/0.1 (+Xert workout designer rows)",
        },
    )
    body = _open_text(opener, request, "Xert workout intervals")
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise TypeError("Expected Xert workout intervals endpoint to return data rows")
    return payload["data"]


def update_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    name: str | None = None,
    description: str | None = None,
    match_name: str | None = None,
    match_power: float | None = None,
    set_duration: str | None = None,
    set_power: float | None = None,
    submit: str = "save",
) -> dict[str, Any]:
    """Update a Xert workout through the authenticated Workout Designer flow."""

    if submit not in {"calculate", "save"}:
        raise ValueError("submit must be 'calculate' or 'save'")
    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    if not any([name, description is not None, set_duration, set_power is not None]):
        raise ValueError("No workout update requested")

    opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, path)
    rows = fetch_workout_designer_rows(opener, path)
    changed_rows = update_workout_rows(
        rows,
        match_name=match_name,
        match_power=match_power,
        set_duration=set_duration,
        set_power=set_power,
    )
    if (set_duration or set_power is not None) and changed_rows == 0:
        raise ValueError("No workout rows matched the requested update")

    form = workout_designer_form_payload(
        page,
        rows=rows,
        name=name,
        description=description,
        submit=submit,
    )
    result = post_workout_designer_form(opener, path, form)
    verification = None
    if submit == "save":
        verification = verify_workout_page(opener, path)
    return {
        "path": path,
        "submit": submit,
        "changed_rows": changed_rows,
        "result": summarize_workout_update_result(result),
        "verification": verification,
    }


def copy_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    name: str,
    description: str | None = None,
    match_name: str | None = None,
    match_power: float | None = None,
    set_power: float | None = None,
    set_interval_count: int | None = None,
    keep_matching_rows: int | None = None,
) -> dict[str, Any]:
    """Copy a Xert workout through the authenticated Workout Designer flow."""

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    opener = xert_web_login(username=username, password=password)
    page = fetch_workout_designer_page(opener, path)
    rows = fetch_workout_designer_rows(opener, path)
    removed_rows = trim_matching_workout_rows(
        rows,
        match_name=match_name,
        match_power=match_power,
        keep_matching_rows=keep_matching_rows,
    )
    changed_rows = update_workout_rows(
        rows,
        match_name=match_name,
        match_power=match_power,
        set_duration=None,
        set_power=set_power,
        set_interval_count=set_interval_count,
    )
    form = workout_designer_form_payload(
        page,
        rows=rows,
        name=name,
        description=description,
        submit="copy",
    )
    result = post_workout_designer_form(opener, path, form)
    summary = summarize_workout_update_result(result)
    new_path = workout_path_from_redirect(summary.get("redirect"))
    rename_result = None
    if new_path:
        copied_page = fetch_workout_designer_page(opener, new_path)
        if copied_page.get("name") != name or (
            description is not None and copied_page.get("description") != description
        ):
            copied_rows = fetch_workout_designer_rows(opener, new_path)
            rename_form = workout_designer_form_payload(
                copied_page,
                rows=copied_rows,
                name=name,
                description=description,
                submit="save",
            )
            rename_result = summarize_workout_update_result(
                post_workout_designer_form(opener, new_path, rename_form)
            )
    verification = verify_workout_page(opener, new_path) if new_path else None
    return {
        "source_path": path,
        "path": new_path,
        "submit": "copy",
        "changed_rows": changed_rows,
        "removed_rows": removed_rows,
        "result": summary,
        "rename_result": rename_result,
        "verification": verification,
    }


def delete_workout(
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Delete a Xert workout through the authenticated web flow."""

    if not username or not password:
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD for Xert web login")
    opener = xert_web_login(username=username, password=password)
    request = Request(
        f"{XERT_API_BASE_URL}/workout/{path}",
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "training-ai/0.1 (+Xert workout delete)",
        },
        method="DELETE",
    )
    body = _open_text(opener, request, "Xert workout delete")
    payload = json.loads(body) if body else {}
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert workout delete endpoint to return an object")
    return payload


def fetch_workout_designer_page(opener, path: str) -> dict[str, Any]:
    """Fetch Workout Designer page values needed for update POSTs."""

    html_text = _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}/workout/{path}",
            headers={"User-Agent": "training-ai/0.1 (+Xert workout designer page)"},
        ),
        "Xert workout designer",
    )
    token = _extract_html_input_value(html_text, "_token")
    if not token:
        raise RuntimeError("Could not find Xert workout CSRF token")
    atc_kj = _parse_float(_extract_html_input_value(html_text, "atc"))
    return {
        "token": token,
        "name": _extract_html_input_value(html_text, "name") or "",
        "description": _extract_html_textarea_value(html_text, "description") or "",
        "pp": _extract_html_input_value(html_text, "pp") or "",
        "atc": "" if atc_kj is None else str(atc_kj * 1000),
        "ftp": _extract_html_input_value(html_text, "ftp") or "",
    }


def verify_workout_page(opener, path: str | None) -> dict[str, Any] | None:
    """Read back the saved Workout Designer page for compact verification."""

    if not path:
        return None
    page = fetch_workout_designer_page(opener, path)
    return {
        "path": path,
        "name": page.get("name"),
        "description": page.get("description"),
    }


def update_workout_rows(
    rows: list[dict[str, Any]],
    *,
    match_name: str | None = None,
    match_power: float | None = None,
    set_duration: str | None = None,
    set_power: float | None = None,
    set_interval_count: int | None = None,
) -> int:
    """Modify editable Workout Designer rows in place."""

    if not set_duration and set_power is None and set_interval_count is None:
        return 0
    changed = 0
    for row in rows:
        if match_name and str(row.get("name", "")).lower() != match_name.lower():
            continue
        if match_power is not None:
            power = row.get("power")
            if not isinstance(power, dict) or not _numbers_equal(power.get("value"), match_power):
                continue
        if set_duration:
            duration = row.setdefault("duration", {})
            if not isinstance(duration, dict):
                raise TypeError(f"Workout row has invalid duration object: {row}")
            duration["value"] = set_duration
            duration.setdefault("type", "absolute")
        if set_power is not None:
            power = row.setdefault("power", {})
            if not isinstance(power, dict):
                raise TypeError(f"Workout row has invalid power object: {row}")
            power["value"] = set_power
            power.setdefault("type", "absolute")
        if set_interval_count is not None:
            row["interval_count"] = str(set_interval_count)
        changed += 1
    return changed


def trim_matching_workout_rows(
    rows: list[dict[str, Any]],
    *,
    match_name: str | None,
    match_power: float | None,
    keep_matching_rows: int | None,
) -> int:
    """Remove matching rows beyond a requested count, preserving order."""

    if keep_matching_rows is None:
        return 0
    if keep_matching_rows < 0:
        raise ValueError("keep_matching_rows must be non-negative")
    matching_indexes = []
    for index, row in enumerate(rows):
        if match_name and str(row.get("name", "")).lower() != match_name.lower():
            continue
        if match_power is not None:
            power = row.get("power")
            if not isinstance(power, dict) or not _numbers_equal(power.get("value"), match_power):
                continue
        matching_indexes.append(index)
    remove_indexes = set(matching_indexes[keep_matching_rows:])
    if not remove_indexes:
        return 0
    rows[:] = [row for index, row in enumerate(rows) if index not in remove_indexes]
    for sequence, row in enumerate(rows):
        row["sequence"] = sequence
    return len(remove_indexes)


def workout_designer_form_payload(
    page: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    name: str | None = None,
    description: str | None = None,
    submit: str,
) -> dict[str, str]:
    """Build Xert Workout Designer form payload."""

    return {
        "_token": str(page["token"]),
        "name": name if name is not None else str(page.get("name") or ""),
        "focus": "",
        "specRating": "",
        "rating": "",
        "description": (
            description if description is not None else str(page.get("description") or "")
        ),
        "pp": str(page.get("pp") or ""),
        "atc": str(page.get("atc") or ""),
        "ftp": str(page.get("ftp") or ""),
        "submit": submit,
        "rows": json.dumps(rows, separators=(",", ":")),
    }


def post_workout_designer_form(opener, path: str, form: dict[str, str]) -> dict[str, Any]:
    """Post a calculate/save request to Xert Workout Designer."""

    request = Request(
        f"{XERT_API_BASE_URL}/workout/{path}",
        data=urlencode(form).encode("utf-8"),
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": form["_token"],
            "Referer": f"{XERT_API_BASE_URL}/workout/{path}",
            "User-Agent": "training-ai/0.1 (+Xert workout designer update)",
        },
        method="POST",
    )
    body = _open_text(opener, request, "Xert workout designer update")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise TypeError("Expected Xert workout update endpoint to return an object")
    return payload


def summarize_workout_update_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary of Xert's verbose workout update response."""

    stats = payload.get("stats")
    compact: dict[str, Any] = {
        "result": payload.get("result"),
        "redirect": payload.get("redirect"),
        "error": payload.get("error"),
        "info": payload.get("info"),
    }
    if isinstance(stats, dict):
        compact["stats"] = {
            key: stats.get(key)
            for key in (
                "duration",
                "xss",
                "xlss",
                "xhss",
                "xpss",
                "difficulty",
                "rating",
                "focus",
                "specRating",
                "specificity",
                "xep",
                "avg_power",
                "max_power",
            )
        }
    if isinstance(payload.get("data"), list):
        compact["data_points"] = len(payload["data"])
    return compact


def workout_path_from_redirect(redirect: Any) -> str | None:
    """Extract the workout path from Xert's post-copy redirect URL."""

    if not isinstance(redirect, str) or not redirect:
        return None
    match = re.search(r"/workout/([^/?#]+)", redirect)
    if not match:
        return None
    return match.group(1)


def parse_work_watts_from_name(name: str) -> float | None:
    """Extract a trailing work target such as '(205W)' from a workout name."""

    match = re.search(r"\((\d+(?:\.\d+)?)\s*W\)", name, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def load_xert_credentials(env_path: str | Path = ".env") -> XertCredentials:
    """Load Xert credentials from a local dotenv-style file."""

    values = _load_env_values(env_path)
    return XertCredentials(
        access_token=values.get("XERT_ACCESS_TOKEN"),
        username=values.get("XERT_USERNAME"),
        password=values.get("XERT_PASSWORD"),
        cookie=values.get("XERT_COOKIE"),
        oauth_client_id=values.get("XERT_OAUTH_CLIENT_ID") or DEFAULT_XERT_OAUTH_CLIENT_ID,
        oauth_client_secret=(
            values.get("XERT_OAUTH_CLIENT_SECRET") or DEFAULT_XERT_OAUTH_CLIENT_SECRET
        ),
    )


def _request_json(
    path: str,
    access_token: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{XERT_API_BASE_URL}{path}{query}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "training-ai/0.1 (+https://www.xertonline.com/API.html)",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc


def _activity_path(activity: dict[str, Any]) -> str:
    path = activity.get("path") or activity.get("id")
    if not path:
        raise KeyError(f"Xert activity is missing path/id: {activity}")
    return str(path)


def _activity_cache_dir(root: Path, activity: dict[str, Any]) -> Path:
    activity_date = _activity_date(activity)
    return root / f"{activity_date}_{_activity_path(activity)}"


def _activity_date(activity: dict[str, Any]) -> str:
    start = activity.get("start_date")
    if isinstance(start, dict):
        raw = str(start.get("date") or "")
        if raw:
            return raw[:10]
    return str(activity.get("date") or "unknown")[:10]


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)


def _extract_html_input_value(html_text: str, name: str) -> str | None:
    pattern = rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*>'
    match = re.search(pattern, html_text)
    if not match:
        return None
    value_match = re.search(r'\bvalue="([^"]*)"', match.group(0))
    if not value_match:
        return None
    return html.unescape(value_match.group(1))


def _extract_html_textarea_value(html_text: str, name: str) -> str | None:
    pattern = rf'<textarea\b[^>]*\bname="{re.escape(name)}"[^>]*>(.*?)</textarea>'
    match = re.search(pattern, html_text, flags=re.DOTALL)
    if not match:
        return None
    return html.unescape(match.group(1))


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _numeric_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _round_optional(value: float | None, digits: int, *, scale: float | None = None) -> float | None:
    if value is None:
        return None
    if scale:
        value = value / scale
    return round(value, digits)


def _numbers_equal(value: Any, expected: float) -> bool:
    if not isinstance(value, int | float):
        return False
    return abs(float(value) - expected) < 1e-9


def _date_to_unix(value: str | date, *, end_of_day: bool = False) -> int:
    from datetime import datetime, time, timezone

    value_date = date.fromisoformat(value) if isinstance(value, str) else value
    value_time = time.max if end_of_day else time.min
    return int(datetime.combine(value_date, value_time, tzinfo=timezone.utc).timestamp())


def _date_to_string(value: str | date) -> str:
    return value.isoformat() if isinstance(value, date) else value


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


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
