"""Regression cases for duration evidence available at the coaching decision."""
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from vt1_dose import dose_comparisons


def event(id_, day, role):
    return {"activity_id": id_, "completed_role": role, "planned_role": role,
            "started_at": f"2026-11-{day:02d}T10:00:00+01:00",
            "reason": "Reviewed training role", "quality_role_fulfilled": role == "vt2"}


class DoseComparisonsTests(unittest.TestCase):
    def test_matches_purpose_and_uses_only_finished_rides_and_quality_outcomes(self):
        events = [event("a", 10, "easy_aerobic"), event("b", 11, "vt2"),
                  event("c", 12, "long_aerobic"), event("d", 13, "easy_aerobic"),
                  event("e", 14, "vt2"), event("f", 15, "easy_aerobic")]
        state = {"activity_events": events}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for row in events:
                ride = root / row["activity_id"]
                ride.mkdir()
                (ride / "activity.json").write_text(json.dumps({"type": "VirtualRide",
                    "moving_time": 3600, "elapsed_time": 3800, "icu_rpe": 3,
                    "icu_ignore_power": row["activity_id"] == "d"}))
                (ride / "streams.csv").write_text("time,watts\n0,215\n5,214\n10,100\n300,240\n")
            (root / "a" / "athlete-report.json").write_text(json.dumps({"athlete_report": "Heavy legs late"}))
            cutoff = datetime.fromisoformat("2026-11-14T10:30:00+01:00")
            result = dose_comparisons(state, "easy_aerobic", 215, cutoff, root)
            newer, older = result["candidates"]
            self.assertEqual([newer["activity_id"], older["activity_id"]], ["d", "a"])
            self.assertIsNone(newer["next_quality_session"])
            self.assertIsNone(newer["observed_minutes_near_working_power"])
            self.assertEqual(older["next_quality_session"]["activity_id"], "b")
            self.assertEqual(older["moving_minutes"], 60)
            self.assertEqual(older["observed_minutes_near_working_power"], round(10/60, 1))
            self.assertEqual(older["valid_power_minutes"], round(20/60, 1))
            self.assertEqual(older["athlete_report"]["athlete_report"], "Heavy legs late")
            self.assertEqual(older["whole_session_rpe"], 3)
            self.assertEqual(dose_comparisons(state, "medium_aerobic", 215, cutoff, root)["candidates"], [])
            (root / "a" / "athlete-report.json").write_text(json.dumps({
                "reported_at": "2026-11-15T10:00:00+01:00", "athlete_report": "Later feedback",
            }))
            result = dose_comparisons(state, "easy_aerobic", 215, cutoff, root)
            self.assertIsNone(result["candidates"][-1]["athlete_report"])

    def test_explicit_older_comparison_is_included_alongside_three_latest(self):
        state = {"activity_events": [event(str(day), day, "easy_aerobic") for day in range(10, 14)]}
        cutoff = datetime.fromisoformat("2026-11-17T10:00:00+01:00")
        with TemporaryDirectory() as tmp:
            result = dose_comparisons(state, "easy_aerobic", None, cutoff, Path(tmp), selected_id="10")
        self.assertEqual([ride["activity_id"] for ride in result["candidates"]], ["13", "12", "11", "10"])
        self.assertTrue(all(ride["observed_minutes_near_working_power"] is None for ride in result["candidates"]))
