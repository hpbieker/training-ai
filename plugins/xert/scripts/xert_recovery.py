"""Xert recovery model calculations and source access."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request

from xert_calendar import fetch_training_forecast_with_opener
from xert_common import (
    LOCAL_TIMEZONE,
    XERT_API_BASE_URL,
    _extract_script_json,
    _nested_float,
    _open_text,
    _parse_xert_datetime,
    _required_float,
    xert_web_login,
)


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

def fetch_my_fitness_model(opener) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch embedded trainingAdvice and trainingPlan from Xert my-fitness."""

    html = _open_text(
        opener,
        Request(
            f"{XERT_API_BASE_URL}/my-fitness",
            headers={"User-Agent": "xert-plugin/0.1 (+Xert my-fitness model)"},
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
            headers={"User-Agent": "xert-plugin/0.1 (+Xert profile settings model)"},
        ),
        "Xert profile settings",
    )
    ir_params = _extract_script_json(html, "ir_params", additional_key="window.user_params =")
    if not isinstance(ir_params, dict):
        raise TypeError("Expected ir_params JSON object in Xert profile settings")
    return ir_params

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
