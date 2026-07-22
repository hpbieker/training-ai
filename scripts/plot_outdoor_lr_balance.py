#!/usr/bin/env python3
"""Plot average left/right balance for saved outdoor rides."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis import ARTIFACTS_DIR, load_activity_metadata
from analyze_outdoor_year import is_outdoor_ride


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot avg left/right balance for outdoor rides.")
    parser.add_argument("--since", help="Start date, YYYY-MM-DD")
    parser.add_argument("--until", help="End date, YYYY-MM-DD")
    parser.add_argument("--output", default="outputs/plots/outdoor_lr_balance.png")
    parser.add_argument("--csv", default="outputs/plots/outdoor_lr_balance.csv")
    parser.add_argument("--excluded-csv", default="outputs/plots/outdoor_lr_balance_excluded.csv")
    parser.add_argument("--rolling", type=int, default=10, help="Rolling session count")
    parser.add_argument("--min-left-pct", type=float, default=35.0)
    parser.add_argument("--max-left-pct", type=float, default=65.0)
    args = parser.parse_args()

    rows, excluded, duplicates_removed = collect_rows(
        since=args.since,
        until=args.until,
        min_left_pct=args.min_left_pct,
        max_left_pct=args.max_left_pct,
    )
    if not rows:
        raise SystemExit("No outdoor rides with avg_lr_balance found.")

    output_path = Path(args.output)
    csv_path = Path(args.csv)
    excluded_csv_path = Path(args.excluded_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    excluded_csv_path.parent.mkdir(parents=True, exist_ok=True)

    write_csv(rows, csv_path)
    write_csv(excluded, excluded_csv_path)
    plot_rows(rows, output_path, rolling=max(1, args.rolling))

    summary = {
        "activities": len(rows),
        "date_start": rows[0]["date"],
        "date_end": rows[-1]["date"],
        "avg_left_pct": round(mean(row["avg_lr_balance"] for row in rows), 2),
        "min_left_pct": round(min(row["avg_lr_balance"] for row in rows), 2),
        "max_left_pct": round(max(row["avg_lr_balance"] for row in rows), 2),
        "excluded_outliers": len(excluded),
        "duplicates_removed": duplicates_removed,
        "power_meter_periods": power_meter_periods(rows),
        "plot": str(output_path.resolve()),
        "csv": str(csv_path.resolve()),
        "excluded_csv": str(excluded_csv_path.resolve()),
    }
    print(summary)


def collect_rows(
    *,
    since: str | None,
    until: str | None,
    min_left_pct: float,
    max_left_pct: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    activities_dir = ARTIFACTS_DIR / "activities"
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for activity_json in sorted(activities_dir.glob("*/activity.json")):
        activity_dir = activity_json.parent
        metadata = load_activity_metadata(activity_dir)
        date = str(metadata.get("start_date_local") or "")[:10]
        if since and date < since:
            continue
        if until and date > until:
            continue
        if not is_outdoor_ride(metadata, activity_dir):
            continue
        balance = metadata.get("avg_lr_balance")
        if balance is None:
            continue
        row = {
            "date": date,
            "datetime": parse_datetime(metadata.get("start_date_local"), date),
            "id": metadata.get("id"),
            "name": metadata.get("name"),
            "type": metadata.get("type"),
            "trainer": metadata.get("trainer"),
            "duration_min": round(float(metadata.get("elapsed_time") or 0) / 60, 1),
            "moving_min": round(float(metadata.get("moving_time") or metadata.get("elapsed_time") or 0) / 60, 1),
            "training_load": metadata.get("icu_training_load"),
            "avg_lr_balance": float(balance),
            "right_pct": 100.0 - float(balance),
            "left_minus_right_pct": 2 * float(balance) - 100.0,
            "power_meter": metadata.get("power_meter"),
            "power_meter_serial": metadata.get("power_meter_serial"),
            "power_meter_label": power_meter_label(metadata),
            "source": metadata.get("source"),
        }
        candidates.append(row)

    candidates, duplicates_removed = dedupe_rows(candidates)
    rows: list[dict[str, Any]] = []
    for row in candidates:
        if min_left_pct <= row["avg_lr_balance"] <= max_left_pct:
            rows.append(row)
        else:
            excluded.append(row)
    return (
        sorted(rows, key=lambda row: (row["datetime"], str(row.get("id") or ""))),
        sorted(excluded, key=lambda row: (row["datetime"], str(row.get("id") or ""))),
        duplicates_removed,
    )


def dedupe_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("date") or ""),
            str(row.get("name") or ""),
            round(float(row.get("moving_min") or 0) / 2) * 2,
        )
        groups.setdefault(key, []).append(row)

    kept: list[dict[str, Any]] = []
    removed = 0
    for group in groups.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        kept.append(max(group, key=dedupe_preference))
        removed += len(group) - 1
    return kept, removed


def dedupe_preference(row: dict[str, Any]) -> tuple[int, int, float, float, str]:
    known_power_meter = 0 if row.get("power_meter_label") == "Unknown" else 1
    garmin_source = 1 if row.get("source") == "GARMIN_CONNECT" else 0
    moving_min = float(row.get("moving_min") or 0)
    training_load = float(row.get("training_load") or 0)
    return (known_power_meter, garmin_source, moving_min, training_load, str(row.get("id") or ""))


def power_meter_label(metadata: dict[str, Any]) -> str:
    power_meter = metadata.get("power_meter")
    serial = metadata.get("power_meter_serial")
    if not power_meter:
        return "Unknown"
    name = str(power_meter).replace("_", " ").replace("ELECTRONICS", "").strip()
    name = " ".join(name.split())
    return f"{name} {serial}" if serial else name


def parse_datetime(value: Any, fallback_date: str) -> datetime:
    text = str(value or "")
    if text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.fromisoformat(fallback_date)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "date",
        "id",
        "name",
        "type",
        "trainer",
        "duration_min",
        "moving_min",
        "training_load",
        "avg_lr_balance",
        "right_pct",
        "left_minus_right_pct",
        "power_meter",
        "power_meter_serial",
        "power_meter_label",
        "source",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def plot_rows(rows: list[dict[str, Any]], path: Path, *, rolling: int) -> None:
    dates = [row["datetime"] for row in rows]
    balances = [row["avg_lr_balance"] for row in rows]
    rolling_values = [
        mean(balances[max(0, index - rolling + 1) : index + 1])
        for index in range(len(balances))
    ]

    fig, axis = plt.subplots(figsize=(13, 6.5), constrained_layout=True)
    palette = ["#2c7fb8", "#7b3294", "#008837", "#b35806", "#7570b3", "#1b9e77"]
    labels = sorted({str(row.get("power_meter_label") or "Unknown") for row in rows})
    colors = {label: palette[index % len(palette)] for index, label in enumerate(labels)}
    for label in labels:
        group = [row for row in rows if str(row.get("power_meter_label") or "Unknown") == label]
        axis.scatter(
            [row["datetime"] for row in group],
            [row["avg_lr_balance"] for row in group],
            s=34,
            color=colors[label],
            alpha=0.75,
            label=label,
        )
    axis.plot(dates, rolling_values, color="#d95f02", linewidth=2.2, label=f"{rolling}-okters snitt")
    axis.axhline(50, color="#303030", linewidth=1.1, linestyle="--", label="50/50")

    avg = mean(balances)
    axis.axhline(avg, color="#4d9221", linewidth=1.4, alpha=0.85, label=f"Snitt {avg:.1f}% venstre")
    mark_power_meter_changes(axis, rows)

    margin = max(1.0, min(8.0, (max(balances) - min(balances)) * 0.25))
    axis.set_ylim(min(balances) - margin, max(balances) + margin)
    axis.set_title("Snitt r/l-balanse for uteokter")
    axis.set_ylabel("Venstre side av kraft (%)")
    axis.set_xlabel("Dato")
    axis.grid(alpha=0.25)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.legend(loc="best")

    fig.autofmt_xdate()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def mark_power_meter_changes(axis: Any, rows: list[dict[str, Any]]) -> None:
    last_label = None
    for row in rows:
        label = str(row.get("power_meter_label") or "Unknown")
        if label == "Unknown":
            continue
        if last_label is None:
            last_label = label
            continue
        if label == last_label:
            continue
        axis.axvline(row["datetime"], color="#8c510a", linewidth=1.4, linestyle=":", alpha=0.9)
        axis.annotate(
            label,
            xy=(row["datetime"], row["avg_lr_balance"]),
            xytext=(8, 24),
            textcoords="offset points",
            rotation=90,
            va="bottom",
            ha="left",
            fontsize=8,
            color="#5c3b09",
        )
        last_label = label


def power_meter_periods(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        label = str(row.get("power_meter_label") or "Unknown")
        if current is None or current["power_meter_label"] != label:
            if current is not None:
                periods.append(finalize_period(current))
            current = {
                "power_meter_label": label,
                "date_start": row["date"],
                "date_end": row["date"],
                "values": [row["avg_lr_balance"]],
            }
        else:
            current["date_end"] = row["date"]
            current["values"].append(row["avg_lr_balance"])
    if current is not None:
        periods.append(finalize_period(current))
    return periods


def finalize_period(period: dict[str, Any]) -> dict[str, Any]:
    values = period.pop("values")
    period["activities"] = len(values)
    period["avg_left_pct"] = round(mean(values), 2)
    return period


if __name__ == "__main__":
    main()
