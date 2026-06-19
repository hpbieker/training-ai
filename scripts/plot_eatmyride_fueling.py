#!/usr/bin/env python3
"""Plot EatMyRide glycogen/energy estimates with food-plan events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
from matplotlib.lines import Line2D


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot an EatMyRide activity's energy graph and food plan from local JSON files.",
    )
    parser.add_argument(
        "activity_dir",
        help=(
            "Path to a local directory containing activity.json and foodplan.json"
        ),
    )
    parser.add_argument("--output", help="Output image path")
    parser.add_argument("--config", type=Path, help="JSON plot configuration file")
    parser.add_argument("--title", help="Plot title override")
    parser.add_argument(
        "--label-min-carbs",
        type=float,
        default=20.0,
        help="Label fueling events with at least this many carbohydrate grams",
    )
    parser.add_argument(
        "--y-axis",
        choices=["carbs", "kcal"],
        default="carbs",
        help="Y-axis units for EatMyRide energy graph values. 'carbs' plots kcal-equivalent values as grams carbohydrate.",
    )
    parser.add_argument(
        "--curve-kcal-per-gram",
        type=float,
        default=4.0,
        help=(
            "Kcal-equivalent divisor for the plotted glycogen curve when --y-axis carbs. "
            "EatMyRide's UI has been observed to show caloriesThreshold / 4 as grams."
        ),
    )
    parser.add_argument(
        "--summary-kcal-per-gram",
        type=float,
        default=4.0,
        help="Kcal-equivalent divisor for summary depletion/final values when --y-axis carbs.",
    )
    parser.add_argument(
        "--hide-fueling",
        action="store_true",
        help="Hide food and drink markers from the food plan.",
    )
    parser.add_argument(
        "--high-risk-ratio",
        type=float,
        default=0.60,
        help="Lower zone boundary as a fraction of caloriesThreshold. EatMyRide only exposes the upper threshold.",
    )
    args = parser.parse_args()
    config = load_config(args.config)

    activity_dir = resolve_activity_dir(args.activity_dir)
    output = Path(args.output) if args.output else default_output_path(activity_dir)
    output.parent.mkdir(parents=True, exist_ok=True)

    plot_eatmyride_fueling(
        activity_dir,
        output=output,
        title=args.title or config.get("title"),
        label_min_carbs=float(config.get("label_min_carbs", args.label_min_carbs)),
        y_axis=str(config.get("y_axis", args.y_axis)),
        show_fueling=not args.hide_fueling,
        high_risk_ratio=float(config.get("high_risk_ratio", args.high_risk_ratio)),
        curve_kcal_per_gram=float(config.get("curve_kcal_per_gram", args.curve_kcal_per_gram)),
        summary_kcal_per_gram=float(config.get("summary_kcal_per_gram", args.summary_kcal_per_gram)),
    )
    print(output.resolve())


def resolve_activity_dir(ref: str) -> Path:
    candidate = Path(ref)
    if (candidate / "activity.json").exists() and (candidate / "foodplan.json").exists():
        return candidate
    raise SystemExit(
        "Expected a directory containing EatMyRide activity.json and foodplan.json: "
        f"{ref}"
    )


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SystemExit(f"Expected plot config to be a JSON object: {path}")
    return config


def plot_eatmyride_fueling(
    activity_dir: Path,
    *,
    output: Path,
    title: str | None = None,
    label_min_carbs: float = 20.0,
    y_axis: str = "carbs",
    show_fueling: bool = False,
    high_risk_ratio: float = 0.60,
    curve_kcal_per_gram: float = 4.8,
    summary_kcal_per_gram: float = 4.0,
) -> None:
    activity = json.loads((activity_dir / "activity.json").read_text(encoding="utf-8"))
    foodplan = json.loads((activity_dir / "foodplan.json").read_text(encoding="utf-8"))
    energy = activity.get("energyGraph", {}).get("energy", {})
    times = energy.get("time") or []
    glycogen_raw = energy.get("glycogen") or []
    if not times or not glycogen_raw:
        raise SystemExit(f"{activity_dir} does not contain energyGraph.energy time/glycogen data")

    duration = float(activity.get("duration") or max(times))
    hours = [float(seconds) / 3600 for seconds in times]
    curve_factor = curve_kcal_per_gram if y_axis == "carbs" else 1.0
    summary_factor = summary_kcal_per_gram if y_axis == "carbs" else 1.0
    glycogen = [float(value) / curve_factor for value in glycogen_raw]
    summary_glycogen = [float(value) / summary_factor for value in glycogen_raw]
    threshold = scaled_number(activity.get("caloriesThreshold"), curve_factor)
    start = scaled_number(activity.get("caloriesStart"), curve_factor)
    y_label = "g" if y_axis == "carbs" else "kcal"
    high_risk = None
    if threshold is not None:
        high_risk = threshold * high_risk_ratio

    fig, axis = plt.subplots(figsize=(10, 8), dpi=170)
    fig.patch.set_facecolor("#f6f6f6")
    axis.set_facecolor("white")

    y_max = nice_axis_max(max(glycogen + ([start] if start is not None else [])))
    if y_axis == "carbs" and threshold is not None and high_risk is not None:
        axis.axhspan(0, high_risk, color="#f8dede", alpha=0.70, linewidth=0)
        axis.axhspan(high_risk, threshold, color="#fdebcf", alpha=0.85, linewidth=0)
        axis.axhspan(threshold, y_max, color="#e9faeb", alpha=0.90, linewidth=0)
        axis.text(0, threshold + 0.012 * y_max, "Optimal", color="#66cc33", fontsize=14, va="bottom")
        axis.text(0, high_risk + 0.012 * y_max, "Sub-optimal", color="#e9801d", fontsize=14, va="bottom")
        axis.text(0, 0.02 * y_max, "High risk", color="#d62222", fontsize=14, va="bottom")

    axis.plot(hours, glycogen, color="#66cc33", linewidth=3.0)
    if threshold is not None:
        axis.axhline(
            threshold,
            color="#cfe7cf",
            linestyle="-",
            linewidth=1.0,
            label=f"Threshold {threshold:.0f}",
        )
    if start is not None:
        axis.axhline(
            start,
            color="#e0e0e0",
            linestyle="-",
            linewidth=1.0,
            label=f"Start {start:.0f}",
        )

    if show_fueling:
        for event in sorted(foodplan, key=lambda item: item.get("time") or 0):
            plot_food_event(axis, event, times, glycogen, label_min_carbs=label_min_carbs)

    plot_title = title or "Glycogen level"
    axis.set_title(plot_title, fontsize=22, weight="semibold", color="#132018", pad=20)
    axis.set_xlabel("h", fontsize=16, color="#6b7280")
    axis.set_ylabel(y_label, fontsize=16, color="#6b7280", rotation=0, labelpad=22)
    axis.set_xlim(0, duration / 3600)
    axis.set_ylim(0, y_max)
    if y_axis == "carbs":
        axis.yaxis.set_major_locator(MultipleLocator(100))
    axis.grid(True, color="#d7ddd7", linewidth=0.8, alpha=0.65)
    axis.tick_params(axis="both", colors="#6b7280", labelsize=14, length=0)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#edf0f3")
    axis.spines["bottom"].set_color("#edf0f3")

    if show_fueling:
        axis.legend(
            handles=legend_handles(threshold is not None, start is not None),
            ncol=3,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.16),
            frameon=False,
        )

    total_carbs = sum(carbohydrates_grams(event) for event in foodplan)
    total_ml = sum(float(event.get("ml") or 0) for event in foodplan)
    depletion = max(0.0, float(summary_glycogen[0]) - float(summary_glycogen[-1]))
    final_unit = "g" if y_axis == "carbs" else "kcal"
    fig.text(0.12, 0.13, "Total glycogen depletion", fontsize=18, color="#132018")
    fig.text(0.88, 0.13, f"{depletion:.0f} {final_unit}", fontsize=18, weight="semibold", ha="right", color="#132018")
    fig.text(0.12, 0.07, "Final glycogen level", fontsize=18, color="#132018")
    fig.text(0.88, 0.07, f"{float(summary_glycogen[-1]):.0f} {final_unit}", fontsize=18, weight="semibold", ha="right", color="#132018")
    if show_fueling:
        fig.text(
            0.12,
            0.02,
            f"Food plan: {total_carbs:.1f} g carbs, {total_ml:.0f} ml fluid, {total_carbs / (duration / 3600):.1f} g/h.",
            fontsize=10,
            color="#555555",
        )
    fig.tight_layout(rect=(0.05, 0.20, 0.98, 0.98))
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def plot_food_event(
    axis,
    event: dict[str, Any],
    energy_times: list[float],
    glycogen: list[float],
    *,
    label_min_carbs: float,
) -> None:
    event_time = float(event.get("time") or 0)
    x = event_time / 3600
    nearest = min(range(len(energy_times)), key=lambda index: abs(float(energy_times[index]) - event_time))
    y = glycogen[nearest]
    carbs = carbohydrates_grams(event)
    milliliters = float(event.get("ml") or 0)
    label = product_label(event)
    color, marker, size, legend_label = marker_style(label)

    axis.scatter(
        [x],
        [y],
        s=size,
        c=[color],
        marker=marker,
        edgecolors="white",
        linewidths=0.8,
        zorder=5,
    )

    annotation = annotation_text(label, carbs, milliliters, label_min_carbs)
    if annotation is None:
        return
    offset = -48 if "kaffe" in label.lower() else 24
    if "svele" in label.lower():
        offset = 34
    axis.annotate(
        annotation,
        (x, y),
        xytext=(0, offset),
        textcoords="offset points",
        ha="center",
        va="bottom" if offset > 0 else "top",
        fontsize=9,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.82, "pad": 2},
    )


def product_label(event: dict[str, Any]) -> str:
    product = event.get("product") or {}
    return str(product.get("label") or event.get("productId") or product.get("id") or "Unknown")


def carbohydrates_grams(event: dict[str, Any]) -> float:
    product = event.get("product") or {}
    carbs = float(product.get("carbohydrates") or 0) / 1000
    serving_quantity = float(product.get("ingredientsQty") or 1)
    if product.get("ingredientsQtyUnit") == "gram" and event.get("gram") is not None:
        return carbs * float(event["gram"]) / serving_quantity
    return carbs


def marker_style(label: str) -> tuple[str, str, int, str]:
    lower = label.lower()
    if "svele" in lower:
        return "#d95f02", "s", 120, "Svele"
    if "gel" in lower:
        return "#d97706", "D", 85, "Gel"
    if "banan" in lower:
        return "#e6ab02", "o", 90, "Banan"
    if "seig" in lower or "laban" in lower:
        return "#7c3aed", "o", 38, "Seigmenn"
    if "elektrolyte" in lower or "drink" in lower:
        return "#2f80ed", "^", 36, "Drikke"
    if "kaffe" in lower or "coffee" in lower:
        return "#3f3028", "X", 90, "Kaffe"
    return "#555555", "o", 40, "Annet"


def annotation_text(label: str, carbs: float, milliliters: float, label_min_carbs: float) -> str | None:
    lower = label.lower()
    if "kaffe" in lower or "coffee" in lower:
        return f"Kaffe\n{milliliters:.0f} ml" if milliliters else "Kaffe"
    if carbs < label_min_carbs:
        return None
    if "svele" in lower:
        name = "Svele"
    elif "gel" in lower:
        name = "Gel"
    elif "banan" in lower:
        name = "Banan"
    else:
        name = label.split(" (", 1)[0][:18]
    return f"{name}\n{carbs:.0f} g"


def legend_handles(show_threshold: bool, show_start: bool) -> list[Line2D]:
    handles: list[Line2D] = [
        Line2D([0], [0], color="#0b7fab", lw=2.8, label="Glykogen/energi"),
    ]
    if show_threshold:
        handles.append(Line2D([0], [0], color="#d33f49", lw=1.7, ls="--", label="Threshold"))
    if show_start:
        handles.append(Line2D([0], [0], color="#6b7280", lw=1.5, ls=":", label="Startnivå"))
    for color, marker, label in [
        ("#2f80ed", "^", "Drikke"),
        ("#7c3aed", "o", "Seigmenn"),
        ("#e6ab02", "o", "Banan"),
        ("#d95f02", "s", "Svele"),
        ("#d97706", "D", "Gel"),
        ("#3f3028", "X", "Kaffe"),
    ]:
        handles.append(
            Line2D([0], [0], marker=marker, color="w", markerfacecolor=color, markersize=8, label=label)
        )
    return handles


def scaled_number(value: Any, factor: float) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / factor
    except (TypeError, ValueError):
        return None


def nice_axis_max(value: float) -> float:
    if value <= 100:
        return 100
    step = 100
    return ((int(value) + step - 1) // step) * step


def default_title(activity: dict[str, Any], activity_dir: Path) -> str:
    label = activity.get("label") or activity.get("name") or activity_dir.name
    date = activity_dir.name.split("_", 1)[0]
    return f"{date}: {label} - EatMyRide fueling"


def default_output_path(activity_dir: Path) -> Path:
    return Path("data/plots") / f"{activity_dir.name}_eatmyride_fueling.png"


if __name__ == "__main__":
    main()
