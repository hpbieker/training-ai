"""Read cached Xert recovery/advice inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")


def latest_recovery_model(data_dir: str | Path = DATA_DIR) -> dict[str, Any]:
    """Load the newest cached direct Xert recovery model document."""

    model_paths = sorted((Path(data_dir) / "xert").glob("recovery_model_*.json"))
    if not model_paths:
        raise FileNotFoundError("No Xert recovery_model cache found")
    return json.loads(model_paths[-1].read_text(encoding="utf-8"))


def main() -> None:
    model = latest_recovery_model()
    at_state = model.get("at_state") or {}
    training_load = at_state.get("tl") if isinstance(at_state, dict) else {}
    recovery_load = at_state.get("rl") if isinstance(at_state, dict) else {}
    recovery_days = model.get("recovery_days") or {}
    workout_capacity = model.get("workout_capacity") or {}
    summary = {
        "source": model.get("source"),
        "training_status": model.get("training_status"),
        "targetXSS": model.get("targetXSS"),
        "recovery_offset": model.get("recovery_offset"),
        "next_workout_days": model.get("next_workout_days"),
        "training_load": {
            "low": training_load.get("ftp") if isinstance(training_load, dict) else None,
            "high": training_load.get("hie") if isinstance(training_load, dict) else None,
            "peak": training_load.get("pp") if isinstance(training_load, dict) else None,
        },
        "recovery_load": {
            "low": recovery_load.get("ftp") if isinstance(recovery_load, dict) else None,
            "high": recovery_load.get("hie") if isinstance(recovery_load, dict) else None,
            "peak": recovery_load.get("pp") if isinstance(recovery_load, dict) else None,
        },
        "recovery_days": {
            "low": recovery_days.get("lo"),
            "high": recovery_days.get("hi"),
            "peak": recovery_days.get("pk"),
        },
        "recovery_hours": {
            "low": model.get("recovery_hours", {}).get("lo"),
            "high": model.get("recovery_hours", {}).get("hi"),
            "peak": model.get("recovery_hours", {}).get("pk"),
        },
        "workout_capacity": {
            "low": workout_capacity.get("lo"),
            "high": workout_capacity.get("hi"),
            "peak": workout_capacity.get("pk"),
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
