import argparse
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_training_request import build_arguments
from recommend_training import (
    calendar_context_with_slack,
    format_compact_summary,
    parse_calendar_context_payload,
    parse_timezone,
)


class SavedRequestTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.now = datetime.fromisoformat("2026-11-20T09:43:00+01:00")
        self.start = "2026-11-20T10:40:00+01:00"
        self.input = {
            "planning_context": {"planned_at": self.start, "local_timezone": "Europe/Oslo",
                                 "calendar": {"day_start": "2026-11-20T08:45:00+01:00",
                                              "setup_buffer_minutes": 15}},
            "sources": {"xert_recommended_training": {
                "path": "advice.json", "read_at": "2026-11-20T09:20:00+01:00"}},
        }
        (self.root / "advice.json").write_text(json.dumps({"advice": {"at": self.start}}))

    def arguments(self, **options):
        path = self.root / "request.json"
        path.write_text(json.dumps(self.input))
        return build_arguments(path, self.now, **options)

    def test_compact_default_and_detailed_opt_in(self):
        self.assertIn("--compact-summary", self.arguments())
        self.assertIn("--summary", self.arguments(details=True))

    def test_vt1_request_requires_activity_volume(self):
        self.input["plan_selection"] = {"intensity_goal": "vt1"}
        with self.assertRaisesRegex(ValueError, "sources.intervals_activity_volume"):
            self.arguments()

    def test_reuse_keeps_source_and_updates_decision_clock(self):
        args = self.arguments()
        planning = json.loads(args[args.index("--planning-context-json") + 1])
        sources = json.loads(args[args.index("--source-overrides-json") + 1])
        self.assertEqual(Path(sources["xert_recommended_training"]), (self.root / "advice.json").resolve())
        self.assertEqual(planning["now"], self.now.isoformat())
        self.assertEqual(planning["calendar"]["day_start"], planning["now"])
        self.assertEqual(planning["planned_at"], self.start)
        self.assertEqual(json.loads(args[args.index("--refresh-json") + 1]), {"mode": "none"})

    def test_new_file_time_does_not_rejuvenate_old_plugin_read(self):
        self.input["sources"]["garmin"] = {"path": "new-copy.json", "read_at": "2026-11-20T09:27:00+01:00"}
        with self.assertRaisesRegex(ValueError, "Refresh.*garmin"):
            self.arguments()

    def test_moving_start_requires_matching_xert_advice(self):
        self.input["planning_context"]["planned_at"] = "2026-11-20T12:30:00+01:00"
        with self.assertRaisesRegex(ValueError, "Xert advice"):
            self.arguments()

    def test_saved_blocker_must_agree_with_resolved_personal_titles(self):
        calendar = self.input["planning_context"]["calendar"]
        event = dict(subject="Reserved slot", classification="fixed_blocker",
                     start="2026-11-20T16:00:00+01:00", end="2026-11-20T17:00:00+01:00")
        calendar.update(day_end="2026-11-20T20:00:00+01:00", events=[event])
        with self.assertRaisesRegex(ValueError, "open_training_subjects"):
            self.arguments()
        calendar["open_training_subjects"] = ["reserved SLOT"]
        zone = parse_timezone("Europe/Oslo")
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "Classify.*open_training"):
            parse_calendar_context_payload(calendar, local_timezone=zone)
        event["classification"] = "open_training"
        for field in ("hard_stop", "practical_stop"):
            with self.subTest(field=field), self.assertRaisesRegex(argparse.ArgumentTypeError, field):
                parse_calendar_context_payload({**calendar, field: {"subject": event["subject"], "at": event["start"]}},
                                              local_timezone=zone)
        sessions = [{"end": "2026-11-20T15:58:00+01:00"}]

        def next_stop():
            parsed = parse_calendar_context_payload(calendar, local_timezone=zone)
            return calendar_context_with_slack(parsed, sessions=sessions)["hard_stop"]

        self.assertIsNone(next_stop())
        calendar["events"].append({**event, "classification": "fixed_blocker", "subject": "Project meeting"})
        self.assertEqual(next_stop(), {"subject": "Project meeting", "at": event["start"]})

    def test_missed_setup_window_requires_new_placement(self):
        self.now = datetime.fromisoformat("2026-11-20T10:30:00+01:00")
        with self.assertRaisesRegex(ValueError, "setup window"):
            self.arguments()

    def test_compact_summary_surfaces_blockers_and_withholds_unusable_timeline(self):
        primary = {
            "action": "rest", "provisional": False,
            "intensity_decision": {"requested_goal": "vt2", "readiness_ceiling": "readiness_unknown"},
            "readiness_evidence": {"direct_signal_coverage": "partial", "unassessed_direct_signals": ["hrv"]},
            "executable_now": {"minutes": 0, "intensity": "none", "timeline": {"status": "unavailable"}},
            "unexecuted_remainder": {"minutes": 0, "disposition": "none"},
        }
        packet = {
            "primary_decision": primary, "planned_at": self.start, "planned_at_source": "planning_context",
            "target_resolution": {},
            "plan_context": {"dated_athlete_constraints": [
                {"active": False, "quote": "Earlier constraint", "source": "chat-old"},
            ]},
            "decision_inputs": {
                "freshness_summary": {"guidance": "review", "stale_inputs": ["xert"]},
                "wellness": {},
            },
            "llm_context": {
                "health_constraints": {"no_training_today": True, "reason": "current_day_sickness_annotation"},
                "time_context": {"calendar": {}},
            },
        }
        packet_path = self.root / "recommendation-packet.json"
        rest = format_compact_summary(packet, packet_path)
        self.assertIn(f"PACKET: {packet_path}", rest)
        self.assertIn("PRIMARY DECISION: REST", rest)
        self.assertIn("current_day_sickness_annotation", rest)
        self.assertIn('"unassessed_direct_signals":["hrv"]', rest)
        self.assertIn("Stale dynamic inputs: xert", rest)
        self.assertNotIn("Earlier constraint", rest)

        primary.update(action="train", provisional=True)
        primary["unexecuted_remainder"] = {"minutes": 30, "disposition": "unscheduled"}
        primary["executable_now"] = {
            "minutes": 50, "intensity": "vt2",
            "segments": [{"role": "vt2", "duration_minutes": 80, "fits_executable_window": False,
                          "available_minutes": 50}],
            "timeline": {"status": "requires_session_specific_calculation"},
        }
        packet["llm_context"]["health_constraints"] = {}
        shortened = format_compact_summary(packet, packet_path)
        self.assertIn("PROVISIONAL SESSION: 80 min VT2 complete workout required", shortened)
        self.assertIn("TIMELINE: requires_session_specific_calculation", shortened)
        self.assertIn("REMAINDER: 30 min; unscheduled; do not schedule automatically", shortened)
        self.assertNotIn("SEGMENT:", shortened)
