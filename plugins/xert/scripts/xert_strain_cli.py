#!/usr/bin/env python3
"""Offline command line interface for the local Xert XSS model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xert_strain_model import calculate_workout, solve_endurance_duration


def _duration_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError("duration must be MM:SS or HH:MM:SS")
    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration must contain integers") from exc
    if len(numbers) == 2:
        minutes, seconds = numbers
        hours = 0
    else:
        hours, minutes, seconds = numbers
    if min(numbers) < 0 or seconds >= 60 or (len(numbers) == 3 and minutes >= 60):
        raise argparse.ArgumentTypeError("invalid duration")
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise argparse.ArgumentTypeError("duration must be positive")
    return total


def _segment(value: str) -> dict[str, Any]:
    try:
        duration_raw, power_raw = value.rsplit("@", 1)
        duration = _duration_seconds(duration_raw)
        if "-" in power_raw:
            start_raw, end_raw = power_raw.split("-", 1)
            return {
                "duration_seconds": duration,
                "power": float(start_raw),
                "end_power": float(end_raw),
            }
        return {"duration_seconds": duration, "power": float(power_raw)}
    except (ValueError, argparse.ArgumentTypeError) as exc:
        raise argparse.ArgumentTypeError(
            "segment must be MM:SS@WATTS or MM:SS@START-END"
        ) from exc


def _row_json(value: str) -> dict[str, Any]:
    try:
        row = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid row JSON: {exc}") from exc
    if not isinstance(row, dict):
        raise argparse.ArgumentTypeError("row JSON must be an object")
    if "duration" in row and "duration_seconds" not in row:
        row["duration_seconds"] = _duration_seconds(str(row.pop("duration")))
    return row


def _json_value_or_file(value: str) -> Any:
    """Load one JSON value from inline text or a file path."""

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        try:
            payload = json.loads(Path(value).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise argparse.ArgumentTypeError(
                "input must be an inline JSON object or a path to a JSON file"
            ) from exc
    return payload


def _designer_value(value: Any, *, field: str) -> Any:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        raise ValueError(f"Designer row {field} is required")
    return value


def _designer_duration_seconds(value: Any, *, field: str) -> int:
    raw = _designer_value(value, field=field)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        seconds = int(raw)
        if seconds <= 0 or seconds != raw:
            raise ValueError(f"Designer row {field} must be positive whole seconds")
        return seconds
    try:
        return _duration_seconds(str(raw))
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"Designer row {field} is invalid: {exc}") from exc


def _designer_power_segment(
    value: Any,
    *,
    duration_seconds: int,
    tp: float,
    ltp: float,
    field: str,
) -> dict[str, Any]:
    power = value if isinstance(value, dict) else {"type": "absolute", "value": value}
    power_type = str(power.get("type") or "absolute")
    start = float(_designer_value(power, field=field))
    end_raw = power.get("second_value")

    if power_type in {"absolute", "ramp_absolute"}:
        scale = 1.0
    elif power_type in {"relative_ftp", "ramp_ftp"}:
        scale = tp / 100.0
    elif power_type == "ramp_ltp":
        scale = ltp / 100.0
    else:
        raise ValueError(f"unsupported Designer {field} type: {power_type}")

    segment = {"duration_seconds": duration_seconds, "power": start * scale}
    if power_type.startswith("ramp_"):
        if end_raw is None:
            raise ValueError(f"Designer {field} ramp requires second_value")
        segment["end_power"] = float(end_raw) * scale
    return segment


def designer_rows_to_segments(
    rows: list[dict[str, Any]],
    *,
    tp: float,
    hie: float,
    adjustable_row: int,
) -> tuple[list[dict[str, Any]], int]:
    """Expand one-based Designer rows into offline model segments."""

    if not rows:
        raise ValueError("Designer rows must contain at least one row")
    if adjustable_row < 1 or adjustable_row > len(rows):
        raise ValueError("--adjustable-row is out of range")
    ltp = tp - hie / 400.0

    segments: list[dict[str, Any]] = []
    adjustable_segment_index: int | None = None
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Designer row {row_number} must be an object")
        duration = _designer_duration_seconds(row.get("duration"), field="duration")
        try:
            count = int(row.get("interval_count", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Designer row interval_count must be an integer") from exc
        if count < 1:
            raise ValueError("Designer row interval_count must be positive")
        if row_number == adjustable_row and count != 1:
            raise ValueError("the adjustable Designer row must have interval_count 1")

        work = _designer_power_segment(
            row.get("power"), duration_seconds=duration, tp=tp, ltp=ltp, field="power"
        )
        rib_raw = row.get("rib_duration", "00:00")
        rib_value = rib_raw.get("value") if isinstance(rib_raw, dict) else rib_raw
        rib_duration = 0
        if str(rib_value or "00:00") not in {"0", "00:00", "0:00"}:
            rib_duration = _designer_duration_seconds(rib_raw, field="rib_duration")

        for _ in range(count):
            if row_number == adjustable_row:
                adjustable_segment_index = len(segments)
            segments.append(dict(work))
            if rib_duration:
                segments.append(
                    _designer_power_segment(
                        row.get("rib_power", 0),
                        duration_seconds=rib_duration,
                        tp=tp,
                        ltp=ltp,
                        field="rib_power",
                    )
                )

    assert adjustable_segment_index is not None
    return segments, adjustable_segment_index


def _spec_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input JSON must be an object")
        return payload
    if None in (args.signature_tp, args.signature_hie, args.signature_pp):
        raise ValueError("provide --input or all three signature values")
    segments = [*(args.segment or []), *(args.row_json or [])]
    if not segments:
        raise ValueError("provide at least one --segment or --row-json")
    return {
        "signature": {
            "tp": args.signature_tp,
            "hie": args.signature_hie,
            "pp": args.signature_pp,
        },
        "segments": segments,
    }


def _calculate(spec: dict[str, Any], *, include_series: bool) -> dict[str, Any]:
    return calculate_workout(
        signature=spec.get("signature"),
        segments=spec.get("segments"),
        include_series=include_series,
    )


def _detailed_without_series(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "series"}


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    strain = result["strain_summary"]
    contributors = strain["largest_system_contributors"]
    return {
        "source": result["source"],
        "network_used": result["network_used"],
        "authority": {
            "server_summary_authoritative": result["server_summary_authoritative"],
            "model_basis": result["model_basis"],
        },
        "signature": result["signature"],
        "duration_seconds": result["duration_seconds"],
        "xss": result["xss"],
        "difficulty": result["difficulty"],
        "focus": {
            key: result["focus"].get(key)
            for key in ("status", "power_watts", "duration_seconds")
        },
        "mpa": {
            "minimum_watts": strain["mpa"]["minimum_watts"],
            "minimum_time_seconds": strain["mpa"]["minimum_time_seconds"],
            "end_watts": strain["mpa"]["end_watts"],
            "maximum_same_power_strain_amplification": strain["mpa"][
                "maximum_same_power_strain_amplification"
            ],
        },
        "feasibility": {
            key: result["feasibility"].get(key)
            for key in (
                "valid",
                "minimum_positive_mpa_reserve_watts",
                "minimum_positive_mpa_reserve_time_seconds",
                "first_point_of_failure",
            )
        },
        "largest_system_contributors": {
            "high": contributors["high"],
            "peak": contributors["peak"],
        },
        "interpretation": {
            "xss_system_statement": result["interpretation"][
                "xss_system_statement"
            ],
            "training_domain": result["interpretation"]["training_domain"],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate and compare Xert XSS locally without network access."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    calculate = subparsers.add_parser("calculate", help="Calculate one local workout")
    calculate.add_argument("--input", help="JSON file with signature and segments")
    calculate.add_argument("--signature-tp", type=float)
    calculate.add_argument("--signature-hie", type=float)
    calculate.add_argument("--signature-pp", type=float)
    calculate.add_argument(
        "--segment",
        action="append",
        type=_segment,
        help="Repeat MM:SS@WATTS or MM:SS@START-END",
    )
    calculate.add_argument("--row-json", action="append", type=_row_json)
    calculate.add_argument(
        "--series-output", help="Optional file for the full second-by-second result"
    )
    calculate.add_argument(
        "--detailed",
        action="store_true",
        help="Print all segment diagnostics and limitations.",
    )

    compare = subparsers.add_parser("compare", help="Compare two local workout JSON specs")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.add_argument(
        "--detailed",
        action="store_true",
        help="Include full results for both workouts.",
    )
    solve_endurance = subparsers.add_parser(
        "solve-endurance",
        help="Adjust one sub-TP endurance segment to match target low XSS",
    )
    solve_endurance.add_argument(
        "--input",
        required=True,
        type=_json_value_or_file,
        help=(
            "Inline JSON or JSON-file path containing either the existing solver "
            "object or a Designer row array"
        ),
    )
    solve_endurance.add_argument(
        "--adjustable-row", type=int, help="One-based adjustable Designer row"
    )
    solve_endurance.add_argument("--target-low-xss", type=float)
    solve_endurance.add_argument("--signature-tp", type=float)
    solve_endurance.add_argument("--signature-hie", type=float)
    solve_endurance.add_argument("--signature-pp", type=float)
    solve_endurance.add_argument("--minimum-duration-seconds", type=int, default=1)
    solve_endurance.add_argument(
        "--maximum-duration-seconds", type=int, default=8 * 60 * 60
    )
    solve_endurance.add_argument("--tolerance-xss", type=float, default=0.05)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "calculate":
        spec = _spec_from_args(args)
        result = _calculate(spec, include_series=bool(args.series_output))
        if args.series_output:
            Path(args.series_output).write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        output = _detailed_without_series(result) if args.detailed else _summary(result)
        print(json.dumps(output, indent=2, sort_keys=True))
        return

    if args.command == "solve-endurance":
        input_value = args.input
        designer_rows = (
            input_value
            if isinstance(input_value, list)
            else input_value.get("rows")
            if isinstance(input_value, dict) and isinstance(input_value.get("rows"), list)
            else None
        )
        if designer_rows is not None:
            required = {
                "--adjustable-row": args.adjustable_row,
                "--target-low-xss": args.target_low_xss,
                "--signature-tp": args.signature_tp,
                "--signature-hie": args.signature_hie,
                "--signature-pp": args.signature_pp,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    "Designer row input requires " + ", ".join(missing)
                )
            signature = {
                "tp": args.signature_tp,
                "hie": args.signature_hie,
                "pp": args.signature_pp,
            }
            segments, adjustable_segment_index = designer_rows_to_segments(
                designer_rows,
                tp=float(args.signature_tp),
                hie=float(args.signature_hie),
                adjustable_row=args.adjustable_row,
            )
            spec = {
                "signature": signature,
                "segments": segments,
                "adjustable_segment_index": adjustable_segment_index,
                "target_low_xss": args.target_low_xss,
                "minimum_duration_seconds": args.minimum_duration_seconds,
                "maximum_duration_seconds": args.maximum_duration_seconds,
                "tolerance_xss": args.tolerance_xss,
            }
        elif isinstance(input_value, dict):
            extra_flags = (
                args.adjustable_row,
                args.target_low_xss,
                args.signature_tp,
                args.signature_hie,
                args.signature_pp,
            )
            if any(value is not None for value in extra_flags):
                raise ValueError(
                    "Designer flags require --input containing Designer rows"
                )
            spec = input_value
        else:
            raise ValueError("--input must contain a solver object or Designer row array")
        output = solve_endurance_duration(
            signature=spec.get("signature"),
            segments=spec.get("segments"),
            adjustable_segment_index=spec.get("adjustable_segment_index"),
            target_low_xss=spec.get("target_low_xss"),
            minimum_duration_seconds=spec.get("minimum_duration_seconds", 1),
            maximum_duration_seconds=spec.get(
                "maximum_duration_seconds", 8 * 60 * 60
            ),
            tolerance_xss=spec.get("tolerance_xss", 0.05),
        )
        if designer_rows is not None:
            output["adjustable_row"] = args.adjustable_row
            output["original_row_duration_seconds"] = _designer_duration_seconds(
                designer_rows[args.adjustable_row - 1].get("duration"),
                field="duration",
            )
            output["solved_row_duration_seconds"] = output[
                "adjustable_duration_seconds"
            ]
        print(json.dumps(output, indent=2, sort_keys=True))
        return

    left_spec = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right_spec = json.loads(Path(args.right).read_text(encoding="utf-8"))
    left = _calculate(left_spec, include_series=False)
    right = _calculate(right_spec, include_series=False)
    print(
        json.dumps(
            {
                "source": "local_xert_strain_model_comparison",
                "network_used": False,
                "left": _detailed_without_series(left) if args.detailed else _summary(left),
                "right": _detailed_without_series(right) if args.detailed else _summary(right),
                "delta_right_minus_left": {
                    "duration_seconds": right["duration_seconds"] - left["duration_seconds"],
                    "xss": {
                        key: right["xss"][key] - left["xss"][key]
                        for key in ("total", "low", "high", "peak")
                    },
                    "difficulty": right["difficulty"] - left["difficulty"],
                    "minimum_mpa_reserve_watts": (
                        None
                        if left["feasibility"]["minimum_positive_mpa_reserve_watts"] is None
                        or right["feasibility"]["minimum_positive_mpa_reserve_watts"] is None
                        else right["feasibility"]["minimum_positive_mpa_reserve_watts"]
                        - left["feasibility"]["minimum_positive_mpa_reserve_watts"]
                    ),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
