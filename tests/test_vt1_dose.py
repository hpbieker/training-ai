"""Regression cases for duration evidence available at the coaching decision."""
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from vt1_dose import dose_comparisons, measured_aerobic_references, prior_quality_sequences, recorded_work_intervals


def event(id_, day, role):
    return {"activity_id": id_, "completed_role": role, "planned_role": role,
            "started_at": f"2026-11-{day:02d}T10:00:00+01:00",
            "reason": "Reviewed training role", "quality_role_fulfilled": role == "vt2"}


class DoseComparisonsTests(unittest.TestCase):
    def test_consecutive_aerobic_days_match_duration_before_looking_at_outcome(self):
        cutoff = datetime.fromisoformat("2026-11-20T18:00:00+01:00")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []

            def add(day, role, minutes, watts):
                key = f"ride{len(events)}"
                entry = event(key, 1, role)
                entry["started_at"] = f"2026-{day}T10:00:00+01:00"
                events.append(entry)
                folder = root / key
                folder.mkdir()
                metadata = {"moving_time": minutes * 60, "elapsed_time": minutes * 60,
                            "icu_intervals": [{"type": "WORK", "elapsed_time": 360, "average_watts": watts}]}
                (folder / "activity.json").write_text(json.dumps(metadata))
                return entry

            for month, first_day, duration in [(9, 3, 95), (10, 4, 100), (11, 1, 60)]:
                add(f"{month:02}-{first_day:02}", "medium_aerobic", duration, 200)
                add(f"{month:02}-{first_day+1:02}", "easy_aerobic", 75, 200)
                attempt = add(f"{month:02}-{first_day+2:02}", "vt2", 45, 280)
                if month == 10:
                    attempt["quality_role_fulfilled"] = False

            add("11-10", "easy_aerobic", 100, 200)
            add("11-10", "vo2max", 30, 340)  # Mixed day cannot count as an aerobic day.
            add("11-11", "easy_aerobic", 75, 200)
            add("11-12", "vt2", 60, 280)
            add("11-19", "easy_aerobic", 110, 200)
            add("11-20", "easy_aerobic", 100, 200)
            add("11-21", "vt2", 80, 280)  # No observed outcome at the cutoff.
            history = prior_quality_sequences({"activity_events": events}, cutoff, root, aerobic_references=True)
        pairs = history["consecutive_aerobic_references"]["vt2"]
        self.assertEqual([p["aerobic_days"][0]["moving_minutes"] for p in pairs], [100, 95])
        self.assertEqual([p["next_quality_attempt"]["activity_id"] for p in pairs], ["ride5", "ride2"])
        self.assertFalse(pairs[0]["next_quality_attempt"]["role_fulfilled"])
        self.assertEqual(pairs[0]["next_quality_attempt"]["work_intervals"],
                         [{"seconds": 360, "average_watts": 280}])
        self.assertEqual(pairs[0]["finish_to_next_quality_minutes"], 24 * 60 - 75)

    def test_measures_spacing_rides_from_recent_and_older_followup(self):
        day_after = {"activity_id": "recent", "completed_role": "easy_aerobic", "start": "2026-11-13"}
        older = {"activity_id": "older", "role": "easy_aerobic", "started_at": "2026-09-15T12:00:00+02:00"}
        history = {"latest_activities": [], "quality_sequences": [{"following_day": {"activities": [day_after]}}],
                   "long_finish_references": {"vo2max": {"intervening_activities": [older],
                       "next_quality_attempt": {"started_at": "2026-09-16T06:30:00Z"}}}}
        with TemporaryDirectory() as tmp:
            directories = {}
            for ride_id, watts in (("recent", 205), ("older", 215)):
                ride = Path(tmp) / ride_id
                ride.mkdir()
                directories[ride_id] = ride
                (ride / "activity.json").write_text(json.dumps({"type": "VirtualRide", "moving_time": 900, "elapsed_time": 1800}))
                (ride / "streams.csv").write_text("time,watts\n" + "".join(
                    f"{i},{watts}\n" for i in range(900)))
            refs = measured_aerobic_references(history, directories)
        self.assertEqual(set(refs), {"recent", "older"})
        self.assertEqual(refs["recent"]["date"], "2026-11-13")
        self.assertEqual(refs["older"]["date"], "2026-09-15")
        self.assertEqual(refs["older"]["finish_to_next_quality_minutes"], 20 * 60)
        self.assertNotIn("finish_to_next_quality_minutes", refs["recent"])
        for key, watts in (("recent", 205), ("older", 215)):
            self.assertEqual(refs[key]["moving_minutes"], 15)
            self.assertEqual(refs[key]["longest_detected_steady_power_block"], {"minutes": 15, "mean_watts": watts})

    def test_long_indoor_finish_reference_survives_recent_history_limit(self):
        events = [event(key, day, role) for key, day, role in
                  (("long", 1, "vo2max"), ("easy", 2, "easy_aerobic"), ("partial", 3, "vt2"),
                   ("newer", 10, "vo2max"), ("short", 15, "vo2max"), ("future", 25, "vo2max"))]
        events[2]["reason"] = "Third threshold effort stopped early"
        cutoff = datetime.fromisoformat("2026-11-20T08:00:00+01:00")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for ride_id, minutes in (("long", 125), ("newer", 12), ("short", 5), ("future", 160)):
                folder = root / ride_id
                folder.mkdir()
                intervals = [{"type": "WORK", "elapsed_time": 180},
                             {"type": "RECOVERY", "elapsed_time": minutes * 60}]
                (folder / "activity.json").write_text(json.dumps({"trainer": True, "icu_intervals": intervals}))
            history = prior_quality_sequences({"activity_events": events}, cutoff, root)
        reference = history["long_finish_references"]["vo2max"]
        self.assertEqual(reference["ride"]["activity_id"], "long")
        self.assertEqual(reference["post_work_minutes_including_cooldown"], 125)
        self.assertEqual([r["activity_id"] for r in reference["intervening_activities"]], ["easy"])
        self.assertEqual(reference["next_quality_attempt"]["review"], events[2]["reason"])

    def test_aerobic_reference_distinguishes_steady_block_from_total_without_hr(self):
        state = {"activity_events": [event("a", 10, "easy_aerobic"), event("b", 11, "vt2")]}
        cutoff = datetime.fromisoformat("2026-11-12T08:00:00+01:00")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ride = root / "a"
            ride.mkdir()
            metadata = {"type": "VirtualRide", "elapsed_time": 1500, "moving_time": 1500}
            (ride / "activity.json").write_text(json.dumps(metadata))
            power = [150] * 300 + [215] * 900 + [120] * 300
            (ride / "streams.csv").write_text("time,watts\n" + "".join(
                f"{i},{w}\n" for i, w in enumerate(power)))
            self.assertNotIn("measured_indoor_aerobic_references", prior_quality_sequences(state, cutoff, root))
            def references():
                return prior_quality_sequences(state, cutoff, root, aerobic_references=True)["measured_indoor_aerobic_references"]
            measured = references()["a"]
            self.assertEqual(measured["moving_minutes"], 25)
            block = measured["longest_detected_steady_power_block"]
            self.assertAlmostEqual(block["minutes"], 15, delta=1)
            self.assertAlmostEqual(block["mean_watts"], 215, delta=2)
            (ride / "activity.json").write_text(json.dumps(dict(metadata, icu_ignore_power=True)))
            self.assertEqual(references(), {})

    def test_quality_sequences_pair_finished_attempt_with_actual_previous_ride(self):
        state = {"activity_events": [event("a", 10, "easy_aerobic"), event("b", 11, "vt2"),
                                     event("c", 12, "easy_aerobic"), event("d", 13, "vt2")]}
        state["activity_events"][1].update(quality_role_fulfilled=True, planned_workout_completed=False)
        cutoff = datetime.fromisoformat("2026-11-13T10:15:00+01:00")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for entry in state["activity_events"]:
                folder = root / entry["activity_id"]
                folder.mkdir()
                (folder / "activity.json").write_text(json.dumps({"moving_time": 2400, "elapsed_time": 3600}))
            for name, day in (("a", 10), ("b", 14)):
                (root / name / "athlete-report.json").write_text(json.dumps({
                    "recorded_at": f"2026-11-{day}T18:00:00+01:00", "reports": ["Legs felt good"]}))
            context = prior_quality_sequences(state, cutoff, root)
        pair, = context["quality_sequences"]
        self.assertTrue(pair["role_fulfilled"])
        self.assertFalse(pair["full_workout_completed"])
        self.assertEqual(pair["previous_activity"]["athlete_report"]["reports"], ["Legs felt good"])
        self.assertNotIn("athlete_report", pair["attempt"])
        self.assertEqual([r["activity_id"] for r in context["latest_activities"]], ["c", "b", "a"])
        self.assertEqual([r["activity_id"] for r in pair["following_day"]["activities"]], ["c"])
        self.assertIsNone(pair["next_quality_session"])  # The next attempt is still in progress.

    def test_quality_followup_uses_local_day_and_next_actual_quality_even_outside_display_limit(self):
        reference = event("reference", 10, "vo2max")
        reference.update(started_at="2026-11-10T23:10:00Z", start_date_local="2026-11-11T00:10:00")
        easy = event("morning", 12, "easy_aerobic")
        easy["planned_role"] = "vt2"
        evening = event("evening", 12, "recovery")
        evening["started_at"] = "2026-11-12T18:00:00+01:00"
        partial = event("partial", 14, "vt2")
        partial.update(planned_workout_completed=False, quality_role_fulfilled=False)
        events = [reference, easy, evening, partial, event("rest-day", 15, "rest"),
                  event("q2", 16, "vt2"), event("q3", 18, "vt2")]
        cutoff = datetime.fromisoformat("2026-11-19T19:00:00+01:00")
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "partial"
            folder.mkdir()
            (folder / "activity.json").write_text(json.dumps({
                "icu_intervals": [{"type": "WORK", "elapsed_time": 75, "average_watts": 298}]}))
            history = prior_quality_sequences({"activity_events": events}, cutoff, Path(tmp))
            earlier = prior_quality_sequences({"activity_events": events[:5]}, cutoff, Path(tmp))
        by_id = {p["attempt"]["activity_id"]: p for p in history["quality_sequences"]}
        followup = by_id["reference"]
        self.assertEqual(followup["following_day"]["date"], "2026-11-12")
        self.assertEqual([r["activity_id"] for r in followup["following_day"]["activities"]],
                         ["morning", "evening"])
        outcome = followup["next_quality_session"]
        self.assertNotIn("partial", by_id)
        self.assertEqual(outcome["attempt"]["activity_id"], "partial")
        self.assertEqual(outcome["work_intervals"], [{"seconds": 75, "average_watts": 298}])
        self.assertFalse(outcome["full_workout_completed"])
        self.assertEqual(by_id["q2"]["following_day"]["activities"], [])
        rest, = earlier["quality_sequences"][0]["following_day"]["activities"]
        self.assertEqual(rest["completed_role"], "rest")

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
            (root / "a" / "athlete-report.json").write_text(json.dumps({"athlete_report": "Heavy legs late", "recorded_at": "2026-11-10T16:00:00+01:00"}))
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

    def test_missing_hr_preserves_matched_power_windows_and_duration(self):
        state = {"activity_events": [event("a", 10, "easy_aerobic")]}
        cutoff = datetime.fromisoformat("2026-11-11T10:00:00+01:00")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ride = root / "a"
            ride.mkdir()
            (ride / "activity.json").write_text(json.dumps({
                "type": "VirtualRide", "moving_time": 600, "elapsed_time": 600,
            }))
            (ride / "streams.csv").write_text(
                "time,watts\n" + "".join(f"{second},215\n" for second in range(600))
            )
            result = dose_comparisons(state, "easy_aerobic", 215, cutoff, root)
        candidate, = result["candidates"]
        self.assertEqual(candidate["moving_minutes"], 10)
        windows = candidate["matched_power_hr_windows"]
        self.assertEqual(windows["status"], "matched")
        self.assertEqual(windows["early"]["power_avg"], 215)
        self.assertEqual(windows["late"]["power_avg"], 215)
        hr = windows["fields"]["heartrate"]
        self.assertEqual(hr["status"], "unavailable")
        self.assertNotIn("delta", hr)

    def test_recorded_work_keeps_actual_short_bout_and_honors_ignored_power(self):
        metadata = {"icu_intervals": [
            {"type": "WORK", "elapsed_time": 178, "average_watts": 349},
            {"type": "RECOVERY", "elapsed_time": 180, "average_watts": 120},
            {"type": "WORK", "elapsed_time": 66, "average_watts": 347},
        ]}
        self.assertEqual(recorded_work_intervals(metadata), [
            {"seconds": 178, "average_watts": 349},
            {"seconds": 66, "average_watts": 347},
        ])
        metadata["icu_ignore_power"] = True
        self.assertIsNone(recorded_work_intervals(metadata)[1]["average_watts"])
        self.assertIsNone(recorded_work_intervals({}))
