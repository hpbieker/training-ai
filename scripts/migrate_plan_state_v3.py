#!/usr/bin/env python3
"""Explicitly migrate v2 classifications without guessing incomplete quality roles."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from plan_state import (
    QUALITY_ROLES, SCHEMA, PlanStateError, plan_state_context, validate_plan_state,
    write_plan_state,
)


def migrate_plan_state_v3(state: dict, quality_reviews: dict) -> dict:
    if state.get("schema") != "training-ai-plan-state-v2":
        raise PlanStateError("Migration requires a v2 state; it never remigrates v3.")
    incomplete = {
        e["activity_id"] for e in state["activity_events"]
        if e["completed_role"] in QUALITY_ROLES and not e["quality_completed"]
    }
    if not isinstance(quality_reviews, dict) or set(quality_reviews) != incomplete:
        raise PlanStateError("Provide explicit reviews for exactly the incomplete quality activities.")
    updated = deepcopy(state)
    updated["schema"] = SCHEMA
    for event in updated["activity_events"]:
        completed = event.pop("quality_completed")
        event["quality_role_fulfilled"] = completed
        # The old flag described quality completion, not the whole prescription.
        event["planned_workout_completed"] = None
        event["quality_stimulus"] = event.get("quality_stimulus", completed)
        review = quality_reviews.get(event["activity_id"])
        if review is not None:
            if set(review) != {
                "quality_role_fulfilled", "planned_workout_completed", "quality_stimulus", "reason",
            } or not isinstance(review.get("reason"), str) or not review["reason"].strip():
                raise PlanStateError("Each incomplete quality review requires explicit outcomes and a reason.")
            event.update({k: review[k] for k in review if k != "reason"})
            event["reason"] += " Migration review: " + review["reason"]
    queue = updated["quality_queue"]
    previous = queue.pop("last_quality_session", None) or queue.get("last_completed_quality")
    queue.pop("last_completed_quality", None)
    if previous is not None:
        matching = next((e for e in updated["activity_events"] if e["activity_id"] == previous["activity_id"]), None)
        if matching is None:
            raise PlanStateError("Last quality session must have a reviewed history event.")
        queue["last_quality_session"] = {
            "activity_id": matching["activity_id"], "date": previous["date"],
            "role": matching["completed_role"],
            "quality_role_fulfilled": matching["quality_role_fulfilled"],
            "planned_workout_completed": matching["planned_workout_completed"],
        }
    else:
        queue["last_quality_session"] = None
    # Preserve the curated queue checkpoint; semantic corrections are replayed
    # explicitly, rather than silently rewriting the entire training history.
    validate_plan_state(updated)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("config/plan-state.json"))
    parser.add_argument("--quality-reviews-file", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    updated = migrate_plan_state_v3(
        json.loads(args.state.read_text()), json.loads(args.quality_reviews_file.read_text()),
    )
    if args.write:
        write_plan_state(args.state, updated)
    print(json.dumps(plan_state_context(updated), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
