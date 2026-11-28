#!/usr/bin/env python3
"""Render a social Strava share card from a saved Intervals.icu activity.

The activity title lives on Strava already.  This card deliberately adds a
plain-language account of how the work was carried out, rather than repeating
the workout title or reproducing a diagnostic dashboard.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from bisect import bisect_left
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.colors import is_color_like, to_rgb
from PIL import Image


OUTPUT_SIZE = (1080, 720)
RENDER_DPI = 400
CHART_SMOOTHING_SECONDS = 9
COLOR_SMOOTHING_SECONDS = 25
TABLE_ROW_HEIGHT = 0.04
TABLE_HEIGHT = 0.308
CHART_TOP = 0.665
NAVY = "#101722"
PANEL = "#182333"
BLUE = "#4d83d3"
RED = "#b5272d"
WHITE = "#f7f9fc"
MUTED = "#a8b4c4"
MINT = "#66d7b5"
DEFAULT_POWER_SCALE_MAX = 800.0
DIFFICULTY_SCALE_MAX = 200.0
HEART_RATE_FLOOR = 40.0
INTERVAL_HEADLINES = {"vo2max": "VO₂MAX", "vt2": "VT2"}


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    target_watts: float


@dataclass(frozen=True)
class WorkoutStory:
    headline: str
    subtitle: str
    work_label: str
    target_watts: float | None
    repetitions: int | None = None


def as_float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def xert_number(value: Any) -> float | None:
    return as_float(value)


def load_xert_session(path: Path) -> tuple[object, dict[str, Any], list[dict[str, Any]]]:
    """Load only the Xert fields needed to reproduce its chart semantics."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        activity = payload["activity"]
        summary = dict(activity["summary"])
        rows = [row for row in activity["session_data"] if isinstance(row, dict)]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read Xert session: {path}") from exc
    if not rows:
        raise ValueError("Xert session has no time-series data")
    return payload.get("activity_path"), summary, rows


def load_lactate_maxima(
    path: Path, activity_path: object, intervals: list[dict[str, object]]
) -> list[float] | None:
    """Read a maximum over each recorded work interval, excluding recovery."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not activity_path or payload.get("activity_path") != activity_path:
        raise ValueError(f"Lactate series does not match the Xert session: {path}")
    series = payload.get("series", {})
    times = series.get("elapsed_s", [])
    lactate = series.get("lactate_model_mmol_l", [])
    if not times or len(times) != len(lactate):
        return None
    if any(not isinstance(time, (int, float)) or not math.isfinite(time) for time in times) or any(
        current <= previous for previous, current in zip(times, times[1:])
    ):
        return None

    maxima = []
    for interval in intervals:
        start = float(interval["start_time"])
        end = float(interval["end_time"])
        first, stop = bisect_left(times, start), bisect_left(times, end)
        values = lactate[first:stop]
        if not values or times[first] >= start + 1 or times[stop - 1] < end - 1:
            return None
        if any(current - previous > 1 for previous, current in zip(times[first:stop], times[first + 1:stop])):
            return None
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values):
            return None
        maxima.append(max(values))
    return maxima or None


def xert_stream(rows: list[dict[str, Any]], key: str) -> tuple[list[float], list[float]]:
    points = [(xert_number(row.get("time")), xert_number(row.get(key))) for row in rows]
    valid = sorted(
        ((time, value) for time, value in points
         if time is not None and value is not None and math.isfinite(time) and math.isfinite(value)),
        key=lambda point: point[0],
    )
    return [time / 60 for time, _ in valid], [value for _, value in valid]


def infer_heart_rate_ceiling(heart_rate: list[float]) -> float:
    return max(160.0, math.ceil(max(heart_rate) / 20.0) * 20.0) if heart_rate else 160.0


def smooth_chart_samples(
    time: list[float], values: list[float] | np.ndarray, *, window_seconds: int = CHART_SMOOTHING_SECONDS
) -> np.ndarray:
    """Use a centered elapsed-time window for the chart only."""
    minutes = np.asarray(time)
    radius = window_seconds / 2 / 60
    start = np.searchsorted(minutes, minutes - radius)
    end = np.searchsorted(minutes, minutes + radius, side="right")
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    return (cumulative[end] - cumulative[start]) / (end - start)


def add_power_fill(graph: Axes, rows: list[dict[str, Any]], time: list[float], power: np.ndarray) -> None:
    """Clip a continuous strip of Xert colors to the power curve."""
    colors = {}
    palette = {BLUE: to_rgb(BLUE)}
    for row in rows:
        seconds = xert_number(row.get("time"))
        color = row.get("powerColor")
        if seconds is not None and isinstance(color, str):
            if color not in palette:
                palette[color] = to_rgb(color) if is_color_like(color) else palette[BLUE]
            colors[seconds / 60] = palette[color]
    channels = np.asarray([colors.get(minute, palette[BLUE]) for minute in time]).T
    left, right = min(time), max(time)
    if left == right:
        return
    pixel_width = OUTPUT_SIZE[0]
    pixel_times = left + (np.arange(pixel_width) + 0.5) * (right - left) / pixel_width
    strip = np.column_stack([
        np.interp(pixel_times, time, smooth_chart_samples(time, channel, window_seconds=COLOR_SMOOTHING_SECONDS))
        for channel in channels
    ])
    area = graph.fill_between(time, power, color=BLUE, linewidth=0)
    gradient = graph.imshow(
        np.clip(strip[np.newaxis, :, :], 0, 1), extent=(left, right, 0, 1),
        aspect="auto", interpolation="bilinear", zorder=area.get_zorder(),
    )
    gradient.set_clip_path(area.get_paths()[0], graph.transData)


def load_activity(activity_dir: Path) -> dict[str, object]:
    path = activity_dir / "activity.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read saved Intervals activity: {path}") from exc
    activity = payload.get("activity", payload) if isinstance(payload, dict) else None
    if not isinstance(activity, dict):
        raise ValueError(f"Saved Intervals activity has no activity object: {path}")
    return activity


def load_steady_finish(inspection_path: Path, activity_id: object) -> dict[str, object] | None:
    """Read the measured finish from a brief inspection of the same activity."""
    inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
    if not activity_id or inspection["activity"]["id"] != activity_id:
        raise ValueError(f"Inspection does not match the Intervals activity: {inspection_path}")
    return inspection.get("steady_vt1_segment")


def load_streams(activity_dir: Path) -> list[dict[str, float]]:
    path = activity_dir / "streams.csv"
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = csv.DictReader(handle)
            rows = [
                {key: value for key, raw in row.items() if (value := as_float(raw)) is not None}
                for row in source_rows
            ]
    except OSError as exc:
        raise ValueError(f"Cannot read activity streams: {path}") from exc
    return [row for row in rows if "time" in row and "watts" in row]


def trailing_mean(values: list[float], window: int = 30) -> np.ndarray:
    if not values:
        return np.array([])
    cumulative = np.cumsum(np.insert(np.asarray(values, dtype=float), 0, 0.0))
    start = np.maximum(np.arange(len(values)) - window + 1, 0)
    counts = np.arange(len(values)) - start + 1
    return (cumulative[1:] - cumulative[start]) / counts


def main_work_segment(rows: list[dict[str, float]]) -> Segment:
    """Find the longest stable plateau without requiring a planned workout."""

    power = [row["watts"] for row in rows]
    positive = [value for value in power if value >= 100]
    if not positive:
        raise ValueError("No usable power samples")
    # The broad, sustained indoor plateau is normally programmed in 10 W
    # increments.  Rounding to five split today's 210 W target around its
    # observed 214 W average into artificial sub-blocks.
    target = round(float(np.median(positive)) / 10) * 10
    smooth = trailing_mean(power)
    matches = np.abs(smooth - target) <= 12
    start: int | None = None
    last_match: int | None = None
    gap = 0
    candidates: list[tuple[int, int]] = []
    for index, matched in enumerate(matches):
        if matched:
            start = index if start is None else start
            last_match = index
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 30:
                if last_match is not None:
                    candidates.append((start, last_match))
                start = last_match = None
                gap = 0
    if start is not None and last_match is not None:
        candidates.append((start, last_match))
    if not candidates:
        return Segment(0, len(rows) - 1, target)
    start, end = max(candidates, key=lambda pair: pair[1] - pair[0])
    return Segment(start, end, target)


def format_duration(seconds: float) -> str:
    total_minutes = int(round(seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def workout_story(
    activity: dict[str, object],
    rows: list[dict[str, float]],
    *,
    workout_role: str | None = None,
    steady_finish: dict[str, object] | None = None,
) -> WorkoutStory:
    """State the purposeful work, using Intervals' detected interval summary."""
    summaries = activity.get("interval_summary")
    parsed_summaries: list[tuple[int, int, int]] = []
    if isinstance(summaries, list):
        for summary in summaries:
            if not isinstance(summary, str):
                continue
            match = re.fullmatch(r"(\d+)x (?:(\d+)m)?(?:(\d+)s)? (\d+)w", summary)
            if not match:
                continue
            repetitions, minutes, seconds, watts = (int(value or 0) for value in match.groups())
            duration = minutes * 60 + seconds
            if duration > 0:
                parsed_summaries.append((repetitions, duration, watts))

    # Intervals.icu also lists warm-up and short finishing blocks. Prefer a
    # repeated work set instead of treating the first summary as the workout.
    repeated = [item for item in parsed_summaries if item[0] > 1]
    candidates = repeated or (parsed_summaries if workout_role in INTERVAL_HEADLINES else [])
    selected = max(candidates, key=lambda item: (item[0], item[0] * item[1], item[2])) if candidates else None
    if selected:
        repetitions, seconds_total, watts = selected
        minutes, seconds = divmod(seconds_total, 60)
        duration = f"{minutes}:{seconds:02d}" if seconds else f"{minutes}:00"
        matching_finishers = [
            item for item in parsed_summaries
            if item[0] == 1
            and item[2] == watts
            and item[1] >= seconds_total * 0.5
        ]
        finisher_text = "".join(
            " + " + (f"{extra_seconds // 60}:{extra_seconds % 60:02d}" if extra_seconds % 60 else f"{extra_seconds // 60}:00")
            for _, extra_seconds, _ in matching_finishers
        )
        work_label = f"{repetitions} × {duration}{finisher_text} @ {watts} W"
        headline = INTERVAL_HEADLINES.get(workout_role, "INTERVALS")
        subtitle = f"{repetitions} × {duration}{finisher_text} at {watts} W"
        if steady_finish:
            finish_seconds = as_float(steady_finish.get("duration_s"))
            finish_watts = as_float(steady_finish.get("watts_avg"))
            if finish_seconds and finish_seconds > 0 and finish_watts and finish_watts > 0:
                subtitle += f", followed by {finish_seconds / 60:.0f} min of VT1 at {finish_watts:.0f} W"
        return WorkoutStory(headline, f"{subtitle}.", work_label, float(watts), repetitions)
    segment = main_work_segment(rows)
    work = rows[segment.start : segment.end + 1]
    duration = format_duration(work[-1]["time"] - work[0]["time"])
    average_power = float(np.mean([row["watts"] for row in work]))
    return WorkoutStory(
        "VT1",
        f"{duration} of steady work at {average_power:.0f} W.",
        f"{duration} @ {average_power:.0f} W",
        average_power,
    )


def repeated_work_intervals(activity: dict[str, object], story: WorkoutStory) -> list[dict[str, object]]:
    """Return substantial work intervals matching the card's stated power.

    Intervals.icu can assign a different group_id when the final repetition is
    shorter than a repeated set. Keep such a meaningful finishing effort in
    the table when it is near the same target and at least half as long as the
    main repetition.
    """
    if story.repetitions is None or story.target_watts is None:
        return []
    candidates = activity.get("icu_intervals")
    if not isinstance(candidates, list):
        return []
    candidates = [
        item for item in candidates
        if isinstance(item, dict)
        and item.get("type") == "WORK"
        and as_float(item.get("start_time")) is not None
        and as_float(item.get("end_time")) is not None
        and as_float(item.get("average_watts")) is not None
        and abs(as_float(item["average_watts"]) - story.target_watts) <= 20
    ]
    if not candidates:
        return []
    longest = max(
        as_float(item["end_time"]) - as_float(item["start_time"])
        for item in candidates
    )
    minimum_duration = longest * 0.5
    matches = [
        item for item in candidates
        if as_float(item["end_time"]) - as_float(item["start_time"]) >= minimum_duration
    ]
    return sorted(matches, key=lambda item: as_float(item["start_time"]) or 0)


def story_rows(
    rows: list[dict[str, float]], activity: dict[str, object], story: WorkoutStory
) -> list[dict[str, float]]:
    """Use all detected repeated work intervals for HR, not one arbitrary repeat."""
    intervals = repeated_work_intervals(activity, story)
    if not intervals:
        segment = main_work_segment(rows)
        return rows[segment.start : segment.end + 1]
    ranges = [
        (as_float(item.get("start_time")), as_float(item.get("end_time")))
        for item in intervals
    ]
    valid_ranges = [(start, end) for start, end in ranges if start is not None and end is not None]
    selected = [row for row in rows if any(start <= row["time"] <= end for start, end in valid_ranges)]
    return selected or rows


def mean_field(rows: list[dict[str, float]], field: str) -> float | None:
    values = [row[field] for row in rows if field in row]
    return float(np.mean(values)) if values else None


def format_measure(value: float | None, digits: int = 0) -> str:
    return f"{value:.{digits}f}" if value is not None else "—"


def add_response_table(
    axis: plt.Axes,
    activity: dict[str, object],
    rows: list[dict[str, float]],
    story: WorkoutStory,
    *,
    lactate_maxima: list[float] | None = None,
) -> None:
    """Draw a compact per-rep physiology table with one easily scanned row per rep."""
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.set_autoscale_on(False)
    intervals = repeated_work_intervals(activity, story)
    if intervals:
        ranges = [
            (as_float(item.get("start_time")), as_float(item.get("end_time")))
            for item in intervals
        ]
        range_rows = [
            [row for row in rows if start is not None and end is not None and start <= row["time"] <= end]
            for start, end in ranges
        ]
        body = [
            (
                f"{index + 1}",
                [
                    as_float(interval.get("average_heartrate")),
                    as_float(interval.get("average_respiration")),
                    as_float(interval.get("average_tidal_volume_min")),
                    as_float(interval.get("MinSmo2")),
                    mean_field(rep_rows, "core_temperature"),
                ],
            )
            for index, (interval, rep_rows) in enumerate(zip(intervals, range_rows))
        ]
    else:
        work = story_rows(rows, activity, story)
        start, end = work[0]["time"], work[-1]["time"]
        # Use legible 30-minute time windows rather than mathematically equal
        # fractions; any remaining time becomes the final, shorter window.
        block_seconds = 30 * 60
        edges = list(np.arange(start, end, block_seconds)) + [end]
        body = []
        for index, (block_start, block_end) in enumerate(zip(edges, edges[1:])):
            block = [
                row for row in work
                if block_start <= row["time"] <= block_end
            ]
            start_minute = int(round((block_start - start) / 60))
            end_minute = int(round((block_end - start) / 60))
            body.append((
                f"{start_minute}–{end_minute} MIN",
                [
                    mean_field(block, "heartrate"),
                    mean_field(block, "respiration"),
                    mean_field(block, "tidal_volume_min"),
                    mean_field(block, "smo2"),
                    mean_field(block, "core_temperature"),
                ],
            ))

    x, y, width, height = 0.0, 0.0, 1.0, TABLE_HEIGHT
    axis.add_patch(plt.Rectangle((x, y), width, height, transform=axis.transAxes, facecolor=PANEL, edgecolor="none"))
    headers = ("REP" if intervals else "TIME", "HR BPM", "BR /MIN", "VE VOL/MIN", "SMO₂ MIN %" if intervals else "SMO₂ %", "CORE TEMP °C")
    precision = (0, 0, 0, 1, 2)
    right_margin = 0
    if intervals and lactate_maxima and len(lactate_maxima) == len(body):
        headers += ("LACTATE MAX EST (mmol/L)",)
        precision += (1,)
        right_margin = 0.014
        for (_, measures), maximum in zip(body, lactate_maxima, strict=True):
            measures.append(maximum)
    header_y = y + height - 0.022
    rep_width = 0.10
    column_width = (width - rep_width - right_margin) / (len(headers) - 1)
    axis.text(x + 0.014, header_y, headers[0], color=MINT, fontsize=7, fontweight="bold", family="DejaVu Sans")
    for index, header in enumerate(headers[1:]):
        center = x + rep_width + (index + 0.5) * column_width
        axis.text(center, header_y, header, ha="center", color=MINT, fontsize=7, fontweight="bold", family="DejaVu Sans")
    axis.plot([x + 0.012, x + width - 0.012], [header_y - 0.016, header_y - 0.016], color="#304053", linewidth=0.6, transform=axis.transAxes)
    first_row_y = header_y - 0.052
    available_row_height = (first_row_y - (y + 0.018)) / max(len(body) - 1, 1)
    row_height = min(TABLE_ROW_HEIGHT, available_row_height)
    compactness = row_height / TABLE_ROW_HEIGHT
    label_size = max(5.5, 7 * compactness)
    measure_size = max(6.0, 8 * compactness)
    for row_index, (label, measures) in enumerate(body):
        baseline = first_row_y - row_index * row_height
        axis.text(x + 0.014, baseline, label, color=MUTED, fontsize=label_size, fontweight="bold", family="DejaVu Sans")
        for column_index, (measure, digits) in enumerate(zip(measures, precision, strict=True)):
            center = x + rep_width + (column_index + 0.5) * column_width
            axis.text(center, baseline, format_measure(measure, digits), ha="center", color=WHITE, fontsize=measure_size, family="DejaVu Sans")


def render(
    activity_dir: Path,
    xert_session: Path,
    output: Path,
    *,
    workout_role: str | None = None,
    inspection_path: Path | None = None,
    lactate_series_path: Path | None = None,
) -> Path:
    activity = load_activity(activity_dir)
    rows = load_streams(activity_dir)
    steady_finish = load_steady_finish(inspection_path, activity.get("id")) if inspection_path else None
    story = workout_story(activity, rows, workout_role=workout_role, steady_finish=steady_finish)
    activity_path, summary, xert_rows = load_xert_session(xert_session)
    lactate_maxima = None
    if lactate_series_path and workout_role in INTERVAL_HEADLINES:
        intervals = repeated_work_intervals(activity, story)
        lactate_maxima = load_lactate_maxima(lactate_series_path, activity_path, intervals)
    time, power = xert_stream(xert_rows, "power")
    hr_time, heart_rate = xert_stream(xert_rows, "hr")
    mpa_time, mpa = xert_stream(xert_rows, "mpa")
    difficulty_time, difficulty = xert_stream(xert_rows, "xds")
    if not power:
        raise ValueError("Xert session has no power stream")
    power_scale = xert_number(summary.get("sig", {}).get("pp")) or DEFAULT_POWER_SCALE_MAX
    scaled_power = np.clip(smooth_chart_samples(time, power) / power_scale, 0, 1)
    hr_ceiling = infer_heart_rate_ceiling(heart_rate)
    scaled_hr = np.clip(
        (smooth_chart_samples(hr_time, heart_rate) - HEART_RATE_FLOOR) / (hr_ceiling - HEART_RATE_FLOOR),
        0, 1,
    )

    figure = plt.figure(figsize=(10.8, 7.2), dpi=RENDER_DPI, facecolor=NAVY)
    figure.patch.set_facecolor(NAVY)
    text = figure.add_axes([0, 0, 1, 1])
    text.set_axis_off()
    text.text(0.055, 0.81, story.headline, color=WHITE, fontsize=28, fontweight="bold", family="DejaVu Sans")
    text.text(
        0.055,
        0.75,
        story.subtitle,
        color=MUTED,
        fontsize=11,
        family="DejaVu Sans",
    )

    # Power and MPA share PP, HR starts at 40 bpm, and Difficulty uses XDS/200.
    graph = figure.add_axes([0.0, TABLE_HEIGHT, 1.0, CHART_TOP - TABLE_HEIGHT], facecolor=NAVY)
    add_power_fill(graph, xert_rows, time, scaled_power)
    if difficulty:
        scaled_difficulty = np.clip(np.asarray(difficulty) / DIFFICULTY_SCALE_MAX, 0, 1)
        power_at_difficulty = np.interp(difficulty_time, time, scaled_power, left=np.nan, right=np.nan)
        difficulty_mask = scaled_difficulty > power_at_difficulty
        graph.fill_between(
            difficulty_time, power_at_difficulty, scaled_difficulty, where=difficulty_mask,
            facecolor="#71839b", linewidth=0, alpha=0.24,
        )
        graph.plot(difficulty_time, np.where(difficulty_mask, scaled_difficulty, np.nan), color="#9aa3af", linewidth=0.75)
    graph.plot(time, scaled_power, color="#245ca8", linewidth=0.65)
    if heart_rate:
        graph.plot(hr_time, scaled_hr, color=RED, linewidth=1.5)
    if mpa:
        graph.plot(mpa_time, [max(0.0, min(1.0, value / power_scale)) for value in mpa], color="#cf6bff", linewidth=2.0)
    graph.set_xlim(min(time), max(time))
    graph.set_ylim(0, 1.04)
    graph.set_xticks([])
    graph.set_yticks([])
    for spine in graph.spines.values():
        spine.set_visible(False)

    # Keep the table on its own full-canvas layer.  Matplotlib otherwise lets
    # the table's separator line autoscale the text layer and clip the heading.
    table = figure.add_axes([0, 0, 1, 1])
    table.set_axis_off()
    add_response_table(table, activity, rows, story, lactate_maxima=lactate_maxima)

    output.parent.mkdir(parents=True, exist_ok=True)
    # Downsample the oversized render for clean edges and export opaque PNG.
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=RENDER_DPI, facecolor=figure.get_facecolor())
    plt.close(figure)
    buffer.seek(0)
    with Image.open(buffer) as image:
        image.convert("RGB").resize(OUTPUT_SIZE, Image.Resampling.LANCZOS).save(output, format="PNG")
    return output.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("activity_dir", type=Path, help="Saved Intervals.icu activity directory")
    parser.add_argument("--xert-session", type=Path, required=True, help="Saved Xert session JSON for the same activity")
    parser.add_argument("--workout-role", choices=INTERVAL_HEADLINES, help="Confirmed role of the work intervals")
    parser.add_argument(
        "--inspection", type=Path, help="Brief inspection JSON for the same activity, with any measured steady VT1 finish"
    )
    parser.add_argument("--lactate-series", type=Path, help="Saved Xert 2.0 Beta model series for the same activity")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(render(
        args.activity_dir,
        args.xert_session,
        args.output,
        workout_role=args.workout_role,
        inspection_path=args.inspection,
        lactate_series_path=args.lactate_series,
    ))


if __name__ == "__main__":
    main()
