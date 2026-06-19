"""Shared local analysis helpers for saved Intervals.icu artifacts."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Iterable


DATA_DIR = Path("data/intervals-old")

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
class CachedActivity:
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


def load_activity(activity_dir: str | Path) -> CachedActivity:
    """Load one saved activity directory."""

    path = Path(activity_dir)
    metadata = json.loads((path / "activity.json").read_text(encoding="utf-8"))
    with (path / "streams.csv").open(newline="", encoding="utf-8-sig") as file:
        streams = list(csv.DictReader(file))
    return CachedActivity(activity_dir=path, metadata=metadata, streams=streams)


def usable_analysis_fields(
    activity: CachedActivity,
    fields: Iterable[str] = CORE_STREAMS,
) -> list[str]:
    """Return requested fields after applying Intervals.icu ignore flags."""

    ignored = activity.ignored_stream_fields
    return [field for field in fields if field not in ignored]


def resolve_activity_ref(ref: str, *, data_dir: str | Path = DATA_DIR) -> CachedActivity:
    """Resolve ``latest``, an Intervals activity id, dir name or path."""

    data_path = Path(data_dir)
    if ref == "latest":
        candidates = sorted(
            iter_cached_activities(data_path),
            key=lambda activity: activity.start_date_local,
        )
        if not candidates:
            raise FileNotFoundError(f"No saved activities under {data_path / 'activities'}")
        return candidates[-1]

    candidate_path = Path(ref)
    if candidate_path.exists():
        return load_activity(candidate_path)

    data_candidate = data_path / "activities" / ref
    if data_candidate.exists():
        return load_activity(data_candidate)

    matches = sorted((data_path / "activities").glob(f"*_{ref}"))
    if not matches and ref.startswith("i"):
        matches = sorted((data_path / "activities").glob(f"*_{ref[1:]}"))
    if matches:
        return load_activity(matches[-1])

    raise FileNotFoundError(f"Could not resolve saved activity: {ref}")


def iter_cached_activities(data_dir: str | Path = DATA_DIR) -> Iterable[CachedActivity]:
    """Yield saved activities sorted by activity directory name."""

    activities_dir = Path(data_dir) / "activities"
    for activity_dir in sorted(activities_dir.iterdir()):
        if (activity_dir / "activity.json").exists() and (activity_dir / "streams.csv").exists():
            yield load_activity(activity_dir)


def value(row: dict[str, str], key: str) -> float | None:
    """Parse a numeric stream value."""

    raw = row.get(key)
    if raw in ("", None):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def stream_values(rows: Iterable[dict[str, str]], key: str) -> list[float]:
    """Return non-empty numeric values for one stream key."""

    return [parsed for row in rows if (parsed := value(row, key)) is not None]


def summarize_rows(
    rows: list[dict[str, str]],
    fields: Iterable[str] = CORE_STREAMS,
) -> dict[str, dict[str, float] | None]:
    """Summarize rows with avg/min/max/start/end/count for each field."""

    summary: dict[str, dict[str, float] | None] = {}
    for field in fields:
        values = stream_values(rows, field)
        if not values:
            summary[field] = None
            continue
        summary[field] = {
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
            "start": values[0],
            "end": values[-1],
            "count": float(len(values)),
        }
    return summary


def data_quality_summary(
    rows: list[dict[str, str]],
    fields: Iterable[str] = CORE_STREAMS,
) -> dict[str, dict[str, float | int | bool]]:
    """Summarize missing values and longer gaps for each stream field."""

    result: dict[str, dict[str, float | int | bool]] = {}
    total = len(rows)
    for field in fields:
        missing = 0
        longest_gap = 0
        current_gap = 0
        present = 0
        for row in rows:
            if value(row, field) is None:
                missing += 1
                current_gap += 1
                longest_gap = max(longest_gap, current_gap)
            else:
                present += 1
                current_gap = 0
        result[field] = {
            "total": total,
            "present": present,
            "missing": missing,
            "missing_fraction": missing / total if total else 0.0,
            "longest_gap": longest_gap,
            "has_values": present > 0,
            "meaningful_gap": longest_gap >= 30 or missing / total >= 0.05 if total else False,
        }
    return result


def half_drift(
    rows: list[dict[str, str]],
    fields: Iterable[str] = CORE_STREAMS,
) -> dict[str, float | None]:
    """Return second-half average minus first-half average for each field."""

    if len(rows) < 2:
        return {field: None for field in fields}
    split = len(rows) // 2
    first = summarize_rows(rows[:split], fields)
    second = summarize_rows(rows[split:], fields)
    drift: dict[str, float | None] = {}
    for field in fields:
        first_avg = first[field]["avg"] if first[field] else None
        second_avg = second[field]["avg"] if second[field] else None
        drift[field] = (
            second_avg - first_avg
            if first_avg is not None and second_avg is not None
            else None
        )
    return drift


def summarize_block(
    rows: list[dict[str, str]],
    *,
    start_index: int,
    end_index: int,
    label: str,
    fields: Iterable[str] = CORE_STREAMS,
    detection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a standard block summary for chat-oriented analysis."""

    block_rows = rows[start_index:end_index]
    start_time = value(rows[start_index], "time") if rows and start_index < len(rows) else None
    end_row_index = max(start_index, end_index - 1)
    end_time = value(rows[end_row_index], "time") if rows and end_row_index < len(rows) else None
    duration_seconds = (
        end_time - start_time + 1
        if start_time is not None and end_time is not None and end_time >= start_time
        else len(block_rows)
    )
    return {
        "label": label,
        "start_index": start_index,
        "end_index": end_index,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "duration_minutes": duration_seconds / 60 if duration_seconds is not None else None,
        "detection": detection or {},
        "summary": summarize_rows(block_rows, fields),
        "drift": half_drift(block_rows, fields),
        "data_quality": data_quality_summary(block_rows, fields),
    }


def interval_rows(activity: CachedActivity, interval: dict[str, Any]) -> list[dict[str, str]]:
    """Return stream rows for one Intervals.icu interval."""

    start = int(interval.get("start_index") or 0)
    end = int(interval.get("end_index") or start)
    return activity.streams[start:end]


def intervals_by_type(activity: CachedActivity, interval_type: str) -> list[list[dict[str, str]]]:
    """Return stream row slices for intervals matching type, e.g. WORK."""

    wanted = interval_type.upper()
    return [
        interval_rows(activity, interval)
        for interval in activity.intervals
        if str(interval.get("type") or "").upper() == wanted
    ]


def rows_with_values(rows: list[dict[str, str]], *fields: str) -> list[dict[str, str]]:
    """Keep rows that have numeric values for all requested fields."""

    return [row for row in rows if all(value(row, field) is not None for field in fields)]


def has_moxy(rows: list[dict[str, str]]) -> bool:
    """Return true when rows contain usable SmO2 and THb values."""

    return bool(rows_with_values(rows, "smo2", "thb"))


def moxy_interval_summary(activity: CachedActivity) -> list[dict[str, Any]]:
    """Summarize Moxy data by Intervals.icu interval."""

    summaries = []
    for index, interval in enumerate(activity.intervals, start=1):
        rows = rows_with_values(interval_rows(activity, interval), "smo2", "thb")
        if not rows:
            continue
        summaries.append(
            {
                "index": index,
                "type": interval.get("type"),
                "rows": len(rows),
                "stats": summarize_rows(rows),
                "drift": half_drift(rows),
            }
        )
    return summaries


def recovery_reoxygenation(activity: CachedActivity) -> list[dict[str, Any]]:
    """Calculate SmO2 rise and peak reached in each recovery interval."""

    recoveries = []
    for index, interval in enumerate(activity.intervals, start=1):
        if str(interval.get("type") or "").upper() != "RECOVERY":
            continue
        rows = rows_with_values(interval_rows(activity, interval), "smo2")
        if not rows:
            continue
        smo2 = stream_values(rows, "smo2")
        thb = stream_values(rows, "thb")
        recoveries.append(
            {
                "index": index,
                "rows": len(rows),
                "smo2_start": smo2[0],
                "smo2_min": min(smo2),
                "smo2_peak": max(smo2),
                "smo2_end": smo2[-1],
                "smo2_rise_start_to_peak": max(smo2) - smo2[0],
                "smo2_rise_min_to_peak": max(smo2) - min(smo2),
                "thb_avg": sum(thb) / len(thb) if thb else None,
            }
        )
    return recoveries


def latest_activity_with_moxy(
    *,
    indoor_only: bool = False,
    name_contains: str | None = None,
    require_work_overlap: bool = True,
    data_dir: str | Path = DATA_DIR,
) -> CachedActivity | None:
    """Find the latest saved activity with Moxy values.

    When ``require_work_overlap`` is true, SmO2/THb must overlap at least one
    WORK interval. This avoids selecting activities where Moxy only appears in
    warm-up or cooldown.
    """

    activities = sorted(
        iter_cached_activities(data_dir),
        key=lambda activity: activity.start_date_local,
        reverse=True,
    )
    for activity in activities:
        if indoor_only and activity.metadata.get("type") != "VirtualRide":
            continue
        if name_contains and name_contains.lower() not in activity.name.lower():
            continue
        if not has_moxy(activity.streams):
            continue
        if require_work_overlap:
            work_has_moxy = any(has_moxy(rows) for rows in intervals_by_type(activity, "WORK"))
            if not work_has_moxy:
                continue
        return activity
    return None


def detect_steady_power_segment(
    rows: list[dict[str, str]],
    *,
    target_candidates: tuple[int, ...] = (195, 200, 205),
    warmup_fallback_seconds: int = 12 * 60,
    cooldown_fallback_seconds: int = 3 * 60,
    tolerance: float = 8,
    stable_seconds: int = 5 * 60,
    step_lookback_seconds: int = 90,
    cooldown_target: int = 150,
    cooldown_tolerance: float = 15,
) -> tuple[list[dict[str, str]], int, int, int]:
    """Detect a steady work segment from a power trace.

    Useful for VT1 rides where warm-up and cooldown should be excluded.
    The user's VT1 rides usually have three power segments: a warm-up ramp below
    target, steady VT1 around 200-205 W, and a steady cooldown around 150 W.
    Detect start from consistent target power and end from consistent cooldown
    power near the end of the file.
    """

    watts = [value(row, "watts") or 0.0 for row in rows]
    if len(watts) < warmup_fallback_seconds + cooldown_fallback_seconds + 60:
        return rows, 0, len(rows), round(median(watts) / 5) * 5

    middle = watts[int(len(watts) * 0.2) : int(len(watts) * 0.8)]
    median_power = median(middle)
    target = min(target_candidates, key=lambda candidate: abs(candidate - median_power))

    smoothed = rolling_mean(watts, 30)
    start = warmup_fallback_seconds
    for index in range(6 * 60, len(watts) - stable_seconds):
        block = smoothed[index : index + stable_seconds]
        block_mean = sum(block) / len(block)
        in_range = sum(1 for watt in block if abs(watt - target) <= tolerance)
        if abs(block_mean - target) <= tolerance and in_range / len(block) >= 0.8:
            step_start = find_power_step_start(
                smoothed,
                index,
                target=target,
                lookback_seconds=step_lookback_seconds,
            )
            start = first_consistent_target_power(
                smoothed,
                step_start,
                target=target,
                tolerance=tolerance,
                hold_seconds=45,
            )
            break

    end = find_cooldown_start(
        smoothed,
        start_index=max(start + 10 * 60, len(watts) // 2),
        work_target=target,
        cooldown_target=cooldown_target,
        tolerance=cooldown_tolerance,
    )
    if end is None:
        end = len(rows) - cooldown_fallback_seconds

    if end <= start:
        end = len(rows)
    return rows[start:end], start, end, target


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

    raw_values = [value(row, field) or 0.0 for row in rows]
    values = rolling_mean(raw_values, smoothing_seconds)
    blocks: list[PowerBlock] = []
    start: int | None = None
    last_match: int | None = None
    gap = 0

    def matches(sample: float) -> bool:
        if target is not None:
            return abs(sample - target) <= tolerance
        return sample >= float(threshold)

    for index, sample in enumerate(values):
        if matches(sample):
            if start is None:
                start = index
            last_match = index
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap > max_gap_seconds:
            assert last_match is not None
            _append_power_block(
                blocks,
                start=start,
                end=last_match + 1,
                min_seconds=min_seconds,
                target=target,
                threshold=threshold,
                tolerance=tolerance,
                max_gap_seconds=max_gap_seconds,
                smoothing_seconds=smoothing_seconds,
            )
            start = None
            last_match = None
            gap = 0

    if start is not None and last_match is not None:
        _append_power_block(
            blocks,
            start=start,
            end=last_match + 1,
            min_seconds=min_seconds,
            target=target,
            threshold=threshold,
            tolerance=tolerance,
            max_gap_seconds=max_gap_seconds,
            smoothing_seconds=smoothing_seconds,
        )

    return blocks


def _append_power_block(
    blocks: list[PowerBlock],
    *,
    start: int,
    end: int,
    min_seconds: int,
    target: float | None,
    threshold: float | None,
    tolerance: float,
    max_gap_seconds: int,
    smoothing_seconds: int,
) -> None:
    if end - start < min_seconds:
        return
    label = f"target_{target:g}" if target is not None else f"threshold_{threshold:g}"
    blocks.append(
        PowerBlock(
            label=f"{label}_{len(blocks) + 1}",
            start_index=start,
            end_index=end,
            detection={
                "target": target,
                "threshold": threshold,
                "tolerance": tolerance,
                "max_gap_seconds": max_gap_seconds,
                "smoothing_seconds": smoothing_seconds,
            },
        )
    )


def rolling_mean(values: list[float], window: int) -> list[float]:
    """Return trailing rolling mean values."""

    if window <= 1:
        return values[:]
    result = []
    total = 0.0
    queue = []
    for value_ in values:
        queue.append(value_)
        total += value_
        if len(queue) > window:
            total -= queue.pop(0)
        result.append(total / len(queue))
    return result


def find_power_step_start(
    smoothed_watts: list[float],
    stable_index: int,
    *,
    target: int,
    lookback_seconds: int,
) -> int:
    """Find the start of the step into steady target power."""

    search_start = max(0, stable_index - lookback_seconds)
    threshold = target - 10
    for index in range(stable_index, search_start, -1):
        before = smoothed_watts[max(0, index - 30) : index]
        after = smoothed_watts[index : min(len(smoothed_watts), index + 30)]
        if not before or not after:
            continue
        before_mean = sum(before) / len(before)
        after_mean = sum(after) / len(after)
        if before_mean < threshold and after_mean >= threshold:
            return index
    return stable_index


def first_consistent_target_power(
    smoothed_watts: list[float],
    start_index: int,
    *,
    target: int,
    tolerance: float,
    hold_seconds: int,
) -> int:
    """Find first point where power consistently reaches target."""

    threshold = target - tolerance
    for index in range(start_index, len(smoothed_watts) - hold_seconds):
        block = smoothed_watts[index : index + hold_seconds]
        in_range = sum(1 for watt in block if watt >= threshold)
        if in_range / hold_seconds >= 0.85:
            return index
    return start_index


def find_cooldown_start(
    smoothed_watts: list[float],
    *,
    start_index: int,
    work_target: int,
    cooldown_target: int,
    tolerance: float,
) -> int | None:
    """Find the transition from steady work to cooldown.

    Use future cooldown stability only after confirming the preceding minute was
    still near work target. This avoids pulling the end point backward just
    because a long look-ahead window contains the cooldown.
    """

    for index in range(start_index, len(smoothed_watts) - 120):
        previous = smoothed_watts[max(0, index - 60) : index]
        next_30 = smoothed_watts[index : index + 30]
        next_120 = smoothed_watts[index : index + 120]
        if not previous or len(next_30) < 30 or len(next_120) < 120:
            continue

        previous_mean = sum(previous) / len(previous)
        next_30_mean = sum(next_30) / len(next_30)
        next_120_mean = sum(next_120) / len(next_120)
        if (
            previous_mean >= work_target - 15
            and next_30_mean <= cooldown_target + 20
            and abs(next_120_mean - cooldown_target) <= tolerance + 10
        ):
            return index
    return None


def load_wellness_range(
    oldest: str | date,
    newest: str | date,
    *,
    data_dir: str | Path = DATA_DIR,
) -> list[dict[str, Any]]:
    """Load a saved wellness JSON range."""

    oldest_value = oldest.isoformat() if isinstance(oldest, date) else oldest
    newest_value = newest.isoformat() if isinstance(newest, date) else newest
    path = Path(data_dir) / "wellness" / f"{oldest_value}_{newest_value}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def wellness_baseline(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """Summarize common readiness fields from wellness rows."""

    fields = ["hrv", "restingHR", "sleepSecs", "sleepScore", "spO2", "steps"]
    baseline: dict[str, float | None] = {}
    for field in fields:
        values = []
        for row in rows:
            raw = row.get(field)
            if raw is not None:
                values.append(float(raw))
        baseline[field] = sum(values) / len(values) if values else None
    return baseline
