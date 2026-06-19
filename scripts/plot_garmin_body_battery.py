#!/usr/bin/env python3
"""Plot Garmin Body Battery and stress from a Garmin Connect JSON payload."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot Garmin Body Battery and stress from Garmin Connect JSON.",
    )
    parser.add_argument(
        "garmin_json",
        help="JSON from plugins/garmin-connect/scripts/garmin_connect_cli.py day",
    )
    parser.add_argument(
        "--activity-dir",
        help="Optional saved activity directory to mark workout start/stop",
    )
    parser.add_argument(
        "--output",
        help="Output PNG path. Defaults to outputs/plots/garmin_body_battery_<date>.png",
    )
    args = parser.parse_args()

    garmin = _load_json(Path(args.garmin_json))
    day = str(garmin.get("date") or "garmin-connect")
    sources = garmin.get("sources") if isinstance(garmin.get("sources"), dict) else garmin
    stress = sources.get("stress") or {}
    body_battery = _body_battery_payload(sources, stress=stress)
    sleep = sources.get("sleep") or {}
    activity_window = _activity_window(args.activity_dir) if args.activity_dir else None
    sleep_window = _sleep_window(sleep)

    output = (
        Path(args.output)
        if args.output
        else Path("outputs") / "plots" / f"garmin_body_battery_{day}.png"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    plot_body_battery(
        day=day,
        body_battery=body_battery,
        stress=stress,
        sleep_window=sleep_window,
        activity_window=activity_window,
        output=output,
    )
    print(output.resolve())


def plot_body_battery(
    *,
    day: str,
    body_battery: dict[str, Any],
    stress: dict[str, Any],
    sleep_window: tuple[datetime, datetime] | None,
    activity_window: tuple[datetime, datetime] | None,
    output: Path,
) -> None:
    """Create the plot."""

    bb_points = _time_value_points(body_battery.get("bodyBatteryValuesArray") or [])
    stress_points = [
        point
        for point in _time_value_points(stress.get("stressValuesArray") or [])
        if point[1] >= 0
    ]

    fig, ax = plt.subplots(figsize=(14, 5.5))
    if stress_points:
        xs = [_hour_of_day(point[0]) for point in stress_points]
        ys = [point[1] for point in stress_points]
        colors = ["#2563eb" if value < 25 else "#f97316" for value in ys]
        width_hours = 2.6 / 60
        ax.bar(
            xs,
            ys,
            width=width_hours,
            color=colors,
            align="center",
            edgecolor="none",
            alpha=0.85,
            label="Stress",
        )

    if bb_points:
        ax.plot(
            [_hour_of_day(point[0]) for point in bb_points],
            [point[1] for point in bb_points],
            color="#111827",
            linewidth=2.4,
            marker="o",
            markersize=4,
            label="Body Battery",
        )

    ax.axhline(25, color="#64748b", linestyle="--", linewidth=1, alpha=0.8)
    if sleep_window:
        _mark_window(
            ax,
            sleep_window,
            label_start="Start søvn",
            label_end="Slutt søvn",
            color="#7c3aed",
            shade_alpha=0.06,
        )
    if activity_window:
        _mark_window(
            ax,
            activity_window,
            label_start="Start økt",
            label_end="Slutt økt",
            color_start="#16a34a",
            color_end="#dc2626",
            shade_alpha=0.08,
        )

    ax.set_ylim(0, 100)
    ax.set_xlim(0, 24)
    ax.set_ylabel("Stress / Body Battery (0-100)")
    ax.set_xlabel("Tid")
    ax.set_title("Body Battery")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(loc="upper right")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: _format_hour(value)))
    fig.tight_layout()
    fig.savefig(output, dpi=160)


def _mark_window(
    ax: Any,
    window: tuple[datetime, datetime],
    *,
    label_start: str,
    label_end: str,
    color: str | None = None,
    color_start: str | None = None,
    color_end: str | None = None,
    shade_alpha: float,
) -> None:
    start, end = window
    start_hour = _hour_of_day(start)
    end_hour = _hour_of_day(end)
    start_color = color_start or color or "#64748b"
    end_color = color_end or color or "#64748b"
    shade_color = color or start_color
    ax.axvspan(start_hour, end_hour, color=shade_color, alpha=shade_alpha)
    ax.axvline(start_hour, color=start_color, linestyle="--", linewidth=1.4)
    ax.axvline(end_hour, color=end_color, linestyle="--", linewidth=1.4)
    ax.text(
        start_hour,
        98,
        label_start,
        rotation=90,
        va="top",
        ha="right",
        color=start_color,
    )
    ax.text(end_hour, 98, label_end, rotation=90, va="top", ha="left", color=end_color)


def _activity_window(activity_dir: str) -> tuple[datetime, datetime]:
    activity = _load_json(Path(activity_dir) / "activity.json")
    start = datetime.fromisoformat(activity["start_date_local"])
    end = datetime.fromtimestamp(start.timestamp() + float(activity.get("moving_time") or 0))
    return start, end


def _sleep_window(sleep: dict[str, Any]) -> tuple[datetime, datetime] | None:
    daily_sleep = sleep.get("dailySleepDTO", {})
    start = sleep.get("sleepStartTimestampLocal") or daily_sleep.get(
        "sleepStartTimestampLocal"
    )
    end = sleep.get("sleepEndTimestampLocal") or daily_sleep.get("sleepEndTimestampLocal")
    if not start or not end:
        return None
    return _parse_garmin_local_datetime(start), _parse_garmin_local_datetime(end)


def _body_battery_payload(
    sources: dict[str, Any],
    *,
    stress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stress:
        dense_points = _body_battery_points_from_stress(stress)
        if dense_points:
            return {"bodyBatteryValuesArray": dense_points}

    payload = sources.get("body_battery") or sources.get("body_battery_range")
    if isinstance(payload, list) and payload:
        return payload[-1]
    if isinstance(payload, dict):
        return payload
    raise ValueError("No Body Battery data found in Garmin Connect JSON")


def _body_battery_points_from_stress(stress: dict[str, Any]) -> list[list[float]]:
    points = []
    for row in stress.get("bodyBatteryValuesArray") or []:
        if (
            isinstance(row, list)
            and len(row) >= 3
            and isinstance(row[0], (int, float))
            and isinstance(row[2], (int, float))
        ):
            points.append([row[0], row[2]])
    return points


def _time_value_points(rows: list[Any]) -> list[tuple[datetime, float]]:
    points = []
    for row in rows:
        if (
            isinstance(row, list)
            and len(row) >= 2
            and isinstance(row[0], (int, float))
            and isinstance(row[1], (int, float))
        ):
            points.append((datetime.fromtimestamp(row[0] / 1000), float(row[1])))
    return points


def _parse_garmin_local_datetime(raw: str | int | float) -> datetime:
    if isinstance(raw, (int, float)):
        # Garmin's *Local millisecond fields encode local clock time as if it
        # were UTC. utcfromtimestamp therefore preserves the intended HH:MM.
        return datetime.utcfromtimestamp(raw / 1000)
    return datetime.fromisoformat(raw.replace(".0", ""))


def _hour_of_day(value: datetime) -> float:
    return value.hour + value.minute / 60 + value.second / 3600


def _format_hour(value: float) -> str:
    if value < 0 or value > 24:
        return ""
    hour = int(value)
    minute = int(round((value - hour) * 60))
    if minute == 60:
        hour += 1
        minute = 0
    return f"{hour:02d}:{minute:02d}"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
