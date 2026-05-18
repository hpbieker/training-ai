#!/usr/bin/env python3
"""Overlay local sensor streams on Xert Forecast AI report images."""

from __future__ import annotations

import argparse
import csv
import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw


DATA_DIR = Path("data")
OSLO = ZoneInfo("Europe/Oslo")
UTC = ZoneInfo("UTC")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Xert xfair report images and overlay Intervals sensor streams.",
    )
    parser.add_argument(
        "--latest-vt2",
        type=int,
        default=None,
        help="Process the latest N cached Intervals activities with VT2 in the name.",
    )
    parser.add_argument(
        "--activity-dir",
        type=Path,
        help="Process one cached Intervals activity directory.",
    )
    parser.add_argument(
        "--xert-path",
        help="Override Xert activity path, e.g. 4ju77engvgq6h4gv.",
    )
    parser.add_argument(
        "--ve-window",
        type=int,
        default=60,
        help="Rolling average window for VE/tidal_volume_min in seconds.",
    )
    parser.add_argument(
        "--smo2-only",
        action="store_true",
        help="Plot only SmO2 over the Xert report.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Download the xfair PNG even when it already exists locally.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
    )
    args = parser.parse_args()

    if not args.latest_vt2 and not args.activity_dir:
        parser.error("Use --latest-vt2 N or --activity-dir PATH")

    xert_index = load_xert_index(args.data_dir)
    activities = (
        latest_vt2_activities(args.data_dir, args.latest_vt2)
        if args.latest_vt2
        else [args.activity_dir]
    )

    for activity_dir in activities:
        try:
            result = process_activity(
                activity_dir=activity_dir,
                xert_index=xert_index,
                xert_path=args.xert_path,
                ve_window=args.ve_window,
                smo2_only=args.smo2_only,
                force_download=args.force_download,
                data_dir=args.data_dir,
            )
        except Exception as exc:  # noqa: BLE001 - CLI should continue with remaining activities.
            print(f"{activity_dir} -> SKIPPED: {exc}")
            continue
        print(f"{result['activity_dir']} -> {result['output_png']}")


def latest_vt2_activities(data_dir: Path, count: int) -> list[Path]:
    candidates = []
    for activity_dir in (data_dir / "activities").iterdir():
        metadata_path = activity_dir / "activity.json"
        streams_path = activity_dir / "streams.csv"
        if not metadata_path.exists() or not streams_path.exists():
            continue
        metadata = read_json(metadata_path)
        name = str(metadata.get("name") or "")
        if "VT2" not in name.upper():
            continue
        start = parse_intervals_start(metadata)
        candidates.append((start, activity_dir))
    candidates.sort(reverse=True, key=lambda item: item[0])
    return [activity_dir for _, activity_dir in candidates[:count]]


def load_xert_index(data_dir: Path) -> list[dict[str, Any]]:
    index = []
    for path in (data_dir / "xert" / "activities").glob("*/activity.json"):
        detail = read_json(path)
        start = parse_xert_start(detail)
        if start is None:
            continue
        summary = detail.get("summary") or {}
        index.append(
            {
                "activity_dir": path.parent,
                "path": path.parent.name.split("_", 1)[1],
                "name": detail.get("name"),
                "start": start,
                "duration": (summary.get("session") or {}).get("total_timer_time"),
            }
        )
    return index


def process_activity(
    *,
    activity_dir: Path,
    xert_index: list[dict[str, Any]],
    xert_path: str | None,
    ve_window: int,
    smo2_only: bool,
    force_download: bool,
    data_dir: Path,
) -> dict[str, Path]:
    metadata = read_json(activity_dir / "activity.json")
    streams = read_streams(activity_dir / "streams.csv")
    if xert_path is None:
        match = match_xert_activity(metadata, xert_index)
        if match is None:
            raise RuntimeError(f"No cached Xert activity match for {activity_dir}")
        xert_path = match["path"]

    xert_dir = data_dir / "xert" / "activities" / f"{activity_dir.name[:10]}_{xert_path}"
    xert_dir.mkdir(parents=True, exist_ok=True)
    report_png = xert_dir / "xfair_downloaded.png"
    if force_download or not report_png.exists():
        download_xfair_report(xert_path, report_png)

    output_name = (
        "xfair_overlay_smo2.png"
        if smo2_only
        else f"xfair_overlay_ve{ve_window}s_smo2.png"
    )
    output_png = xert_dir / output_name
    overlay_report(
        report_png=report_png,
        streams=streams,
        output_png=output_png,
        ve_window=ve_window,
        smo2_only=smo2_only,
    )
    return {"activity_dir": activity_dir, "output_png": output_png}


def match_xert_activity(
    intervals_metadata: dict[str, Any],
    xert_index: list[dict[str, Any]],
) -> dict[str, Any] | None:
    start = parse_intervals_start(intervals_metadata)
    duration = intervals_metadata.get("elapsed_time") or intervals_metadata.get("moving_time")
    best = None
    for item in xert_index:
        delta = abs((item["start"] - start).total_seconds())
        if delta > 6 * 60 * 60:
            continue
        duration_penalty = 0.0
        if duration and item.get("duration"):
            duration_penalty = abs(float(item["duration"]) - float(duration))
        score = delta + duration_penalty
        if best is None or score < best[0]:
            best = (score, item)
    return best[1] if best else None


def download_xfair_report(xert_path: str, output_path: Path) -> None:
    url = f"https://www.xertonline.com/breakthrough-report-download/{xert_path}/xfair"
    request = Request(
        url,
        headers={
            "Accept": "image/png,image/*,*/*",
            "User-Agent": "training-ai/0.1 (+Xert xfair overlay)",
        },
    )
    with urlopen(request, timeout=60) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "")
    if not payload.startswith(b"\x89PNG"):
        raise RuntimeError(f"Expected PNG from {url}, got {content_type}")
    output_path.write_bytes(payload)


def overlay_report(
    *,
    report_png: Path,
    streams: list[dict[str, str]],
    output_png: Path,
    ve_window: int,
    smo2_only: bool,
) -> None:
    base = Image.open(report_png).convert("RGBA")
    width, height = base.size
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")

    plot_left = 0
    plot_right = width - 1
    plot_top = round(height * 343 / 720)
    plot_bottom = round(height * 660 / 720)
    plot_height = plot_bottom - plot_top

    rows = [(value(row, "time"), row) for row in streams if value(row, "time") is not None]
    if not rows:
        raise RuntimeError("No time values in streams")
    max_time = max(time for time, _ in rows)
    series = []
    if not smo2_only:
        ve_values = rolling_average(
            [(time, value(row, "tidal_volume_min")) for time, row in rows],
            ve_window,
        )
        series.append(("ve", ve_values, (213, 128, 38, 190), 0.0, 3))
    series.append(
        (
            "smo2",
            [(time, value(row, "smo2")) for time, row in rows],
            (20, 124, 184, 205),
            0.0,
            3,
        ),
    )
    for _, points, color, lower, line_width in series:
        valid = [point_value for _, point_value in points if point_value is not None]
        if not valid:
            continue
        upper = max(valid) * 1.05 if max(valid) else 1.0
        if upper <= lower:
            upper = lower + 1.0
        pixel_points = []
        for time, point_value in points:
            if point_value is None:
                draw_polyline(draw, pixel_points, color, line_width)
                pixel_points = []
                continue
            x = round(plot_left + (time / max_time) * (plot_right - plot_left))
            fraction = max(0.0, min(1.0, (point_value - lower) / (upper - lower)))
            y = round(plot_bottom - fraction * plot_height)
            pixel_points.append((x, y))
        draw_polyline(draw, pixel_points, color, line_width)

    Image.alpha_composite(base, layer).convert("RGB").save(output_png, quality=95)


def draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    color: tuple[int, int, int, int],
    line_width: int,
) -> None:
    if len(points) <= 1:
        return
    draw.line(points, fill=(0, 0, 0, 45), width=line_width + 2)
    draw.line(points, fill=color, width=line_width)


def rolling_average(
    points: list[tuple[float, float | None]],
    window: int,
) -> list[tuple[float, float | None]]:
    queue: deque[float] = deque()
    total = 0.0
    averaged = []
    for time, point_value in points:
        if point_value is None:
            queue.clear()
            total = 0.0
            averaged.append((time, None))
            continue
        queue.append(point_value)
        total += point_value
        while len(queue) > window:
            total -= queue.popleft()
        averaged.append((time, total / len(queue)))
    return averaged


def parse_intervals_start(metadata: dict[str, Any]) -> datetime:
    raw = metadata.get("start_date_local") or metadata.get("start_date")
    if not raw:
        raise KeyError("Activity metadata missing start date")
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=OSLO)
    return parsed.astimezone(OSLO)


def parse_xert_start(detail: dict[str, Any]) -> datetime | None:
    summary = detail.get("summary") or {}
    start = summary.get("start_date")
    raw = None
    if isinstance(start, dict):
        raw = start.get("date")
    elif isinstance(start, str):
        raw = start
    if raw is None:
        raw = (summary.get("session") or {}).get("timestamp")
    if raw is None:
        return None
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(OSLO)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_streams(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def value(row: dict[str, str], key: str) -> float | None:
    raw = row.get(key)
    if raw in ("", None):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


if __name__ == "__main__":
    main()
