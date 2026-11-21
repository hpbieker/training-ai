import argparse
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from recommend_training import aerobic_finish_lines, parse_training_target_json, resolve_aerobic_finish


class AerobicFinishTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime.fromisoformat("2026-11-20T12:50:00+01:00")
        self.offer = {"decision": "offer", "reason": "Useful aerobic volume before an easy day",
                      "check_at_minute": 90, "extra_minutes": 15, "alternative_extra_minutes": 40,
                      "good_response_limit": "Omit the difference to stay within the athlete's time limit.",
                      "intensity": "215 W",
                      "cue": "Breathing and effort are steady"}
        self.primary = {"action": "train", "selected_intensity": "vo2max",
                        "executable_now": {"minutes": 93}, "coaching_selection": {"minutes": 93}}
        self.target = {"target_minutes": 93}
        self.windows = [{"start": self.start, "end": self.start + timedelta(hours=3)}]
        self.calendar = {"cleanup_buffer_minutes": 15}

    def resolve(self, required=True, spacing_day=False):
        return resolve_aerobic_finish(self.primary, self.target, planned_at=self.start,
                                     available_windows=self.windows, calendar=self.calendar,
                                     required=required, spacing_day=spacing_day)

    def test_spacing_day_decline_requires_reviewing_a_smaller_addition(self):
        finish = {"decision": "finish", "reason": "Protect the next quality session",
                  "alternative_extra_minutes": 60, "good_response_limit": "The longer ride preceded a shortened set"}
        self.primary["coaching_selection"]["aerobic_finish"] = finish
        with self.assertRaisesRegex(ValueError, "smaller_extra_minutes"):
            self.resolve(spacing_day=True)
        finish.update(smaller_extra_minutes=20, good_response_limit="Even the shorter option exceeds the agreed dose")
        self.assertEqual(self.resolve(spacing_day=True), finish)
        self.assertIn("+20 / +60", "\n".join(aerobic_finish_lines(finish)))
        target = {"minutes": 93, "load": 100, "basis": "duration", "reason": "Agreed primary",
                  "evidence": ["Athlete report"], "aerobic_finish": finish}
        self.assertEqual(parse_training_target_json(json.dumps(target)), target)
        finish["smaller_extra_minutes"] = 60
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "below"):
            parse_training_target_json(json.dumps(target))

    def test_saved_primary_needs_separate_decision_even_with_planned_endurance(self):
        self.primary["coaching_selection"]["endurance_extension"] = {"reason": "Base volume"}
        with self.assertRaisesRegex(ValueError, "training_target.aerobic_finish"):
            self.resolve()
        self.assertIsNone(self.resolve(required=False))

    def test_spacing_offer_compares_work_recovery_and_achieved_reference(self):
        offer = {**self.offer, "extra_minutes": 15, "alternative_extra_minutes": 30}
        self.primary["coaching_selection"]["aerobic_finish"] = offer
        self.target["capacity_horizon"] = {"next_workout_at": (self.start + timedelta(days=1)).isoformat()}
        self.target["vt1_dose_comparison"] = {
            "working_power_w": 210, "prescribed_steady_work_minutes": 78,
            "reference_vs_prescription": {"reference": {"activity_id": "ref",
                "detected_steady_block": {"minutes": 108, "mean_watts": 211}}},
            "candidates": [{"activity_id": "ref", "next_quality_session": {"planned_role": "vt2",
                "planned_workout_completed": False, "quality_role_fulfilled": True}}]}
        with self.assertRaisesRegex(ValueError, "aerobic_finish.limit_basis"):
            self.resolve(spacing_day=True)
        offer["limit_basis"] = "plan_limit"
        result = self.resolve(spacing_day=True)
        facts = result["spacing_comparison"]
        self.assertEqual(facts["offered"]["work_minutes_including_extension"], 93)
        self.assertEqual(facts["alternative"]["work_minutes_including_extension"], 108)
        self.assertEqual(facts["alternative"]["finish_to_next_start_minutes"], 1440 - 123)
        self.assertEqual(facts["offered"]["finish_to_next_start_minutes"], 1440 - 108)
        self.assertFalse(facts["reference"]["subsequent_quality"]["planned_workout_completed"])
        self.assertIn("plan_limit", "\n".join(aerobic_finish_lines(result)))
        del offer["limit_basis"]
        offer.update(extra_minutes=30, alternative_extra_minutes=15)
        self.assertEqual(self.resolve(spacing_day=True)["total_minutes"], 123)
        offer.update(extra_minutes=60, alternative_extra_minutes=45)
        with self.assertRaisesRegex(ValueError, "marginal_benefit"):
            self.resolve(spacing_day=True)
        offer["marginal_benefit"] = "Only long-ride opportunity before the event; the other available day is short."
        result = self.resolve(spacing_day=True)
        self.assertEqual(result["total_minutes"], 153)
        self.assertIn(offer["marginal_benefit"], "\n".join(aerobic_finish_lines(result)))

    def test_checkpoint_and_optional_times_preserve_primary_and_cooldown(self):
        self.primary["coaching_selection"]["aerobic_finish"] = self.offer
        result = self.resolve()
        self.assertEqual(result["total_minutes"], 108)
        for field, minutes in (("finish_at", 108), ("cleanup_end", 123)):
            self.assertEqual(datetime.fromisoformat(result[field]), self.start + timedelta(minutes=minutes))
        self.assertEqual(self.primary["executable_now"]["minutes"], 93)
        summary = "\n".join(aerobic_finish_lines(result))
        for required in ("90 min from workout start", "+15 min", "215 W", "108 min", "14:38", "14:53", self.offer["cue"]):
            self.assertIn(required, summary)
        self.assertNotIn("14:20", summary)

    def test_early_response_check_does_not_start_the_extra_minutes(self):
        self.primary["selected_intensity"] = "vt1"
        self.primary["coaching_selection"]["aerobic_finish"] = {**self.offer, "check_at_minute": 142}
        self.primary["executable_now"] = {"minutes": 150, "timeline": {"status": "complete", "segments": [
            {"start_seconds": 0, "end_seconds": 720, "duration_seconds": 720, "power": 165, "end_power": 204},
            {"start_seconds": 720, "end_seconds": 8820, "duration_seconds": 8100, "power": 215},
            {"start_seconds": 8820, "end_seconds": 9000, "duration_seconds": 180, "power": 150}]}}
        self.target.update(target_minutes=150, vt1_dose_comparison={"working_power_w": 215})
        finish = self.resolve()
        self.assertEqual(finish["checkpoint_segment"]["minutes_completed"], 130)
        self.assertEqual(finish["extension_start"], {"segment": 2, "work_minutes": 135, "ridden_minutes": 147})
        summary = aerobic_finish_lines(finish)
        self.assertIn("after completing 135 min", summary[0])
        self.assertIn("Total 165 min", summary[0])
        self.assertTrue(any("EARLIER RESPONSE CHECK: after 130 min" in line for line in summary))

    def test_calendar_and_cleanup_can_veto_an_offer(self):
        self.primary["coaching_selection"]["aerobic_finish"] = self.offer
        self.calendar["hard_stop"] = {"at": "2026-11-20T14:38:00+01:00"}
        self.assertEqual(self.resolve()["decision"], "finish")
        self.calendar.clear()
        self.windows[0]["end"] = self.start + timedelta(minutes=100)
        self.assertEqual(self.resolve()["decision"], "finish")
        self.windows.clear()
        unknown = self.resolve()
        self.assertEqual(unknown["decision"], "finish")
        self.assertIn("has not been confirmed", unknown["reason"])

    def test_prior_offer_needs_a_comparison_only_if_still_feasible(self):
        legacy = self.offer.copy()
        del legacy["alternative_extra_minutes"]
        del legacy["good_response_limit"]
        self.primary["coaching_selection"]["aerobic_finish"] = legacy
        with self.assertRaisesRegex(ValueError, "alternative_extra_minutes"):
            self.resolve()
        self.assertEqual(self.resolve(required=False)["decision"], "offer")
        self.calendar["hard_stop"] = {"at": "2026-11-20T14:38:00+01:00"}
        self.assertEqual(self.resolve()["decision"], "finish")

    def test_short_offer_must_review_the_marginal_minutes_on_good_legs(self):
        offer = {**self.offer, "extra_minutes": 15, "alternative_extra_minutes": 30}
        limit = offer.pop("good_response_limit")
        self.primary["coaching_selection"]["aerobic_finish"] = offer
        with self.assertRaisesRegex(ValueError, "good_response_limit"):
            self.resolve()
        self.assertEqual(self.resolve(required=False)["extra_minutes"], 15)
        offer["good_response_limit"] = limit
        self.assertIn(limit, "\n".join(aerobic_finish_lines(self.resolve())))
        del offer["good_response_limit"]
        offer.update(extra_minutes=30, alternative_extra_minutes=15)
        self.assertEqual(self.resolve()["extra_minutes"], 30)

    def test_respects_coach_finish_and_existing_limits(self):
        finish = {"decision": "finish", "reason": "Prioritize recovery before the next quality ride",
                  "alternative_extra_minutes": 30,
                  "good_response_limit": "Last comparable addition compromised the early quality ride"}
        self.primary["coaching_selection"]["aerobic_finish"] = finish
        self.assertEqual(self.resolve(), finish)
        self.primary["coaching_selection"]["aerobic_finish"] = self.offer
        self.target["illness_return_guardrail"] = {"active": True}
        self.assertEqual(self.resolve()["decision"], "finish")
        self.primary["selected_intensity"] = "active_recovery"
        self.assertIsNone(self.resolve())

    def test_saved_finish_needs_good_response_comparison_when_there_is_room(self):
        previous = {"decision": "finish", "reason": "Tomorrow morning is open for easy training"}
        self.primary["coaching_selection"]["aerobic_finish"] = previous
        with self.assertRaisesRegex(ValueError, "good_response_limit"):
            self.resolve()
        self.assertEqual(self.resolve(required=False), previous)
        self.calendar["hard_stop"] = {"at": "2026-11-20T14:38:00+01:00"}
        self.assertEqual(self.resolve()["decision"], "finish")

    def test_offer_requires_actionable_finite_fields(self):
        target = {"minutes": 93, "load": 100, "basis": "duration", "reason": "Primary dose",
                  "evidence": ["Training history"], "aerobic_finish": self.offer}
        self.assertEqual(parse_training_target_json(json.dumps(target)), target)
        for change in ({"extra_minutes": True}, {"check_at_minute": 94}, {"extra_minutes": float("inf")},
                       {"cue": ""}, {"intensity": None}, {"extra_minutes": 0}, {"good_response_limit": " "},
                       {"alternative_extra_minutes": 15}, {"alternative_extra_minutes": 0},
                       {"alternative_extra_minutes": True}):
            with self.subTest(change=change), self.assertRaises(argparse.ArgumentTypeError):
                parse_training_target_json(json.dumps({**target, "aerobic_finish": {**self.offer, **change}}))
