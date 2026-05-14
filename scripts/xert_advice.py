"""Read cached Xert training advice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")


def latest_training_advice(data_dir: str | Path = DATA_DIR) -> dict[str, Any]:
    """Load the newest cached Xert training advice document."""

    advice_paths = sorted((Path(data_dir) / "xert").glob("training_advice_*.json"))
    if not advice_paths:
        raise FileNotFoundError("No Xert training_advice cache found")
    return json.loads(advice_paths[-1].read_text(encoding="utf-8"))


def main() -> None:
    advice = latest_training_advice()
    summary = {
        "training_status": advice.get("training_status"),
        "targetXSS": advice.get("targetXSS"),
        "completed_xss": advice.get("x_completed_xss"),
        "placeholder_xss": advice.get("x_placeholder_xss"),
        "training_load": {
            "low": advice.get("trainingload_xlss"),
            "high": advice.get("trainingload_xhss"),
            "peak": advice.get("trainingload_xpss"),
        },
        "recovery_load": {
            "low": advice.get("recoveryload_xlss"),
            "high": advice.get("recoveryload_xhss"),
            "peak": advice.get("recoveryload_xpss"),
        },
        "recovery_days": {
            "low": advice.get("recovery_days_lo"),
            "high": advice.get("recovery_days_hi"),
            "peak": advice.get("recovery_days_pk"),
        },
        "workout_capacity": {
            "low": advice.get("workout_capacity_xlss"),
            "high": advice.get("workout_capacity_xhss"),
            "peak": advice.get("workout_capacity_xpss"),
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
