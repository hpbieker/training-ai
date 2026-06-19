#!/usr/bin/env python3
"""Fetch and save the newest source activity for later local inspection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


INTERVALS_PLUGIN_SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "intervals-icu" / "scripts"
sys.path.insert(0, str(INTERVALS_PLUGIN_SCRIPTS))

from intervals_icu_api import load_intervals_icu_api_key, save_latest_activity_streams


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch the newest Intervals.icu activity and save metadata + streams.",
    )
    parser.add_argument("--output-dir", default="outputs/intervals")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument(
        "--stream-type",
        dest="stream_types",
        action="append",
        help="Stream type to request from Intervals.icu. Can be repeated.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print all saved artifact paths as JSON instead of only the activity directory.",
    )
    args = parser.parse_args()

    artifacts = save_latest_activity_streams(
        api_key=load_intervals_icu_api_key(),
        output_dir=args.output_dir,
        lookback_days=args.lookback_days,
        stream_types=args.stream_types,
    )
    if args.json:
        print(json.dumps({key: str(value) for key, value in artifacts.items()}, indent=2, sort_keys=True))
        return
    print(artifacts["activity_dir"])


if __name__ == "__main__":
    main()
