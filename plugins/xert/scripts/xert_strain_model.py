#!/usr/bin/env python3
"""Pure, offline Xert XSS model reconstructed from Calculate probes.

This module performs no network access and imports no Xert API code. Its
per-sample equations are empirically validated against Workout Designer
Calculate, but they are not published Xert formulas.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


EMPIRICAL_CALCULATE_RECOVERY_OFFSET_SECONDS = 0.0038245044912813284
MODEL_BASIS = "xert_staff_semantics_plus_calculate_validated_equations"


def _finite_number(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def validate_signature(signature: dict[str, Any]) -> tuple[float, float, float]:
    if not isinstance(signature, dict):
        raise ValueError("signature must be an object")
    tp = _finite_number(signature.get("tp"), field="signature.tp")
    hie = _finite_number(signature.get("hie"), field="signature.hie")
    pp = _finite_number(signature.get("pp"), field="signature.pp")
    if tp <= 0 or hie <= 0 or pp <= tp:
        raise ValueError("require TP > 0, HIE > 0, and PP > TP")
    return tp, hie, pp


def work_allocation(power: float, *, tp: float, pp: float) -> dict[str, float]:
    """Allocate instantaneous power to Xert's low/high/peak work systems."""

    if power < 0:
        raise ValueError("power must be non-negative")
    if power <= tp:
        return {"low": power, "high": 0.0, "peak": 0.0}
    excess = power - tp
    peak = excess * excess / (pp - tp)
    return {"low": tp, "high": excess - peak, "peak": peak}


def mpa_from_wexp(wexp: float, *, tp: float, hie: float, pp: float) -> float:
    """Calculate-validated MPA mapping with the observed TP floor."""

    bounded_wexp = min(max(wexp, 0.0), hie)
    return max(tp, pp - (pp - tp) * (bounded_wexp / hie) ** 2)


def strain_coefficient(power: float, *, mpa: float, tp: float, pp: float) -> float:
    """Return Calculate's common low/high/peak strain coefficient."""

    if power < 0:
        raise ValueError("power must be non-negative")
    if power >= mpa:
        if power == 0:
            return 0.0
        return mpa / power
    denominator = pp - power + tp
    if denominator == 0:
        raise ValueError("strain denominator is zero")
    return (pp - mpa + tp) / denominator


def sample_strain(
    power: float,
    *,
    mpa: float,
    tp: float,
    pp: float,
    duration_seconds: float = 1.0,
) -> dict[str, Any]:
    """Return allocation, coefficient, XSS rate, and system XSS for one sample."""

    allocation = work_allocation(power, tp=tp, pp=pp)
    coefficient = strain_coefficient(power, mpa=mpa, tp=tp, pp=pp)
    normalization = pp / (tp * tp) * 100.0 / 3600.0
    return {
        "allocation": allocation,
        "strain_coefficient": coefficient,
        "xssr": coefficient * power * pp / (tp * tp) * 100.0,
        "xss": {
            system: coefficient * value * normalization * duration_seconds
            for system, value in allocation.items()
        },
    }


def difficulty_step(
    current: float, *, xss_rate_per_hour: float, duration_seconds: float
) -> float:
    """Advance Xert's Calculate-validated 30-minute XSS-rate EWMA."""

    alpha = 1.0 - math.exp(-duration_seconds / 1800.0)
    return current + alpha * (xss_rate_per_hour - current)


def recovery_wexp(
    wexp: float,
    *,
    power: float,
    duration_seconds: float,
    tp: float,
    hie: float,
    offset_seconds: float,
) -> float:
    """Recover Wexp with an explicit source-specific affine offset."""

    if power >= tp or wexp <= 0:
        return min(max(wexp, 0.0), hie)
    recovery_gap = tp - power
    recovered = (
        wexp * math.exp(-recovery_gap * duration_seconds / hie)
        - offset_seconds * recovery_gap * duration_seconds
    )
    return min(hie, max(0.0, recovered))


def update_wexp(
    wexp: float,
    *,
    power: float,
    duration_seconds: float,
    tp: float,
    hie: float,
) -> float:
    """Advance Calculate's observed HIE expenditure/recovery state."""

    if power > tp:
        return min(hie, wexp + (power - tp) * duration_seconds)
    return recovery_wexp(
        wexp,
        power=power,
        duration_seconds=duration_seconds,
        tp=tp,
        hie=hie,
        offset_seconds=EMPIRICAL_CALCULATE_RECOVERY_OFFSET_SECONDS,
    )


def focus_from_xss(
    *, low_xss: float, peak_xss: float, tp: float, hie: float, pp: float
) -> dict[str, Any]:
    if low_xss <= 0:
        return {
            "status": "undefined_no_low_xss",
            "power_watts": None,
            "duration_seconds": None,
            "peak_to_low_ratio": None,
        }
    if peak_xss <= 0:
        return {
            "status": "endurance",
            "power_watts": tp,
            "duration_seconds": None,
            "peak_to_low_ratio": 0.0,
        }
    ratio = peak_xss / low_xss
    power = tp + math.sqrt(ratio * tp * (pp - tp))
    duration = (
        0.0
        if power >= pp
        else hie * math.sqrt((pp - power) / (pp - tp)) / (power - tp)
    )
    return {
        "status": "calculated",
        "power_watts": power,
        "duration_seconds": duration,
        "peak_to_low_ratio": ratio,
    }


def specificity_from_xss(
    *, total_xss: float, high_xss: float, focus: dict[str, Any], tp: float, pp: float
) -> dict[str, Any]:
    if total_xss == 0:
        value = 0.5
        status = "zero_load_convention"
    elif focus["status"] == "endurance":
        value = 1.0
        status = "pure_endurance"
    elif isinstance(focus.get("power_watts"), float):
        focus_power = focus["power_watts"]
        excess = focus_power - tp
        pure_high_power = excess * (pp - focus_power) / (pp - tp)
        pure_high_share = pure_high_power / focus_power
        value = high_xss / total_xss / pure_high_share if pure_high_share > 0 else None
        status = "calculated" if value is not None else "undefined"
    else:
        value = None
        status = "undefined"
    rating = (
        None
        if value is None
        else "Polar"
        if value <= 1.0 / 3.0
        else "Pure"
        if value >= 2.0 / 3.0
        else "Mixed"
    )
    return {"status": status, "value": value, "rating": rating}


def _segment_power(segment: dict[str, Any], elapsed: int, duration: int) -> float:
    start = _finite_number(
        segment.get("power", segment.get("start_power")), field="segment.power"
    )
    end_value = segment.get("end_power")
    if end_value is None or duration <= 1:
        return start
    end = _finite_number(end_value, field="segment.end_power")
    return start + (end - start) * elapsed / (duration - 1)


def calculate_workout(
    *,
    signature: dict[str, Any],
    segments: Iterable[dict[str, Any]],
    include_series: bool = True,
) -> dict[str, Any]:
    """Calculate an offline XSS estimate for constant or linear-ramp segments."""

    tp, hie, pp = validate_signature(signature)
    segment_list = list(segments)
    if not segment_list:
        raise ValueError("segments must contain at least one segment")

    totals = {"low": 0.0, "high": 0.0, "peak": 0.0}
    segment_results: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    wexp = 0.0
    difficulty = 0.0
    maximum_difficulty = 0.0
    maximum_difficulty_time: int | None = None
    minimum_positive_reserve = math.inf
    minimum_positive_reserve_time: int | None = None
    first_failure: dict[str, Any] | None = None
    invalid_above_pp = False
    maximum_xss_rate = 0.0
    maximum_xss_rate_time: int | None = None
    maximum_strain_amplification = 1.0
    maximum_strain_amplification_time: int | None = None
    minimum_mpa = pp
    minimum_mpa_time = 0
    final_mpa = pp
    total_seconds = 0

    for segment_index, segment in enumerate(segment_list):
        if not isinstance(segment, dict):
            raise ValueError(f"segments[{segment_index}] must be an object")
        duration_raw = segment.get("duration_seconds")
        duration = int(_finite_number(duration_raw, field="segment.duration_seconds"))
        if duration <= 0 or duration != float(duration_raw):
            raise ValueError("segment.duration_seconds must be a positive integer")
        before = totals.copy()
        segment_failure = False
        segment_minimum_mpa = pp
        segment_minimum_reserve = math.inf
        segment_maximum_xss_rate = 0.0
        segment_maximum_strain_amplification = 1.0

        for elapsed in range(duration):
            power = _segment_power(segment, elapsed, duration)
            if power < 0:
                raise ValueError("segment power must be non-negative")
            invalid_above_pp = invalid_above_pp or power > pp
            mpa = mpa_from_wexp(wexp, tp=tp, hie=hie, pp=pp)
            final_mpa = mpa
            if mpa < minimum_mpa:
                minimum_mpa = mpa
                minimum_mpa_time = total_seconds
            segment_minimum_mpa = min(segment_minimum_mpa, mpa)
            reserve = mpa - power
            if reserve > 0:
                segment_minimum_reserve = min(segment_minimum_reserve, reserve)
            if reserve > 0 and reserve < minimum_positive_reserve:
                minimum_positive_reserve = reserve
                minimum_positive_reserve_time = total_seconds
            if reserve <= 0 and first_failure is None:
                first_failure = {
                    "time_seconds": total_seconds,
                    "segment_index": segment_index,
                    "power_watts": power,
                    "mpa_watts": mpa,
                    "reserve_watts": reserve,
                }
            segment_failure = segment_failure or reserve <= 0

            strain = sample_strain(power, mpa=mpa, tp=tp, pp=pp)
            coefficient = strain["strain_coefficient"]
            increments = strain["xss"]
            for system, value in increments.items():
                totals[system] += value
            xss_rate = strain["xssr"]
            if xss_rate > maximum_xss_rate:
                maximum_xss_rate = xss_rate
                maximum_xss_rate_time = total_seconds
            segment_maximum_xss_rate = max(segment_maximum_xss_rate, xss_rate)
            if 0 < power <= pp:
                fresh_xss_rate = sample_strain(
                    power, mpa=pp, tp=tp, pp=pp
                )["xssr"]
                amplification = (
                    xss_rate / fresh_xss_rate if fresh_xss_rate > 0 else 1.0
                )
                if amplification > maximum_strain_amplification:
                    maximum_strain_amplification = amplification
                    maximum_strain_amplification_time = total_seconds
                segment_maximum_strain_amplification = max(
                    segment_maximum_strain_amplification, amplification
                )
            difficulty = difficulty_step(
                difficulty, xss_rate_per_hour=xss_rate, duration_seconds=1.0
            )
            if difficulty > maximum_difficulty:
                maximum_difficulty = difficulty
                maximum_difficulty_time = total_seconds

            if include_series:
                series.append(
                    {
                        "time_seconds": total_seconds,
                        "segment_index": segment_index,
                        "power": power,
                        "mpa": mpa,
                        "wexp": wexp,
                        "reserve": reserve,
                        "strain_coefficient": coefficient,
                        "xssr": xss_rate,
                        "difficulty": difficulty,
                        "xss": sum(totals.values()),
                        "low_xss": totals["low"],
                        "high_xss": totals["high"],
                        "peak_xss": totals["peak"],
                    }
                )
            wexp = update_wexp(
                wexp, power=power, duration_seconds=1.0, tp=tp, hie=hie
            )
            total_seconds += 1

        segment_results.append(
            {
                "index": segment_index,
                "name": segment.get("name"),
                "duration_seconds": duration,
                "start_power": _segment_power(segment, 0, duration),
                "end_power": _segment_power(segment, duration - 1, duration),
                "xss": {
                    system: totals[system] - before[system] for system in totals
                },
                "xss_rate_per_hour": {
                    "average": (
                        sum(totals[system] - before[system] for system in totals)
                        * 3600.0
                        / duration
                    ),
                    "maximum": segment_maximum_xss_rate,
                },
                "mpa": {
                    "minimum_watts": segment_minimum_mpa,
                    "minimum_positive_reserve_watts": (
                        None
                        if math.isinf(segment_minimum_reserve)
                        else segment_minimum_reserve
                    ),
                    "maximum_same_power_strain_amplification": (
                        segment_maximum_strain_amplification
                    ),
                },
                "point_of_failure": segment_failure,
            }
        )

    total_xss = sum(totals.values())
    focus = focus_from_xss(
        low_xss=totals["low"], peak_xss=totals["peak"], tp=tp, hie=hie, pp=pp
    )
    specificity = specificity_from_xss(
        total_xss=total_xss,
        high_xss=totals["high"],
        focus=focus,
        tp=tp,
        pp=pp,
    )
    low_only = abs(totals["high"]) < 1e-12 and abs(totals["peak"]) < 1e-12
    contributor = {
        system: max(
            segment_results,
            key=lambda segment: segment["xss"][system],
        )
        for system in ("low", "high", "peak")
    }

    def contributor_summary(system: str) -> dict[str, Any] | None:
        segment = contributor[system]
        value = segment["xss"][system]
        if abs(value) < 1e-12:
            return None
        return {
            "segment_index": segment["index"],
            "segment_name": segment["name"],
            "xss": value,
        }

    mpa_statement = (
        "Short-term fatigue materially amplified strain at the same power; "
        f"the maximum modeled multiplier versus fresh MPA was "
        f"{maximum_strain_amplification:.3f}."
        if maximum_strain_amplification >= 1.05
        else "MPA movement had little effect on same-power strain in this workout; "
        f"the maximum modeled multiplier versus fresh MPA was "
        f"{maximum_strain_amplification:.3f}."
    )
    focus_statement = (
        "Accumulated Peak-to-Low strain maps to Endurance Focus."
        if focus["status"] == "endurance"
        else (
            "Accumulated Peak-to-Low strain maps to approximately "
            f"{focus['power_watts']:.1f} W for {focus['duration_seconds']:.1f} s."
            if focus["status"] == "calculated"
            else "Focus is undefined because the modeled result has no Low XSS."
        )
    )
    interpretation = {
        "xss_system_statement": (
            "All modeled XSS is low because no modeled power exceeded TP. "
            "Xert system allocation alone does not identify the workout's "
            "training domain."
            if low_only
            else "The workout accumulates low XSS throughout and adds high/peak "
            "XSS during work above TP. Judge high/peak as absolute doses and in "
            "the context of interval structure, not only as shares of total XSS."
        ),
        "training_domain": "not_inferred_from_xss_alone",
        "difficulty_statement": (
            "Difficulty is the maximum 30-minute EWMA of modeled XSS rate; it is "
            "not synonymous with total XSS or breakthrough."
        ),
        "mpa_statement": mpa_statement,
        "focus_statement": focus_statement,
    }
    result = {
        "source": "local_xert_strain_model",
        "network_used": False,
        "model_basis": MODEL_BASIS,
        "server_summary_authoritative": False,
        "signature": {"tp": tp, "hie": hie, "pp": pp},
        "duration_seconds": total_seconds,
        "xss": {**totals, "total": total_xss},
        "maximum_xss_rate_per_hour": maximum_xss_rate,
        "maximum_xss_rate_time_seconds": maximum_xss_rate_time,
        "difficulty": maximum_difficulty,
        "difficulty_time_seconds": maximum_difficulty_time,
        "focus": focus,
        "specificity": specificity,
        "feasibility": {
            "valid": first_failure is None and not invalid_above_pp,
            "minimum_positive_mpa_reserve_watts": (
                None if math.isinf(minimum_positive_reserve) else minimum_positive_reserve
            ),
            "minimum_positive_mpa_reserve_time_seconds": minimum_positive_reserve_time,
            "first_point_of_failure": first_failure,
            "invalid_power_above_pp": invalid_above_pp,
            "post_failure_is_hypothetical": first_failure is not None,
        },
        "segments": segment_results,
        "strain_summary": {
            "largest_system_contributors": {
                system: contributor_summary(system)
                for system in ("low", "high", "peak")
            },
            "mpa": {
                "start_watts": pp,
                "minimum_watts": minimum_mpa,
                "minimum_time_seconds": minimum_mpa_time,
                "end_watts": final_mpa,
                "maximum_same_power_strain_amplification": (
                    maximum_strain_amplification
                ),
                "maximum_amplification_time_seconds": (
                    maximum_strain_amplification_time
                ),
            },
            "load_concentration": {
                "total_xss": total_xss,
                "maximum_xss_rate_per_hour": maximum_xss_rate,
                "maximum_difficulty": maximum_difficulty,
            },
        },
        "interpretation": interpretation,
        "limitations": [
            "Per-sample equations are Calculate-validated, not published Xert formulas.",
            "Xert server summary totals can differ slightly when MPA changes or power ramps.",
            "The recovery offset is an empirical Calculate fit of unpublished origin.",
            "Completed activities can contain hidden state not recoverable from summary signature and Wexp.",
            "Breakthrough detection and Fitness Signature updates are not modeled.",
        ],
    }
    if include_series:
        result["series"] = series
    return result


def solve_endurance_duration(
    *,
    signature: dict[str, Any],
    segments: Iterable[dict[str, Any]],
    adjustable_segment_index: int,
    target_low_xss: float,
    minimum_duration_seconds: int = 1,
    maximum_duration_seconds: int = 8 * 60 * 60,
    tolerance_xss: float = 0.05,
) -> dict[str, Any]:
    """Solve one sub-TP endurance segment so complete-workout low XSS matches."""

    tp, _, _ = validate_signature(signature)
    segment_list = [dict(segment) for segment in segments]
    if not segment_list:
        raise ValueError("segments must contain at least one segment")
    if (
        isinstance(adjustable_segment_index, bool)
        or not isinstance(adjustable_segment_index, int)
        or not 0 <= adjustable_segment_index < len(segment_list)
    ):
        raise ValueError("adjustable_segment_index is out of range")
    target = _finite_number(target_low_xss, field="target_low_xss")
    if target <= 0:
        raise ValueError("target_low_xss must be positive")
    if (
        isinstance(minimum_duration_seconds, bool)
        or isinstance(maximum_duration_seconds, bool)
        or not isinstance(minimum_duration_seconds, int)
        or not isinstance(maximum_duration_seconds, int)
        or minimum_duration_seconds <= 0
        or maximum_duration_seconds < minimum_duration_seconds
    ):
        raise ValueError("require 0 < minimum duration <= maximum duration")
    tolerance = _finite_number(tolerance_xss, field="tolerance_xss")
    if tolerance <= 0:
        raise ValueError("tolerance_xss must be positive")

    adjustable = segment_list[adjustable_segment_index]
    start_power = _finite_number(
        adjustable.get("power", adjustable.get("start_power")),
        field="adjustable segment power",
    )
    end_power = _finite_number(
        adjustable.get("end_power", start_power),
        field="adjustable segment end_power",
    )
    if start_power > tp or end_power > tp:
        raise ValueError("adjustable endurance segment must remain at or below TP")

    def calculate_at(duration_seconds: int) -> dict[str, Any]:
        candidate_segments = [dict(segment) for segment in segment_list]
        candidate_segments[adjustable_segment_index]["duration_seconds"] = duration_seconds
        result = calculate_workout(
            signature=signature,
            segments=candidate_segments,
            include_series=False,
        )
        return {"segments": candidate_segments, "calculation": result}

    lower = calculate_at(minimum_duration_seconds)
    upper = calculate_at(maximum_duration_seconds)
    lower_xss = float(lower["calculation"]["xss"]["low"])
    upper_xss = float(upper["calculation"]["xss"]["low"])
    if target < lower_xss - tolerance or target > upper_xss + tolerance:
        raise ValueError(
            "target_low_xss is outside the configured endurance-duration bounds"
        )

    best = min(
        (lower, upper),
        key=lambda item: abs(float(item["calculation"]["xss"]["low"]) - target),
    )
    lo = minimum_duration_seconds
    hi = maximum_duration_seconds
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = calculate_at(mid)
        candidate_low = float(candidate["calculation"]["xss"]["low"])
        if abs(candidate_low - target) < abs(
            float(best["calculation"]["xss"]["low"]) - target
        ):
            best = candidate
        if candidate_low < target:
            lo = mid + 1
        elif candidate_low > target:
            hi = mid - 1
        else:
            best = candidate
            break

    calculation = best["calculation"]
    achieved_low = float(calculation["xss"]["low"])
    return {
        "source": "local_xert_endurance_duration_solver",
        "network_used": False,
        "model_basis": calculation["model_basis"],
        "signature": calculation["signature"],
        "adjustable_segment_index": adjustable_segment_index,
        "adjustable_duration_seconds": best["segments"][adjustable_segment_index][
            "duration_seconds"
        ],
        "duration_seconds": calculation["duration_seconds"],
        "target_low_xss": target,
        "achieved_xss": calculation["xss"],
        "low_xss_error": achieved_low - target,
        "tolerance_xss": tolerance,
        "matched_within_tolerance": abs(achieved_low - target) <= tolerance,
        "segments": best["segments"],
        "difficulty": calculation["difficulty"],
        "feasibility": calculation["feasibility"],
    }
