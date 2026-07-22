#!/usr/bin/env python3
"""Analyze saved outdoor cycling activities for one calendar year."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from analysis import ARTIFACTS_DIR, load_activity_metadata, load_streams_csv, value


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze saved outdoor rides for a year.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--vt1-watts", type=float, default=210.0)
    parser.add_argument("--output-dir", default="outputs/activity-inspect")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=240, help="Seconds per activity inspection")
    args = parser.parse_args()

    activities = outdoor_activity_dirs(args.year)
    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                inspect_and_summarize,
                activity_dir,
                vt1_watts=args.vt1_watts,
                timeout=args.timeout,
            ): activity_dir
            for activity_dir in activities
        }
        for future in as_completed(futures):
            activity_dir = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - command-line report should continue.
                errors.append({"activity_dir": str(activity_dir), "error": str(exc)})
    results.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("name") or "")))
    results, duplicates = deduplicate_results(results)

    summary = summarize_year(results, args.year, errors, duplicates)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"outdoor_{args.year}_analysis.json"
    md_path = output_dir / f"outdoor_{args.year}_analysis.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), **summary["overview"]}, indent=2))


def outdoor_activity_dirs(year: int) -> list[Path]:
    activities_dir = ARTIFACTS_DIR / "activities"
    candidates = []
    for activity_dir in sorted(activities_dir.glob(f"{year}-*")):
        if not (activity_dir / "activity.json").exists() or not (activity_dir / "streams.csv").exists():
            continue
        metadata = load_activity_metadata(activity_dir)
        if not is_outdoor_ride(metadata, activity_dir):
            continue
        candidates.append(activity_dir)
    return sorted(
        candidates,
        key=lambda path: str(load_activity_metadata(path).get("start_date_local") or path.name),
    )


def is_outdoor_ride(metadata: dict[str, Any], activity_dir: Path) -> bool:
    if metadata.get("trainer") is True:
        return False
    if str(metadata.get("type") or "").lower() != "ride":
        return False
    stream_types = metadata.get("stream_types") or []
    if isinstance(stream_types, list) and any(str(item).lower() in {"latlng", "lat", "lng"} for item in stream_types):
        return True
    rows = load_streams_csv(activity_dir / "streams.csv")
    gps_rows = 0
    for row in rows:
        if value(row, "lat") is None or value(row, "lng") is None:
            continue
        gps_rows += 1
        if gps_rows >= 60:
            return True
    return False


def inspect_and_summarize(activity_dir: Path, *, vt1_watts: float, timeout: int) -> dict[str, Any]:
    brief = inspect_activity(activity_dir, vt1_watts=vt1_watts, timeout=timeout)
    return summarize_activity(activity_dir, brief)


def inspect_activity(activity_dir: Path, *, vt1_watts: float, timeout: int) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        "scripts/activity_inspect.py",
        str(activity_dir),
        "--brief",
        "--stdout",
        "--auto-blocks",
        "--outdoor-vt1",
        "--vt1-watts",
        str(vt1_watts),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    return json.loads(completed.stdout)


def summarize_activity(activity_dir: Path, brief: dict[str, Any]) -> dict[str, Any]:
    activity = brief.get("activity") or {}
    vt1 = brief.get("outdoor_vt1_pacing") or {}
    vt1_scores = vt1.get("quality_scores") or {}
    vt1_best = (vt1.get("experimental_metrics") or {}).get("best_continuous_vt1_blocks") or {}
    vt2 = brief.get("vt2_quality") or {}
    best_vt2 = vt2.get("best_duration_block") or {}
    total = brief.get("total") or {}
    key_efforts = brief.get("key_efforts") or {}
    moving_min = activity.get("moving_min")
    vt1_summary = summarize_vt1(vt1, vt1_scores, vt1_best)
    vt2_summary = summarize_vt2(vt2, best_vt2)

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
        "best_20m_w": (key_efforts.get("best_20m_power") or {}).get("avg"),
        "vt1": vt1_summary,
        "vt2": vt2_summary,
        "quality_label": quality_label(activity.get("name"), moving_min, vt1_summary, vt2_summary or {}),
    }


def summarize_vt1(
    vt1: dict[str, Any],
    scores: dict[str, Any],
    best_blocks: dict[str, Any],
) -> dict[str, Any]:
    best_by_duration = best_blocks.get("best_by_duration") or []
    best60 = next((block for block in best_by_duration if block.get("duration_min") == 60), None)
    best90 = next((block for block in best_by_duration if block.get("duration_min") == 90), None)
    characterization = vt1.get("training_characterization") or {}
    return {
        "assessment": (vt1.get("assessment") or {}).get("verdict"),
        "characterization": {
            "summary": characterization.get("summary"),
            "stimulus": characterization.get("stimulus"),
            "strict_vt1_fit": characterization.get("strict_vt1_fit"),
            "physiological_response": characterization.get("physiological_response"),
            "climb_moving_min": characterization.get("climb_moving_min"),
            "climb_moving_pct": characterization.get("climb_moving_pct"),
        },
        "rating": scores.get("rating"),
        "combined_score": scores.get("combined_score"),
        "execution_score": scores.get("execution_score"),
        "response_score": scores.get("response_score"),
        "session_value_score": scores.get("session_value_score"),
        "pedaling_min": ((vt1.get("duration") or {}).get("pedaling_min")),
        "best60": compact_best_block(best60),
        "best90": compact_best_block(best90),
    }


def compact_best_block(block: dict[str, Any] | None) -> dict[str, Any] | None:
    if not block:
        return None
    return {
        "combined_score": block.get("combined_score"),
        "rating": block.get("rating"),
        "control_score": block.get("control_score"),
        "session_value_score": block.get("session_value_score"),
        "pedaling_avg_w": block.get("pedaling_avg_w"),
        "start_min": block.get("start_min"),
        "end_min": block.get("end_min"),
        "hr_per_w_delta_pct": block.get("matched_hr_per_w_delta_pct"),
        "ve_per_w_delta_pct": block.get("matched_ve_per_w_delta_pct"),
    }


def summarize_vt2(vt2: dict[str, Any], best: dict[str, Any]) -> dict[str, Any] | None:
    if not vt2:
        return None
    physiology = best.get("physiology") or {}
    return {
        "verdict": best.get("verdict"),
        "rating": best.get("rating"),
        "duration_s": best.get("duration_s"),
        "watts_avg": best.get("watts_avg"),
        "execution_score": best.get("execution_score"),
        "response_score": best.get("response_score"),
        "heat_adjusted_response_score": best.get("heat_adjusted_response_score"),
        "recovery_score": best.get("recovery_score"),
        "combined_score": best.get("combined_score"),
        "heat_penalty_points": physiology.get("heat_penalty_points"),
        "limiter_hints": best.get("limiter_hints") or [],
    }


def quality_label(
    activity_name: Any,
    moving_min: Any,
    vt1_scores: dict[str, Any],
    best_vt2: dict[str, Any],
) -> str:
    if isinstance(moving_min, (int, float)) and moving_min < 30:
        return "short_or_unscored"
    vt2_verdict = best_vt2.get("verdict")
    if vt2_verdict and activity_name_implies_threshold(activity_name):
        return str(vt2_verdict)
    characterization = vt1_scores.get("characterization") or {}
    summary = characterization.get("summary")
    if summary:
        return str(summary)
    rating = vt1_scores.get("rating")
    if rating:
        return f"vt1_{rating}"
    return "unscored"


def activity_name_implies_threshold(activity_name: Any) -> bool:
    name = str(activity_name or "").lower().replace("₂", "2")
    threshold_tokens = (
        "vt2",
        "terskel",
        "threshold",
        "tryvann",
        "klatring",
        "climb",
        "bakke",
    )
    return any(token in name for token in threshold_tokens)


def deduplicate_results(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for item in results:
        moving_min = item.get("moving_min") if isinstance(item.get("moving_min"), (int, float)) else 0
        key = (
            str(item.get("date") or ""),
            str(item.get("name") or ""),
            round(moving_min / 2) * 2,
        )
        groups.setdefault(key, []).append(item)

    kept: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for group in groups.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        winner = max(group, key=dedupe_preference)
        kept.append(winner)
        duplicates.append(
            {
                "kept_id": winner.get("id"),
                "date": winner.get("date"),
                "name": winner.get("name"),
                "removed": [
                    {
                        "id": item.get("id"),
                        "moving_min": item.get("moving_min"),
                        "training_load": item.get("training_load"),
                        "intensity": item.get("intensity"),
                    }
                    for item in group
                    if item is not winner
                ],
            }
        )
    return sorted(kept, key=lambda item: (str(item.get("date") or ""), str(item.get("name") or ""))), duplicates


def dedupe_preference(item: dict[str, Any]) -> tuple[float, float, float, str]:
    moving_min = item.get("moving_min") if isinstance(item.get("moving_min"), (int, float)) else 0
    training_load = item.get("training_load") if isinstance(item.get("training_load"), (int, float)) else 0
    best20 = item.get("best_20m_w") if isinstance(item.get("best_20m_w"), (int, float)) else 0
    return (moving_min, training_load, best20, str(item.get("id") or ""))


def summarize_year(
    results: list[dict[str, Any]],
    year: int,
    errors: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
) -> dict[str, Any]:
    vt1_rankable = [
        item
        for item in results
        if isinstance((item.get("vt1") or {}).get("combined_score"), (int, float))
        and isinstance(item.get("moving_min"), (int, float))
        and item["moving_min"] >= 30
    ]
    ranked_vt1 = sorted(
        vt1_rankable,
        key=lambda item: (item["vt1"].get("combined_score") or 0, item["vt1"].get("session_value_score") or 0),
        reverse=True,
    )
    useful_endurance = sorted(
        [
            item
            for item in vt1_rankable
            if (item.get("vt1") or {}).get("characterization", {}).get("summary")
            == "not_strict_vt1_but_useful_endurance"
        ],
        key=lambda item: (
            item["vt1"].get("session_value_score") or 0,
            item["vt1"].get("response_score") or 0,
            item.get("moving_min") or 0,
        ),
        reverse=True,
    )
    poor_response = sorted(
        [
            item
            for item in vt1_rankable
            if isinstance((item.get("vt1") or {}).get("response_score"), (int, float))
            and item["vt1"]["response_score"] < 65
        ],
        key=lambda item: item["vt1"].get("response_score") or 0,
    )
    ranked_vt2 = sorted(
        [item for item in results if item.get("vt2")],
        key=lambda item: item["vt2"].get("combined_score") or 0,
        reverse=True,
    )
    heat_limited = [
        item for item in results if item.get("vt2") and item["vt2"].get("verdict") == "heat_limited_controlled_vt2"
    ]
    return {
        "overview": {
            "year": year,
            "outdoor_activities": len(results),
            "duplicates_removed": sum(len(item.get("removed") or []) for item in duplicates),
            "errors": len(errors),
            "date_start": results[0]["date"] if results else None,
            "date_end": results[-1]["date"] if results else None,
        },
        "rankings": {
            "best_vt1_overall": ranked_vt1[:10],
            "best_vt1_60min": sorted(
                [item for item in results if (item.get("vt1") or {}).get("best60")],
                key=lambda item: item["vt1"]["best60"].get("combined_score") or 0,
                reverse=True,
            )[:10],
            "useful_endurance_not_strict_vt1": useful_endurance[:10],
            "poor_physiological_response": poor_response[:10],
            "best_vt2_control": ranked_vt2[:10],
            "heat_limited_vt2": heat_limited,
        },
        "activities": results,
        "duplicates": duplicates,
        "errors": errors,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    overview = summary["overview"]
    lines = [
        f"# Uteokter {overview['year']}",
        "",
        (
            f"Kilde: {overview['outdoor_activities']} lokale outdoor Ride-aktiviteter "
            f"fra {overview['date_start']} til {overview['date_end']}. "
            f"Duplikater fjernet: {overview.get('duplicates_removed', 0)}. "
            f"Failures: {overview['errors']}."
        ),
        "",
        "## Beste VT1-kontroll samlet",
        render_rows(summary["rankings"]["best_vt1_overall"], mode="vt1"),
        "",
        "## Beste 60 min VT1-vinduer",
        render_rows(summary["rankings"]["best_vt1_60min"], mode="vt1_60"),
        "",
        "## Nyttig endurance, men ikke streng VT1",
        render_rows(summary["rankings"]["useful_endurance_not_strict_vt1"], mode="useful_endurance"),
        "",
        "## Svak fysiologisk respons",
        render_rows(summary["rankings"]["poor_physiological_response"], mode="all"),
        "",
        "## Beste VT2/threshold-kontroll",
        render_rows(summary["rankings"]["best_vt2_control"], mode="vt2"),
        "",
        "## Alle uteokter",
        render_rows(summary["activities"], mode="all"),
    ]
    if summary["errors"]:
        lines.extend(["", "## Errors", "```json", json.dumps(summary["errors"], indent=2), "```"])
    if summary.get("duplicates"):
        lines.extend(["", "## Duplikater fjernet", "```json", json.dumps(summary["duplicates"], indent=2), "```"])
    return "\n".join(lines) + "\n"


def render_rows(rows: list[dict[str, Any]], *, mode: str) -> str:
    if not rows:
        return "_Ingen._"
    if mode == "vt2":
        header = "| Dato | Okt | VT2 | Watt | Score | Exec | Resp | Heat |"
        sep = "|---|---|---:|---:|---:|---:|---:|---:|"
        body = [
            "| {date} | {name} | {verdict} | {watts} | {score} | {exec} | {resp} | {heat} |".format(
                date=row["date"],
                name=escape_pipe(row["name"]),
                verdict=escape_pipe((row.get("vt2") or {}).get("verdict")),
                watts=fmt((row.get("vt2") or {}).get("watts_avg")),
                score=fmt((row.get("vt2") or {}).get("combined_score")),
                exec=fmt((row.get("vt2") or {}).get("execution_score")),
                resp=fmt((row.get("vt2") or {}).get("response_score")),
                heat=fmt((row.get("vt2") or {}).get("heat_penalty_points")),
            )
            for row in rows
        ]
        return "\n".join([header, sep, *body])

    header = "| Dato | Okt | Min | TL | VT1 score | Exec | Resp | Stimulus | 60min | VT2 |"
    sep = "|---|---|---:|---:|---:|---:|---:|---|---:|---|"
    body = []
    for row in rows:
        vt1 = row.get("vt1") or {}
        characterization = vt1.get("characterization") or {}
        best60 = vt1.get("best60") or {}
        vt2 = row.get("vt2") or {}
        body.append(
            "| {date} | {name} | {mins} | {tl} | {score} | {exec} | {resp} | {stimulus} | {best60} | {vt2} |".format(
                date=row["date"],
                name=escape_pipe(row["name"]),
                mins=fmt(row.get("moving_min")),
                tl=fmt(row.get("training_load")),
                score=fmt(vt1.get("combined_score")),
                exec=fmt(vt1.get("execution_score")),
                resp=fmt(vt1.get("response_score")),
                stimulus=escape_pipe(characterization.get("summary") or characterization.get("stimulus") or ""),
                best60=fmt(best60.get("combined_score")),
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


def escape_pipe(value_: Any) -> str:
    return str(value_ or "").replace("|", "\\|")


if __name__ == "__main__":
    main()
