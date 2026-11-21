#!/usr/bin/env python3
"""Persist one Intervals.icu MCP activity and stream file for local analysis."""

from __future__ import annotations

import argparse
import json
import hashlib
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("outputs/intervals")


def load_activity(path: Path, *, activity_id: str | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"activity JSON is invalid: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("activity JSON must contain one object")
    if "activities" in payload:
        if activity_id is None:
            raise ValueError("batch activity JSON requires a stream manifest activity_id")
        activities = payload["activities"]
        if not isinstance(activities, list) or not all(isinstance(item, dict) for item in activities):
            raise ValueError("activity JSON field 'activities' must contain a list of objects")
        matches = [item for item in activities if str(item.get("id")) == activity_id]
        if len(matches) != 1:
            raise ValueError(
                f"expected one batch activity matching stream manifest activity_id {activity_id!r}; "
                f"found {len(matches)}"
            )
        return matches[0]
    activity = payload.get("activity", payload)
    if not isinstance(activity, dict):
        raise ValueError("activity JSON field 'activity' must contain one object")
    if "activity_id" in payload and str(payload["activity_id"]) != str(activity.get("id")):
        raise ValueError("activity envelope identity does not match activity")
    return activity


def save_activity_package(
    *,
    activity_json: Path,
    streams_manifest: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    manifest = json.loads(streams_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("stream manifest JSON must contain one object")
    manifest_id = manifest.get("activity_id")
    if manifest_id is None or isinstance(manifest_id, bool) or not str(manifest_id):
        raise ValueError("stream manifest is missing a valid activity_id")
    activity = load_activity(activity_json, activity_id=str(manifest_id))
    activity_id = activity.get("id")
    if activity_id is None or isinstance(activity_id, bool) or not str(activity_id):
        raise ValueError("activity is missing a valid id")
    if str(manifest_id) != str(activity_id):
        raise ValueError("stream manifest activity_id does not match activity metadata")
    start_date = str(activity.get("start_date_local") or "")[:10]
    try:
        parsed_date = date.fromisoformat(start_date)
    except ValueError as exc:
        raise ValueError("activity is missing a valid start_date_local") from exc
    if not isinstance(manifest.get("streams_file"), str) or not manifest["streams_file"]:
        raise ValueError("stream manifest is missing streams_file")
    streams_file = Path(manifest["streams_file"])
    if not streams_file.is_absolute():
        streams_file = streams_manifest.parent / streams_file
    if not streams_file.is_file():
        raise ValueError(f"streams file does not exist: {streams_file}")

    stream_bytes = streams_file.read_bytes()
    if hashlib.sha256(stream_bytes).hexdigest() != manifest.get("sha256"):
        raise ValueError("stream file checksum does not match its manifest")

    activity_dir = output_dir / "activities" / f"{parsed_date.isoformat()}_{activity_id}"
    activity_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = activity_dir / "activity.json"
    streams_path = activity_dir / "streams.csv"
    metadata_path.write_text(
        json.dumps(activity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    streams_path.write_bytes(stream_bytes)

    if json.loads(metadata_path.read_text(encoding="utf-8")) != activity:
        raise RuntimeError("saved activity metadata did not verify")
    if streams_path.read_bytes() != stream_bytes:
        raise RuntimeError("saved activity streams did not verify")
    provenance_path = activity_dir / "streams-manifest.json"
    provenance_path.write_text(json.dumps({**manifest, "streams_file": "streams.csv"}, indent=2) + "\n", encoding="utf-8")
    return {
        "streams_manifest": provenance_path,
        "activity_dir": activity_dir,
        "activity_metadata": metadata_path,
        "streams_csv": streams_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save Intervals.icu MCP activity metadata and streams for local analysis.",
        epilog="Pass the returned activity_dir to activity_inspect.py.",
    )
    parser.add_argument(
        "--activity-json", required=True, type=Path,
        help="Full activity or batch JSON. The stream manifest selects the activity by ID.",
    )
    parser.add_argument("--streams-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        artifacts = save_activity_package(
            activity_json=args.activity_json,
            streams_manifest=args.streams_manifest,
            output_dir=args.output_dir,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: str(value) for key, value in artifacts.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
