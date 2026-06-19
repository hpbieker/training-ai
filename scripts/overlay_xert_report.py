#!/usr/bin/env python3
"""Overlay local sensor streams on Xert Forecast AI report images."""

from __future__ import annotations

import argparse
import csv
from collections import deque
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw


ARTIFACTS_DIR = Path("outputs")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Xert xfair report images and overlay Intervals sensor streams.",
    )
    parser.add_argument(
        "--activity-dir",
        type=Path,
        required=True,
        help="Process one saved Intervals activity artifact directory.",
    )
    parser.add_argument(
        "--xert-path",
        required=True,
        help="Xert activity path, e.g. 4ju77engvgq6h4gv.",
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
        "--artifacts-dir",
        type=Path,
        default=ARTIFACTS_DIR,
    )
    args = parser.parse_args()

    result = process_activity(
        activity_dir=args.activity_dir,
        xert_path=args.xert_path,
        ve_window=args.ve_window,
        smo2_only=args.smo2_only,
        force_download=args.force_download,
        artifacts_dir=args.artifacts_dir,
    )
    print(f"{result['activity_dir']} -> {result['output_png']}")


def process_activity(
    *,
    activity_dir: Path,
    xert_path: str,
    ve_window: int,
    smo2_only: bool,
    force_download: bool,
    artifacts_dir: Path,
) -> dict[str, Path]:
    streams = read_streams(activity_dir / "streams.csv")

    xert_dir = artifacts_dir / "plots" / "xert_report_overlays" / f"{activity_dir.name[:10]}_{xert_path}"
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
