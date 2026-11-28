"""Exercise cutoff, complete VT2 series and activity-scoped evidence through normal entry points."""
from argparse import Namespace
from datetime import date, datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from activity_inspect_pipeline import inspect_with_cache
from progression_advisor import compact_inspect_summary, recent_relevant_activities
from recommend_training import annotate_volume_density, training_history_context, xert_load_windows

OSLO = ZoneInfo("Europe/Oslo")


class VT2SeriesTests(unittest.TestCase):
    def test_dated_evidence_retains_weak_short_and_unmapped_repetitions(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            ride = root / "activities" / "ride"
            ride.mkdir(parents=True)
            intervals, lines = [], ["time,watts,heartrate,cadence"]
            for duration, watts, kind in ((600, 300, "WORK"), (60, 100, "RECOVERY"),
                                          (600, 300, "WORK"), (60, 100, "RECOVERY"),
                                          (90, 240, "WORK"), (600, 205, "WORK")):
                start = len(lines)-1
                for i in range(start, start + duration//5):
                    lines.append(f"{i*5},{watts},145,85")
                intervals.append({"type": kind, "start_index": start, "end_index": len(lines)-1,
                                  "elapsed_time": duration, "average_watts": watts})
            (ride / "streams.csv").write_text("\n".join(lines))
            (ride / "activity.json").write_text(json.dumps({"id": "ride", "name": "Trainer",
                "start_date_local": "2026-11-16T10:00:00", "type": "VirtualRide", "trainer": True,
                "icu_intervals": intervals}))
            path = ride / "vt2-evidence.json"
            evidence = {"activity_id": "ride", "prescription_source": "saved workout",
                        "prescribed_watts": 300, "series": [
                            {"source_interval": i, "duration_s": 600} for i in (1, 3, 5)]}
            args = Namespace(artifacts_dir=str(root), output_dir=root/"cache", force=False,
                             analysis_options_json={"shape": "brief", "mode": "vt2"})
            def run():
                manifest = inspect_with_cache(str(ride), args)
                return json.loads(Path(manifest["cache_path"]).read_text())["result"]
            path.write_text(json.dumps(evidence))
            result = compact_inspect_summary(run())
            self.assertEqual([r["watts_avg"] for r in result["vt2_series"]], [300, 300, 240])
            self.assertEqual(result["vt2_intensity_classification"], "unresolved")
            self.assertEqual(result["vt2_series"][-1]["duration_difference_s"], -510)
            self.assertEqual(result["vt2_mechanical_execution"]["power_fade_pct"], 20)
            self.assertEqual(result["vt2_verdict"], "power_execution_variable_or_off_target")

            evidence["anchor"] = {"watts": 295, "source": "dated assessment", "valid_on": "2026-11-16"}
            evidence["series"].append({"source_interval": None, "duration_s": 600})
            path.write_text(json.dumps(evidence))
            result = run()["vt2_quality"]
            self.assertEqual(result["anchor_watts"], 295)
            self.assertEqual(result["blocks"][2]["target_watts"], 300)
            self.assertFalse(result["blocks"][2]["within_anchor_candidate_band"])
            self.assertEqual(result["blocks"][3]["reason"], "no_mapped_recording")
            quality = result["session_quality"]
            self.assertEqual((quality["mapped_repetitions"], quality["prescribed_repetitions"]), (3, 4))
            self.assertNotIn("power_fade_pct", quality)
            self.assertEqual(quality["verdict"], "execution_incomplete_evidence")

            path.unlink()
            result = run()["vt2_quality"]
            self.assertEqual(result["series_scope"], "recorded_work_intervals")
            self.assertEqual(result["block_count"], 4)
            self.assertEqual(result["session_quality"]["target_attainment"], "unresolved")


class HistoryCutoffTests(unittest.TestCase):
    def test_native_xert_windows_and_projection_use_completed_rides_once(self):
        cutoff = datetime(2026, 11, 17, 9, tzinfo=OSLO)
        activities = [
            {"start_local": f"2026-11-{when}", "duration_s": 3600, "xss": {"total": 80}}
            for when in ("10T09:00:00", "16T10:00:00", "17T06:00:00", "17T08:30:00")
        ]
        payload = {
            "start_date": "2026-10-25", "end_date": "2026-11-17",
            "activities": activities, "includeFields": ["xss", "duration_s"],
            "filters": [], "sort": [], "limit": None,
            "source_count": len(activities), "matched_count": len(activities),
            "count": len(activities),
        }
        with TemporaryDirectory() as folder:
            def history(source=payload):
                return training_history_context("2026-11-17", cutoff=cutoff, artifacts_dir=Path(folder),
                                                xert_activity_loads=source, local_timezone=OSLO)

            context = history()
            windows = context["xert_load_windows"]
            self.assertEqual(windows["completed_7d"]["xss"], 160)
            self.assertEqual(windows["week_including_today"]["activity_count"], 2)
            self.assertEqual(windows["completed_3d"]["elapsed_hours"], 1)
            target = {"endurance_duration_solution": {"duration_minutes": 90, "achieved_xss": {"total": 95}}}
            annotate_volume_density(target, history_context=context)
            projected = target["week_if_full_remaining_session_ridden_today"]
            self.assertEqual((projected["elapsed_hours"], projected["xss"]), (3.5, 255))
            self.assertEqual(history()["xert_load_windows"], windows)
            del activities[1]["duration_s"]
            self.assertNotIn("completed_7d", history()["xert_load_windows"])

    def test_xert_v2_windows_require_an_unfiltered_and_uncapped_list(self):
        cutoff = datetime(2026, 11, 17, 9, tzinfo=OSLO)
        payload = {
            "start_date": "2026-10-27", "end_date": "2026-11-17",
            "activities": [], "includeFields": ["xss", "duration_s"],
            "filters": [], "sort": [], "limit": None,
            "source_count": 0, "matched_count": 0, "count": 0,
        }
        result = xert_load_windows(payload, cutoff=cutoff, local_timezone=OSLO)
        self.assertEqual(len(result), 5)
        for window in result.values():
            self.assertEqual((window["activity_count"], window["elapsed_hours"], window["xss"]), (0, 0, 0))
        for changes in (
            {"filters": [{"field": "xss.total", "op": "gt", "value": 0}]},
            {"limit": 5},
            {"source_count": 1},
            {"matched_count": 1},
            {"count": 1},
            {"count": False},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(xert_load_windows(
                    {**payload, **changes}, cutoff=cutoff, local_timezone=OSLO,
                ), {})

    def test_all_history_uses_completion_before_or_equal_to_cutoff(self):
        cutoff = datetime(2026, 11, 17, 9, tzinfo=OSLO)
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name, start, elapsed in [
                ("overnight", "2026-11-16T23:50:00", 1200),
                ("boundary", "2026-11-17T07:00:00Z", 3600),
                ("in_progress", "2026-11-17T08:01:00", 3600),
                ("unknown_finish", "2026-11-17T04:00:00", None),
                ("unknown_start", "2026-11-17", 3600),
                ("later", "2026-11-17T14:44:44", 9006),
            ]:
                ride = root/"activities"/name
                ride.mkdir(parents=True)
                (ride/"activity.json").write_text(json.dumps({"id": name, "name": "VT2",
                    "start_date_local": start, "moving_time": 300, "elapsed_time": elapsed}))
            xert = {"activities": [
                {"start_local": "2026-11-17T08:02:00", "name": "VT2", "elapsed_minutes": 60,
                 "xss": {"total": 120}}]}
            history = training_history_context("2026-11-17", cutoff=cutoff, artifacts_dir=root,
                                               xert_activity_loads=xert, local_timezone=OSLO)
            self.assertEqual(history["activity_history_count"], 2)
            self.assertEqual(history["rolling_14d"]["activity_count"], 2)
            self.assertEqual(history["rolling_7d"]["xss"], 0)
            self.assertEqual(history["xss_activity_match_count"], 0)
            candidates = recent_relevant_activities(workout_type="vt2", day=date(2026, 11, 17),
                cutoff=cutoff, local_timezone=OSLO, lookback_days=7, max_sessions=5,
                artifacts_dir=root, target_power_w=300, reviewed_events={})
            self.assertEqual([r.activity_id for r in candidates], ["boundary", "overnight"])
