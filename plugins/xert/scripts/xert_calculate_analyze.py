#!/usr/bin/env python3
"""Analyze Xert Calculate or activity session series."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

from xert_strain_model import (
    EMPIRICAL_CALCULATE_RECOVERY_OFFSET_SECONDS,
    difficulty_step,
    focus_from_xss,
    mpa_from_wexp,
    recovery_wexp,
    sample_strain,
    specificity_from_xss,
)
def _number(value: Any, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _signature(payload: dict[str, Any]) -> tuple[float, float, float]:
    signature = payload.get("signature")
    if not isinstance(signature, dict):
        raise ValueError("series payload must contain a signature object")
    tp = _number(signature.get("ftp"), field="signature.ftp")
    hie = _number(signature.get("atc"), field="signature.atc")
    pp = _number(signature.get("pp"), field="signature.pp")
    if tp <= 0 or hie <= 0 or pp <= tp:
        raise ValueError("require signature FTP/TP > 0, ATC/HIE > 0, and PP > TP")
    return tp, hie, pp


def _stats(payload: dict[str, Any]) -> dict[str, Any]:
    stats = payload.get("calculation_stats")
    return stats if isinstance(stats, dict) else {}


def _normalize_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Accept native Calculate payloads and normalized Xert activity payloads."""

    if isinstance(payload.get("series"), list):
        return payload, "xert_workout_calculate"
    session_data = payload.get("session_data")
    summary = payload.get("summary")
    if not isinstance(session_data, list) or not isinstance(summary, dict):
        raise ValueError(
            "payload must contain either a series array or activity session_data "
            "and summary objects"
        )
    signature = summary.get("sig")
    if not isinstance(signature, dict):
        raise ValueError("activity summary must contain a sig object")
    stats = {
        target: summary.get(source)
        for target, source in (
            ("xss", "xss"),
            ("xlss", "xlss"),
            ("xhss", "xhss"),
            ("xpss", "xpss"),
            ("difficulty", "difficulty"),
            ("sfd", "sfd"),
            ("focus", "focus"),
        )
    }
    if isinstance(summary.get("specificity"), (int, float)):
        stats["specificity"] = summary["specificity"]
    elif isinstance(summary.get("specificity"), str):
        stats["specRating"] = summary["specificity"]
    return {
        "signature": signature,
        "series": session_data,
        "calculation_stats": stats,
    }, "xert_activity_session"


def _sample_durations(series: list[dict[str, Any]]) -> tuple[list[float], dict[str, Any]]:
    """Derive sample durations from time fields and describe sampling quality."""

    times: list[float] = []
    for index, sample in enumerate(series):
        value = sample.get("time", sample.get("seconds"))
        if value is None:
            return [1.0] * len(series), {
                "time_source": "implicit_one_second",
                "irregular_intervals": 0,
                "maximum_interval_seconds": 1.0,
            }
        times.append(_number(value, field=f"series[{index}].time"))
    differences = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    if any(value <= 0 for value in differences):
        raise ValueError("series time values must be strictly increasing")
    typical = statistics.median(differences) if differences else 1.0
    durations = differences + [typical]
    return durations, {
        "time_source": "time_or_seconds",
        "typical_interval_seconds": typical,
        "irregular_intervals": sum(
            not math.isclose(value, typical, rel_tol=0.0, abs_tol=1e-9)
            for value in differences
        ),
        "maximum_interval_seconds": max(durations),
        "irregular_integration_assumption": "sample_and_hold_to_next_timestamp",
    }


def _max_abs(values: list[float]) -> float | None:
    return max(values, default=None)


def analyze_calculate_series(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate Xert model equations against one Calculate series payload."""

    if not isinstance(payload, dict):
        raise TypeError("series payload must be a JSON object")
    payload, source_kind = _normalize_payload(payload)
    series = payload.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("series payload must contain a non-empty series array")

    tp, hie, pp = _signature(payload)
    stats = _stats(payload)
    sample_durations, sampling = _sample_durations(series)

    mpa_residuals: list[float] = []
    published_linear_mpa_residuals: list[float] = []
    xssr_residuals: list[float] = []
    reported_xds_residuals: list[float] = []
    reconstructed = {"low": 0.0, "high": 0.0, "peak": 0.0}
    difficulty = 0.0
    maximum_difficulty = 0.0
    maximum_reported_xds: float | None = None
    minimum_positive_reserve = math.inf
    minimum_positive_reserve_index: int | None = None
    failure_index: int | None = None
    failure_reserve: float | None = None
    at_or_above_mpa_sample_count = 0
    mpa_floor_sample_count = 0
    valid_sample_count = 0
    recovery_residuals: list[float] = []
    simple_recovery_residuals: list[float] = []

    for index, sample in enumerate(series):
        if not isinstance(sample, dict):
            raise ValueError(f"series[{index}] must be an object")
        power = _number(
            sample.get("power", sample.get("watts")),
            field=f"series[{index}].power",
        )
        wexp = _number(sample.get("wexp"), field=f"series[{index}].wexp")
        reported_mpa = _number(sample.get("mpa"), field=f"series[{index}].mpa")
        sample_duration = sample_durations[index]
        if failure_index is not None and source_kind == "xert_activity_session":
            continue

        reserve = reported_mpa - power
        if reserve <= 0 and failure_index is None:
            failure_index = index
            failure_reserve = reserve
        if reserve <= 0:
            at_or_above_mpa_sample_count += 1
        elif reserve < minimum_positive_reserve:
            minimum_positive_reserve = reserve
            minimum_positive_reserve_index = index

        expected_mpa = mpa_from_wexp(wexp, tp=tp, hie=hie, pp=pp)
        if math.isclose(reported_mpa, tp, rel_tol=0.0, abs_tol=1e-9):
            mpa_floor_sample_count += 1
        mpa_residuals.append(abs(reported_mpa - expected_mpa))
        published_linear_mpa = pp - (pp - tp) * (wexp / hie)
        published_linear_mpa_residuals.append(
            abs(reported_mpa - published_linear_mpa)
        )

        valid_sample_count += 1
        strain = sample_strain(
            power,
            mpa=reported_mpa,
            tp=tp,
            pp=pp,
            duration_seconds=sample_duration,
        )
        for system, value in strain["xss"].items():
            reconstructed[system] += value

        expected_xssr = strain["xssr"]
        if sample.get("xssr") is not None:
            reported_xssr = _number(
                sample.get("xssr"),
                field=f"series[{index}].xssr",
            )
            xssr_residuals.append(abs(reported_xssr - expected_xssr))

        difficulty = difficulty_step(
            difficulty,
            xss_rate_per_hour=expected_xssr,
            duration_seconds=sample_duration,
        )
        maximum_difficulty = max(maximum_difficulty, difficulty)
        if sample.get("xds") is not None:
            reported_xds = _number(sample.get("xds"), field=f"series[{index}].xds")
            maximum_reported_xds = (
                reported_xds
                if maximum_reported_xds is None
                else max(maximum_reported_xds, reported_xds)
            )
            reported_xds_residuals.append(abs(reported_xds - difficulty))

        if index + 1 < len(series) and power < tp and wexp > 0:
            next_sample = series[index + 1]
            if isinstance(next_sample, dict) and next_sample.get("wexp") is not None:
                next_wexp = _number(
                    next_sample.get("wexp"),
                    field=f"series[{index + 1}].wexp",
                )
                if next_wexp <= wexp:
                    exponential_next = recovery_wexp(
                        wexp,
                        power=power,
                        duration_seconds=sample_duration,
                        tp=tp,
                        hie=hie,
                        offset_seconds=0.0,
                    )
                    empirical_next = recovery_wexp(
                        wexp,
                        power=power,
                        duration_seconds=sample_duration,
                        tp=tp,
                        hie=hie,
                        offset_seconds=EMPIRICAL_CALCULATE_RECOVERY_OFFSET_SECONDS,
                    )
                    simple_recovery_residuals.append(
                        abs(exponential_next - next_wexp)
                    )
                    recovery_residuals.append(abs(empirical_next - next_wexp))

    reconstructed_total = sum(reconstructed.values())
    reported_system = {
        "low": _number(stats.get("xlss"), field="calculation_stats.xlss")
        if stats.get("xlss") is not None
        else None,
        "high": _number(stats.get("xhss"), field="calculation_stats.xhss")
        if stats.get("xhss") is not None
        else None,
        "peak": _number(stats.get("xpss"), field="calculation_stats.xpss")
        if stats.get("xpss") is not None
        else None,
    }
    reported_total = (
        _number(stats.get("xss"), field="calculation_stats.xss")
        if stats.get("xss") is not None
        else None
    )
    system_residual = {
        key: (
            reconstructed[key] - reported_system[key]
            if reported_system[key] is not None
            and (failure_index is None or source_kind == "xert_workout_calculate")
            else None
        )
        for key in reconstructed
    }

    focus_source_low = reported_system["low"]
    focus_source_peak = reported_system["peak"]
    focus = (
        focus_from_xss(
            low_xss=focus_source_low,
            peak_xss=focus_source_peak,
            tp=tp,
            hie=hie,
            pp=pp,
        )
        if focus_source_low is not None and focus_source_peak is not None
        else {
            "status": "unavailable_without_calculation_stats",
            "peak_to_low_ratio": None,
            "power_watts": None,
            "duration_seconds": None,
        }
    )
    reported_sfd = (
        _number(stats.get("sfd"), field="calculation_stats.sfd")
        if stats.get("sfd") is not None
        else None
    )
    focus["reported_duration_seconds"] = reported_sfd
    focus["reported_label"] = stats.get("focus")
    focus_is_clamped_endurance = (
        focus.get("status") == "calculated"
        and stats.get("focus") == "Endurance"
        and reported_sfd == 0
    )
    focus["duration_residual_seconds"] = (
        focus["duration_seconds"] - reported_sfd
        if isinstance(focus["duration_seconds"], float)
        and reported_sfd is not None
        and not focus_is_clamped_endurance
        else None
    )
    focus["comparison_status"] = (
        "xert_endurance_display_clamp"
        if focus_is_clamped_endurance
        else "comparable"
        if focus["duration_residual_seconds"] is not None
        else "not_comparable"
    )

    reported_specificity = (
        _number(stats.get("specificity"), field="calculation_stats.specificity")
        if stats.get("specificity") is not None
        else None
    )
    if reported_total is not None and reported_system["high"] is not None:
        specificity = specificity_from_xss(
            total_xss=reported_total,
            high_xss=reported_system["high"],
            focus=focus,
            tp=tp,
            pp=pp,
        )
        calculated_specificity = specificity["value"]
        specificity_status = specificity["status"]
        specificity_rating = specificity["rating"]
    else:
        calculated_specificity = None
        specificity_status = "unavailable"
        specificity_rating = None

    reported_difficulty = (
        _number(stats.get("difficulty"), field="calculation_stats.difficulty")
        if stats.get("difficulty") is not None
        else None
    )
    summary_integration_warning = False
    if failure_index is None or source_kind == "xert_workout_calculate":
        summary_integration_warning = any(
            residual is not None and abs(residual) > 1e-9
            for residual in system_residual.values()
        )
    authoritative_summary_comparison = sampling["irregular_intervals"] == 0

    return {
        "source": "xert_series_analysis",
        "source_kind": source_kind,
        "signature": {"tp": tp, "hie": hie, "pp": pp},
        "samples": {
            "total": len(series),
            "valid_for_fitting": valid_sample_count,
            "first_failure_index": failure_index,
            "at_or_above_mpa": at_or_above_mpa_sample_count,
            "at_mpa_floor": mpa_floor_sample_count,
            **sampling,
        },
        "feasibility": {
            "valid": failure_index is None,
            "minimum_positive_mpa_reserve_watts": (
                minimum_positive_reserve
                if minimum_positive_reserve_index is not None
                else None
            ),
            "minimum_positive_mpa_reserve_index": minimum_positive_reserve_index,
            "first_failure_reserve_watts": failure_reserve,
        },
        "model_residuals": {
            "maximum_absolute_mpa_watts": _max_abs(mpa_residuals),
            "root_mean_square_mpa_watts": (
                math.sqrt(sum(value * value for value in mpa_residuals) / len(mpa_residuals))
                if mpa_residuals
                else None
            ),
            "maximum_absolute_published_linear_mpa_watts": _max_abs(
                published_linear_mpa_residuals
            ),
            "root_mean_square_published_linear_mpa_watts": (
                math.sqrt(
                    sum(value * value for value in published_linear_mpa_residuals)
                    / len(published_linear_mpa_residuals)
                )
                if published_linear_mpa_residuals
                else None
            ),
            "maximum_absolute_xssr_per_hour": _max_abs(xssr_residuals),
            "maximum_absolute_reconstructed_xds": _max_abs(reported_xds_residuals),
            "mpa_interpretation": (
                "For completed activities, reported MPA is authoritative. Exported "
                "Wexp plus summary signature may not reproduce deeply depleted MPA; "
                "neither prev_sig nor the published linear Wbal mapping resolved this."
                if source_kind == "xert_activity_session"
                else "Calculate uses the squared Wexp-to-MPA mapping with a TP floor once Wexp reaches HIE."
            ),
        },
        "system_xss": {
            "reconstructed": {
                **reconstructed,
                "total": reconstructed_total,
            },
            "reported": {
                **reported_system,
                "total": reported_total,
            },
            "residual_reconstructed_minus_reported": {
                **system_residual,
                "total": (
                    reconstructed_total - reported_total
                    if reported_total is not None
                    and (failure_index is None or source_kind == "xert_workout_calculate")
                    else None
                ),
            },
            "summary_integration_warning": summary_integration_warning,
            "authoritative_summary_comparison": authoritative_summary_comparison,
            "note": (
                "Completed Xert activity summaries matched integration of their "
                "exposed series in tested activities. Workout Designer Calculate "
                "summaries can differ slightly when MPA changes or power is a ramp. "
                "Treat source summaries as authoritative for totals."
                if source_kind == "xert_activity_session"
                else "When MPA changes or power is a ramp, Calculate summary strain "
                "can differ slightly from summing exposed samples. Treat stats as "
                "authoritative for totals without altering validated per-sample equations."
            ),
            "irregular_sampling_note": (
                None
                if authoritative_summary_comparison
                else "Sample-and-hold reconstruction is diagnostic only when timestamp "
                "gaps exist; do not use its summary residual as a model validation result."
            ),
        },
        "difficulty": {
            "reconstructed_maximum": maximum_difficulty,
            "maximum_reported_series_xds": maximum_reported_xds,
            "reported_summary": reported_difficulty,
            "summary_residual": (
                maximum_difficulty - reported_difficulty
                if reported_difficulty is not None
                and (failure_index is None or source_kind == "xert_workout_calculate")
                else None
            ),
        },
        "focus": {
            **focus,
            "valid_for_model": (
                failure_index is None or source_kind == "xert_workout_calculate"
            ),
        },
        "specificity": {
            "status": specificity_status,
            "calculated": calculated_specificity,
            "reported": reported_specificity,
            "residual": (
                calculated_specificity - reported_specificity
                if calculated_specificity is not None
                and reported_specificity is not None
                else None
            ),
            "calculated_rating": specificity_rating,
            "reported_rating": stats.get("specRating"),
        },
        "recovery": {
            "status": (
                "activity_series_pure_exponential"
                if recovery_residuals and source_kind == "xert_activity_session"
                else "calculate_empirical_affine_exponential_unpublished_origin"
                if recovery_residuals
                else "no_recovery_samples"
            ),
            "samples": len(recovery_residuals),
            "offset_seconds": EMPIRICAL_CALCULATE_RECOVERY_OFFSET_SECONDS,
            "maximum_absolute_wexp_residual_joules": _max_abs(recovery_residuals),
            "root_mean_square_wexp_residual_joules": (
                math.sqrt(sum(value * value for value in recovery_residuals) / len(recovery_residuals))
                if recovery_residuals
                else None
            ),
            "simple_exponential_root_mean_square_residual_joules": (
                math.sqrt(
                    sum(value * value for value in simple_recovery_residuals)
                    / len(simple_recovery_residuals)
                )
                if simple_recovery_residuals
                else None
            ),
            "equation": (
                "Wexp_next=Wexp*exp(-(TP-P)*dt/HIE)"
                if source_kind == "xert_activity_session"
                else "Wexp_next=max(0,Wexp*exp(-(TP-P)*dt/HIE)-c*(TP-P)*dt)"
            ),
            "evidence": (
                "tested completed activity series matched the pure exponential "
                "recurrence to floating-point precision"
                if source_kind == "xert_activity_session"
                else "empirical Calculate fit; coefficient origin not present in "
                "published documentation or inspected Workout Designer client code"
            ),
        },
        "validity": {
            "per_sample_model_valid": (
                failure_index is None or source_kind == "xert_workout_calculate"
            ),
            "fit_domain": (
                "Calculate: all P, including P >= MPA with strain-rate cap; "
                "activity: P < MPA"
            ),
            "post_failure_samples_excluded": (
                failure_index is not None and source_kind == "xert_activity_session"
            ),
            "post_failure_strain_rule": (
                "k_strain=MPA/P, so XSSR=MPA*PP/TP^2*100"
                if source_kind == "xert_workout_calculate"
                else "not validated for completed activity series"
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a Xert MCP calculate_workout result file or native "
            "activity --session-data JSON file."
        )
    )
    parser.add_argument("series_file", help="Path to Calculate series JSON")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print single-line JSON rather than indented JSON.",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Print equation residuals and all validation diagnostics.",
    )
    return parser


def summarize_analysis(result: dict[str, Any]) -> dict[str, Any]:
    reported_xss = result["system_xss"]["reported"]
    reconstructed_xss = result["system_xss"]["reconstructed"]
    authoritative_xss = (
        reported_xss if reported_xss.get("total") is not None else reconstructed_xss
    )
    reported_difficulty = result["difficulty"]["reported_summary"]
    difficulty = (
        reported_difficulty
        if reported_difficulty is not None
        else result["difficulty"]["reconstructed_maximum"]
    )
    high_or_peak = (authoritative_xss.get("high") or 0) + (
        authoritative_xss.get("peak") or 0
    )
    feasibility = result["feasibility"]
    return {
        "source": result["source"],
        "source_kind": result["source_kind"],
        "authority": {
            "xert_summary_authoritative": reported_xss.get("total") is not None,
            "series_used_for_explanation": True,
        },
        "signature": result["signature"],
        "samples": result["samples"]["total"],
        "xss": authoritative_xss,
        "difficulty": difficulty,
        "focus": {
            key: result["focus"].get(key)
            for key in (
                "status",
                "reported_label",
                "power_watts",
                "duration_seconds",
            )
        },
        "specificity": {
            "rating": result["specificity"]["reported_rating"]
            or result["specificity"]["calculated_rating"],
            "calculated": result["specificity"]["calculated"],
        },
        "feasibility": {
            "valid": feasibility["valid"],
            "minimum_positive_mpa_reserve_watts": feasibility[
                "minimum_positive_mpa_reserve_watts"
            ],
            "first_failure_reserve_watts": feasibility[
                "first_failure_reserve_watts"
            ],
        },
        "validity": {
            "per_sample_model_valid": result["validity"][
                "per_sample_model_valid"
            ]
        },
        "interpretation": {
            "xss_system_statement": (
                "Xert reported only Low XSS. This does not by itself identify "
                "the training domain or imply that the workout was easy."
                if high_or_peak <= 1e-12
                else "Xert reported effectively only Low XSS; trace High/Peak "
                "was below 0.1 XSS. This does not identify the training domain."
                if high_or_peak < 0.1
                else "Xert reported Low throughout plus additional High/Peak "
                "strain from work above TP."
            ),
            "training_domain": "not_inferred_from_xss_alone",
            "mpa_statement": (
                "No point-of-failure was detected."
                if result["feasibility"]["valid"]
                else "The series reached or crossed MPA; inspect first failure."
            ),
        },
    }


def main() -> None:
    args = build_parser().parse_args()
    path = Path(args.series_file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = analyze_calculate_series(payload)
    output = result if args.detailed else summarize_analysis(result)
    print(
        json.dumps(
            output,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
