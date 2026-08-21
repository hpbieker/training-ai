import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "simulate_recommend_training_under_test",
    ROOT / "scripts" / "simulate_recommend_training.py",
)
assert SPEC is not None and SPEC.loader is not None
SIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIM)


class ScenarioProgressionTests(unittest.TestCase):
    def test_advances_vo2_calibration_step(self):
        state = {"progression": {"vo2max": {"next_step": "4 x 4 min @ 340 W"}}}
        self.assertEqual(
            SIM.scenario_progression_update("vo2max", state),
            {
                "status": "sensor_calibration_2_of_3",
                "next_step": "2 x 8 x 60/60 @ 380 W",
            },
        )

    def test_advances_vt2_ladder_step(self):
        state = {"progression": {"vt2": {"next_step": "3 x 18 min @ 290 W"}}}
        self.assertEqual(
            SIM.scenario_progression_update("vt2", state)["next_step"],
            "3 x 20 min @ 290 W",
        )

    def test_initial_vo2_uses_existing_calculation(self):
        state = {"progression": {"vo2max": {"next_step": "4 x 4 min @ 340 W"}}}
        self.assertEqual(SIM.quality_calculation("vo2max", state), SIM.QUALITY)

    def test_later_quality_step_requires_mcp_calculation(self):
        state = {"progression": {"vt2": {"next_step": "3 x 18 min @ 290 W"}}}
        with self.assertRaisesRegex(SystemExit, "MCP calculate_workout"):
            SIM.quality_calculation("vt2", state)

    def test_later_quality_step_uses_supplied_mcp_calculation(self):
        state = {"progression": {"vt2": {"next_step": "3 x 18 min @ 290 W"}}}
        calculation = {"xss": 90, "low_xss": 85, "high_xss": 5}
        self.assertEqual(
            SIM.quality_calculation(
                "vt2",
                state,
                calculations={"3 x 18 min @ 290 W": calculation},
            ),
            calculation,
        )


if __name__ == "__main__":
    unittest.main()
