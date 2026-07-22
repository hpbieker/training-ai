#!/usr/bin/env python3
"""Analyze saved indoor cycling activities for one calendar year."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from analysis import ARTIFACTS_DIR, load_activity_metadata, load_streams_csv, value


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze saved indoor rides for a year.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--vt1-watts", type=float, default=210.0)
    parser.add_argument("--vt2-watts", type=float, default=300.0)
    parser.add_argument("--output-dir", default="outputs/activity-inspect")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    activities = indoor_activity_dirs(args.year)
    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                inspect_and_summarize,
                activity_dir,
                vt1_watts=args.vt1_watts,
                vt2_watts=args.vt2_watts,
                timeout=args.timeout,
            ): activity_dir
            for activity_dir in activities
        }
        for future in as_completed(futures):
            activity_dir = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - keep batch reporting useful.
                errors.append({"activity_dir": str(activity_dir), "error": str(exc)})
    results.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("name") or "")))

    summary = summarize_year(results, args.year, errors)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"indoor_{args.year}_analysis.json"
    md_path = output_dir / f"indoor_{args.year}_analysis.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), **summary["overview"]}, indent=2))


def indoor_activity_dirs(year: int) -> list[Path]:
    activities_dir = ARTIFACTS_DIR / "activities"
    candidates = []
    for activity_dir in sorted(activities_dir.glob(f"{year}-*")):
        if not (activity_dir / "activity.json").exists() or not (activity_dir / "streams.csv").exists():
            continue
        metadata = load_activity_metadata(activity_dir)
        if is_indoor_ride(metadata, activity_dir):
            candidates.append(activity_dir)
    return sorted(
        candidates,
        key=lambda path: str(load_activity_metadata(path).get("start_date_local") or path.name),
    )


def is_indoor_ride(metadata: dict[str, Any], activity_dir: Path) -> bool:
    if str(metadata.get("type") or "").lower() not in {"ride", "virtualride"}:
        return False
    if metadata.get("trainer") is True:
        return True
    if str(metadata.get("type") or "").lower() == "virtualride":
        return True
    stream_types = metadata.get("stream_types") or []
    if isinstance(stream_types, list) and any(str(item).lower() in {"latlng", "lat", "lng"} for item in stream_types):
        return False
    rows = load_streams_csv(activity_dir / "streams.csv")
    gps_rows = 0
    for row in rows:
        if value(row, "lat") is None or value(row, "lng") is None:
            continue
        gps_rows += 1
        if gps_rows >= 60:
            return False
    return True


def inspect_and_summarize(
    activity_dir: Path,
    *,
    vt1_watts: float,
    vt2_watts: float,
    timeout: int,
) -> dict[str, Any]:
    brief = inspect_activity(activity_dir, vt1_watts=vt1_watts, vt2_watts=vt2_watts, timeout=timeout)
    return summarize_activity(activity_dir, brief)


def inspect_activity(activity_dir: Path, *, vt1_watts: float, vt2_watts: float, timeout: int) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        "scripts/activity_inspect.py",
        str(activity_dir),
        "--brief",
        "--stdout",
        "--auto-blocks",
        "--indoor-vt1",
        "--vt1-watts",
        str(vt1_watts),
        "--vt2-watts",
        str(vt2_watts),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    return json.loads(completed.stdout)


def summarize_activity(activity_dir: Path, brief: dict[str, Any]) -> dict[str, Any]:
    activity = brief.get("activity") or {}
    indoor_vt1 = brief.get("indoor_vt1_quality") or {}
    vt2 = brief.get("vt2_quality") or {}
    best_vt2 = vt2.get("best_duration_block") or {}
    total = brief.get("total") or {}
    beta = brief.get("beta_summary") or {}
    return {
        "activity_dir": str(activity_dir),
        "id": activity.get("id"),
        "date": str(activity.get("start_date_local") or "")[:10],
        "name": activity.get("name"),
        "duration_min": activity.get("duration_min"),
        "moving_min": activity.get("moving_min"),
        "training_load": activity.get("icu_training_load"),
        "intensity": activity.get("icu_intensity"),
        "total_avg_w": total.get("watts_avg"),
        "total_hr_avg": total.get("hr_avg"),
        "total_ve_avg": total.get("ve_avg"),
        "core_temp_max": total.get("core_temp_max"),
        "beta_category": beta.get("category"),
        "beta_status": beta.get("status"),
        "vt1": summarize_indoor_vt1(indoor_vt1),
        "vt2": summarize_vt2(vt2, best_vt2),
        "quality_label": quality_label(indoor_vt1, best_vt2, beta),
    }


def summarize_indoor_vt1(indoor_vt1: dict[str, Any]) -> dict[str, Any] | None:
    if not indoor_vt1 or indoor_vt1.get("error"):
        return None
    assessment = indoor_vt1.get("assessment") or {}
    drift = indoor_vt1.get("drift") or {}
    duration = indoor_vt1.get("duration") or {}
    power = indoor_vt1.get("power_control") or {}
    return {
        "rating": assessment.get("rating"),
        "verdict": assessment.get("verdict"),
        "score": assessment.get("score"),
        "limiter_hints": assessment.get("limiter_hints") or [],
        "pedaling_min": duration.get("pedaling_min"),
        "avg_w": power.get("avg_w"),
        "pct_within_vt1_10w": power.get("pct_within_vt1_10w"),
        "hr_per_w_delta_pct": drift.get("hr_per_w_delta_pct"),
        "ve_per_w_delta_pct": drift.get("ve_per_w_delta_pct"),
        "br_per_w_delta_pct": drift.get("br_per_w_delta_pct"),
        "core_temp_delta_c": drift.get("core_temp_delta_c"),
    }


def summarize_vt2(vt2: dict[str, Any], best: dict[str, Any]) -> dict[str, Any] | None:
    if not vt2:
        return None
    physiology = best.get("physiology") or {}
    controlled_blocks = controlled_vt2_blocks(vt2.get("blocks") or [])
    return {
        "verdict": best.get("verdict"),
        "rating": best.get("rating"),
        "duration_s": best.get("duration_s"),
        "controlled_reps": len(controlled_blocks),
        "controlled_duration_s": sum(float(block.get("duration_s") or 0) for block in controlled_blocks),
        "watts_avg": best.get("watts_avg"),
        "execution_score": best.get("execution_score"),
        "response_score": best.get("response_score"),
        "heat_adjusted_response_score": best.get("heat_adjusted_response_score"),
        "recovery_score": best.get("recovery_score"),
        "combined_score": best.get("combined_score"),
        "heat_penalty_points": physiology.get("heat_penalty_points"),
        "limiter_hints": best.get("limiter_hints") or [],
    }


def controlled_vt2_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    controlled_verdicts = {
        "controlled_vt2",
        "controlled_high_cost_vt2",
        "heat_limited_controlled_vt2",
        "near_upper_control_limit",
    }
    return [
        block
        for block in blocks
        if block.get("verdict") in controlled_verdicts and float(block.get("duration_s") or 0) >= 7.5 * 60
    ]


def quality_label(indoor_vt1: dict[str, Any], best_vt2: dict[str, Any], beta: dict[str, Any]) -> str:
    vt2_verdict = best_vt2.get("verdict")
    if vt2_verdict:
        return str(vt2_verdict)
    assessment = indoor_vt1.get("assessment") or {}
    rating = assessment.get("rating")
    if rating:
        return f"indoor_vt1_{rating}"
    return str(beta.get("category") or "unscored")


def summarize_year(results: list[dict[str, Any]], year: int, errors: list[dict[str, Any]]) -> dict[str, Any]:
    vt1_rows = [item for item in results if item.get("vt1")]
    vt2_rows = [item for item in results if item.get("vt2")]
    controlled_vt2_rows = [item for item in vt2_rows if is_controlled_vt2_row(item)]
    return {
        "overview": {
            "year": year,
            "indoor_activities": len(results),
            "errors": len(errors),
            "date_start": results[0]["date"] if results else None,
            "date_end": results[-1]["date"] if results else None,
        },
        "rankings": {
            "best_indoor_vt1": sorted(vt1_rows, key=lambda item: vt1_sort_key(item), reverse=True)[:15],
            "best_vt2_control": sorted(
                controlled_vt2_rows,
                key=lambda item: item["vt2"].get("combined_score") or 0,
                reverse=True,
            )[:15],
        },
        "activities": results,
        "errors": errors,
    }


def is_controlled_vt2_row(item: dict[str, Any]) -> bool:
    vt2 = item.get("vt2") or {}
    verdict = vt2.get("verdict")
    if verdict not in {
        "controlled_vt2",
        "controlled_high_cost_vt2",
        "heat_limited_controlled_vt2",
        "near_upper_control_limit",
    }:
        return False
    if float(vt2.get("execution_score") or 0) < 65:
        return False
    if float(vt2.get("duration_s") or 0) < 8 * 60:
        return False
    return True


def vt1_sort_key(item: dict[str, Any]) -> tuple[float, float, float]:
    vt1 = item.get("vt1") or {}
    rating_order = {"A": 5, "A-": 4, "B": 3, "C": 2, "D": 1}
    return (
        rating_order.get(str(vt1.get("rating")), 0),
        float(vt1.get("pedaling_min") or 0),
        float(vt1.get("pct_within_vt1_10w") or 0),
    )


def render_markdown(summary: dict[str, Any]) -> str:
    overview = summary["overview"]
    lines = [
        f"# Inneokter {overview['year']}",
        "",
        (
            f"Kilde: {overview['indoor_activities']} lokale indoor Ride/VirtualRide-aktiviteter "
            f"fra {overview['date_start']} til {overview['date_end']}. Failures: {overview['errors']}."
        ),
        "",
        "## Beste indoor VT1",
        render_vt1_rows(summary["rankings"]["best_indoor_vt1"]),
        "",
        "## Beste indoor VT2",
        render_vt2_rows(summary["rankings"]["best_vt2_control"]),
        "",
        "## Alle inneokter",
        render_all_rows(summary["activities"]),
    ]
    if summary["errors"]:
        lines.extend(["", "## Errors", "```json", json.dumps(summary["errors"], indent=2), "```"])
    return "\n".join(lines) + "\n"


def render_vt1_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_Ingen._"
    header = "| Dato | Okt | Min | Rating | Avg W | Inom 10W | HR/W | VE/W | Hint |"
    sep = "|---|---|---:|---:|---:|---:|---:|---:|---|"
    body = []
    for row in rows:
        vt1 = row.get("vt1") or {}
        body.append(
            "| {date} | {name} | {mins} | {rating} | {watts} | {within} | {hr} | {ve} | {hint} |".format(
                date=row["date"],
                name=escape_pipe(row["name"]),
                mins=fmt(vt1.get("pedaling_min")),
                rating=escape_pipe(vt1.get("rating")),
                watts=fmt(vt1.get("avg_w")),
                within=fmt(vt1.get("pct_within_vt1_10w")),
                hr=fmt(vt1.get("hr_per_w_delta_pct")),
                ve=fmt(vt1.get("ve_per_w_delta_pct")),
                hint=escape_pipe(",".join(vt1.get("limiter_hints") or [])),
            )
        )
    return "\n".join([header, sep, *body])


def render_vt2_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_Ingen._"
    header = "| Dato | Okt | Terskel | Reps | VT2 | Watt | Score | Exec | Resp | Heat |"
    sep = "|---|---|---:|---:|---|---:|---:|---:|---:|---:|"
    body = []
    for row in rows:
        vt2 = row.get("vt2") or {}
        body.append(
            "| {date} | {name} | {threshold} | {reps} | {verdict} | {watts} | {score} | {exec} | {resp} | {heat} |".format(
                date=row["date"],
                name=escape_pipe(row["name"]),
                threshold=fmt_minutes(vt2.get("controlled_duration_s")),
                reps=fmt(vt2.get("controlled_reps")),
                verdict=escape_pipe(vt2.get("verdict")),
                watts=fmt(vt2.get("watts_avg")),
                score=fmt(vt2.get("combined_score")),
                exec=fmt(vt2.get("execution_score")),
                resp=fmt(vt2.get("response_score")),
                heat=fmt(vt2.get("heat_penalty_points")),
            )
        )
    return "\n".join([header, sep, *body])


def render_all_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_Ingen._"
    header = "| Dato | Okt | Min | TL | Kategori | VT1 | VT2 |"
    sep = "|---|---|---:|---:|---|---|---|"
    body = []
    for row in rows:
        vt1 = row.get("vt1") or {}
        vt2 = row.get("vt2") or {}
        body.append(
            "| {date} | {name} | {mins} | {tl} | {cat} | {vt1} | {vt2} |".format(
                date=row["date"],
                name=escape_pipe(row["name"]),
                mins=fmt(row.get("moving_min")),
                tl=fmt(row.get("training_load")),
                cat=escape_pipe(row.get("beta_category")),
                vt1=escape_pipe(vt1.get("rating") or ""),
                vt2=escape_pipe(vt2.get("verdict") or ""),
            )
        )
    return "\n".join([header, sep, *body])


def fmt(value_: Any) -> str:
    if isinstance(value_, float):
        return f"{value_:.1f}"
    if isinstance(value_, int):
        return str(value_)
    return ""


def fmt_minutes(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return ""
    return f"{seconds / 60:.1f}"


def escape_pipe(value_: Any) -> str:
    return str(value_ or "").replace("|", "\\|")


if __name__ == "__main__":
    main()
