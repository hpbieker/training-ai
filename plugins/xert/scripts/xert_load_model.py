"""Offline Xert multi-system Training Load and fitness projection model.

The load recurrences are the standard EWMA form exposed by Xert's current
per-system impulse-response parameters.  Fitness projections are deliberately
anchored to a supplied current Fitness Signature: current Xert production uses
Training Load and athlete-specific responsiveness, while breakthroughs, decay,
and near-breakthroughs can move the production signature outside a naive
``p0 + k1*TL`` reconstruction.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


SYSTEMS = {
    "low": {"state_key": "ftp", "signature_key": "ftp", "unit": "W"},
    "high": {"state_key": "hie", "signature_key": "hie", "unit": "kJ"},
    "peak": {"state_key": "pp", "signature_key": "pp", "unit": "W"},
}

RECOVERY_DEMAND_MIN = -0.8
RECOVERY_DEMAND_MAX = 1.2
RECOVERY_DEMAND_STEP = 0.1
DECAY_METHOD_LABELS = {
    1.0: "None - Training Load Matched",
    1.03: "Small",
    1.1: "Optimal - Default",
    1.2: "Aggressive",
}


def ewma_gain(tau_days: float) -> float:
    """Return Xert's one-day EWMA gain for a time constant in days."""

    if tau_days <= 0 or not math.isfinite(tau_days):
        raise ValueError("tau_days must be finite and positive")
    return 1.0 - math.exp(-1.0 / tau_days)


def project_load(load: float, *, xss: float, tau_days: float, days: float) -> float:
    """Project one load after applying an XSS impulse at the start."""

    if days < 0 or xss < 0:
        raise ValueError("days and xss must be non-negative")
    return (load + xss * ewma_gain(tau_days)) * math.exp(-days / tau_days)


def project_load_with_scheduled_impulse(
    load: float,
    *,
    xss: float,
    tau_days: float,
    horizon_days: float,
    impulse_after_days: float,
) -> float:
    """Project a load with an XSS impulse at an explicit time in the horizon."""

    if not 0 <= impulse_after_days <= horizon_days:
        raise ValueError("impulse_after_days must be between 0 and horizon_days")
    before = load * math.exp(-impulse_after_days / tau_days)
    remaining = horizon_days - impulse_after_days
    return (before + xss * ewma_gain(tau_days)) * math.exp(-remaining / tau_days)


def xss_for_target_load(
    current_load: float,
    *,
    target_load: float,
    tau_days: float,
    horizon_days: float,
    impulse_after_days: float,
) -> float:
    """Solve the impulse needed at the planned time to reach a horizon target."""

    if not 0 <= impulse_after_days <= horizon_days:
        raise ValueError("impulse_after_days must be between 0 and horizon_days")
    baseline = current_load * math.exp(-horizon_days / tau_days)
    post_impulse_decay = math.exp(-(horizon_days - impulse_after_days) / tau_days)
    return max(
        0.0,
        (target_load - baseline) / (ewma_gain(tau_days) * post_impulse_decay),
    )


def linear_daily_xss_distribution(
    *,
    current_load: float,
    current_signature: float,
    target_signature: float,
    tau_days: float,
    responsiveness: float,
    horizon_days: float,
    start_xss: float | None = None,
) -> dict[str, Any]:
    """Solve a daily linear XSS ramp that reaches a signature target."""

    if horizon_days <= 0:
        raise ValueError("linear daily distribution requires a positive horizon")
    if responsiveness <= 0:
        raise ValueError("responsiveness must be positive")
    if target_signature < current_signature:
        raise ValueError("target signature must not be below current signature")
    if start_xss is not None and start_xss < 0:
        raise ValueError("start_xss must be non-negative")

    target_load = current_load + (target_signature - current_signature) / responsiveness
    no_training_load = current_load * math.exp(-horizon_days / tau_days)
    impulse_count = max(1, math.ceil(horizon_days))
    impulse_days = [float(day) for day in range(impulse_count)]
    weights = [
        ewma_gain(tau_days) * math.exp(-(horizon_days - day) / tau_days)
        for day in impulse_days
    ]

    if impulse_count == 1:
        dose = max(0.0, (target_load - no_training_load) / weights[0])
        start_dose = end_dose = dose
    else:
        start_dose = (
            float(start_xss)
            if start_xss is not None
            else current_load * math.exp(1.0 / tau_days)
        )
        start_weight = sum(
            weight * (1.0 - index / (impulse_count - 1))
            for index, weight in enumerate(weights)
        )
        end_weight = sum(
            weight * (index / (impulse_count - 1))
            for index, weight in enumerate(weights)
        )
        end_dose = (target_load - no_training_load - start_weight * start_dose) / end_weight
        if end_dose < 0:
            raise ValueError("start_xss is too high for a non-negative linear ramp")

    daily_step = (end_dose - start_dose) / max(1, impulse_count - 1)
    doses = [start_dose + daily_step * index for index in range(impulse_count)]
    projected_load = no_training_load + sum(
        dose * weight for dose, weight in zip(doses, weights)
    )
    projected_signature = current_signature + responsiveness * (
        projected_load - current_load
    )
    return {
        "distribution": "linear",
        "frequency": "daily",
        "system": "low",
        "impulse_count": impulse_count,
        "first_impulse_after_days": 0.0,
        "last_impulse_after_days": impulse_days[-1],
        "start_xss": start_dose,
        "end_xss": end_dose,
        "xss_step_per_impulse": daily_step,
        "average_xss_per_impulse": sum(doses) / impulse_count,
        "average_xss_per_week": sum(doses) / impulse_count * 7.0,
        "total_xss": sum(doses),
        "current_signature": current_signature,
        "target_signature": target_signature,
        "current_training_load": current_load,
        "target_training_load": target_load,
        "projected_training_load": projected_load,
        "projected_signature": projected_signature,
        "horizon_days": horizon_days,
        "start_policy": "explicit" if start_xss is not None else "current_load_maintenance",
        "projection_scope": "low_training_load_and_marginal_tp_only",
        "recovery_load_and_status_projected": False,
        "caveat": "mathematical_system_xss_ramp_not_a_training_plan",
    }


def capped_recovery_load(classic_recovery_load: float, *, training_load: float, tau_days: float) -> float:
    """Apply Xert's Forecast-AI minimum RL cap after inactivity."""

    return max(classic_recovery_load, training_load * math.exp(-1.0 / tau_days))


def same_day_completed_and_planned_policy(
    *,
    completed_xss: dict[str, float],
    remaining_xss: dict[str, float],
    planned_xss: dict[str, float],
) -> dict[str, Any]:
    """Keep completed dose, remaining advice, and future Planner load distinct."""

    normalize = lambda values: {system: float(values.get(system, 0.0)) for system in SYSTEMS}
    return {
        "completed_xss": normalize(completed_xss),
        "remaining_xss": normalize(remaining_xss),
        "planned_xss": normalize(planned_xss),
        "dose_to_recommend": normalize(remaining_xss),
        "additional_tl_impulse": normalize(planned_xss),
        "rules": {
            "baseline_already_includes_completed_activity": True,
            "do_not_subtract_completed_xss_again": True,
            "planner_xss_does_not_reduce_remaining_xss": True,
            "completed_xss_resets_on_next_calendar_day": True,
        },
    }


def simulate_calendar_sequence(
    *,
    initial_time: str,
    initial_state: dict[str, dict[str, float]],
    initial_signature: dict[str, float],
    ir_params: dict[str, Any],
    events: list[dict[str, Any]],
    observation_time: str,
    same_day_policy: str = "aggregate_last",
) -> dict[str, Any]:
    """Simulate Xert Planner impulses and return every retained pre-event state.

    Xert's forecast endpoint aggregates same-day XSS and applies the combined
    impulse at the last planned exercise time. ``same_day_policy='all'`` is
    available for completed activities or hypothetical independent impulses.
    """

    def parse(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    if same_day_policy not in {"aggregate_last", "all"}:
        raise ValueError("same_day_policy must be 'aggregate_last' or 'all'")
    ordered = sorted(events, key=lambda event: parse(str(event["at"])))
    coalesced_events: list[dict[str, Any]] = []
    if same_day_policy == "aggregate_last":
        retained_by_day: dict[str, dict[str, Any]] = {}
        for event in ordered:
            raw = str(event["at"]).replace("Z", "+00:00")
            day = datetime.fromisoformat(raw).date().isoformat()
            previous = retained_by_day.get(day)
            if previous is not None:
                coalesced_events.append(previous)
                combined = dict(event)
                previous_xss = previous.get("xss") or {}
                event_xss = event.get("xss") or {}
                combined["xss"] = {
                    system: float(previous_xss.get(system, 0.0)) + float(event_xss.get(system, 0.0))
                    for system in SYSTEMS
                }
                retained_by_day[day] = combined
            else:
                retained_by_day[day] = dict(event)
        ordered = sorted(retained_by_day.values(), key=lambda event: parse(str(event["at"])))
    final_time = parse(observation_time)
    current_time = parse(initial_time)
    if final_time < current_time:
        raise ValueError("observation_time must not precede initial_time")
    tl = {system: float(initial_state["tl"][system]) for system in SYSTEMS}
    rl = {system: float(initial_state["rl"][system]) for system in SYSTEMS}
    signature = {mapping["signature_key"]: float(initial_signature[mapping["signature_key"]]) for mapping in SYSTEMS.values()}
    pending_xss = {system: 0.0 for system in SYSTEMS}
    pre_event_states: list[dict[str, Any]] = []

    def advance(target: datetime) -> None:
        nonlocal current_time
        days = (target - current_time).total_seconds() / 86400
        if days < 0:
            raise ValueError("events must not precede initial_time")
        for system, mapping in SYSTEMS.items():
            params = ir_params[mapping["state_key"]]
            old_tl = tl[system]
            tl[system] = project_load(
                old_tl, xss=pending_xss[system], tau_days=float(params["tau1"]), days=days
            )
            rl[system] = capped_recovery_load(
                project_load(
                    rl[system], xss=pending_xss[system], tau_days=float(params["tau2"]), days=days
                ),
                training_load=tl[system],
                tau_days=float(params["tau2"]),
            )
            key = mapping["signature_key"]
            signature[key] += float(params["k1"]) * (tl[system] - old_tl)
        current_time = target

    for event in ordered:
        event_time = parse(str(event["at"]))
        if event_time > final_time:
            raise ValueError("event occurs after observation_time")
        advance(event_time)
        pre_event_states.append(
            {"at": event_time.isoformat(), "tl": dict(tl), "rl": dict(rl), "signature": dict(signature)}
        )
        event_xss = event.get("xss") or {}
        pending_xss = {system: float(event_xss.get(system, 0.0)) for system in SYSTEMS}

    advance(final_time)
    return {
        "initial_time": parse(initial_time).isoformat(),
        "observation_time": final_time.isoformat(),
        "same_day_policy": same_day_policy,
        "coalesced_events": coalesced_events,
        "pre_event_states": pre_event_states,
        "final_state": {"tl": tl, "rl": rl, "signature": signature},
    }


def training_status_from_total_load(total_load: float) -> dict[str, Any]:
    """Return Xert's published star/category thresholds."""

    if total_load < 25:
        stars, category = 0, "Untrained"
    elif total_load < 50:
        stars, category = 1, "Recreational"
    elif total_load < 75:
        stars, category = 2, "Trained"
    elif total_load < 110:
        stars, category = 3, "Competitive"
    elif total_load < 150:
        stars, category = 4, "Elite"
    else:
        stars, category = 5, "Pro Level"
    return {"stars": stars, "category": category, "total_training_load": total_load}


def readiness_class_from_recovery_days(
    recovery_days: dict[str, float | None],
    *,
    recovery_loads: dict[str, float] | None = None,
    recovery_load_caps: dict[str, float] | None = None,
    days_since_activity: float | None = None,
) -> dict[str, Any]:
    """Classify Xert freshness from per-system readiness and RL caps."""

    low = recovery_days.get("low")
    high = recovery_days.get("high")
    peak = recovery_days.get("peak")
    if days_since_activity is not None and days_since_activity > 7:
        status = "Detraining"
    elif low is not None and low > 0:
        status = "Very Tired"
    elif any(value is not None and value > 0 for value in (high, peak)):
        status = "Tired"
    else:
        at_all_caps = bool(recovery_loads and recovery_load_caps) and all(
            math.isclose(
                float(recovery_loads[system]),
                float(recovery_load_caps[system]),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            for system in SYSTEMS
        )
        if at_all_caps and days_since_activity is not None and days_since_activity > 7:
            status = "Detraining"
        elif at_all_caps:
            status = "Very Fresh"
        else:
            status = "Fresh"
    return {
        "model_status": status,
        "boundary_basis": "system_recovery_days_then_recovery_load_caps",
        "detraining_clock_available": days_since_activity is not None,
    }


def calculate_load_projection(
    *,
    at_state: dict[str, Any],
    ir_params: dict[str, Any],
    current_signature: dict[str, Any],
    planned_xss: dict[str, float] | None = None,
    horizon_days: float = 1.0,
    workout_after_days: float = 0.0,
    desired_signature_gain: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Project TL/RL, Form, status, and marginal TP/HIE/PP response."""

    if horizon_days < 0 or not 0 <= workout_after_days <= horizon_days:
        raise ValueError("require 0 <= workout_after_days <= horizon_days")
    planned_xss = planned_xss or {}
    desired_signature_gain = desired_signature_gain or {}
    current_tl = at_state.get("tl")
    current_rl = at_state.get("rl")
    if not isinstance(current_tl, dict) or not isinstance(current_rl, dict):
        raise TypeError("at_state must contain tl and rl objects")

    systems: dict[str, Any] = {}
    signature_projection: dict[str, float] = {}
    required: dict[str, Any] = {}
    total_tl = 0.0
    total_rl = 0.0

    for system, mapping in SYSTEMS.items():
        state_key = mapping["state_key"]
        signature_key = mapping["signature_key"]
        params = ir_params.get(state_key)
        if not isinstance(params, dict):
            raise TypeError(f"ir_params.{state_key} must be an object")
        tl0 = float(current_tl[state_key])
        rl0 = float(current_rl[state_key])
        tau1 = float(params["tau1"])
        tau2 = float(params["tau2"])
        xss = float(planned_xss.get(system, 0.0))
        tl1 = project_load_with_scheduled_impulse(
            tl0,
            xss=xss,
            tau_days=tau1,
            horizon_days=horizon_days,
            impulse_after_days=workout_after_days,
        )
        tl_at_workout = tl0 * math.exp(-workout_after_days / tau1)
        classic_rl_at_workout = rl0 * math.exp(-workout_after_days / tau2)
        rl_at_workout = capped_recovery_load(
            classic_rl_at_workout,
            training_load=tl_at_workout,
            tau_days=tau2,
        )
        remaining_days = horizon_days - workout_after_days
        classic_rl1 = project_load(
            rl_at_workout,
            xss=xss,
            tau_days=tau2,
            days=remaining_days,
        )
        rl1 = capped_recovery_load(classic_rl1, training_load=tl1, tau_days=tau2)
        rl_cap1 = tl1 * math.exp(-1.0 / tau2)
        form1 = tl1 - rl1
        total_tl += tl1
        total_rl += rl1

        k1 = float(params["k1"])
        sig0 = float(current_signature[signature_key])
        sig1 = sig0 + k1 * (tl1 - tl0)
        signature_projection[signature_key] = sig1
        systems[system] = {
            "xss": xss,
            "training_load": {"current": tl0, "projected": tl1, "tau_days": tau1},
            "recovery_load": {
                "current": rl0,
                "projected": rl1,
                "minimum_cap": rl_cap1,
                "tau_days": tau2,
            },
            "form": form1,
            "signature": {
                "current": sig0,
                "projected": sig1,
                "change": sig1 - sig0,
                "responsiveness_per_training_load": k1,
                "unit": mapping["unit"],
            },
        }

        gain = float(desired_signature_gain.get(signature_key, 0.0))
        if gain > 0:
            delta_tl = gain / k1
            target_tl = tl0 + delta_tl
            required[signature_key] = {
                "desired_gain": gain,
                "required_training_load_increase": delta_tl,
                "single_impulse_xss_at_workout_time": xss_for_target_load(
                    tl0,
                    target_load=target_tl,
                    tau_days=tau1,
                    horizon_days=horizon_days,
                    impulse_after_days=workout_after_days,
                ),
                "system": system,
                "horizon_days": horizon_days,
                "workout_after_days": workout_after_days,
                "caveat": "marginal_TL_model_not_breakthrough_guarantee",
            }

    recovery_days = _recovery_days_from_projected_state(
        systems=systems,
        ir_params=ir_params,
        recovery_offset=float(at_state.get("recovery_offset", 0.0)),
    )
    return {
        "model": "xert_multi_system_impulse_response",
        "state_sync": {
            "state_as_of": at_state.get("start_date"),
            "input_source": "caller_supplied_xert_state",
            "invalidated_when": "xert_processes_any_completed_activity_or_profile_model_change",
            "required_action": "refetch_signature_tl_rl_ir_params_and_recovery_demand_before_next_projection",
            "local_projection_must_not_cross_processed_activity_without_resync": True,
        },
        "horizon_days": horizon_days,
        "workout_after_days": workout_after_days,
        "systems": systems,
        "totals": {
            "training_load": total_tl,
            "recovery_load": total_rl,
            "form": total_tl - total_rl,
        },
        "training_status": training_status_from_total_load(total_tl),
        "freshness": readiness_class_from_recovery_days(
            recovery_days,
            recovery_loads={name: values["recovery_load"]["projected"] for name, values in systems.items()},
            recovery_load_caps={name: values["recovery_load"]["minimum_cap"] for name, values in systems.items()},
        ),
        "recovery_days": recovery_days,
        "signature_projection": signature_projection,
        "required_to_build": required,
        "evidence": {
            "load_model": "published_EWMA_plus_exposed_Xert_time_constants",
            "fitness_model": "current_signature_anchor_plus_exposed_k1_times_delta_TL",
            "recovery_load_in_fitness_prediction": False,
            "forward_parameter_policy": "use_current_live_tau_k1_and_recovery_demand_at_projection_time",
            "signature_anchor_policy": "anchor_to_current_live_signature; do_not_reconstruct_from_p0_or_stl",
            "completed_breakthrough_policy": "after_xert_processes_activity_use_its_saved_new_signature_and_recalculated_activity_xss",
            "historical_data_role": "verification_only_not_parameter_fitting_or_old_activity_explanation",
            "production_equivalence": False,
            "production_differences": [
                "signature decay method",
                "breakthrough and near-breakthrough adjustments",
                "Detraining clock when time since last recorded activity is unavailable",
            ],
        },
    }


def recovery_demand_sensitivity(
    *, at_state: dict[str, Any], ir_params: dict[str, Any], offsets: list[float] | None = None
) -> dict[str, Any]:
    """Evaluate the exact Train/Recover boundaries across slider settings."""

    from xert_recovery import RECOVERY_COMPONENTS, calc_recovery_days_component

    if offsets is None:
        count = round((RECOVERY_DEMAND_MAX - RECOVERY_DEMAND_MIN) / RECOVERY_DEMAND_STEP)
        offsets = [round(RECOVERY_DEMAND_MIN + i * RECOVERY_DEMAND_STEP, 10) for i in range(count + 1)]
    tl = at_state["tl"]
    rl = at_state["rl"]
    critical: dict[str, float] = {}
    for system, mapping in SYSTEMS.items():
        key = mapping["state_key"]
        config = RECOVERY_COMPONENTS[{"low": "lo", "high": "hi", "peak": "pk"}[system]]
        critical[system] = (
            float(tl[key]) * (1.0 - 1.0 / float(config["tired_training_divisor"]))
            + float(config["tired_base"])
            - float(rl[key])
        ) / float(config["tired_recovery_scale"])
    scenarios = []
    for offset in offsets:
        days: dict[str, float | None] = {}
        boundaries: dict[str, float] = {}
        for system, mapping in SYSTEMS.items():
            key = mapping["state_key"]
            config = RECOVERY_COMPONENTS[{"low": "lo", "high": "hi", "peak": "pk"}[system]]
            params = ir_params[key]
            tired_value = (
                float(tl[key]) / float(config["tired_training_divisor"])
                - float(config["tired_base"])
                + float(offset) * float(config["tired_recovery_scale"])
            )
            boundaries[system] = float(tl[key]) - tired_value
            days[system] = calc_recovery_days_component(
                training_load=float(tl[key]),
                recovery_load=float(rl[key]),
                training_load_tau=float(params["tau1"]),
                recovery_load_tau=float(params["tau2"]),
                tired_training_divisor=float(config["tired_training_divisor"]),
                tired_base=float(config["tired_base"]),
                tired_recovery_scale=float(config["tired_recovery_scale"]),
                recovery_offset=float(offset),
            )
        scenarios.append(
            {
                "recovery_demand": offset,
                "status": readiness_class_from_recovery_days(days)["model_status"],
                "train_recover_rl_boundary": boundaries,
                "recovery_days": days,
            }
        )
    return {
        "slider": {"min": RECOVERY_DEMAND_MIN, "max": RECOVERY_DEMAND_MAX, "step": RECOVERY_DEMAND_STEP},
        "direction": "higher_values_lower_the_allowed_RL_boundary_and_require_more_recovery",
        "critical_recovery_demand_above_which_system_is_tired": critical,
        "scenarios": scenarios,
    }


def validate_freshness_history(
    history: list[dict[str, Any]], *, ir_params: dict[str, Any], recovery_offset: float
) -> dict[str, Any]:
    """Validate status colours against recovery boundaries and exact RL caps."""

    from xert_recovery import RECOVERY_COMPONENTS, calc_recovery_days_component

    color_status = {
        "#FF0000": "Very Tired", "#F5A623": "Tired", "#0000FF": "Fresh",
        "#7ED321": "Very Fresh", "#8C452B": "Detraining",
    }
    matches = 0
    compared = 0
    mismatches: list[dict[str, Any]] = []
    for row in history:
        actual = color_status.get(row.get("tsbColor"))
        if actual is None:
            continue
        days: dict[str, float | None] = {}
        loads: dict[str, float] = {}
        caps: dict[str, float] = {}
        complete = True
        for system, (tl_key, rl_key, cap_key, param_key, config_key) in {
            "low": ("ltl", "lrl", "lrl-cap", "ftp", "lo"),
            "high": ("htl", "hrl", "hrl-cap", "hie", "hi"),
            "peak": ("ptl", "prl", "prl-cap", "pp", "pk"),
        }.items():
            if any(row.get(key) is None for key in (tl_key, rl_key, cap_key)):
                complete = False
                break
            params = ir_params[param_key]
            config = RECOVERY_COMPONENTS[config_key]
            loads[system], caps[system] = float(row[rl_key]), float(row[cap_key])
            days[system] = calc_recovery_days_component(
                training_load=float(row[tl_key]), recovery_load=loads[system],
                training_load_tau=float(params["tau1"]), recovery_load_tau=float(params["tau2"]),
                tired_training_divisor=float(config["tired_training_divisor"]),
                tired_base=float(config["tired_base"]),
                tired_recovery_scale=float(config["tired_recovery_scale"]),
                recovery_offset=recovery_offset,
            )
        if not complete:
            continue
        predicted = readiness_class_from_recovery_days(
            days,
            recovery_loads=loads,
            recovery_load_caps=caps,
            days_since_activity=float(row["diff"]) if row.get("diff") is not None else None,
        )["model_status"]
        # Both states share the same load boundary; brown additionally requires
        # the seven-day activity clock, which this response does not expose reliably.
        equivalent = actual == predicted or (actual == "Detraining" and predicted == "Very Fresh")
        compared += 1
        matches += int(equivalent)
        if not equivalent and len(mismatches) < 20:
            mismatches.append({"start_date": row.get("start_date"), "actual": actual, "predicted": predicted})
    return {
        "transition_state_count": compared,
        "matched_count": matches,
        "match_share": matches / compared if compared else None,
        "valid": compared > 0 and matches == compared,
        "detraining_rule": "same_all_system_RL_caps_as_very_fresh_plus_more_than_7_days_without_recorded_activity",
        "mismatches": mismatches,
    }


def _recovery_days_from_projected_state(
    *, systems: dict[str, Any], ir_params: dict[str, Any], recovery_offset: float
) -> dict[str, float | None]:
    # Import locally so this module stays usable in isolation and avoids a
    # module-level dependency cycle through the public API facade.
    from xert_recovery import RECOVERY_COMPONENTS, calc_recovery_days_component

    result: dict[str, float | None] = {}
    for system, output_key in (("low", "low"), ("high", "high"), ("peak", "peak")):
        state_key = SYSTEMS[system]["state_key"]
        config_key = {"low": "lo", "high": "hi", "peak": "pk"}[system]
        config = RECOVERY_COMPONENTS[config_key]
        params = ir_params[state_key]
        result[output_key] = calc_recovery_days_component(
            training_load=systems[system]["training_load"]["projected"],
            recovery_load=systems[system]["recovery_load"]["projected"],
            training_load_tau=float(params["tau1"]),
            recovery_load_tau=float(params["tau2"]),
            tired_training_divisor=float(config["tired_training_divisor"]),
            tired_base=float(config["tired_base"]),
            tired_recovery_scale=float(config["tired_recovery_scale"]),
            recovery_offset=recovery_offset,
        )
    return result


def validate_fitness_measures_history(
    history: list[dict[str, Any]], *, ir_params: dict[str, Any]
) -> dict[str, Any]:
    """Validate recurrence against consecutive pre-activity calendar states."""

    field_map = {
        "low": ("ltl", "lrl", "xlss", "ftp"),
        "high": ("htl", "hrl", "xhss", "hie"),
        "peak": ("ptl", "prl", "xpss", "pp"),
    }
    residuals: dict[str, dict[str, list[float]]] = {
        system: {"training_load": [], "recovery_load": []} for system in field_map
    }
    transitions = 0
    ordered = sorted(
        (row for row in history if isinstance(row, dict) and row.get("start_date")),
        key=lambda row: str(row["start_date"]),
    )
    for previous, current in zip(ordered, ordered[1:]):
        t0 = datetime.fromisoformat(str(previous["start_date"]).replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(str(current["start_date"]).replace("Z", "+00:00"))
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        if t1.tzinfo is None:
            t1 = t1.replace(tzinfo=timezone.utc)
        days = (t1 - t0).total_seconds() / 86400
        if days <= 0:
            continue
        used = False
        for system, (tl_key, rl_key, xss_key, param_key) in field_map.items():
            if previous.get(tl_key) is None or current.get(tl_key) is None:
                continue
            if previous.get(rl_key) is None or current.get(rl_key) is None:
                continue
            params = ir_params.get(param_key)
            if not isinstance(params, dict):
                continue
            xss = float(previous.get(xss_key) or 0.0)
            predicted_tl = project_load(
                float(previous[tl_key]), xss=xss, tau_days=float(params["tau1"]), days=days
            )
            classic_predicted_rl = project_load(
                float(previous[rl_key]), xss=xss, tau_days=float(params["tau2"]), days=days
            )
            predicted_rl = capped_recovery_load(
                classic_predicted_rl,
                training_load=predicted_tl,
                tau_days=float(params["tau2"]),
            )
            residuals[system]["training_load"].append(predicted_tl - float(current[tl_key]))
            residuals[system]["recovery_load"].append(predicted_rl - float(current[rl_key]))
            used = True
        transitions += int(used)

    summary: dict[str, Any] = {}
    for system, load_sets in residuals.items():
        summary[system] = {}
        for load_name, values in load_sets.items():
            summary[system][load_name] = {
                "count": len(values),
                "mean_absolute_residual": (
                    sum(abs(value) for value in values) / len(values) if values else None
                ),
                "maximum_absolute_residual": max((abs(value) for value in values), default=None),
            }
    return {
        "source": "xert_fitness_measures_pre_activity_states",
        "impulse_timing": "previous_activity_xss_at_previous_activity_start",
        "elapsed_time_basis": "exact_start_to_start_seconds",
        "transition_count": transitions,
        "systems": summary,
        "valid": all(
            stats[load_name]["count"] > 0
            and stats[load_name]["maximum_absolute_residual"] <= 0.01
            for stats in summary.values()
            for load_name in ("training_load", "recovery_load")
        ),
        "acceptance_threshold_max_absolute_residual": 0.01,
        "validation_scope": "stored_historical_xss_recurrence_only",
        "forward_use": "verify_equations; always_project_new_work_with_current_live_parameters",
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    """Return a linearly interpolated percentile without external dependencies."""

    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def validate_signature_history(
    history: list[dict[str, Any]],
    *,
    ir_params: dict[str, Any],
    activity_events: dict[str, dict[str, Any]] | None = None,
    flagged_activity_starts: set[str] | None = None,
) -> dict[str, Any]:
    """Test whether historical signature changes follow ``k1 * delta TL``.

    Fitness Measures stores HIE as ATC in joules, while Xert's exposed HIE k1
    is in kJ per Training Load.  Residuals are normalized to the public
    signature units (W, kJ, W).  A residual is an *adjustment candidate*, not
    proof of decay or a breakthrough: the history response does not expose
    enough production metadata to classify the cause.
    """

    activity_events = activity_events or {}
    flagged_activity_starts = flagged_activity_starts or set()
    fields = {
        "tp": {
            "tl": "ltl", "signature": "ftp", "params": "ftp", "scale": 1.0,
            "unit": "W", "tolerance": 1.0,
        },
        "hie": {
            "tl": "htl", "signature": "atc", "params": "hie", "scale": 0.001,
            "unit": "kJ", "tolerance": 0.1,
        },
        "pp": {
            "tl": "ptl", "signature": "pp", "params": "pp", "scale": 1.0,
            "unit": "W", "tolerance": 2.0,
        },
    }
    ordered = sorted(
        (row for row in history if isinstance(row, dict) and row.get("start_date")),
        key=lambda row: str(row["start_date"]),
    )
    result: dict[str, Any] = {}
    for name, config in fields.items():
        params = ir_params.get(config["params"])
        if not isinstance(params, dict):
            continue
        k1 = float(params["k1"])
        adjustments: list[float] = []
        activity_adjustments: list[float] = []
        synthetic_adjustments: list[float] = []
        candidates: list[dict[str, Any]] = []
        manual_override_count = 0
        initialization_count = 0
        breakthrough_count = 0
        event_metadata_match_count = 0
        post_manual_transition_count = 0
        post_manual_model_consistent_count = 0
        flagged_activity_transition_count = 0
        post_flagged_anchor_transition_count = 0
        tolerance = float(config["tolerance"])
        for previous, current in zip(ordered, ordered[1:]):
            required = (config["tl"], config["signature"])
            if any(previous.get(field) is None or current.get(field) is None for field in required):
                continue
            # `manual: true` marks a Fitness Signature value explicitly set or
            # locked by the athlete. The transition into that value tests the
            # override, not Xert's predictive model, and must not be scored as
            # model error. The following transition may still validly evolve
            # from that manually supplied anchor.
            if current.get("manual") is True:
                manual_override_count += 1
                continue
            if current.get("error"):
                initialization_count += 1
                continue
            current_time = datetime.fromisoformat(str(current["start_date"]).replace("Z", "+00:00"))
            previous_time = datetime.fromisoformat(str(previous["start_date"]).replace("Z", "+00:00"))
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
            if previous_time.tzinfo is None:
                previous_time = previous_time.replace(tzinfo=timezone.utc)
            event_key = current_time.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            previous_event_key = previous_time.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            if event_key in flagged_activity_starts:
                flagged_activity_transition_count += 1
                continue
            if previous_event_key in flagged_activity_starts:
                post_flagged_anchor_transition_count += 1
                continue
            # Fitness Measures combines pre-activity loads with the signature
            # resolved for that activity row. `pmcb` therefore marks the
            # signature transition into the breakthrough/near-BT row.
            if current.get("pmcb") is not None:
                breakthrough_count += 1
                continue
            event = activity_events.get(event_key)
            if event is not None:
                event_metadata_match_count += 1
                if event.get("manual") is True:
                    manual_override_count += 1
                    continue
                if event.get("breakthrough") not in (None, 0, False):
                    breakthrough_count += 1
                    continue
            tl_delta = float(current[config["tl"]]) - float(previous[config["tl"]])
            actual_delta = (
                float(current[config["signature"]]) - float(previous[config["signature"]])
            ) * float(config["scale"])
            predicted_delta = k1 * tl_delta
            adjustment = actual_delta - predicted_delta
            adjustments.append(adjustment)
            current_xss = sum(float(current.get(key) or 0.0) for key in ("xlss", "xhss", "xpss"))
            (activity_adjustments if current_xss > 0 else synthetic_adjustments).append(adjustment)
            if previous.get("manual") is True:
                post_manual_transition_count += 1
                post_manual_model_consistent_count += int(abs(adjustment) <= tolerance)
            if abs(adjustment) > 5 * tolerance:
                candidates.append(
                    {
                        "start_date": current["start_date"],
                        "actual_change": actual_delta,
                        "tl_model_change": predicted_delta,
                        "adjustment": adjustment,
                    }
                )

        absolute = [abs(value) for value in adjustments]
        consistent = [value for value in adjustments if abs(value) <= tolerance]
        negative = [value for value in adjustments if value < -tolerance]
        positive = [value for value in adjustments if value > tolerance]
        result[name] = {
            "unit": config["unit"],
            "responsiveness_per_training_load": k1,
            "transition_count": len(adjustments),
            "manual_override_transitions_excluded": manual_override_count,
            "pre_first_signature_transitions_excluded": initialization_count,
            "breakthrough_transitions_excluded": breakthrough_count,
            "activity_event_metadata_matches": event_metadata_match_count,
            "post_manual_transition_count": post_manual_transition_count,
            "post_manual_model_consistent_count": post_manual_model_consistent_count,
            "persistent_lock_evidence": post_manual_transition_count > 0 and post_manual_model_consistent_count == 0,
            "flagged_activity_transitions_excluded": flagged_activity_transition_count,
            "post_flagged_anchor_transitions_excluded": post_flagged_anchor_transition_count,
            "mean_adjustment": sum(adjustments) / len(adjustments) if adjustments else None,
            "median_adjustment": _percentile(adjustments, 0.5),
            "mean_absolute_adjustment": sum(absolute) / len(absolute) if absolute else None,
            "p95_absolute_adjustment": _percentile(absolute, 0.95),
            "maximum_absolute_adjustment": max(absolute, default=None),
            "exact_zero_adjustment_share": (
                sum(abs(value) < 1e-9 for value in adjustments) / len(adjustments)
                if adjustments else None
            ),
            "activity_row_adjustments": {
                "count": len(activity_adjustments),
                "mean_absolute_adjustment": (
                    sum(abs(value) for value in activity_adjustments) / len(activity_adjustments)
                    if activity_adjustments else None
                ),
            },
            "synthetic_daily_row_adjustments": {
                "count": len(synthetic_adjustments),
                "mean_absolute_adjustment": (
                    sum(abs(value) for value in synthetic_adjustments) / len(synthetic_adjustments)
                    if synthetic_adjustments else None
                ),
            },
            "practical_tolerance": tolerance,
            "model_consistent_count": len(consistent),
            "model_consistent_share": len(consistent) / len(adjustments) if adjustments else None,
            "negative_adjustment_count": len(negative),
            "positive_adjustment_count": len(positive),
            "large_adjustment_candidates": candidates,
        }

    return {
        "model": "signature_change_equals_current_k1_times_training_load_change",
        "systems": result,
        "interpretation": {
            "adjustment_definition": "actual_signature_change_minus_k1_times_delta_training_load",
            "negative_adjustments": "compatible_with_decay_or_other_downward_production_adjustment",
            "positive_adjustments": "compatible_with_breakthrough_or_other_upward_production_adjustment",
            "classification_limit": "fitness_measures_does_not_expose_sufficient_event_metadata",
            "manual_lock_handling": "transitions_into_rows_with_manual_true_are_excluded_from_all_error_statistics",
            "breakthrough_handling": "exclude_transition_into_each_fitness_measures_pmcb_activity; activity_detail_breakthrough_verifies_event_semantics",
            "event_metadata_scope": "remaining_large_adjustment_candidates",
            "flag_handling": "exclude_transition_into_flagged_activity_and_next_transition_from_its_invalid_signature_anchor",
            "medal_field": "constant_in_observed_history_and_not_usable_for_breakthrough_detection",
            "production_equivalence": False,
            "historical_data_role": "verification_only_not_parameter_fitting",
            "breakthrough_load_handling": "exclude_signature_prediction_transition_but_keep_xerts_recalculated_activity_xss_in_tl_rl_recurrence",
        },
    }


def summarize_signature_decay_analysis(signature_validation: dict[str, Any], *, decay_method: Any) -> dict[str, Any]:
    """Summarize what signature residuals establish—and what they do not."""

    systems = signature_validation.get("systems", {})
    numeric_decay_method = float(decay_method) if isinstance(decay_method, int | float) else None
    return {
        "configured_decay_method": decay_method,
        "configured_decay_method_label": DECAY_METHOD_LABELS.get(numeric_decay_method),
        "systems": {
            name: {
                "model_consistent_share": stats.get("model_consistent_share"),
                "negative_adjustment_count": stats.get("negative_adjustment_count"),
                "positive_adjustment_count": stats.get("positive_adjustment_count"),
                "large_adjustment_candidate_count": len(stats.get("large_adjustment_candidates", [])),
                "exact_zero_adjustment_share": stats.get("exact_zero_adjustment_share"),
                "activity_row_adjustments": stats.get("activity_row_adjustments"),
                "synthetic_daily_row_adjustments": stats.get("synthetic_daily_row_adjustments"),
            }
            for name, stats in systems.items()
        },
        "conclusion": "training_load_matched_changes_dominate; residual_adjustments_are_concentrated_on_activity_rows; proprietary_decay_convergence_rate_remains_unresolved",
        "observed_decay_shape": "not_a_separate_continuous_daily_subtraction_in_fitness_measures_history",
        "published_production_boundary": "post_2023_decay_methods_follow_training_load_then_converge_toward_about_5_percent_below_no_decay_estimate_at_method_specific_rates",
        "implementation_boundary": "numeric_decay_method_is_a_frontend_enum; convergence_formula_is_server_side_and_not_exposed",
        "exact_decay_formula_identified": False,
        "xert_write_required": False,
    }
