"""Shared analysis helpers for saved Intervals.icu inputs."""

from __future__ import annotations

import csv
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from physiological_evidence import MAX_MISSING_FRACTION, MAX_SAMPLE_INTERVAL, numeric, timeline, quality, field_summary, matched_windows, prepare_windows
from typing import Any, Iterable


ARTIFACTS_DIR = Path("outputs/intervals")

CORE_STREAMS = [
    "watts",
    "heartrate",
    "cadence",
    "torque",
    "respiration",
    "tidal_volume",
    "tidal_volume_min",
    "smo2",
    "thb",
    "core_temperature",
    "skin_temperature",
    "heat_strain_index",
    "temp",
    "RuuviTemperature",
    "Humidity",
    "RuuviHumidity",
]


@dataclass(frozen=True)
class SavedActivity:
    """A saved Intervals.icu activity plus stream rows."""

    activity_dir: Path
    metadata: dict[str, Any]
    streams: list[dict[str, str]]

    @property
    def id(self) -> str:
        return str(self.metadata.get("id") or self.activity_dir.name)

    @property
    def name(self) -> str:
        return str(self.metadata.get("name") or "")

    @property
    def start_date_local(self) -> str:
        return str(self.metadata.get("start_date_local") or "")

    @property
    def intervals(self) -> list[dict[str, Any]]:
        intervals = self.metadata.get("icu_intervals") or []
        return intervals if isinstance(intervals, list) else []

    @property
    def ignored_stream_fields(self) -> set[str]:
        """Stream fields that Intervals.icu has explicitly marked unreliable."""

        ignored: set[str] = set()
        if self.metadata.get("icu_ignore_hr"):
            ignored.add("heartrate")
        if self.metadata.get("icu_ignore_power"):
            ignored.update({"watts", "torque"})
        return ignored


@dataclass(frozen=True)
class PowerBlock:
    """A detected contiguous power block."""

    label: str
    start_index: int
    end_index: int
    detection: dict[str, Any]


def load_streams_csv(path: str | Path) -> list[dict[str, str]]:
    """Load an Intervals.icu streams CSV with normalized header names."""

    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        reader.fieldnames = [
            normalize_stream_fieldname(field)
            for field in (reader.fieldnames or [])
        ]
        rows = [
            {
                normalize_stream_fieldname(key): value
                for key, value in row.items()
            }
            for row in reader
        ]

        # Some source exports end with an empty delimiter row, not a sample.
        # Trim only the suffix so saved interval indices remain unchanged.
        while rows and all(v in (None, "") for v in rows[-1].values()):
            rows.pop()
        return rows


def normalize_stream_fieldname(fieldname: str | None) -> str:
    """Return a stable stream field name from CSV headers."""

    return str(fieldname or "").lstrip("\ufeff").strip()


def load_activity(activity_dir: str | Path) -> SavedActivity:
    """Load one saved activity directory."""

    path = Path(activity_dir)
    metadata = load_activity_metadata(path)
    streams = load_streams_csv(path / "streams.csv")
    activity = SavedActivity(activity_dir=path, metadata=metadata, streams=streams)
    # Mask unreliable channels before any effort search, matching or normalization.
    # Keep the sample clock and the original saved files intact.
    for field in activity.ignored_stream_fields:
        for row in streams:
            row.pop(field, None)
    return activity


def load_activity_metadata(activity_dir: str | Path) -> dict[str, Any]:
    """Load only activity metadata, without reading the stream CSV."""

    path = Path(activity_dir)
    metadata_payload = json.loads((path / "activity.json").read_text(encoding="utf-8"))
    if isinstance(metadata_payload, dict) and isinstance(metadata_payload.get("activity"), dict):
        return metadata_payload["activity"]
    return metadata_payload


def usable_analysis_fields(
    activity: SavedActivity,
    fields: Iterable[str] = CORE_STREAMS,
) -> list[str]:
    """Return requested fields after applying Intervals.icu ignore flags."""

    ignored = activity.ignored_stream_fields
    return [field for field in fields if field not in ignored]


def resolve_activity_ref(ref: str, *, artifacts_dir: str | Path = ARTIFACTS_DIR) -> SavedActivity:
    """Resolve an Intervals activity id, dir name, dir path or file path."""

    artifacts_path = Path(artifacts_dir)
    candidate_path = Path(ref)
    if candidate_path.exists():
        candidate_path = activity_dir_from_path(candidate_path)
        return load_activity(candidate_path)

    artifacts_candidate = artifacts_path / "activities" / ref
    if artifacts_candidate.exists():
        return load_activity(artifacts_candidate)

    matches = sorted((artifacts_path / "activities").glob(f"*_{ref}"))
    if not matches and ref.startswith("i"):
        matches = sorted((artifacts_path / "activities").glob(f"*_{ref[1:]}"))
    if matches:
        return load_activity(matches[-1])

    raise FileNotFoundError(f"Could not resolve saved activity: {ref}")


def activity_dir_from_path(path: Path) -> Path:
    """Return an activity directory from either a directory or known file path."""

    activity_dir = path.parent if path.is_file() else path
    activity_json = activity_dir / "activity.json"
    streams_csv = activity_dir / "streams.csv"
    if not activity_json.exists() or not streams_csv.exists():
        missing = [
            str(candidate)
            for candidate in (activity_json, streams_csv)
            if not candidate.exists()
        ]
        message = (
            f"Expected an activity directory with activity.json and streams.csv; missing: "
            f"{', '.join(missing)}"
        )
        if (activity_dir / "activities").is_dir():
            message += ". Pass the activity_dir returned by save_intervals_activity.py."
        raise FileNotFoundError(message)
    return activity_dir


def value(row: dict[str, str], key: str) -> float | None:
    """Parse a numeric stream value."""

    return numeric(row, key)


def summarize_rows(
    rows: list[dict[str, str]],
    fields: Iterable[str] = CORE_STREAMS,
) -> dict[str, dict[str, float] | None]:
    """Summarize rows with avg/min/max/start/end/count for each field."""

    clock = timeline(rows)
    return {field: field_summary(rows, field, clock) for field in fields}


def data_quality_summary(
    rows: list[dict[str, str]],
    fields: Iterable[str] = CORE_STREAMS,
) -> dict[str, dict[str, float | int | bool]]:
    """Summarize missing values and longer gaps for each stream field."""

    clock = timeline(rows)
    return {field: quality(rows, field, clock) for field in fields}


def summarize_block(
    rows: list[dict[str, str]],
    *,
    start_index: int,
    end_index: int,
    label: str,
    fields: Iterable[str] = CORE_STREAMS,
    detection: dict[str, Any] | None = None,
    window_context=None,
) -> dict[str, Any]:
    """Return a standard block summary for chat-oriented analysis."""

    block_rows = rows[start_index:end_index]
    start_time = value(rows[start_index], "time") if rows and start_index < len(rows) else None
    end_row_index = max(start_index, end_index - 1)
    end_time = value(rows[end_row_index], "time") if rows and end_row_index < len(rows) else None
    duration_seconds = (detection or {}).get("duration_seconds")
    if duration_seconds is None:
        clock = timeline(block_rows)
        if clock is not None:
            duration_seconds = clock[2]
        elif start_time is not None and end_time is not None and end_time >= start_time:
            duration_seconds = end_time - start_time
        else:
            duration_seconds = len(block_rows)
    fields = list(fields)
    comparison = matched_windows(block_rows, fields, window_context=(
        window_context if window_context is not None else prepare_windows(rows)))
    return {
        "comparison": comparison,
        "label": label,
        "start_index": start_index,
        "end_index": end_index,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "duration_minutes": duration_seconds / 60 if duration_seconds is not None else None,
        "detection": detection or {},
        "summary": summarize_rows(block_rows, fields),
        "drift": {f: comparison["fields"].get(f, {}).get("delta") for f in fields},
        "relative_to_power_drift": {f: comparison["fields"].get(f, {}).get("per_watt_change_pct") for f in ("heartrate", "respiration", "tidal_volume_min")},
        "data_quality": data_quality_summary(block_rows, fields),
    }


def detect_pause_segments(
    rows: list[dict[str, str]],
    *,
    min_seconds: float = 60,
    speed_threshold: float = 0.6,
    watts_threshold: float = 20,
) -> list[dict[str, Any]]:
    """Detect likely stopped/coasting pause segments from stream rows."""

    segments: list[dict[str, Any]] = []
    start_index: int | None = None
    for index, row in enumerate(rows):
        if value(row, "time") is None:
            if start_index is not None:
                append_pause_segment(
                    segments,
                    rows,
                    start_index=start_index,
                    end_index=index,
                    min_seconds=min_seconds,
                    speed_threshold=speed_threshold,
                    watts_threshold=watts_threshold,
                )
                start_index = None
            continue
        is_pause = pause_row(
            row,
            speed_threshold=speed_threshold,
            watts_threshold=watts_threshold,
        )
        if is_pause and start_index is None:
            start_index = index
        if (not is_pause or index == len(rows) - 1) and start_index is not None:
            end_index = index + 1 if is_pause and index == len(rows) - 1 else index
            append_pause_segment(
                segments,
                rows,
                start_index=start_index,
                end_index=end_index,
                min_seconds=min_seconds,
                speed_threshold=speed_threshold,
                watts_threshold=watts_threshold,
            )
            start_index = None
    return segments


def pause_row(
    row: dict[str, str],
    *,
    speed_threshold: float,
    watts_threshold: float,
) -> bool:
    """Return true when a stream row looks like a stop/pause."""

    speed = value(row, "velocity_smooth") or 0.0
    watts = value(row, "watts") or 0.0
    return speed < speed_threshold and watts < watts_threshold


def append_pause_segment(
    segments: list[dict[str, Any]],
    rows: list[dict[str, str]],
    *,
    start_index: int,
    end_index: int,
    min_seconds: float,
    speed_threshold: float,
    watts_threshold: float,
) -> None:
    """Append a pause segment if it has a usable duration."""

    start_row = rows[start_index]
    end_row = rows[max(start_index, end_index - 1)]
    start_time = value(start_row, "time")
    end_time = value(end_row, "time")
    if start_time is None or end_time is None or end_time < start_time:
        return
    duration_s = end_time - start_time + 1
    if duration_s < min_seconds:
        return
    mid_row = rows[(start_index + max(start_index, end_index - 1)) // 2]
    segments.append(
        {
            "start_index": start_index,
            "end_index": end_index,
            "start_s": round(start_time),
            "end_s": round(end_time),
            "duration_s": round(duration_s),
            "mid_s": round((start_time + end_time) / 2),
            "distance_m": rounded_value(mid_row, "distance"),
            "lat": rounded_value(mid_row, "lat", digits=6),
            "lng": rounded_value(mid_row, "lng", digits=6),
            "hr_start": rounded_value(start_row, "heartrate"),
            "hr_end": rounded_value(end_row, "heartrate"),
            "detection": {
                "method": "speed_and_power",
                "speed_threshold_mps": speed_threshold,
                "watts_threshold": watts_threshold,
                "min_seconds": min_seconds,
            },
        }
    )


def rounded_value(row: dict[str, str], field: str, *, digits: int = 0) -> float | int | None:
    """Return a rounded stream value for compact output."""

    parsed = value(row, field)
    if parsed is None:
        return None
    rounded = round(parsed, digits)
    return int(rounded) if digits == 0 else rounded


def interval_rows(activity: SavedActivity, interval: dict[str, Any]) -> list[dict[str, str]]:
    """Return stream rows for one Intervals.icu interval."""

    start = int(interval.get("start_index") or 0)
    end = int(interval.get("end_index") or start)
    return activity.streams[start:end]


def rows_with_values(rows: list[dict[str, str]], *fields: str) -> list[dict[str, str]]:
    """Keep rows that have numeric values for all requested fields."""

    return [row for row in rows if all(value(row, field) is not None for field in fields)]


def _smo2_window_mean(rows: list[dict[str, str]], start: float, end: float) -> float | None:
    """Describe a fixed elapsed window without filling gaps with earlier samples."""
    clock = timeline(rows)
    if clock is None:
        return None
    times, weights, _ = clock
    nominal = weights[-1]
    if times[0] > start or times[-1] + nominal < end:
        return None
    covered = total = 0.0
    for row, time, weight in zip(rows, times, weights):
        duration = min(end, time + min(weight, nominal)) - max(start, time)
        level = value(row, "smo2")
        if duration > 0 and level is not None:
            covered += duration
            total += duration * level
    if 1 - covered / (end - start) >= MAX_MISSING_FRACTION:
        return None
    return total / covered


def recovery_reoxygenation(activity: SavedActivity) -> list[dict[str, Any]]:
    """Calculate SmO2 rise and peak reached in each recovery interval."""

    recoveries = []
    for index, interval in enumerate(activity.intervals, start=1):
        if str(interval.get("type") or "").upper() != "RECOVERY":
            continue
        rows = interval_rows(activity, interval)
        if not rows:
            continue
        coverage = quality(rows, "smo2")
        start = int(interval.get("start_index") or 0)
        previous = activity.intervals[index - 2] if index > 1 else {}
        boundary = activity.streams[start - 1:start + 1] if start > 0 else []
        boundary_ok = (
            str(previous.get("type")).upper() == "WORK"
            and previous.get("end_index") == start
            and len(boundary) == 2 and quality(boundary, "smo2")["usable"]
            and value(boundary[1], "time") - value(boundary[0], "time") <= MAX_SAMPLE_INTERVAL
        )
        result = {"index": index, "rows": len(rows), "quality": coverage,
                  "work_end_boundary_observed": boundary_ok,
                  "smo2_30s_change_status": "unavailable"}
        if boundary_ok:
            pause_start = value(boundary[1], "time")
            end_work = _smo2_window_mean(interval_rows(activity, previous), pause_start - 30, pause_start)
            at_30s = _smo2_window_mean(rows, pause_start + 25, pause_start + 30)
            if end_work is not None and at_30s is not None:
                result.update(smo2_30s_change_status="observed",
                              smo2_change_end_work_to_30s_pp=at_30s - end_work)
        if not coverage["usable"] or not boundary_ok or value(rows[-1], "smo2") is None:
            recoveries.append({**result, "status": "unavailable"})
            continue
        samples = [(value(row, "time"), level) for row in rows if (level := value(row, "smo2")) is not None]
        smo2 = [level for _, level in samples]
        nadir = smo2.index(min(smo2))
        peak_after = max(range(nadir, len(samples)), key=smo2.__getitem__)
        thb = field_summary(rows, "thb")
        recoveries.append(
            {
                **result,
                "status": "observed",
                "work_end_smo2": value(boundary[0], "smo2"),
                "smo2_start": smo2[0],
                "smo2_min": min(smo2),
                "smo2_peak": max(smo2),
                "smo2_end": smo2[-1],
                "smo2_rise_start_to_peak": max(smo2) - smo2[0],
                "smo2_min_at_s": samples[nadir][0],
                "smo2_peak_after_min_at_s": samples[peak_after][0],
                "smo2_peak_after_min": smo2[peak_after],
                "smo2_rise_min_to_peak": smo2[peak_after] - smo2[nadir],
                "thb_avg": thb["avg"] if thb else None,
            }
        )
    return recoveries


def detect_steady_finish(
    rows: list[dict[str, str]], target: float, intervals: list[dict[str, Any]],
) -> PowerBlock | None:
    """Find a single sustained finish at the prescribed power after harder work."""
    tolerance = 10
    harder_than = target + tolerance
    source_end = max((
        interval["end_index"] for interval in intervals
        if interval.get("type") == "WORK"
        and (numeric(interval, "average_watts") or 0) > harder_than
        and isinstance(interval.get("end_index"), int)
    ), default=0)
    # Source laps may be missing or group several efforts. Check the trace too.
    harder = detect_power_blocks(
        rows, threshold=harder_than + 1, min_seconds=30,
        max_gap_seconds=2, smoothing_seconds=5,
    )
    after = max(source_end, harder[-1].end_index if harder else 0)
    at_target = detect_power_blocks(rows, target=target, tolerance=tolerance, min_seconds=300)
    candidates = [block for block in at_target if block.start_index >= after]
    if len(candidates) != 1:
        return None
    block = candidates[0]
    # Alternating efforts can average to the target under the rolling mean.
    _, widths, _ = timeline(rows)
    watts = [value(row, "watts") for row in rows]
    if stable_power_block(watts, widths, block, tolerance=25, min_fraction=0.75, max_stddev=35):
        return block
    return None


def detect_power_blocks(
    rows: list[dict[str, str]],
    *,
    target: float | None = None,
    threshold: float | None = None,
    tolerance: float = 10,
    min_seconds: int = 180,
    max_gap_seconds: int = 20,
    smoothing_seconds: int = 15,
    field: str = "watts",
) -> list[PowerBlock]:
    """Detect contiguous power blocks by target range or lower threshold.

    ``target`` detects blocks within ``target +/- tolerance``. ``threshold``
    detects blocks at or above the threshold. Short gaps are tolerated so a
    brief dropout does not split an otherwise coherent interval.
    """

    if target is None and threshold is None:
        raise ValueError("Use either target or threshold")
    if target is not None and threshold is not None:
        raise ValueError("Use only one of target or threshold")

    clock = timeline(rows)
    if clock is None:
        return []
    times, widths, _ = clock
    watts = [value(row, field) for row in rows]
    smoothed = _smooth_power(watts, times, widths, smoothing_seconds)
    return _blocks_from_smoothed_power(
        smoothed, times, widths, target=target, threshold=threshold,
        tolerance=tolerance, min_seconds=min_seconds, max_gap_seconds=max_gap_seconds,
        smoothing_seconds=smoothing_seconds,
    )


def _smooth_power(
    watts: list[float | None], times: list[float], widths: list[float], window_seconds: int,
) -> list[float | None]:
    """Trailing time-weighted mean over covered time, evaluated at each sample's end."""
    if window_seconds <= 0:
        return watts
    window = deque()
    integral = 0.0
    result = []
    for index, (power, start, width) in enumerate(zip(watts, times, widths)):
        if power is None or (index and start - times[index - 1] > widths[index - 1]):
            window.clear()
            integral = 0.0
        if power is None:
            result.append(None)
            continue
        end = start + width
        window.append((start, end, power))
        integral += width * power
        cutoff = end - window_seconds
        while window[0][1] <= cutoff:
            left, right, old_power = window.popleft()
            integral -= (right - left) * old_power
        left, right, old_power = window[0]
        if left < cutoff:
            integral -= (cutoff - left) * old_power
            window[0] = (cutoff, right, old_power)
        result.append(integral / (end - window[0][0]))
    return result


def _blocks_from_smoothed_power(
    smoothed: list[float | None], times: list[float], widths: list[float], *,
    target: float | None, threshold: float | None, tolerance: float, min_seconds: int,
    max_gap_seconds: int, smoothing_seconds: int,
) -> list[PowerBlock]:
    """Bridge short observed excursions, but never join across unrecorded time."""
    blocks = []
    start = None
    last_match = None
    label = f"target_{target:g}" if target is not None else f"threshold_{threshold:g}"

    def finish_block(first: int, last: int) -> None:
        duration = times[last] - times[first] + widths[last]
        if duration >= min_seconds:
            blocks.append(PowerBlock(
                label=f"{label}_{len(blocks) + 1}",
                start_index=first, end_index=last + 1,
                detection={"target": target, "threshold": threshold, "tolerance": tolerance,
                           "max_gap_seconds": max_gap_seconds, "smoothing_seconds": smoothing_seconds,
                           "duration_seconds": duration},
            ))

    for index, (time, power) in enumerate(zip(times, smoothed)):
        if start is not None:
            recording_gap = time - times[index - 1] > widths[index - 1]
            since_match = time - times[last_match] - widths[last_match]
            if recording_gap or since_match > max_gap_seconds:
                finish_block(start, last_match)
                start = None
        if power is None:
            continue
        matches = abs(power - target) <= tolerance if target is not None else power >= threshold
        if matches:
            if start is None:
                start = index
            last_match = index

    if start is not None:
        finish_block(start, last_match)
    return blocks


def detect_stable_power_blocks(
    rows: list[dict[str, str]],
    *,
    min_power: float = 120,
    min_seconds: int = 8 * 60,
    max_gap_seconds: int = 60,
    smoothing_seconds: int = 30,
    bin_size: int = 5,
    tolerance: float = 12,
    raw_stability_tolerance: float = 25,
    min_stability_fraction: float = 0.75,
    max_power_stddev: float = 35,
    max_targets: int = 8,
    field: str = "watts",
) -> list[PowerBlock]:
    """Detect sustained stable power plateaus without knowing the workout type.

    This is intentionally conservative and mainly targets structured indoor
    rides where ERG-like blocks cluster around repeated watt levels. It first
    finds common rounded power targets by covered time, detects sustained
    blocks for each candidate, then resolves overlaps by duration.
    """

    clock = timeline(rows)
    if clock is None:
        return []
    times, widths, _ = clock
    watts = [value(row, field) for row in rows]
    smoothed = _smooth_power(watts, times, widths, smoothing_seconds)
    buckets: dict[int, float] = {}
    for power, seconds in zip(smoothed, widths):
        if power is None or power < min_power:
            continue
        bucket = int(round(power / bin_size) * bin_size)
        buckets[bucket] = buckets.get(bucket, 0.0) + seconds

    target_candidates = [
        target
        for target, seconds in sorted(buckets.items(), key=lambda item: item[1], reverse=True)
        if seconds >= min_seconds
    ]
    selected_targets: list[int] = []
    for target in target_candidates:
        if any(abs(target - selected) <= tolerance for selected in selected_targets):
            continue
        selected_targets.append(target)
        if len(selected_targets) >= max_targets:
            break

    candidates: list[PowerBlock] = []
    for target in selected_targets:
        for block in _blocks_from_smoothed_power(
            smoothed, times, widths,
            target=target, threshold=None,
            tolerance=tolerance,
            min_seconds=min_seconds,
            max_gap_seconds=max_gap_seconds,
            smoothing_seconds=smoothing_seconds,
        ):
            if not stable_power_block(
                watts, widths, block,
                tolerance=raw_stability_tolerance,
                min_fraction=min_stability_fraction,
                max_stddev=max_power_stddev,
            ):
                continue
            candidates.append(
                PowerBlock(
                    label=f"auto_power_{target}_{len(candidates) + 1}",
                    start_index=block.start_index,
                    end_index=block.end_index,
                    detection={
                        **block.detection,
                        "method": "detect_stable_power_blocks",
                        "auto_target": target,
                        "min_power": min_power,
                        "bin_size": bin_size,
                    },
                )
            )

    return remove_overlapping_power_blocks(candidates)


def stable_power_block(
    watts: list[float | None],
    widths: list[float],
    block: PowerBlock,
    *,
    tolerance: float,
    min_fraction: float,
    max_stddev: float,
) -> bool:
    """Return true when raw power is stable enough for a plateau label."""

    indices = range(block.start_index, block.end_index)
    samples = [(watts[i], widths[i]) for i in indices if watts[i] is not None]
    if not samples:
        return False
    seconds = sum(width for _, width in samples)
    average = sum(power * width for power, width in samples) / seconds
    variance = sum((power - average) ** 2 * width for power, width in samples) / seconds
    within_target = sum(width for power, width in samples if abs(power - average) <= tolerance)
    return variance**0.5 <= max_stddev and within_target / seconds >= min_fraction


def remove_overlapping_power_blocks(blocks: list[PowerBlock]) -> list[PowerBlock]:
    """Keep the longest block when auto-detected power plateaus overlap."""

    selected: list[PowerBlock] = []
    for block in sorted(
        blocks,
        key=lambda candidate: candidate.detection["duration_seconds"],
        reverse=True,
    ):
        if any(blocks_overlap(block, existing) for existing in selected):
            continue
        selected.append(block)
    return sorted(selected, key=lambda candidate: candidate.start_index)


def blocks_overlap(left: PowerBlock, right: PowerBlock) -> bool:
    return max(left.start_index, right.start_index) < min(left.end_index, right.end_index)
