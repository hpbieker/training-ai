#!/usr/bin/env python3
"""Plot saved Intervals.icu activity artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis import load_activity, value


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a saved Intervals.icu activity artifact.")
    parser.add_argument("activity", help="Saved activity dir name or path")
    parser.add_argument("--output", help="Output image path")
    parser.add_argument("--moxy", action="store_true", help="Include Moxy-focused panels")
    args = parser.parse_args()

    activity_dir = Path(args.activity)
    if not activity_dir.exists():
        activity_dir = Path("data/intervals-old/activities") / args.activity
    activity = load_activity(activity_dir)

    output = Path(args.output) if args.output else _default_output_path(activity_dir, args.moxy)
    output.parent.mkdir(parents=True, exist_ok=True)

    plot_activity(activity, output=output, moxy=args.moxy)
    print(output.resolve())


def plot_activity(activity, *, output: Path, moxy: bool = False) -> None:
    rows = activity.streams
    time = [(value(row, "time") if value(row, "time") is not None else index) / 60 for index, row in enumerate(rows)]

    panels = [
        [("watts", "Watt"), ("heartrate", "HR")],
        [("respiration", "BR"), ("tidal_volume_min", "VE")],
        [("core_temperature", "Core"), ("skin_temperature", "Skin")],
    ]
    if moxy:
        panels.insert(1, [("smo2", "SmO2"), ("thb", "THb")])

    fig, axes = plt.subplots(
        len(panels),
        1,
        figsize=(13, 2.2 * len(panels) + 1.2),
        sharex=True,
        constrained_layout=True,
    )
    if len(panels) == 1:
        axes = [axes]

    title = f"{activity.start_date_local[:10]} {activity.name or activity.id}"
    fig.suptitle(title, fontsize=14)

    for axis, panel in zip(axes, panels):
        _shade_intervals(axis, activity)
        for key, label in panel:
            values = [value(row, key) for row in rows]
            if not any(v is not None for v in values):
                continue
            axis.plot(time, values, linewidth=1.1, label=label)
        axis.grid(alpha=0.25)
        axis.legend(loc="upper right", ncol=len(panel), fontsize=9)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    axes[-1].set_xlabel("Time (min)")
    fig.savefig(output, dpi=160)
    plt.close(fig)


def _shade_intervals(axis, activity) -> None:
    rows = activity.streams
    for interval in activity.intervals:
        start = int(interval.get("start_index") or 0)
        end = int(interval.get("end_index") or start)
        if start >= len(rows):
            continue
        end = min(max(end - 1, start), len(rows) - 1)
        start_time = value(rows[start], "time")
        end_time = value(rows[end], "time")
        if start_time is None or end_time is None:
            start_time = start
            end_time = end
        color = "#e8f1ff" if interval.get("type") == "WORK" else "#f3f3f3"
        axis.axvspan(start_time / 60, end_time / 60, color=color, alpha=0.55, linewidth=0)


def _default_output_path(activity_dir: Path, moxy: bool) -> Path:
    suffix = "moxy" if moxy else "overview"
    return Path("data/plots") / f"{activity_dir.name}_{suffix}.png"


if __name__ == "__main__":
    main()
