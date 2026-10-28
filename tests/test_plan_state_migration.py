import unittest

from test_plan_state import base_state
from migrate_plan_state_v3 import migrate_plan_state_v3
from plan_state import PlanStateError


class PlanStateMigrationTests(unittest.TestCase):
    def legacy_state(self):
        state = base_state()
        state["schema"] = "training-ai-plan-state-v2"
        for item in state["activity_events"]:
            item["quality_completed"] = item.pop("quality_role_fulfilled")
            item.pop("planned_workout_completed")
            item.pop("quality_stimulus")
        return state

    def test_completed_quality_does_not_prove_whole_prescription_completion(self):
        original = self.legacy_state()
        migrated = migrate_plan_state_v3(original, {})
        self.assertTrue(migrated["activity_events"][0]["quality_role_fulfilled"])
        self.assertIsNone(migrated["activity_events"][0]["planned_workout_completed"])
        self.assertIn("quality_completed", original["activity_events"][0])
        self.assertEqual(migrated["quality_queue"]["next_quality_step"], "vo2max")

    def test_incomplete_quality_requires_explicit_review(self):
        state = self.legacy_state()
        state["activity_events"][0]["quality_completed"] = False
        with self.assertRaisesRegex(PlanStateError, "explicit reviews"):
            migrate_plan_state_v3(state, {})
        review = {"quality_role_fulfilled": True, "planned_workout_completed": False,
                  "quality_stimulus": True, "reason": "Substantial completed work fulfills role."}
        migrated = migrate_plan_state_v3(state, {"quality-1": review})
        self.assertTrue(migrated["activity_events"][0]["quality_role_fulfilled"])
        self.assertFalse(migrated["activity_events"][0]["planned_workout_completed"])
        with self.assertRaises(PlanStateError):
            migrate_plan_state_v3(migrated, {})


if __name__ == "__main__":
    unittest.main()
