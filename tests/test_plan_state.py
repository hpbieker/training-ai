from pathlib import Path
import argparse
import json
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from plan_state import (  # noqa: E402
    PlanStateError,
    apply_activity_classification,
    load_plan_state,
    pending_activities,
    parse_classification_json,
    recommendation_plan_context,
    replay_activity_classifications,
    write_plan_state,
)


def base_state() -> dict:
    return {
        "schema": "training-ai-plan-state-v3",
        "updated_at": "2026-07-24T12:00:00Z",
        "active_plan": {
            "id": "test-plan",
            "path": "config/plans/test-plan.md",
        },
        "activity_cursor": {
            "activity_id": "quality-1",
            "started_at": "2026-07-24T09:00:00+02:00",
        },
        "next_role": "easy_aerobic",
        "quality_queue": {
            "steps": [
                {"id": "vt2_primary", "intensity_goal": "vt2"},
                {"id": "vt2_secondary", "intensity_goal": "vt2"},
                {"id": "vo2max", "intensity_goal": "vo2max"},
            ],
            "minimum_aerobic_days_after_quality": 1,
            "last_quality_session": {
                "activity_id": "quality-1",
                "date": "2026-07-24",
                "role": "vt2",
            },
            "next_quality_step": "vo2max",
            "aerobic_dates_since_quality": [],
            "aerobic_days_since_quality": 0,
        },
        "progression": {},
        "activity_events": [
            {
                "activity_id": "quality-1",
                "activity_name": "VT2",
                "started_at": "2026-07-24T09:00:00+02:00",
                "planned_role": "vt2",
                "completed_role": "vt2",
                "quality_role_fulfilled": True,
                "planned_workout_completed": True,
                "quality_stimulus": True,
                "progression_effect": "advance",
                "reason": "Completed.",
                "evidence": ["analysis.json"],
            }
        ],
    }


def event(
    *,
    activity_id: str,
    started_at: str,
    completed_role: str,
    quality_role_fulfilled: bool = False,
    planned_workout_completed: bool | None = None,
    quality_stimulus: bool | None = None,
    progression_effect: str = "none",
    progression_update: dict | None = None,
) -> dict:
    return {
        "activity_id": activity_id,
        "activity_name": activity_id,
        "started_at": started_at,
        "planned_role": completed_role,
        "completed_role": completed_role,
        "quality_role_fulfilled": quality_role_fulfilled,
        "planned_workout_completed": planned_workout_completed,
        "quality_stimulus": quality_role_fulfilled if quality_stimulus is None else quality_stimulus,
        "progression_effect": progression_effect,
        "reason": "Reviewed classification.",
        "evidence": [f"{activity_id}.json"],
        "progression_update": progression_update or {},
    }


class PlanStateTransitionTests(unittest.TestCase):
    def test_fulfilled_shortened_vo2_advances_without_progression(self):
        state = base_state()
        state["progression"] = {"vo2max": {"anchor": "7 x 3 min @ 350 W"}}
        sunday = event(
            activity_id="sunday-seven-full-plus-partial-eighth",
            started_at="2026-07-26T12:00:00+02:00", completed_role="vo2max",
            quality_role_fulfilled=True, planned_workout_completed=False,
            progression_effect="hold",
        )
        sunday["reason"] = "Seven full three-minute repetitions; eighth stopped after 86 seconds."
        quality = apply_activity_classification(state, sunday)
        self.assertEqual(quality["quality_queue"]["next_quality_step"], "vt2_primary")
        self.assertEqual(quality["next_role"], "easy_aerobic")
        self.assertFalse(quality["quality_queue"]["last_quality_session"]["planned_workout_completed"])
        monday = apply_activity_classification(quality, event(
            activity_id="monday-aerobic", started_at="2026-07-27T12:00:00+02:00",
            completed_role="easy_aerobic", planned_workout_completed=True,
        ))
        context = recommendation_plan_context(monday, intensity_goal="vt2")
        self.assertTrue(context["goal_matches_state"])
        self.assertEqual(context["next_quality_step"], "vt2_primary")
        self.assertEqual(context["aerobic_days_since_quality"], 1)
        self.assertEqual(context["progression"]["vo2max"]["anchor"], "7 x 3 min @ 350 W")
        with self.assertRaisesRegex(PlanStateError, "conflicts"):
            recommendation_plan_context(monday, intensity_goal="vo2max")

    def test_completed_consolidation_advances_queue_without_raising_anchor(self):
        state = base_state()
        state["progression"] = {"vo2max": {"anchor": "7 x 3 min @ 350 W"}}
        updated = apply_activity_classification(state, event(
            activity_id="consolidation", started_at="2026-07-25T09:00:00+02:00",
            completed_role="vo2max", quality_role_fulfilled=True,
            planned_workout_completed=True, progression_effect="consolidate",
        ))
        self.assertEqual(updated["quality_queue"]["next_quality_step"], "vt2_primary")
        self.assertEqual(updated["progression"], state["progression"])

    def test_fulfilled_role_requires_actual_quality_stimulus(self):
        with self.assertRaisesRegex(PlanStateError, "requires quality_stimulus"):
            apply_activity_classification(base_state(), event(
                activity_id="contradictory", started_at="2026-07-25T09:00:00+02:00",
                completed_role="vo2max", quality_role_fulfilled=True,
                quality_stimulus=False,
            ))

    def test_aerobic_activity_opens_the_queued_quality_role(self):
        updated = apply_activity_classification(
            base_state(),
            event(
                activity_id="aerobic-1",
                started_at="2026-07-25T08:00:00+02:00",
                completed_role="long_aerobic",
            ),
            updated_at="2026-07-25T12:00:00Z",
        )

        self.assertEqual(updated["next_role"], "vo2max")
        self.assertEqual(updated["quality_queue"]["next_quality_step"], "vo2max")
        self.assertEqual(updated["quality_queue"]["aerobic_days_since_quality"], 1)

    def test_extra_aerobic_activity_does_not_advance_quality_queue(self):
        once = apply_activity_classification(
            base_state(),
            event(
                activity_id="aerobic-1",
                started_at="2026-07-25T08:00:00+02:00",
                completed_role="long_aerobic",
            ),
        )
        twice = apply_activity_classification(
            once,
            event(
                activity_id="aerobic-2",
                started_at="2026-07-26T08:00:00+02:00",
                completed_role="easy_aerobic",
            ),
        )

        self.assertEqual(twice["next_role"], "vo2max")
        self.assertEqual(twice["quality_queue"]["next_quality_step"], "vo2max")
        self.assertEqual(twice["quality_queue"]["aerobic_days_since_quality"], 2)

    def test_completed_queued_quality_advances_and_requires_aerobic_day(self):
        aerobic = apply_activity_classification(
            base_state(),
            event(
                activity_id="aerobic-1",
                started_at="2026-07-25T08:00:00+02:00",
                completed_role="long_aerobic",
            ),
        )
        quality = apply_activity_classification(
            aerobic,
            event(
                activity_id="quality-2",
                started_at="2026-07-26T08:00:00+02:00",
                completed_role="vo2max",
                quality_role_fulfilled=True,
                progression_effect="advance",
                progression_update={
                    "status": "progress",
                    "next_step": "2 x 9 x 60 sec",
                    "last_result": "Completed 2 x 8 x 60 sec without power fade.",
                },
            ),
        )

        self.assertEqual(quality["quality_queue"]["next_quality_step"], "vt2_primary")
        self.assertEqual(quality["next_role"], "easy_aerobic")
        self.assertEqual(quality["quality_queue"]["aerobic_days_since_quality"], 0)
        self.assertEqual(
            quality["progression"]["vo2max"]["next_step"],
            "2 x 9 x 60 sec",
        )
        self.assertEqual(
            quality["progression"]["vo2max"]["last_result"],
            "Completed 2 x 8 x 60 sec without power fade.",
        )

    def test_insufficient_quality_stimulus_resets_spacing_without_advancing_queue(self):
        state = apply_activity_classification(
            base_state(),
            event(
                activity_id="aerobic-before-incomplete",
                started_at="2026-07-25T08:00:00+02:00",
                completed_role="easy_aerobic",
            ),
        )
        updated = apply_activity_classification(
            state,
            dict(event(
                activity_id="incomplete-quality",
                started_at="2026-07-26T08:00:00+02:00",
                completed_role="vo2max",
                quality_role_fulfilled=False,
                progression_effect="hold",
            ), quality_stimulus=True),
        )
        self.assertEqual(updated["quality_queue"]["next_quality_step"], "vo2max")
        self.assertEqual(updated["quality_queue"]["aerobic_days_since_quality"], 0)
        self.assertEqual(updated["next_role"], "easy_aerobic")
        self.assertFalse(updated["quality_queue"]["last_quality_session"]["quality_role_fulfilled"])

    def test_repeated_vt2_goals_advance_by_step_identity(self):
        state = base_state()
        state["next_role"] = "vt2"
        state["quality_queue"]["next_quality_step"] = "vt2_primary"
        state["quality_queue"]["aerobic_dates_since_quality"] = ["2026-07-25"]
        state["quality_queue"]["aerobic_days_since_quality"] = 1

        first = apply_activity_classification(
            state,
            event(
                activity_id="vt2-primary",
                started_at="2026-07-26T08:00:00+02:00",
                completed_role="vt2",
                quality_role_fulfilled=True,
                progression_effect="advance",
            ),
        )
        self.assertEqual(first["quality_queue"]["next_quality_step"], "vt2_secondary")
        self.assertEqual(first["next_role"], "easy_aerobic")

        aerobic = apply_activity_classification(
            first,
            event(
                activity_id="aerobic-between-vt2",
                started_at="2026-07-27T08:00:00+02:00",
                completed_role="easy_aerobic",
            ),
        )
        self.assertEqual(aerobic["next_role"], "vt2")

        second = apply_activity_classification(
            aerobic,
            event(
                activity_id="vt2-secondary",
                started_at="2026-07-28T08:00:00+02:00",
                completed_role="vt2",
                quality_role_fulfilled=True,
                progression_effect="advance",
            ),
        )
        self.assertEqual(second["quality_queue"]["next_quality_step"], "vo2max")

    def test_same_day_aerobic_after_quality_does_not_count_as_spacing_day(self):
        quality = apply_activity_classification(
            base_state(),
            event(
                activity_id="quality-am",
                started_at="2026-07-25T09:00:00+02:00",
                completed_role="vt2",
                quality_role_fulfilled=True,
                progression_effect="advance",
            ),
        )
        evening_aerobic = apply_activity_classification(
            quality,
            event(
                activity_id="aerobic-pm",
                started_at="2026-07-25T19:00:00+02:00",
                completed_role="easy_aerobic",
            ),
        )

        self.assertEqual(
            evening_aerobic["quality_queue"]["aerobic_dates_since_quality"], []
        )
        self.assertEqual(
            evening_aerobic["quality_queue"]["aerobic_days_since_quality"], 0
        )
        self.assertEqual(evening_aerobic["next_role"], "easy_aerobic")

    def test_repeated_vo2max_goals_are_supported_without_special_cases(self):
        state = base_state()
        state["quality_queue"]["steps"] = [
            {"id": "vt2", "intensity_goal": "vt2"},
            {"id": "vo2max_primary", "intensity_goal": "vo2max"},
            {"id": "vo2max_secondary", "intensity_goal": "vo2max"},
        ]
        state["quality_queue"]["next_quality_step"] = "vo2max_primary"

        aerobic = apply_activity_classification(
            state,
            event(
                activity_id="aerobic-before-vo2",
                started_at="2026-07-25T08:00:00+02:00",
                completed_role="easy_aerobic",
            ),
        )
        first = apply_activity_classification(
            aerobic,
            event(
                activity_id="vo2-primary",
                started_at="2026-07-26T08:00:00+02:00",
                completed_role="vo2max",
                quality_role_fulfilled=True,
                progression_effect="advance",
            ),
        )

        self.assertEqual(first["quality_queue"]["next_quality_step"], "vo2max_secondary")
        self.assertEqual(first["next_role"], "easy_aerobic")

    def test_completed_out_of_queue_quality_updates_own_progression(self):
        quality = apply_activity_classification(
            base_state(),
            event(
                activity_id="quality-vt2",
                started_at="2026-07-25T08:00:00+02:00",
                completed_role="vt2",
                quality_role_fulfilled=True,
                progression_effect="advance",
                progression_update={
                    "status": "progress",
                    "next_step": "3 x 23 min @ 290 W",
                },
            ),
        )

        self.assertEqual(quality["quality_queue"]["next_quality_step"], "vo2max")
        self.assertEqual(quality["quality_queue"]["last_quality_session"]["role"], "vt2")
        self.assertEqual(quality["next_role"], "easy_aerobic")
        self.assertEqual(quality["quality_queue"]["aerobic_days_since_quality"], 0)
        self.assertEqual(
            quality["progression"]["vt2"]["next_step"],
            "3 x 23 min @ 290 W",
        )

        aerobic = apply_activity_classification(
            quality,
            event(
                activity_id="aerobic-after-vt2",
                started_at="2026-07-26T08:00:00+02:00",
                completed_role="easy_aerobic",
            ),
        )
        self.assertEqual(aerobic["next_role"], "vo2max")

    def test_classification_json_is_validated_as_one_object(self):
        classification = event(
            activity_id="aerobic-json",
            started_at="2026-07-25T08:00:00+02:00",
            completed_role="long_aerobic",
        )

        parsed = parse_classification_json(json.dumps(classification))

        self.assertEqual(parsed, classification)

    def test_classification_json_rejects_unknown_fields_and_string_boolean(self):
        classification = event(
            activity_id="aerobic-json",
            started_at="2026-07-25T08:00:00+02:00",
            completed_role="long_aerobic",
        )
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "unsupported classification field",
        ):
            parse_classification_json(
                json.dumps({**classification, "activity": "typo"})
            )
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "quality_role_fulfilled must be boolean",
        ):
            parse_classification_json(
                json.dumps({**classification, "quality_role_fulfilled": "no"})
            )

    def test_reapplying_identical_activity_is_idempotent(self):
        classification = event(
            activity_id="aerobic-1",
            started_at="2026-07-25T08:00:00+02:00",
            completed_role="long_aerobic",
        )
        once = apply_activity_classification(base_state(), classification)
        twice = apply_activity_classification(once, classification)

        self.assertEqual(twice, once)

    def test_rejects_changed_duplicate_and_out_of_order_activity(self):
        classification = event(
            activity_id="aerobic-1",
            started_at="2026-07-25T08:00:00+02:00",
            completed_role="long_aerobic",
        )
        once = apply_activity_classification(base_state(), classification)
        changed = dict(classification, reason="Different.")
        with self.assertRaises(PlanStateError):
            apply_activity_classification(once, changed)
        with self.assertRaises(PlanStateError):
            apply_activity_classification(
                once,
                event(
                    activity_id="older",
                    started_at="2026-07-24T07:00:00+02:00",
                    completed_role="easy_aerobic",
                ),
            )

    def test_goal_conflict_requires_explicit_plan_level_reason(self):
        state = apply_activity_classification(
            base_state(),
            event(
                activity_id="aerobic-1",
                started_at="2026-07-25T08:00:00+02:00",
                completed_role="long_aerobic",
            ),
        )
        with self.assertRaises(PlanStateError):
            recommendation_plan_context(state, intensity_goal="vt1")

        context = recommendation_plan_context(
            state,
            intensity_goal="vt1",
            mismatch_reason="Deliberate long-ride placement before the next quality opportunity.",
        )
        self.assertFalse(context["goal_matches_state"])
        self.assertEqual(context["next_quality_step"], "vo2max")
        self.assertEqual(context["next_quality_role"], "vo2max")


class PlanStatePersistenceTests(unittest.TestCase):
    def test_replay_corrects_role_without_losing_later_aerobic_day(self):
        checkpoint = base_state()
        short = event(
            activity_id="sunday", started_at="2026-07-26T12:00:00+02:00",
            completed_role="vo2max", quality_role_fulfilled=False,
            quality_stimulus=True, planned_workout_completed=False,
            progression_effect="hold",
        )
        monday = event(
            activity_id="monday", started_at="2026-07-27T12:00:00+02:00",
            completed_role="easy_aerobic",
        )
        current = apply_activity_classification(apply_activity_classification(checkpoint, short), monday)
        corrected = dict(short, quality_role_fulfilled=True)
        result = replay_activity_classifications(current, checkpoint, [corrected, monday])
        self.assertEqual(result["quality_queue"]["next_quality_step"], "vt2_primary")
        self.assertEqual(result["next_role"], "vt2")
        self.assertEqual(result["activity_cursor"], current["activity_cursor"])
        self.assertEqual(len(result["activity_events"]), len(current["activity_events"]))
        self.assertEqual(result["activity_events"][-1], monday)
        self.assertFalse(current["activity_events"][-2]["quality_role_fulfilled"])
        self.assertEqual(apply_activity_classification(result, monday), result)
        for invalid in ([corrected], [monday, corrected], [corrected, corrected]):
            with self.assertRaises(PlanStateError):
                replay_activity_classifications(current, checkpoint, invalid)

    def test_atomic_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan-state.json"
            write_plan_state(path, base_state())
            self.assertEqual(load_plan_state(path), base_state())

    def test_pending_lists_only_new_unprocessed_activities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder, payload in (
                (
                    "old",
                    {
                        "id": "quality-1",
                        "name": "Old",
                        "type": "Ride",
                        "start_date_local": "2026-07-24T09:00:00+02:00",
                    },
                ),
                (
                    "new",
                    {
                        "id": "new-1",
                        "name": "New",
                        "type": "Ride",
                        "start_date_local": "2026-07-25T09:00:00+02:00",
                    },
                ),
            ):
                activity_dir = root / folder
                activity_dir.mkdir()
                (activity_dir / "activity.json").write_text(
                    json.dumps(payload),
                    encoding="utf-8",
                )

            pending = pending_activities(base_state(), root)

        self.assertEqual([item["activity_id"] for item in pending], ["new-1"])


if __name__ == "__main__":
    unittest.main()
