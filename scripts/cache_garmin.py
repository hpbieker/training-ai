#!/usr/bin/env python3
"""Cache Garmin Connect health data via gccli.

This script expects ``gccli auth login`` to have been completed outside the
project. Credentials are managed by gccli/keyring, not by this repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_GCCLI = "/opt/homebrew/bin/gccli"
DEFAULT_OUTPUT_DIR = Path("data/garmin")
DAILY_SPEC_CHOICES = [
    "heart-rate",
    "hrv",
    "sleep",
    "stress",
    "summary",
    "training-readiness",
    "training-status",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache Garmin Connect health/readiness data using gccli.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    day = subparsers.add_parser("day", help="Cache Garmin health data for one day")
    day.add_argument("date", nargs="?", default=date.today().isoformat())
    day.add_argument(
        "--only",
        action="append",
        choices=DAILY_SPEC_CHOICES,
        help="Cache only one daily source. Can be repeated.",
    )

    recent = subparsers.add_parser("recent", help="Cache Garmin health data for recent days")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--until", default=date.today().isoformat())

    subparsers.add_parser("status", help="Show gccli auth status")

    args = parser.parse_args()
    gccli = _resolve_gccli()

    if args.command == "status":
        subprocess.run([gccli, "auth", "status"], check=True)
        return

    if args.command == "day":
        artifacts = cache_day(args.date, gccli=gccli, only=args.only)
        _print_artifacts(artifacts)
        return

    if args.command == "recent":
        until = date.fromisoformat(args.until)
        artifacts = []
        for offset in range(args.days - 1, -1, -1):
            current = until - timedelta(days=offset)
            artifacts.extend(cache_day(current.isoformat(), gccli=gccli).values())
        body_battery = cache_body_battery_range(
            (until - timedelta(days=args.days - 1)).isoformat(),
            until.isoformat(),
            gccli=gccli,
        )
        artifacts.append(body_battery)
        for path in artifacts:
            print(path)
        return


def cache_day(
    day: str,
    *,
    gccli: str,
    only: Iterable[str] | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Cache useful Garmin daily health endpoints for one date."""

    output_path = Path(output_dir)
    specs = _daily_specs(day)
    if only:
        wanted = {_daily_spec_key(name) for name in only}
        specs = {name: command for name, command in specs.items() if name in wanted}
    artifacts = {}
    for name, command in specs.items():
        target = output_path / name / f"{day}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _run_gccli_json(gccli, command)
        _write_json(target, payload)
        artifacts[name] = target
    return artifacts


def _daily_specs(day: str) -> dict[str, list[str]]:
    return {
        "training_readiness": ["health", "training-readiness", day],
        "stress": ["health", "stress", "view", day],
        "heart_rate": ["health", "hr", day],
        "hrv": ["health", "hrv", day],
        "sleep": ["health", "sleep", day],
        "summary": ["health", "summary", day],
        "training_status": ["health", "training-status", day],
    }


def _daily_spec_key(name: str) -> str:
    return name.replace("-", "_")


def cache_body_battery_range(
    start: str,
    end: str,
    *,
    gccli: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Cache Garmin Body Battery data for a date range."""

    target = Path(output_dir) / "body_battery" / f"{start}_{end}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _run_gccli_json(
        gccli,
        ["health", "body-battery", "range", "--start", start, "--end", end],
    )
    _write_json(target, payload)
    return target


def _run_gccli_json(gccli: str, args: list[str]) -> Any:
    result = subprocess.run(
        [gccli, "--json", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _resolve_gccli() -> str:
    if Path(DEFAULT_GCCLI).exists():
        return DEFAULT_GCCLI
    resolved = shutil.which("gccli")
    if resolved:
        return resolved
    raise SystemExit("gccli not found. Install it and run `gccli auth login` first.")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _print_artifacts(artifacts: dict[str, Path]) -> None:
    for name, path in artifacts.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
