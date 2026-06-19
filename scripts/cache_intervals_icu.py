#!/usr/bin/env python3
"""Compatibility wrapper for the Intervals.icu plugin CLI."""

from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "intervals-icu" / "scripts"
sys.path.insert(0, str(PLUGIN_SCRIPTS))

from intervals_icu_cli import main  # noqa: E402


if __name__ == "__main__":
    main()
