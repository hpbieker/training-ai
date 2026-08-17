#!/usr/bin/env python3
"""Cache activity_inspect.py results as reusable analysis artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analysis import ARTIFACTS_DIR, resolve_activity_ref


PIPELINE_SCHEMA = "training-ai-activity-inspect-pipeline-v1"
PIPELINE_VERSION = "v1"
DEFAULT_OUTPUT_DIR = Path("outputs/activity-inspect")
ANALYSIS_OPTION_FIELDS = {
    "shape",
    "mode",
    "vt1_watts",
    "vt2_watts",
    "target",
    "threshold",
    "tolerance",
    "min_block",
    "max_gap",
    "smoothing",
    "auto_blocks",
    "auto_min_power",
    "auto_min_block",
    "auto_max_gap",
    "auto_smoothing",
    "auto_tolerance",
    "steady_vt1",
    "no_auto_outdoor_vt1",
    "no_auto_indoor_vt1",
    "fields",
    "include_intervals",
    "garmin_json",
}


def parse_analysis_options_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--analysis-options-json must be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(
            "--analysis-options-json must contain one JSON object"
        )
    unknown = sorted(set(payload) - ANALYSIS_OPTION_FIELDS)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unsupported analysis-option field: {unknown[0]}"
        )
    if payload.get("shape", "brief") not in {"brief", "compact", "full"}:
        raise argparse.ArgumentTypeError(
            "analysis-option shape must be brief, compact, or full"
        )
    if payload.get("mode", "default") not in {
        "default", "vt2", "vo2max", "indoor-vt1", "outdoor-vt1"
    }:
        raise argparse.ArgumentTypeError(
            "analysis-option mode is unsupported"
        )
    numeric_fields = {
        "vt1_watts", "vt2_watts", "target", "threshold", "tolerance",
        "auto_min_power", "auto_tolerance",
    }
    for field in numeric_fields & payload.keys():
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise argparse.ArgumentTypeError(
                f"analysis-option {field} must be a non-negative number"
            )
    boolean_fields = {
        "auto_blocks", "steady_vt1", "no_auto_outdoor_vt1",
        "no_auto_indoor_vt1", "include_intervals",
    }
    for field in boolean_fields & payload.keys():
        if not isinstance(payload[field], bool):
            raise argparse.ArgumentTypeError(
                f"analysis-option {field} must be boolean"
            )
    string_fields = {
        "min_block", "max_gap", "smoothing", "auto_min_block",
        "auto_max_gap", "auto_smoothing", "fields", "garmin_json",
    }
    for field in string_fields & payload.keys():
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise argparse.ArgumentTypeError(
                f"analysis-option {field} must be a non-empty string"
            )
    return {"shape": "brief", "mode": "default", **payload}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run activity_inspect.py with stable cache paths and metadata. "
            "This script is intentionally standalone; it does not choose training."
        )
    )
    parser.add_argument("activities", nargs="+", help="Saved activity id, dir, or file path.")
    parser.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--analysis-options-json",
        type=parse_analysis_options_json,
        default={"shape": "brief", "mode": "default"},
        help=(
            "Validated JSON analysis options. Supports shape, mode, watt anchors, "
            "block detection, smoothing, fields, and include_intervals."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when a matching cache artifact is fresh.",
    )
    parser.add_argument(
        "--print-results",
        action="store_true",
        help="Print cached result JSON objects instead of the manifest.",
    )
    args = parser.parse_args()

    manifest = [
        inspect_with_cache(activity_ref, args)
        for activity_ref in args.activities
    ]
    if args.print_results:
        results = [load_json(Path(item["cache_path"]))["result"] for item in manifest]
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2, sort_keys=True))
        return
    print(json.dumps(manifest[0] if len(manifest) == 1 else manifest, indent=2, sort_keys=True))


def inspect_with_cache(activity_ref: str, args: argparse.Namespace) -> dict[str, Any]:
    activity = resolve_activity_ref(activity_ref, artifacts_dir=args.artifacts_dir)
    source_files = source_file_metadata(activity.activity_dir)
    options = args.analysis_options_json
    if options.get("garmin_json"):
        source_files["garmin_json"] = file_metadata(Path(options["garmin_json"]))
    inspect_args = build_inspect_args(options)
    cache_key_payload = {
        "pipeline_schema": PIPELINE_SCHEMA,
        "pipeline_version": PIPELINE_VERSION,
        "activity_id": activity.id,
        "activity_dir": str(activity.activity_dir),
        "shape": options["shape"],
        "mode": options["mode"],
        "inspect_args": inspect_args,
        "activity_inspect_mtime_ns": script_mtime_ns(activity_inspect_script()),
    }
    cache_key = stable_hash(cache_key_payload)
    cache_path = cache_output_path(
        args.output_dir,
        activity_id=activity.id,
        mode=options["mode"],
        shape=options["shape"],
        cache_key=cache_key,
    )
    cached = None if args.force else fresh_cached_payload(
        cache_path,
        cache_key=cache_key,
        source_files=source_files,
    )
    if cached is not None:
        return manifest_row(cached, cache_path=cache_path, cache_hit=True)

    raw_result = run_activity_inspect(
        activity_ref=str(activity.activity_dir),
        artifacts_dir=args.artifacts_dir,
        inspect_args=inspect_args,
    )
    payload = {
        "schema": PIPELINE_SCHEMA,
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "cache_key": cache_key,
        "cache_key_payload": cache_key_payload,
        "source_files": source_files,
        "activity": {
            "id": activity.id,
            "name": activity.name,
            "start_date_local": activity.start_date_local,
            "activity_dir": str(activity.activity_dir),
        },
        "result": raw_result,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_row(payload, cache_path=cache_path, cache_hit=False)


def build_inspect_args(options: dict[str, Any]) -> list[str]:
    inspect_args: list[str] = []
    if options["shape"] == "brief":
        inspect_args.append("--brief")
    elif options["shape"] == "compact":
        inspect_args.append("--compact")

    mode = options["mode"]
    if mode == "vt2":
        inspect_args.extend(["--auto-blocks"])
    elif mode == "vo2max":
        inspect_args.extend(["--auto-blocks"])
    elif mode == "indoor-vt1":
        inspect_args.append("--indoor-vt1")
    elif mode == "outdoor-vt1":
        inspect_args.append("--outdoor-vt1")

    if options.get("auto_blocks") and "--auto-blocks" not in inspect_args:
        inspect_args.append("--auto-blocks")
    for flag, value in (
        ("--vt1-watts", options.get("vt1_watts")),
        ("--vt2-watts", options.get("vt2_watts")),
        ("--target", options.get("target")),
        ("--threshold", options.get("threshold")),
        ("--tolerance", options.get("tolerance")),
        ("--min-block", options.get("min_block")),
        ("--max-gap", options.get("max_gap")),
        ("--smoothing", options.get("smoothing")),
        ("--auto-min-power", options.get("auto_min_power")),
        ("--auto-min-block", options.get("auto_min_block")),
        ("--auto-max-gap", options.get("auto_max_gap")),
        ("--auto-smoothing", options.get("auto_smoothing")),
        ("--auto-tolerance", options.get("auto_tolerance")),
        ("--fields", options.get("fields")),
        ("--garmin-json", options.get("garmin_json")),
    ):
        if value is not None:
            inspect_args.extend([flag, format_number(value) if isinstance(value, float) else str(value)])
    if options.get("include_intervals") is False:
        inspect_args.append("--no-intervals")
    for flag, enabled in (
        ("--steady-vt1", options.get("steady_vt1")),
        ("--no-auto-outdoor-vt1", options.get("no_auto_outdoor_vt1")),
        ("--no-auto-indoor-vt1", options.get("no_auto_indoor_vt1")),
    ):
        if enabled:
            inspect_args.append(flag)
    return inspect_args


def run_activity_inspect(
    *,
    activity_ref: str,
    artifacts_dir: str,
    inspect_args: list[str],
) -> Any:
    with tempfile.TemporaryDirectory(prefix="activity-inspect-pipeline-") as tmpdir:
        raw_output = Path(tmpdir) / "result.json"
        command = [
            sys.executable,
            "-B",
            str(activity_inspect_script()),
            activity_ref,
            "--artifacts-dir",
            artifacts_dir,
            *inspect_args,
            "--output",
            str(raw_output),
        ]
        completed = subprocess.run(
            command,
            check=True,
            cwd=repo_root(),
            text=True,
            capture_output=True,
        )
        if not raw_output.exists():
            raise RuntimeError(
                "activity_inspect.py did not write expected output. "
                f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
            )
        return load_json(raw_output)


def fresh_cached_payload(
    cache_path: Path,
    *,
    cache_key: str,
    source_files: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = load_json(cache_path)
    except json.JSONDecodeError:
        return None
    if payload.get("schema") != PIPELINE_SCHEMA or payload.get("cache_key") != cache_key:
        return None
    cached_sources = payload.get("source_files")
    if not isinstance(cached_sources, dict):
        return None
    for name, metadata in source_files.items():
        cached_metadata = cached_sources.get(name)
        if not isinstance(cached_metadata, dict):
            return None
        if cached_metadata.get("mtime_ns") != metadata.get("mtime_ns"):
            return None
        if cached_metadata.get("size") != metadata.get("size"):
            return None
    return payload


def source_file_metadata(activity_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        "activity_json": file_metadata(activity_dir / "activity.json"),
        "streams_csv": file_metadata(activity_dir / "streams.csv"),
        "activity_inspect_py": file_metadata(activity_inspect_script()),
    }


def file_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def cache_output_path(
    output_dir: Path,
    *,
    activity_id: str,
    mode: str,
    shape: str,
    cache_key: str,
) -> Path:
    safe_id = sanitize_filename(activity_id)
    safe_mode = sanitize_filename(mode)
    safe_shape = sanitize_filename(shape)
    return output_dir / safe_id / f"{safe_shape}-{safe_mode}-{cache_key[:12]}.json"


def manifest_row(payload: dict[str, Any], *, cache_path: Path, cache_hit: bool) -> dict[str, Any]:
    return {
        "schema": PIPELINE_SCHEMA,
        "cache_hit": cache_hit,
        "cache_path": str(cache_path),
        "activity": payload.get("activity"),
        "mode": (payload.get("cache_key_payload") or {}).get("mode"),
        "shape": (payload.get("cache_key_payload") or {}).get("shape"),
        "inspect_args": (payload.get("cache_key_payload") or {}).get("inspect_args"),
        "generated_at": payload.get("generated_at"),
    }


def stable_hash(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def script_mtime_ns(path: Path) -> int:
    return path.stat().st_mtime_ns


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def activity_inspect_script() -> Path:
    return repo_root() / "scripts" / "activity_inspect.py"


def sanitize_filename(raw: str) -> str:
    clean = "".join(char if char.isalnum() or char in "._-" else "-" for char in raw.strip())
    return clean.strip("-") or "activity"


def format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


if __name__ == "__main__":
    main()
