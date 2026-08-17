#!/usr/bin/env python3
"""Persist one Intervals.icu MCP activity and stream file for local analysis."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("outputs/intervals")


def load_activity(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"activity JSON is invalid: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("activity JSON must contain one object")
    activity = payload.get("activity", payload)
    if not isinstance(activity, dict):
        raise ValueError("activity JSON field 'activity' must contain one object")
    return activity


def save_activity_package(
    *,
    activity_json: Path,
    streams_file: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    activity = load_activity(activity_json)
    activity_id = activity.get("id")
    if activity_id is None or isinstance(activity_id, bool) or not str(activity_id):
        raise ValueError("activity is missing a valid id")
    start_date = str(activity.get("start_date_local") or "")[:10]
    try:
        parsed_date = date.fromisoformat(start_date)
    except ValueError as exc:
        raise ValueError("activity is missing a valid start_date_local") from exc
    if not streams_file.is_file():
        raise ValueError(f"streams file does not exist: {streams_file}")

    activity_dir = output_dir / "activities" / f"{parsed_date.isoformat()}_{activity_id}"
    activity_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = activity_dir / "activity.json"
    streams_path = activity_dir / "streams.csv"
    metadata_path.write_text(
        json.dumps(activity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(streams_file, streams_path)

    if json.loads(metadata_path.read_text(encoding="utf-8")) != activity:
        raise RuntimeError("saved activity metadata did not verify")
    if streams_path.read_bytes() != streams_file.read_bytes():
        raise RuntimeError("saved activity streams did not verify")
    return {
        "activity_dir": activity_dir,
        "activity_metadata": metadata_path,
        "streams_csv": streams_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save Intervals.icu MCP activity metadata and streams for local analysis."
    )
    parser.add_argument("--activity-json", required=True, type=Path)
    parser.add_argument("--streams-file", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        artifacts = save_activity_package(
            activity_json=args.activity_json,
            streams_file=args.streams_file,
            output_dir=args.output_dir,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: str(value) for key, value in artifacts.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
