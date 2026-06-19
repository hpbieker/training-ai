"""Compatibility imports for the Intervals.icu plugin API module."""

from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "intervals-icu" / "scripts"
sys.path.insert(0, str(PLUGIN_SCRIPTS))

from intervals_icu_api import *  # noqa: F401,F403,E402
