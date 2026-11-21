from datetime import datetime
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from athlete_feedback import save_answer, saved_context
from vt1_dose import dose_comparisons, prior_quality_sequences


class AthleteFeedbackTests(unittest.TestCase):
    def test_source_time_correction_and_normal_read_paths(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            for day, role in [(1, "vt2"), (2, "easy_aerobic"), (3, "vt2")]:
                activity_id = f"i{day}"
                directory = root / activity_id
                directory.mkdir()
                (directory / "activity.json").write_text(json.dumps(
                    dict(id=activity_id, type="Ride", elapsed_time=3600, moving_time=3500)))
                events.append(dict(activity_id=activity_id, planned_role=role, completed_role=role,
                                   reason="reviewed", started_at=f"2026-11-0{day}T10:00:00+01:00"))
            ride = root / "i2"
            review = ride / "analysis.md"
            review.write_text("Athlete report")
            facts = dict(observed_at="2026-11-02", reported_at="2026-11-02T18:00:00+01:00",
                         context="late in the ride", question="What changed?", answer="Not sure.")
            first = save_answer(ride, "i2", **facts)
            self.assertEqual(first, save_answer(ride, "i2", **facts))
            with self.assertRaises(ValueError):
                save_answer(ride, "i3", **facts)
            with self.assertRaises(ValueError):
                save_answer(ride, "i2", **dict(facts, reported_at="2026-11-02T18:00:00"))
            later = dict(facts, reported_at="2026-11-04T18:00:00+01:00", answer="The legs felt heavy.")
            save_answer(ride, "i2", **later)
            cutoff = datetime.fromisoformat("2026-11-04T08:00:00+01:00")
            os.utime(review, (cutoff.timestamp()+1, cutoff.timestamp()+1))
            state = {"activity_events":events}
            seq = prior_quality_sequences(state, cutoff, root)["quality_sequences"][0]
            self.assertEqual(seq["activity_before_previous"]["activity_id"], "i1")
            pair = seq["previous_activity"]
            self.assertNotIn("reviewed_analysis_file", pair)
            self.assertEqual([a["answer"] for a in pair["athlete_answers"]], ["Not sure."])
            os.utime(review, (cutoff.timestamp()-1, cutoff.timestamp()-1))
            legacy = ride / "athlete-report.json"
            legacy.write_text(json.dumps({"athlete_report":"Older observation"}))
            os.utime(legacy, (cutoff.timestamp()-1, cutoff.timestamp()-1))
            ride_row = dose_comparisons(state,"easy_aerobic",None,cutoff,root)["candidates"][0]
            self.assertEqual(ride_row["athlete_answers"],pair["athlete_answers"])
            self.assertEqual(ride_row["reviewed_analysis_file"], str(review))
            self.assertEqual(ride_row["undated_athlete_report_file"], str(legacy))
            self.assertIsNone(ride_row["athlete_report"])
            rows = saved_context(ride,datetime.fromisoformat(later["reported_at"]))["athlete_answers"]
            self.assertEqual([a["answer"] for a in rows], ["Not sure.","The legs felt heavy."])

    def test_morning_observation_and_stop_clarification_reach_distinct_contexts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = {"activity_events": []}
            for day, role in [(1, "easy_aerobic"), (2, "vt2")]:
                key = f"i{day}"
                (root / key).mkdir()
                (root / key / "activity.json").write_text(json.dumps(
                    dict(id=key, type="Ride", elapsed_time=3600, moving_time=3000)))
                state["activity_events"].append(dict(activity_id=key, planned_role=role,
                    completed_role=role, reason="stop unknown", started_at=f"2026-11-0{day}T10:00:00+01:00"))
            for observed, answer in [("2026-11-02", "Stopped voluntarily"),
                                     ("2026-11-02T23:30:00Z", "No soreness this morning")]:
                save_answer(root/"i2", "i2", observed_at=observed,
                            reported_at="2026-11-03T08:00:00+01:00", question="How?", answer=answer,
                            context="Follow-up")
            for hour, expected in [(7, []), (8, ["No soreness this morning"])]:
                cutoff = datetime.fromisoformat(f"2026-11-03T0{hour}:00:00+01:00")
                history = prior_quality_sequences(state, cutoff, root)
                self.assertEqual([a["answer"] for a in history["current_day_athlete_answers"]], expected)
                ride = dose_comparisons(state, "easy_aerobic", None, cutoff, root)["candidates"][0]
                self.assertEqual(ride["finish_to_next_quality_minutes"], 23*60)
                quality = ride["next_quality_session"]
                if hour == 7:
                    self.assertNotIn("athlete_answers", quality)
                else:
                    self.assertEqual(quality["prior_review"], "stop unknown")
                    self.assertIn("Stopped voluntarily", [a["answer"] for a in quality["athlete_answers"]])
