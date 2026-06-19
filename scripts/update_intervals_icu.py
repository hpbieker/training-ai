#!/usr/bin/env python3
"""Compatibility wrapper for Intervals.icu update commands."""

from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "intervals-icu" / "scripts"
sys.path.insert(0, str(PLUGIN_SCRIPTS))

from intervals_icu_cli import main  # noqa: E402


COMMAND_ALIASES = {
    "wellness": "wellness-update",
}


def _rewrite_legacy_update_command() -> None:
    if len(sys.argv) > 1:
        sys.argv[1] = COMMAND_ALIASES.get(sys.argv[1], sys.argv[1])


if __name__ == "__main__":
    _rewrite_legacy_update_command()
    main()
