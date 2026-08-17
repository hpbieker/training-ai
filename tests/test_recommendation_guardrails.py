import argparse
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from plan_state import recommendation_plan_context
from recommend_training import (
    annotate_volume_density,
    apply_split_preference_to_windows,
    annotate_dose_composition_window_fit,
    annotate_route_window_fit,
    authoritative_progression_line,
    apply_execution_modality_constraint,
    apply_quality_workout_vt1_composition,
    apply_xert_endurance_duration_solution,
    apply_acute_readiness_target_guardrail,
    apply_readiness_domain_target_cap,
    body_battery_summary_line,
    build_primary_decision,
    build_planning_context,
    build_source_refresh_plan,
    calendar_context_with_slack,
    compact_xert_workout_recommendations,
    compact_freshness_summary,
    executable_now_line,
    finalize_plan_trace,
    format_summary,
    garmin_readiness_line,
    garmin_readiness_driver_line,
    garmin_vo2max_line,
    garmin_source_day,
    hrv_readiness_risk,
    initialize_plan_trace,
    intensity_signal_agreement,
    mcp_sources_requiring_refresh,
    parse_availability_payload,
    parse_planning_context_json,
    parse_plan_selection_json,
    parse_quality_workout_json,
    parse_endurance_workout_json,
    parse_endurance_structure_json,
    parse_refresh_json,
    parse_route_options_json,
    parse_source_overrides_json,
    parse_training_target_json,
    presentation_requirements,
    resolve_training_targets,
    route_dose_fit_line,
    required_plan_target_power,
    require_endurance_solution_for_selected_domain,
    require_quality_workout_for_selected_domain,
    select_intensity_domain,
    solve_endurance_structure,
    split_endurance_structure,
    split_session_info,
    split_session_guidance,
    xert_readiness_command,
)
from route_recommendations import score_route, surface_classification


class TrainingTargetContractTests(unittest.TestCase):
    def test_split_endurance_structure_preserves_first_session_and_solves_second(self):
        structure = split_endurance_structure(
            {
                "signature": {"tp": 295.85, "hie": 14201, "pp": 777.6},
                "segments": [
                    {"duration_seconds": 900, "power": 150},
                    {"duration_seconds": 3600, "power": 200},
                    {"duration_seconds": 900, "power": 120},
                ],
                "adjustable_segment_index": 1,
                "minimum_duration_seconds": 1800,
                "maximum_duration_seconds": 7200,
            },
            first_session_minutes=180,
        )
        calculation = solve_endurance_structure(
            {"target_load": 259, "xert_recommended_target_xss": {"low": 259}},
            structure=structure,
        )

        self.assertEqual(sum(
            segment["duration_seconds"] for segment in calculation["segments"][:3]
        ), 10800)
        self.assertAlmostEqual(calculation["achieved_xss"]["low"], 259, delta=0.05)
        self.assertGreater(calculation["duration_seconds"] / 60, 269.3)

    def test_volume_density_classifies_projected_14_and_21_day_load(self):
        target = {"target_minutes": 270}
        annotate_volume_density(
            target,
            history_context={
                "rolling_14d": {"moving_hours": 25.5},
                "rolling_21d": {"moving_hours": 40.5},
            },
        )

        self.assertEqual(target["volume_density"]["classification"], "normal_density")
        self.assertEqual(
            [row["projected_weekly_equivalent_hours"] for row in target["volume_density"]["windows"]],
            [15.0, 15.0],
        )

    def test_route_duration_match_improves_score_when_quality_is_equal(self):
        common = {
            "distance_km": 100,
            "starts_ends_near_start_anchor": True,
            "steady_endurance": {"downhill_disruption_pct": 2},
            "surface": {"surface": "road"},
        }
        matched = score_route(
            {**common, "moving_minutes": 265},
            target_distance_km=100,
            target_minutes=269,
            prefer_terrain_steady_endurance=True,
            surface_preference="road",
        )
        short = score_route(
            {**common, "moving_minutes": 205},
            target_distance_km=100,
            target_minutes=269,
            prefer_terrain_steady_endurance=True,
            surface_preference="road",
        )
        self.assertGreater(matched, short)

    def test_route_window_fit_separates_calendar_fit_from_dose_fit(self):
        oslo = ZoneInfo("Europe/Oslo")
        packet = {
            "recommendations": [
                {"name": "Sørkedalen x 6", "moving_minutes": 205.2}
            ]
        }

        annotate_route_window_fit(
            packet,
            target_minutes=269.3,
            planned_at=datetime(2026, 8, 8, 9, 30, tzinfo=oslo),
            now=datetime(2026, 8, 8, 9, 0, tzinfo=oslo),
            available_windows=[
                {
                    "start": datetime(2026, 8, 8, 9, 30, tzinfo=oslo),
                    "end": datetime(2026, 8, 8, 21, 0, tzinfo=oslo),
                }
            ],
        )

        route = packet["recommendations"][0]
        self.assertTrue(route["window_fit"]["fits_first_window"])
        self.assertFalse(route["dose_fit"]["covers_prescribed_duration"])
        self.assertEqual(route["dose_fit"]["under_by_minutes"], 64.1)
        self.assertEqual(
            route["dose_fit"]["action"],
            "extend_route_or_add_vt1_minutes",
        )
        self.assertIn(
            "short of prescribed duration by 64.1 min",
            route_dose_fit_line(route["dose_fit"]),
        )

    def test_endurance_structure_parser_requires_agent_selected_structure(self):
        parsed = parse_endurance_structure_json(
            json.dumps(
                {
                    "signature": {"tp": 300, "hie": 14000, "pp": 800},
                    "segments": [{"duration_seconds": 3600, "power": 210}],
                    "adjustable_segment_index": 0,
                }
            )
        )
        self.assertEqual(parsed["adjustable_segment_index"], 0)
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_endurance_structure_json(
                json.dumps({"signature": {}, "segments": []})
            )

    def test_endurance_structure_uses_post_guardrail_low_xss_target(self):
        target = {
            "target_load": 150.0,
            "xert_recommended_target_xss": {"low": 200.0},
        }
        calculation = solve_endurance_structure(
            target,
            structure={
                "signature": {"tp": 300, "hie": 14000, "pp": 800},
                "segments": [
                    {"duration_seconds": 900, "power": 150},
                    {"duration_seconds": 3600, "power": 210},
                    {"duration_seconds": 900, "power": 120},
                ],
                "adjustable_segment_index": 1,
            },
        )

        self.assertEqual(calculation["target_low_xss"], 150.0)
        self.assertTrue(calculation["matched_within_tolerance"])

    def test_endurance_workout_parser_requires_calculation(self):
        parsed = parse_endurance_workout_json(
            json.dumps({"calculation": {"source": "solver"}})
        )
        self.assertEqual(parsed["calculation"]["source"], "solver")
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_endurance_workout_json(json.dumps({"calculation": {}}))

    def test_xert_endurance_solution_replaces_mixed_history_duration(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 220.2,
            "target_load": 264.2,
            "xert_recommended_target_xss": {
                "low": 259.0,
                "high": 5.0,
                "peak": 0.2,
            },
            "reason": "mixed-history estimate",
        }
        initialize_plan_trace(target)
        solution = apply_xert_endurance_duration_solution(
            target,
            selected_intensity="vt1",
            calculation={
                "source": "local_xert_endurance_duration_solver",
                "network_used": False,
                "model_basis": "test-model",
                "matched_within_tolerance": True,
                "target_low_xss": 259.0,
                "achieved_xss": {
                    "total": 259.01,
                    "low": 259.01,
                    "high": 0.0,
                    "peak": 0.0,
                },
                "duration_seconds": 14820,
                "adjustable_segment_index": 1,
                "adjustable_duration_seconds": 13020,
                "segments": [{}, {}, {}],
                "difficulty": 62.0,
                "feasibility": {"valid": True},
                "low_xss_error": 0.01,
                "tolerance_xss": 0.05,
            },
        )

        self.assertEqual(target["pre_endurance_solution_target_minutes"], 220.2)
        self.assertEqual(target["target_minutes"], 247.0)
        self.assertEqual(target["target_load"], 259.0)
        self.assertEqual(solution["target_low_xss"], 259.0)
        self.assertEqual(solution["achieved_xss"]["high"], 0.0)
        self.assertNotIn("mixed-history estimate", target["reason"])
        self.assertEqual(
            target["dose_position_vs_typical"]["label"],
            "xert_solved_for_selected_domain",
        )

        finalize_plan_trace(target)
        self.assertEqual(target["plan_trace"]["adjustment"]["status"], "recalculated")
        self.assertEqual(
            target["plan_trace"]["final_plan"]["relationship_to_base"],
            "recalculated_for_selected_domain",
        )

    def test_xert_endurance_solution_rejects_wrong_low_target(self):
        with self.assertRaisesRegex(ValueError, "post-guardrail"):
            apply_xert_endurance_duration_solution(
                {
                    "target_minutes": 220.2,
                    "target_load": 264.2,
                    "xert_recommended_target_xss": {"low": 259.0},
                },
                selected_intensity="vt1",
                calculation={
                    "source": "local_xert_endurance_duration_solver",
                    "network_used": False,
                    "matched_within_tolerance": True,
                    "target_low_xss": 200.0,
                    "achieved_xss": {
                        "total": 200.0,
                        "low": 200.0,
                        "high": 0.0,
                        "peak": 0.0,
                    },
                    "duration_seconds": 12000,
                    "feasibility": {"valid": True},
                    "tolerance_xss": 0.05,
                },
            )

    def test_vt1_requires_xert_solved_endurance_duration(self):
        with self.assertRaisesRegex(SystemExit, "solve-endurance"):
            require_endurance_solution_for_selected_domain(
                intensity_decision={"selected_domain": "vt1"},
                target_resolution={"target_minutes": 220.2},
            )

        require_endurance_solution_for_selected_domain(
            intensity_decision={"selected_domain": "vt1"},
            target_resolution={"endurance_duration_solution": {"source": "xert"}},
        )

    def test_garmin_recovery_time_line_explains_scope(self):
        line = garmin_readiness_line(
            {
                "training_readiness_score": 28,
                "training_readiness_level": "LOW",
                "projected_recovery_time_hours_at_planned": 44.0,
                "recovery_time_factor_feedback": "POOR",
            }
        )
        self.assertIn("Garmin Recovery Time 44.0 h", line)
        self.assertIn("next hard workout", line)
        self.assertIn("not a ban on easy or moderate activity", line)

    def test_training_readiness_drivers_are_grouped_and_diagnostic(self):
        line = garmin_readiness_driver_line(
            {
                "training_readiness_drivers": {
                    "sleep_score": {"feedback": "GOOD"},
                    "hrv_status": {"feedback": "GOOD"},
                    "recovery_time": {"feedback": "POOR"},
                    "acute_load": {"feedback": "MODERATE"},
                },
                "training_readiness_driver_families": {
                    "autonomic_lifestyle": ["sleep_score", "hrv_status"],
                    "load_recovery": ["acute_load", "recovery_time"],
                },
            }
        )
        self.assertIn("sleep/HRV/stress", line)
        self.assertIn("load/recovery", line)
        self.assertIn("Recovery Time=POOR", line)
        self.assertIn("diagnostic only", line)
        self.assertIn("overlapping signals", line)

    def test_vo2max_line_preserves_generic_and_explains_scope(self):
        line = garmin_vo2max_line(
            {
                "estimates": {
                    "cycling": {
                        "precise_value": 53.4,
                        "calendar_date": "2026-08-07",
                        "age_days_at_requested_date": 1,
                    },
                    "generic": {"value": 51.0},
                }
            }
        )
        self.assertIn("cycling=53.4", line)
        self.assertIn("generic=51.0", line)
        self.assertNotIn("running", line.lower())
        self.assertIn("trend context only", line)
        self.assertIn("not acute readiness", line)

    def test_vt2_progression_requires_explicit_plan_power(self):
        self.assertEqual(
            required_plan_target_power(
                {"vt2": {"target_power_w": 290}},
                workout_type="vt2",
            ),
            290,
        )
        with self.assertRaisesRegex(SystemExit, "target_power_w"):
            required_plan_target_power(
                {"vt2": {"anchor": "3 x 18 min @ 290 W"}},
                workout_type="vt2",
            )

    def test_accepts_minutes_and_or_load(self):
        self.assertEqual(
            parse_training_target_json('{"minutes":75,"load":60}'),
            {"minutes": 75.0, "load": 60.0},
        )
        self.assertEqual(
            parse_training_target_json('{"minutes":75}'),
            {"minutes": 75.0},
        )

    def test_rejects_empty_unknown_and_non_positive_values(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "minutes and/or load"):
            parse_training_target_json("{}")
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "unsupported"):
            parse_training_target_json('{"xss":60}')
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "positive number"):
            parse_training_target_json('{"load":0}')

    def test_plan_selection_requires_and_normalizes_goal(self):
        selection = parse_plan_selection_json('{"intensity_goal":"vt2"}')
        self.assertEqual(selection["intensity_goal"], "vt2")
        self.assertEqual(selection["state"], Path("config/plan-state.json"))
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "intensity_goal"):
            parse_plan_selection_json("{}")


class ExecutionOptionsContractTests(unittest.TestCase):
    def test_parses_refresh_modes_and_selected_sources(self):
        self.assertEqual(parse_refresh_json('{"mode":"auto"}'), {"mode": "auto", "sources": []})
        self.assertEqual(
            parse_refresh_json('{"mode":"selected","sources":["xert","garmin"]}'),
            {"mode": "selected", "sources": ["garmin", "xert"]},
        )

    def test_rejects_inconsistent_refresh_options(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "requires sources"):
            parse_refresh_json('{"mode":"selected"}')
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "only allowed"):
            parse_refresh_json('{"mode":"auto","sources":["garmin"]}')

    def test_parses_route_options_with_defaults(self):
        options = parse_route_options_json('{"map_scope":"none","rebuild_index":true}')
        self.assertEqual(options["index"], Path("outputs/route-index.json"))
        self.assertTrue(options["rebuild_index"])
        self.assertEqual(options["map_scope"], "none")

    def test_parses_normalized_source_override_files(self):
        with tempfile.TemporaryDirectory() as directory:
            garmin_path = Path(directory) / "garmin.json"
            xert_path = Path(directory) / "xert.json"
            garmin_path.write_text('{"date":"2026-07-31"}', encoding="utf-8")
            xert_path.write_text('{"training_advice":{}}', encoding="utf-8")
            overrides = parse_source_overrides_json(
                json.dumps({"garmin": str(garmin_path), "xert": str(xert_path)})
            )
        self.assertEqual(overrides, {"garmin": garmin_path, "xert": xert_path})

    def test_rejects_unknown_or_missing_source_override(self):
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "unsupported"):
            parse_source_overrides_json('{"garmins":"day.json"}')
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "does not exist"):
            parse_source_overrides_json('{"garmin":"/tmp/no-such-training-source.json"}')


class WeatherCommandTests(unittest.TestCase):
    def test_available_windows_inherit_resolved_location_timezone(self):
        lisbon = ZoneInfo("Europe/Lisbon")
        windows = parse_availability_payload(
            {
                "windows": [
                    {
                        "start": "2026-07-28T07:00:00+01:00",
                        "end": "2026-07-28T10:00:00+01:00",
                        "note": "before breakfast",
                    }
                ]
            },
            expected_timezone=lisbon,
            argument_name="test availability",
        )

        self.assertEqual(
            windows[0]["start"].isoformat(),
            "2026-07-28T07:00:00+01:00",
        )
        self.assertEqual(
            windows[0]["end"].isoformat(),
            "2026-07-28T10:00:00+01:00",
        )
        self.assertEqual(windows[0]["time_zone"], "Europe/Lisbon")

    def test_availability_requires_explicit_offset_and_matching_timezone(self):
        lisbon = ZoneInfo("Europe/Lisbon")
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "explicit UTC offset",
        ):
            parse_availability_payload(
                {
                    "windows": [
                        {
                            "start": "2026-07-28T07:00:00",
                            "end": "2026-07-28T10:00:00+01:00",
                            "time_zone": "Europe/Lisbon",
                        }
                    ]
                },
                expected_timezone=lisbon,
                argument_name="test availability",
            )
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "when provided, must equal --local-timezone",
        ):
            parse_availability_payload(
                {
                    "windows": [
                        {
                            "start": "2026-07-28T07:00:00+01:00",
                            "end": "2026-07-28T10:00:00+01:00",
                            "time_zone": "Europe/Oslo",
                        }
                    ]
                },
                expected_timezone=lisbon,
                argument_name="test availability",
            )

    def test_future_recommendation_fetches_latest_real_garmin_day(self):
        now = datetime.fromisoformat("2026-07-27T12:38:00+02:00")

        self.assertEqual(
            garmin_source_day("2026-07-28", now=now),
            "2026-07-27",
        )
        self.assertEqual(
            garmin_source_day("2026-07-27", now=now),
            "2026-07-27",
        )


class PlanningContextTests(unittest.TestCase):
    def test_builder_validates_context_and_normalizes_none_remainder(self):
        context = build_planning_context(
            day="2026-08-08",
            local_timezone="Europe/Oslo",
            now="2026-08-08T09:00:00+02:00",
            planned_at="2026-08-08T09:30:00+02:00",
            availability_windows=[{
                "start": "2026-08-08T09:30:00+02:00",
                "end": "2026-08-08T21:00:00+02:00",
            }],
            cycling={"available_modalities": ["indoor_cycling"], "unavailable_reasons": {}},
            calendar={"remainder_disposition": "none"},
        )

        self.assertEqual(context["availability"]["windows"][0]["time_zone"], "Europe/Oslo")
        self.assertEqual(context["calendar"]["remainder_disposition"], "unscheduled")

    def test_split_preference_creates_two_explicit_windows(self):
        oslo = ZoneInfo("Europe/Oslo")
        windows = apply_split_preference_to_windows(
            [{
                "start": datetime(2026, 8, 8, 9, 30, tzinfo=oslo),
                "end": datetime(2026, 8, 8, 21, 0, tzinfo=oslo),
                "time_zone": "Europe/Oslo",
                "note": None,
            }],
            planned_at=datetime(2026, 8, 8, 9, 30, tzinfo=oslo),
            split_preference={
                "first_session_minutes": 180,
                "second_session_start": "2026-08-08T18:45:00+02:00",
            },
        )

        self.assertEqual(windows[0]["end"].isoformat(), "2026-08-08T12:30:00+02:00")
        self.assertEqual(windows[1]["start"].isoformat(), "2026-08-08T18:45:00+02:00")

    def test_accepts_calendar_assumptions_stops_and_remainder_disposition(self):
        context = parse_planning_context_json(
            json.dumps(
                {
                    "date": "2026-07-31",
                    "local_timezone": "Europe/Lisbon",
                    "now": "2026-07-31T12:50:00+01:00",
                    "planned_at": "2026-07-31T13:35:00+01:00",
                    "availability": {
                        "windows": [
                            {
                                "start": "2026-07-31T13:35:00+01:00",
                                "end": "2026-07-31T14:30:00+01:00",
                            }
                        ]
                    },
                    "cycling": {
                        "available_modalities": ["indoor_cycling_gym"],
                        "unavailable_reasons": {},
                    },
                    "calendar": {
                        "cleanup_buffer_minutes": 15,
                        "assumptions": ["Lunch moved and shortened to 30 min"],
                        "practical_stop": {
                            "subject": "Transport hotel-Faro (confirm time)",
                            "at": "2026-07-31T15:00:00+01:00",
                        },
                        "hard_stop": {
                            "subject": "Flight home",
                            "at": "2026-07-31T18:20:00+01:00",
                        },
                        "remainder_disposition": "dropped",
                    },
                }
            )
        )

        self.assertEqual(context["calendar"]["remainder_disposition"], "dropped")
        self.assertEqual(context["calendar"]["cleanup_buffer_minutes"], 15.0)
        resolved = calendar_context_with_slack(
            context["calendar"],
            planned_at=datetime.fromisoformat("2026-07-31T13:35:00+01:00"),
            available_windows=[
                {
                    "start": datetime.fromisoformat("2026-07-31T13:35:00+01:00"),
                    "end": datetime.fromisoformat("2026-07-31T14:30:00+01:00"),
                }
            ],
        )
        self.assertEqual(resolved["practical_stop_slack_minutes"], 15.0)
        self.assertEqual(resolved["hard_stop_slack_minutes"], 215.0)

    def test_accepts_no_available_cycling_modality(self):
        context = parse_planning_context_json(
            json.dumps(
                {
                    "date": "2026-07-31",
                    "local_timezone": "Europe/Lisbon",
                    "now": "2026-07-31T08:32:00+01:00",
                    "planned_at": "2026-07-31T10:15:00+01:00",
                    "availability": {
                        "windows": [
                            {
                                "start": "2026-07-31T10:15:00+01:00",
                                "end": "2026-07-31T13:45:00+01:00",
                                "time_zone": "Europe/Lisbon",
                            }
                        ]
                    },
                    "cycling": {
                        "available_modalities": [],
                        "unavailable_reasons": {
                            "indoor_cycling": "no_indoor_cycling_equipment",
                            "outdoor_cycling": "rental_bike_collected",
                        },
                    },
                }
            )
        )

        self.assertEqual(context["cycling"]["available_modalities"], [])
        self.assertEqual(
            context["availability"]["windows"][0]["start"],
            "2026-07-31T10:15:00+01:00",
        )

    def test_outdoor_cycling_requires_route_anchor(self):
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "requires route.start_anchor",
        ):
            parse_planning_context_json(
                json.dumps(
                    {
                        "date": "2026-07-31",
                        "local_timezone": "Europe/Lisbon",
                        "now": "2026-07-31T08:32:00+01:00",
                        "cycling": {
                            "available_modalities": ["outdoor_cycling"],
                            "unavailable_reasons": {},
                        },
                    }
                )
            )

    def test_accepts_indoor_cycling_gym_without_route_anchor(self):
        context = parse_planning_context_json(
            json.dumps(
                {
                    "date": "2026-07-31",
                    "local_timezone": "Europe/Oslo",
                    "now": "2026-07-31T12:00:00+02:00",
                    "cycling": {
                        "available_modalities": ["indoor_cycling_gym"],
                        "unavailable_reasons": {},
                    },
                }
            )
        )

        self.assertEqual(
            context["cycling"]["available_modalities"],
            ["indoor_cycling_gym"],
        )


class RecommendationSummaryTests(unittest.TestCase):
    def test_future_freshness_separates_current_sources_from_tomorrow_signals(self):
        freshness = compact_freshness_summary(
            {},
            garmin_recovery_readiness={},
            wellness={},
            target_date="2026-08-01",
            snapshot_time_local="2026-07-31T16:00:00+02:00",
        )

        self.assertEqual(
            freshness["guidance"],
            "current_sources_fresh_future_daily_signals_not_available_yet",
        )
        self.assertEqual(
            freshness["future_daily_signals_not_available_yet"],
            ["sleep", "overnight_hrv", "resting_hr", "body_battery_at_wake"],
        )
        summary = format_summary(
            {
                "primary_decision": {"action": "rest"},
                "decision_inputs": {"freshness_summary": freshness},
            }
        )
        self.assertIn("Future-day signals not available yet", summary)

    def test_plan_state_leads_progression_output(self):
        line = authoritative_progression_line(
            {
                "progression": {
                    "vt2": {
                        "anchor": "3 x 18 min @ 290 W",
                        "status": "consolidate_before_large_progression",
                    }
                }
            },
            {
                "vt2": {
                    "coach_summary": "repeat_or_bridge: VT2 2x18 min + 5 min @ 290W"
                }
            },
            "vt2",
        )

        self.assertTrue(
            line.startswith("PLAN STATE (authoritative): 3 x 18 min @ 290 W")
        )
        self.assertNotIn("historical_advisor=", line)
        self.assertNotIn("2x18", line)

    def test_historical_advisor_is_fallback_without_plan_step(self):
        line = authoritative_progression_line(
            {"progression": {}},
            {
                "vt2": {
                    "coach_summary": "repeat_or_bridge: VT2 2x18 min + 5 min @ 290W"
                }
            },
            "vt2",
        )

        self.assertIn("VT2 2x18 min + 5 min @ 290W", line)

    def test_split_guidance_uses_explicit_remainder_disposition(self):
        split = {
            "unscheduled_minutes": 167.3,
            "guidance": (
                "Calendar allocation: 13:35-14:30: 55 min VT1. "
                "The remaining 167 min VT1 is unscheduled; do not invent another session."
            ),
        }

        guidance = split_session_guidance(
            split,
            remainder_disposition="dropped",
        )

        self.assertIn("remainder is dropped today", guidance)
        self.assertNotIn("is unscheduled", guidance)

    def test_shows_calendar_assumptions_slack_and_remainder_disposition(self):
        summary = format_summary(
            {
                "primary_decision": {
                    "action": "train",
                    "executable_now": {"minutes": 55, "intensity": "vt1"},
                    "intensity_decision": {},
                    "unexecuted_remainder": {
                        "minutes": 167.3,
                        "disposition": "dropped",
                    },
                },
                "llm_context": {
                    "time_context": {
                        "calendar": {
                            "assumptions": ["Lunch moved and shortened to 30 min"],
                            "practical_stop": {
                                "subject": "Transport hotel-Faro (confirm time)",
                                "at": "2026-07-31T15:00:00+01:00",
                            },
                            "practical_stop_slack_minutes": 15,
                            "hard_stop": {
                                "subject": "Flight home",
                                "at": "2026-07-31T18:20:00+01:00",
                            },
                            "hard_stop_slack_minutes": 215,
                        }
                    }
                },
            }
        )

        self.assertIn("disposition=dropped", summary)
        self.assertIn("Calendar assumption: Lunch moved and shortened", summary)
        self.assertIn("Practical stop: Transport hotel-Faro", summary)
        self.assertIn("slack after cleanup=15 min", summary)
        self.assertIn("Hard stop: Flight home", summary)

    def test_distinguishes_stale_dynamic_from_usable_daily_signals(self):
        summary = format_summary(
            {
                "primary_decision": {"action": "rest"},
                "decision_inputs": {
                    "freshness_summary": {
                        "guidance": "dynamic_signals_stale_completed_daily_signals_usable",
                        "stale_dynamic_inputs": ["garmin_heart_rate_latest"],
                        "completed_daily_signals_usable": ["sleep", "overnight_hrv"],
                    }
                },
            }
        )

        self.assertIn("Stale dynamic inputs: garmin_heart_rate_latest", summary)
        self.assertIn("Completed daily signals still usable: sleep, overnight_hrv", summary)

    def test_shows_readiness_ceiling_and_workout_goal(self):
        summary = format_summary(
            {
                "date": "2026-07-24",
                "planned_at": "2026-07-24T09:30:00+02:00",
                "primary_decision": {
                    "action": "train",
                    "executable_now": {
                        "minutes": 45.0,
                        "intensity": "active_recovery",
                    },
                    "intensity_decision": {
                        "readiness_ceiling": "normal_vt1",
                        "requested_goal": "recovery",
                    },
                },
            }
        )

        self.assertIn("READINESS CEILING: normal_vt1", summary)
        self.assertIn("WORKOUT GOAL: recovery", summary)

    def test_do_now_shows_quality_plus_vt1_composition(self):
        target = {
            "target_minutes": 260.1,
            "target_load": 279.0,
            "dose_composition": {
                "selected_intensity": "vo2max",
                "quality_base": {
                    "duration_minutes": 53.0,
                    "counted_in_remaining_plan": True,
                    "includes": [
                        "warmup",
                        "work_intervals",
                        "recoveries",
                        "cooldown",
                    ],
                },
                "vt1_filler": {"duration_minutes": 207.1},
            },
        }
        decision = build_primary_decision(
            readiness_packet={
                "recommendation_inputs": {
                    "intervals_wellness_events": {},
                }
            },
            target_resolution=target,
            intensity_decision={
                "selected_domain": "vo2max",
                "readiness_ceiling": "high_intensity_ok",
                "requested_goal": "vo2max",
            },
        )

        summary = format_summary(
            {
                "primary_decision": decision,
                "llm_context": {"target_resolution": target},
            }
        )

        self.assertIn(
            "DO NOW: 53.0 min VO2MAX quality workout + 207.1 min VT1",
            summary,
        )
        self.assertEqual(
            decision["executable_now"]["segments"][0]["role"],
            "vo2max",
        )
        self.assertEqual(
            decision["executable_now"]["segments"][1],
            {
                "role": "vt1",
                "duration_minutes": 207.1,
                "includes_easy_start_and_finish": True,
            },
        )


    def test_plan_state_progression_overrides_historical_advisor_step(self):
        decision = select_intensity_domain(
            day="2026-08-01",
            readiness_ceiling="high_intensity_ok",
            intensity_goal="vo2max",
            progression_advice={
                "vo2max": {
                    "status": "repeat",
                    "next_step": {
                        "prescription": {"summary": "2 x 8 x 60/60 @ 380 W"}
                    },
                    "sessions_considered": [],
                }
            },
            plan_progression={
                "vo2max": {
                    "status": "sensor_calibration_1_of_3",
                    "next_step": "4 x 4 min @ 340 W",
                    "anchor": "sensor calibration",
                }
            },
        )

        self.assertEqual(
            decision["progression_status"], "sensor_calibration_1_of_3"
        )
        self.assertEqual(
            decision["progression_next_step"],
            {
                "summary": "4 x 4 min @ 340 W",
                "anchor": "sensor calibration",
                "source": "plan_state",
            },
        )

    def test_shows_persistent_plan_role_provenance(self):
        state = {
            "schema": "training-ai-plan-state-v2",
            "updated_at": "2026-07-28T20:00:00Z",
            "active_plan": {
                "id": "vt2-kapasitet-ut-2026",
                "path": "config/plans/2026-07-25-vt2-kapasitet-ut-2026.md",
            },
            "activity_cursor": {
                "activity_id": "i170000292",
                "started_at": "2026-07-28T07:13:25+01:00",
            },
            "next_role": "vo2max",
            "quality_queue": {
                "steps": [
                    {"id": "vt2_primary", "intensity_goal": "vt2"},
                    {"id": "vt2_secondary", "intensity_goal": "vt2"},
                    {"id": "vo2max", "intensity_goal": "vo2max"},
                ],
                "minimum_aerobic_days_after_quality": 1,
                "last_completed_quality": {
                    "activity_id": "i168713772",
                    "date": "2026-07-24",
                    "role": "vt2",
                },
                "next_quality_step": "vo2max",
                "aerobic_dates_since_quality": ["2026-07-25"],
                "aerobic_days_since_quality": 1,
            },
            "progression": {},
            "activity_events": [
                {
                    "activity_id": "i170000292",
                    "activity_name": "Algarve dag 4",
                    "started_at": "2026-07-28T07:13:25+01:00",
                    "planned_role": "easy_aerobic",
                    "completed_role": "long_aerobic",
                    "quality_completed": False,
                    "progression_effect": "none",
                    "reason": "Reviewed.",
                    "evidence": ["analysis.json"],
                }
            ],
        }
        plan_context = recommendation_plan_context(
            state,
            intensity_goal="vo2max",
        )
        summary = format_summary(
            {
                "date": "2026-07-29",
                "planned_at": "2026-07-29T07:00:00+01:00",
                "plan_context": plan_context,
                "primary_decision": {
                    "action": "train",
                    "executable_now": {"minutes": 60.0, "intensity": "vt1"},
                    "intensity_decision": {
                        "readiness_ceiling": "normal_vt1",
                        "requested_goal": "vo2max",
                    },
                },
            }
        )

        self.assertIn(
            "PLAN ROLE: vo2max; next quality=vo2max; goal matches state=True",
            summary,
        )
        self.assertIn("WORKOUT GOAL: vo2max", summary)


class QualityWorkoutDoseCompositionTests(unittest.TestCase):
    def test_parses_quality_workout_contract(self):
        workout = parse_quality_workout_json(
            '{"status":"planned","calculation":'
            '{"source":"xert_workout_calculate","duration_minutes":53,'
            '"xss":71.9,"low_xss":66.5,"high_xss":4.9,"peak_xss":0.5}}'
        )

        self.assertEqual(workout["status"], "planned")
        self.assertEqual(workout["calculation"]["duration_minutes"], 53)
        self.assertEqual(workout["calculation"]["xss"], 71.9)

    def test_rejects_invalid_quality_workout_contract(self):
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "must be valid JSON",
        ):
            parse_quality_workout_json('{"status":"planned"')
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "missing required"):
            parse_quality_workout_json('{"status":"planned"}')
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "planned or completed"):
            parse_quality_workout_json(
                '{"status":"done","calculation":{"xss":71.9}}'
            )

    def test_fills_remaining_target_with_vt1_at_sixty_xss_per_hour(self):
        target = {
            "source": "explicit_load_derived_minutes",
            "target_minutes": 188.2,
            "target_load": 160.0,
            "reason": "explicit target",
            "plan_trace": {
                "final_plan": {
                    "minutes": 188.2,
                    "load_xss": 160.0,
                }
            },
        }
        calculation = {
            "submit": "calculate",
            "saved": False,
            "result": {
                "stats": {
                    "duration": 2760,
                    "xss": 63.0,
                    "xlss": 58.6,
                    "xhss": 4.0,
                    "xpss": 0.4,
                }
            },
        }

        composition = apply_quality_workout_vt1_composition(
            target,
            quality_calculation=calculation,
            selected_intensity="vo2max",
        )

        self.assertEqual(composition["quality_base"]["duration_minutes"], 46.0)
        self.assertEqual(composition["quality_base"]["xss"], 63.0)
        self.assertEqual(composition["vt1_filler"]["xss"], 97.0)
        self.assertEqual(composition["vt1_filler"]["duration_minutes"], 97.0)
        self.assertEqual(
            composition["estimated_total"],
            {"duration_minutes": 143.0, "xss": 160.0},
        )
        self.assertEqual(target["target_minutes"], 143.0)
        self.assertEqual(target["plan_trace"]["final_plan"]["minutes"], 143.0)

    def test_calendar_fit_exposes_executable_dose_and_shortfall(self):
        oslo = ZoneInfo("Europe/Oslo")
        target = {
            "target_minutes": 188.2,
            "target_load": 160.0,
            "reason": "explicit target",
        }
        apply_quality_workout_vt1_composition(
            target,
            quality_calculation={
                "result": {
                    "stats": {
                        "duration": 2760,
                        "xss": 63.0,
                    }
                }
            },
            selected_intensity="vo2max",
        )

        annotate_dose_composition_window_fit(
            target,
            planned_at=datetime(2026, 8, 1, 9, 0, tzinfo=oslo),
            now=datetime(2026, 8, 1, 8, 0, tzinfo=oslo),
            available_windows=[
                {
                    "start": datetime(2026, 8, 1, 9, 0, tzinfo=oslo),
                    "end": datetime(2026, 8, 1, 11, 0, tzinfo=oslo),
                }
            ],
        )

        fit = target["dose_composition"]["calendar_fit"]
        self.assertEqual(fit["executable_minutes"], 120.0)
        self.assertEqual(fit["shortfall_minutes"], 23.0)
        self.assertEqual(fit["estimated_executable_xss"], 137.0)
        self.assertEqual(fit["estimated_shortfall_xss"], 23.0)
        self.assertFalse(fit["fits"])

    def test_full_calendar_fit_has_zero_xss_shortfall(self):
        oslo = ZoneInfo("Europe/Oslo")
        target = {
            "target_minutes": 279.0,
            "target_load": 279.0,
            "reason": "xert target",
        }
        apply_quality_workout_vt1_composition(
            target,
            quality_calculation={
                "source": "xert_workout_calculate",
                "duration_minutes": 53.0,
                "xss": 71.9,
                "low_xss": 66.5,
                "high_xss": 4.9,
                "peak_xss": 0.5,
            },
            selected_intensity="vo2max",
        )
        target["split"] = {
            "scheduled_minutes": 260.1,
            "allocations": [
                {"estimated_xss": 71.9},
                {"estimated_xss": 207.1},
            ],
        }

        annotate_dose_composition_window_fit(
            target,
            planned_at=datetime(2026, 8, 1, 11, 0, tzinfo=oslo),
            now=datetime(2026, 7, 31, 16, 0, tzinfo=oslo),
            available_windows=[
                {
                    "start": datetime(2026, 8, 1, 11, 0, tzinfo=oslo),
                    "end": datetime(2026, 8, 1, 16, 45, tzinfo=oslo),
                }
            ],
        )

        fit = target["dose_composition"]["calendar_fit"]
        self.assertEqual(fit["shortfall_minutes"], 0.0)
        self.assertEqual(fit["estimated_shortfall_xss"], 0.0)

    def test_zero_remainder_is_none_in_structure_and_summary(self):
        decision = build_primary_decision(
            readiness_packet={"recommendation_inputs": {"intervals_wellness_events": {}}},
            target_resolution={
                "target_minutes": 60.0,
                "target_load": 60.0,
                "split": {"unscheduled_minutes": 0.0},
            },
            intensity_decision={
                "selected_domain": "vt1",
                "readiness_ceiling": "normal_vt1",
                "requested_goal": "vt1",
            },
            remainder_disposition="dropped",
        )

        self.assertEqual(
            decision["unexecuted_remainder"]["disposition"],
            "none",
        )
        summary = format_summary({"primary_decision": decision})
        self.assertIn("REMAINDER: none", summary)
        self.assertNotIn("disposition=dropped", summary)

    def test_summary_shows_xert_target_composition_and_calendar_shortfall(self):
        target = {
            "target_load": 160.0,
            "xert_recommended_total_xss": 279.0,
            "xert_recommended_target_xss": {
                "low": 275.0,
                "high": 3.7,
                "peak": 0.3,
            },
            "dose_composition": {
                "daily_target_xss": 160.0,
                "quality_base": {
                    "duration_minutes": 46.0,
                    "xss": 63.0,
                    "low_xss": 58.6,
                    "high_xss": 4.0,
                    "peak_xss": 0.4,
                },
                "vt1_filler": {
                    "duration_minutes": 97.0,
                    "xss": 97.0,
                    "assumed_xss_per_hour": 60.0,
                },
                "estimated_total": {
                    "duration_minutes": 143.0,
                    "xss": 160.0,
                },
                "calendar_fit": {
                    "available": True,
                    "executable_minutes": 120.0,
                    "intended_minutes": 143.0,
                    "shortfall_minutes": 23.0,
                    "estimated_shortfall_xss": 23.0,
                },
            },
        }

        summary = format_summary(
            {
                "date": "2026-08-01",
                "planned_at": "2026-08-01T09:00:00+02:00",
                "llm_context": {"target_resolution": target},
                "primary_decision": {
                    "action": "train",
                    "executable_now": {
                        "minutes": 120.0,
                        "intensity": "vo2max",
                    },
                    "intensity_decision": {
                        "readiness_ceiling": "high_intensity_ok",
                        "requested_goal": "vo2max",
                    },
                },
            }
        )

        self.assertIn("XERT REMAINING DOSE: 279.0 XSS", summary)
        self.assertIn("CHOSEN DAILY TARGET: 160.0 XSS", summary)
        self.assertIn("QUALITY BASE: 46.0 min / 63.0 XSS", summary)
        self.assertIn("VT1 FILLER: 97.0 min / 97.0 XSS", summary)
        self.assertIn("EXPECTED TOTAL: 143.0 min / 160.0 XSS", summary)
        self.assertIn(
            "CALENDAR DOSE: executable 120.0/143.0 min; shortfall 23.0 min / 23.0 XSS",
            summary,
        )

    def test_does_not_add_vt1_when_quality_workout_exceeds_target(self):
        target = {
            "target_minutes": 45.0,
            "target_load": 50.0,
            "reason": "guardrailed target",
        }
        calculation = {
            "result": {
                "stats": {
                    "duration": "00:46:00",
                    "xss": 63.0,
                }
            }
        }

        composition = apply_quality_workout_vt1_composition(
            target,
            quality_calculation=calculation,
            selected_intensity="vo2max",
        )

        self.assertEqual(composition["vt1_filler"]["xss"], 0.0)
        self.assertEqual(composition["vt1_filler"]["duration_minutes"], 0.0)
        self.assertEqual(composition["estimated_total"]["xss"], 63.0)
        self.assertEqual(target["target_minutes"], 46.0)

    def test_rejects_quality_calculation_after_intensity_downgrade(self):
        with self.assertRaisesRegex(SystemExit, "selected intensity is easy_vt1"):
            apply_quality_workout_vt1_composition(
                {"target_load": 160.0},
                quality_calculation={"result": {"stats": {}}},
                selected_intensity="easy_vt1",
            )

    def test_completed_quality_is_not_subtracted_from_remaining_xss(self):
        target = {
            "target_minutes": 207.1,
            "target_load": 207.1,
            "reason": "Xert remaining_xss",
        }

        composition = apply_quality_workout_vt1_composition(
            target,
            quality_calculation={
                "source": "xert_workout_calculate",
                "duration_minutes": 53.0,
                "xss": 71.9,
                "low_xss": 66.5,
                "high_xss": 4.9,
                "peak_xss": 0.5,
            },
            selected_intensity="vt1",
            quality_workout_status="completed",
        )

        self.assertFalse(
            composition["quality_base"]["counted_in_remaining_plan"]
        )
        self.assertEqual(composition["vt1_filler"]["xss"], 207.1)
        self.assertEqual(composition["vt1_filler"]["duration_minutes"], 207.1)
        self.assertEqual(
            composition["estimated_total"],
            {"duration_minutes": 207.1, "xss": 207.1},
        )
        self.assertEqual(target["target_minutes"], 207.1)


class XertRemainingDoseTests(unittest.TestCase):
    def test_remaining_xss_takes_precedence_over_target_xss(self):
        target = resolve_training_targets(
            explicit_minutes=None,
            explicit_load=None,
            readiness_packet={
                "date": "2026-08-01",
                "recommendation_inputs": {
                    "xert_training_advice": {
                        "target_xss": {
                            "low": 275.0,
                            "high": 3.7,
                            "peak": 0.3,
                        },
                        "remaining_xss": {
                            "low": 120.0,
                            "high": 0.5,
                            "peak": 0.0,
                        },
                        "completed_xss": {
                            "low": 155.0,
                            "high": 3.2,
                            "peak": 0.3,
                        },
                        "original_target_xss": {
                            "low": 275.0,
                            "high": 3.7,
                            "peak": 0.3,
                        },
                        "xss_deficit": 507.2,
                        "xss_goal": 120.5,
                        "availability": 2,
                        "is_availability_restricted": True,
                        "targets_source": "XATA",
                        "improvement_rate": 3,
                        "phase": "Continuous",
                    }
                },
            },
            history_context={
                "rolling_7d": {},
                "typical_training_day_baseline": {
                    "median_minutes": 160.0,
                    "xss_per_min_from_available_xert_window": 1.0,
                    "xss_match_count": 6,
                },
            },
        )

        self.assertEqual(target["target_load"], 120.5)
        self.assertEqual(target["xert_dose_basis"], "remaining_xss")
        self.assertEqual(
            target["xert_recommended_target_xss"],
            {"low": 120.0, "high": 0.5, "peak": 0.0},
        )
        self.assertEqual(
            target["xert_completed_xss"],
            {"low": 155.0, "high": 3.2, "peak": 0.3},
        )
        self.assertEqual(target["xert_planning_context"]["xss_deficit"], 507.2)
        self.assertTrue(
            target["xert_planning_context"]["is_availability_restricted"]
        )
        self.assertEqual(target["target_load"], 120.5)
        self.assertIn("not added to today's dose", target["reason"])

    def test_xert_fetch_command_is_bound_to_planned_decision_time(self):
        command = xert_readiness_command(
            planned_at=datetime.fromisoformat("2026-08-08T10:30:00+02:00"),
            now=datetime.fromisoformat("2026-08-08T08:00:00+02:00"),
        )

        self.assertEqual(
            command[command.index("--advice-source") + 1],
            "recommended-training",
        )
        self.assertEqual(
            command[command.index("--advice-at") + 1],
            "2026-08-08T10:30:00+02:00",
        )
        self.assertEqual(
            command[command.index("--advice-now") + 1],
            "2026-08-08T08:00:00+02:00",
        )


class BodyBatteryPresentationTests(unittest.TestCase):
    def test_summary_exposes_wake_and_current_values(self):
        self.assertEqual(
            body_battery_summary_line(
                {
                    "body_battery_at_wake": 84,
                    "body_battery_most_recent": 72,
                }
            ),
            "at wake=84, now=72",
        )

    def test_presentation_contract_requires_both_values_when_present(self):
        requirement = presentation_requirements()["body_battery"]
        self.assertEqual(
            requirement["required_when_present"],
            ["body_battery_at_wake", "body_battery_most_recent"],
        )
        self.assertIn("holistic", requirement["meaning"])


class HrvDecisionTests(unittest.TestCase):
    def test_three_day_mean_is_primary_and_weekly_average_is_diagnostic_only(self):
        wellness = {
            "hrv_3day_mean": 67.333,
            "hrv_nights_used_3d": 3,
            "hrv_last_night_avg": 65,
            "hrv_weekly_avg": 63,
            "hrv_balanced_low": 67,
            "hrv_balanced_upper": 83,
        }

        self.assertEqual(hrv_readiness_risk(wellness), 0.0)

    def test_last_night_is_fallback_when_three_nights_are_unavailable(self):
        wellness = {
            "hrv_3day_mean": 67.333,
            "hrv_nights_used_3d": 2,
            "hrv_last_night_avg": 65,
            "hrv_balanced_low": 67,
            "hrv_balanced_upper": 83,
        }

        self.assertAlmostEqual(hrv_readiness_risk(wellness), 2 / 8.04)

    def test_one_moderate_hrv_signal_does_not_block_hard_intensity(self):
        agreement = intensity_signal_agreement(
            wellness={
                "hrv_3day_mean": 64,
                "hrv_nights_used_3d": 3,
                "hrv_last_night_avg": 65,
                "hrv_balanced_low": 67,
                "hrv_balanced_upper": 83,
                "sleep_time_seconds": 27000,
                "sleep_score": 85,
                "resting_hr": 45,
                "resting_hr_7day": 45,
                "body_battery_at_wake": 85,
            },
            xert={
                "projected_recovery_hours_at_planned_time": {
                    "low": -5,
                    "high": -10,
                    "peak": -8,
                }
            },
            intervals_events={},
        )

        self.assertTrue(agreement["vt2_allowed"])
        self.assertTrue(agreement["high_intensity_allowed"])
        self.assertEqual(agreement["moderate_signals"], ["hrv_3day"])

    def test_sleep_score_replaces_sleep_duration_for_intensity_decisions(self):
        agreement = intensity_signal_agreement(
            wellness={
                "hrv_3day_mean": 76.667,
                "hrv_nights_used_3d": 3,
                "hrv_last_night_avg": 74,
                "hrv_balanced_low": 65,
                "hrv_balanced_upper": 82,
                "sleep_time_seconds": 20640,
                "sleep_score": 73,
                "resting_hr": 42,
                "resting_hr_7day": 42,
                "body_battery_at_wake": 88,
            },
            xert={
                "projected_recovery_hours_at_planned_time": {
                    "low": -40.7,
                    "high": -244.0,
                    "peak": -163.9,
                }
            },
            intervals_events={},
        )

        self.assertTrue(agreement["vt2_allowed"])
        self.assertTrue(agreement["high_intensity_allowed"])
        self.assertEqual(agreement["moderate_signals"], [])
        self.assertAlmostEqual(agreement["risks"]["sleep"], 0.233, places=3)

    def test_two_related_moderate_signals_do_not_count_as_independent_blockers(self):
        agreement = intensity_signal_agreement(
            wellness={
                "hrv_3day_mean": 64,
                "hrv_nights_used_3d": 3,
                "hrv_last_night_avg": 65,
                "hrv_balanced_low": 67,
                "hrv_balanced_upper": 83,
                "sleep_time_seconds": 23400,
                "sleep_score": 65,
                "resting_hr": 45,
                "resting_hr_7day": 45,
                "body_battery_at_wake": 85,
            },
            xert={
                "projected_recovery_hours_at_planned_time": {
                    "low": -5,
                    "high": -10,
                    "peak": -8,
                }
            },
            intervals_events={},
        )

        self.assertTrue(agreement["vt2_allowed"])
        self.assertTrue(agreement["high_intensity_allowed"])
        self.assertNotIn("multiple_moderate_direct_signals", agreement["blockers"])
        self.assertEqual(
            agreement["grouped_families"]["autonomic_recovery"],
            agreement["risks"]["sleep"],
        )

    def test_body_battery_is_support_not_an_independent_intensity_blocker(self):
        agreement = intensity_signal_agreement(
            wellness={
                "hrv_3day_mean": 70,
                "hrv_nights_used_3d": 3,
                "hrv_last_night_avg": 70,
                "hrv_balanced_low": 67,
                "hrv_balanced_upper": 83,
                "sleep_score": 85,
                "resting_hr": 45,
                "resting_hr_7day": 45,
                "body_battery_at_wake": 20,
            },
            xert={
                "projected_recovery_hours_at_planned_time": {
                    "low": -5,
                    "high": -10,
                    "peak": -8,
                }
            },
            intervals_events={},
        )

        self.assertTrue(agreement["vt2_allowed"])
        self.assertTrue(agreement["high_intensity_allowed"])
        self.assertEqual(agreement["grouped_families"]["body_resources_support"], 1.0)
        self.assertFalse(agreement["body_resources_used_as_independent_signal"])

    def test_low_system_recovery_allows_vt2_but_not_high_intensity(self):
        agreement = intensity_signal_agreement(
            wellness={
                "hrv_3day_mean": 70,
                "hrv_nights_used_3d": 3,
                "hrv_last_night_avg": 70,
                "hrv_balanced_low": 67,
                "hrv_balanced_upper": 83,
                "sleep_time_seconds": 27000,
                "sleep_score": 85,
                "resting_hr": 45,
                "resting_hr_7day": 45,
                "body_battery_at_wake": 85,
            },
            xert={
                "projected_recovery_hours_at_planned_time": {
                    "low": -5,
                    "high": 2,
                    "peak": -8,
                }
            },
            intervals_events={},
        )

        self.assertTrue(agreement["vt2_allowed"])
        self.assertFalse(agreement["high_intensity_allowed"])
        self.assertIn(
            "xert_high_or_peak_system_recovery",
            agreement["high_intensity_blockers"],
        )

    def test_severe_last_night_drop_can_block_alone(self):
        agreement = intensity_signal_agreement(
            wellness={
                "hrv_3day_mean": 67,
                "hrv_nights_used_3d": 3,
                "hrv_last_night_avg": 55,
                "hrv_balanced_low": 67,
                "hrv_balanced_upper": 83,
                "sleep_time_seconds": 27000,
                "sleep_score": 85,
                "resting_hr": 45,
                "resting_hr_7day": 45,
                "body_battery_at_wake": 85,
            },
            xert={
                "projected_recovery_hours_at_planned_time": {
                    "low": -5,
                    "high": -10,
                    "peak": -8,
                }
            },
            intervals_events={},
        )

        self.assertFalse(agreement["vt2_allowed"])
        self.assertFalse(agreement["high_intensity_allowed"])
        self.assertIn("severe_direct_signal", agreement["blockers"])


class AcuteReadinessGuardrailTests(unittest.TestCase):
    def test_low_body_battery_alone_does_not_cap_model_dose(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 120.0,
            "target_load": 90.0,
        }
        apply_acute_readiness_target_guardrail(
            target,
            {
                "recommendation_inputs": {
                    "wellness": {
                        "sleep_score": 85,
                        "hrv_last_night_avg": 70,
                        "hrv_balanced_low": 67,
                        "hrv_balanced_upper": 83,
                        "resting_hr": 45,
                        "resting_hr_7day": 45,
                        "body_battery_at_wake": 20,
                    },
                    "xert_recovery": {
                        "recovery_load": {"low": 100.0},
                        "training_load": {"low": 120.0},
                        "recovery_hours": {"low": 12.0},
                    },
                }
            },
        )

        self.assertEqual(target["target_minutes"], 120.0)
        self.assertNotIn("acute_readiness_guardrail", target)

    def test_caps_xert_dose_for_poor_direct_inputs_and_high_cumulative_load(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 221.3,
            "target_load": 221.3,
            "caution_score": 2.55,
        }
        initialize_plan_trace(target)
        packet = {
            "date": "2026-07-20",
            "recommendation_inputs": {
                "garmin_recovery_readiness": {
                    "training_readiness_score": 1,
                },
                "garmin_load_focus": {"acute_load": 400, "acwr": 1.3},
                "xert_recovery": {
                    "recovery_load": {"low": 100.0},
                    "training_load": {"low": 120.0},
                    "recovery_hours": {"low": 12.0},
                },
                "wellness": {
                    "sleep_time_seconds": 21720,
                    "sleep_score": 45,
                    "hrv_last_night_avg": 54,
                    "hrv_balanced_low": 67,
                    "hrv_balanced_upper": 84,
                    "resting_hr": 50,
                    "resting_hr_7day": 45,
                    "body_battery_at_wake": 45,
                },
                "latest_activity_load": {
                    "start_local": "2026-07-19T15:45:29",
                    "xert_xss": 192.1,
                },
            },
        }

        apply_acute_readiness_target_guardrail(target, packet)
        finalize_plan_trace(target)

        self.assertEqual(target["target_minutes"], 45.0)
        self.assertEqual(target["target_load"], 30.0)
        self.assertEqual(target["acute_readiness_guardrail"]["level"], "recovery_day")
        self.assertEqual(
            target["dose_position_vs_typical"]["label"], "acute_readiness_capped"
        )
        self.assertFalse(
            target["acute_readiness_guardrail"]["training_readiness_used_for_dose"]
        )
        self.assertEqual(
            set(target["acute_readiness_guardrail"]["direct_domains"]),
            {"autonomic_recovery"},
        )
        self.assertFalse(
            target["acute_readiness_guardrail"][
                "body_resources_used_as_independent_domain"
            ]
        )
        self.assertEqual(target["plan_trace"]["base_plan"]["load_xss"], 221.3)
        self.assertEqual(target["plan_trace"]["adjustment"]["status"], "reduced")
        self.assertEqual(
            target["plan_trace"]["final_plan"]["relationship_to_base"],
            "reduced_by_guardrail",
        )

    def test_trace_says_xert_plan_is_unchanged_without_guardrail(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 140.2,
            "target_load": 140.2,
            "reason": "target load from Xert's recommended XSS",
        }

        initialize_plan_trace(target)
        apply_acute_readiness_target_guardrail(
            target,
            {
                "recommendation_inputs": {
                    "garmin_recovery_readiness": {"training_readiness_score": 3},
                    "garmin_load_focus": {"acwr": 0.9},
                    "wellness": {
                        "sleep_time_seconds": 27000,
                        "sleep_score": 85,
                        "hrv_last_night_avg": 68,
                        "hrv_balanced_low": 67,
                        "hrv_balanced_upper": 83,
                        "body_battery_at_wake": 84,
                    },
                }
            },
        )
        finalize_plan_trace(target)

        self.assertEqual(
            target["plan_trace"]["base_plan"]["label"],
            "xert_recommended_remaining_dose",
        )
        self.assertEqual(target["plan_trace"]["adjustment"]["status"], "unchanged")
        self.assertEqual(
            target["plan_trace"]["final_plan"]["relationship_to_base"],
            "same_as_base",
        )
        self.assertIn("xert_recovery_training_diagnostic", target)

    def test_low_cumulative_load_uses_easy_endurance_cap_independent_of_yesterday(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 221.3,
            "target_load": 221.3,
        }
        inputs = {
            "garmin_recovery_readiness": {"training_readiness_score": 1},
            "garmin_load_focus": {"acute_load": 665, "acwr": 0.7},
            "xert_recovery": {
                "recovery_load": {"low": 122.2},
                "training_load": {"low": 117.8},
                "recovery_hours": {"low": -5.2},
            },
            "wellness": {
                "sleep_time_seconds": 21720,
                "sleep_score": 45,
                "hrv_weekly_avg": 61,
                "hrv_balanced_low": 67,
                "hrv_balanced_upper": 84,
                "resting_hr": 49,
                "resting_hr_7day": 45,
                "body_battery_at_wake": 60,
            },
            "latest_activity_load": {
                "start_local": "2026-07-19T15:45:29",
                "xert_xss": 192.1,
            },
        }

        apply_acute_readiness_target_guardrail(
            target, {"date": "2026-07-20", "recommendation_inputs": inputs}
        )

        self.assertEqual(target["target_minutes"], 60.0)
        self.assertEqual(target["target_load"], 45.0)
        self.assertEqual(
            target["acute_readiness_guardrail"]["level"], "easy_endurance_only"
        )
        self.assertEqual(target["acute_readiness_guardrail"]["cumulative_load_risk"], 0.0)
        self.assertEqual(
            target["acute_readiness_guardrail"]["cumulative_load_source"],
            "xert_recovery_vs_training",
        )

        target_with_high_garmin_score = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 221.3,
            "target_load": 221.3,
        }
        inputs["garmin_recovery_readiness"]["training_readiness_score"] = 99
        inputs["latest_activity_load"]["xert_xss"] = 500.0
        apply_acute_readiness_target_guardrail(
            target_with_high_garmin_score,
            {"date": "2026-07-20", "recommendation_inputs": inputs},
        )
        self.assertEqual(target_with_high_garmin_score["target_minutes"], 60.0)
        self.assertFalse(
            target_with_high_garmin_score["training_readiness_diagnostic"]["used_for_dose"]
        )

    def test_does_not_override_explicit_dose(self):
        target = {
            "source": "explicit_cli",
            "target_minutes": 90.0,
            "target_load": 80.0,
            "caution_score": 3.0,
        }
        apply_acute_readiness_target_guardrail(target, {"recommendation_inputs": {}})
        self.assertEqual(target["target_minutes"], 90.0)
        self.assertNotIn("acute_readiness_guardrail", target)


class PrimaryDecisionContractTests(unittest.TestCase):
    def test_active_recovery_caps_xert_model_dose_before_primary_decision(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 264.1,
            "target_load": 264.1,
        }
        intensity = {
            "selected_domain": "active_recovery",
            "readiness_ceiling": "active_recovery_only",
            "requested_goal": "vt1",
        }

        initialize_plan_trace(target)
        apply_readiness_domain_target_cap(target, intensity_decision=intensity)
        finalize_plan_trace(target)
        target["split"] = {
            "available": True,
            "first_session_minutes": target["target_minutes"],
            "unscheduled_minutes": 0.0,
        }
        decision = build_primary_decision(
            readiness_packet={
                "recommendation_inputs": {"intervals_wellness_events": {}}
            },
            target_resolution=target,
            intensity_decision=intensity,
        )

        self.assertEqual(decision["selected_intensity"], "active_recovery")
        self.assertEqual(decision["executable_now"]["minutes"], 45.0)
        self.assertEqual(
            decision["executable_now"]["segments"],
            [{"role": "active_recovery", "duration_minutes": 45.0}],
        )
        self.assertEqual(target["pre_readiness_domain_cap_target_minutes"], 264.1)
        self.assertEqual(
            target["readiness_domain_cap"]["remainder_disposition"],
            "dropped_not_rescheduled",
        )
        self.assertIn("readiness_domain_cap", target["plan_trace"]["adjustment"]["types"])
        summary = format_summary({"primary_decision": decision})
        self.assertIn("DO NOW: 45.0 min ACTIVE_RECOVERY", summary)
        self.assertNotIn("264.1 min ACTIVE_RECOVERY", summary)

    def test_active_recovery_primary_decision_rejects_uncapped_long_dose(self):
        with self.assertRaisesRegex(SystemExit, "cannot exceed 60 minutes"):
            build_primary_decision(
                readiness_packet={
                    "recommendation_inputs": {"intervals_wellness_events": {}}
                },
                target_resolution={"target_minutes": 264.1, "target_load": 264.1},
                intensity_decision={
                    "selected_domain": "active_recovery",
                    "readiness_ceiling": "active_recovery_only",
                    "requested_goal": "vt1",
                },
            )

    def test_xert_remaining_dose_yields_train_and_does_not_double_subtract(self):
        target = {
            "source": "xert_training_advice_target_xss",
            "target_minutes": 140.2,
            "target_load": 140.2,
            "split": {
                "available": True,
                "first_session_minutes": 60.0,
                "unscheduled_minutes": 80.2,
            },
        }
        packet = {
            "recommendation_inputs": {
                "intervals_wellness_events": {},
                "latest_activity_load": {"xert_xss": 82.5},
            }
        }

        decision = build_primary_decision(
            readiness_packet=packet,
            target_resolution=target,
            intensity_decision={
                "selected_domain": "easy_vt1",
                "readiness_ceiling": "easy_vt1",
                "requested_goal": "vt1",
            },
        )

        self.assertEqual(decision["action"], "train")
        self.assertEqual(decision["selected_intensity"], "easy_vt1")
        self.assertEqual(decision["executable_now"]["minutes"], 60.0)
        self.assertEqual(decision["unexecuted_remainder"]["minutes"], 80.2)
        self.assertEqual(
            decision["dose_semantics"], "remaining_after_completed_activities"
        )
        self.assertTrue(decision["completed_activities_already_accounted_for"])

    def test_quality_domain_without_workout_is_rejected(self):
        with self.assertRaisesRegex(
            SystemExit,
            "requires --quality-workout-json",
        ):
            build_primary_decision(
                readiness_packet={
                    "recommendation_inputs": {"intervals_wellness_events": {}}
                },
                target_resolution={
                    "source": "xert_training_advice_target_xss",
                    "target_minutes": 222.3,
                    "target_load": 222.3,
                    "split": {
                        "available": True,
                        "first_session_minutes": 210.0,
                        "unscheduled_minutes": 12.3,
                        "sessions": [
                            {
                                "segments": [
                                    {
                                        "role": "vt1",
                                        "duration_minutes": 210.0,
                                        "complete_workout_required": False,
                                    }
                                ]
                            }
                        ],
                    },
                },
                intensity_decision={
                    "selected_domain": "vo2max",
                    "readiness_ceiling": "high_intensity_ok",
                    "requested_goal": "vo2max",
                },
            )

    def test_quality_domain_accepts_calculated_quality_composition(self):
        require_quality_workout_for_selected_domain(
            intensity_decision={"selected_domain": "vo2max"},
            dose_composition={"quality_base": {"duration_minutes": 53.0}},
        )

    def test_no_cycling_modality_leaves_full_dose_unscheduled(self):
        decision = build_primary_decision(
            readiness_packet={
                "recommendation_inputs": {"intervals_wellness_events": {}}
            },
            target_resolution={
                "source": "xert_training_advice_target_xss",
                "target_minutes": 90.0,
                "target_load": 80.0,
                "split": {
                    "available": True,
                    "first_session_minutes": 90.0,
                    "unscheduled_minutes": 0.0,
                },
            },
            intensity_decision={
                "selected_domain": "vo2max",
                "readiness_ceiling": "high_intensity_ok",
                "requested_goal": "vo2max",
            },
            cycling_available=False,
        )

        self.assertEqual(decision["action"], "unavailable")
        self.assertEqual(decision["selected_intensity"], "none_available")
        self.assertEqual(decision["executable_now"]["minutes"], 0.0)
        self.assertEqual(decision["executable_now"]["segments"], [])
        self.assertEqual(decision["unexecuted_remainder"]["minutes"], 90.0)
        self.assertEqual(
            decision["intensity_decision"]["selected_domain"],
            "vo2max",
        )

    def test_unresolved_sickness_yields_form_check(self):
        decision = build_primary_decision(
            readiness_packet={
                "recommendation_inputs": {
                    "intervals_wellness_events": {"illness_followup_needed": True}
                }
            },
            target_resolution={"target_minutes": 45, "target_load": 30},
            intensity_decision={
                "selected_domain": "easy_vt1",
                "readiness_ceiling": "easy_vt1",
                "requested_goal": "vt1",
            },
        )

        self.assertEqual(decision["action"], "form_check")
        self.assertEqual(decision["executable_now"]["minutes"], 0.0)

    def test_missing_later_window_leaves_remainder_unscheduled(self):
        planned = datetime.fromisoformat("2026-07-22T19:30:00+02:00")
        split = split_session_info(
            {"target_minutes": 140.2},
            planned_at=planned,
            now=planned,
            available_windows=[
                {
                    "start": planned,
                    "end": datetime.fromisoformat("2026-07-22T20:30:00+02:00"),
                    "note": "after dinner",
                }
            ],
        )

        self.assertEqual(split["first_session_minutes"], 60.0)
        self.assertEqual(split["unscheduled_minutes"], 80.2)
        self.assertIsNone(split["next_window"])
        self.assertIn("do not invent", split["guidance"])

    def test_composed_split_names_quality_first_and_vt1_second(self):
        planned = datetime.fromisoformat("2026-08-01T09:00:00+02:00")
        split = split_session_info(
            {
                "target_minutes": 141.0,
                "dose_composition": {
                    "selected_intensity": "vo2max",
                    "quality_base": {
                        "duration_minutes": 53.0,
                        "counted_in_remaining_plan": True,
                    },
                    "vt1_filler": {"duration_minutes": 88.0},
                },
            },
            planned_at=planned,
            now=planned,
            available_windows=[
                {
                    "start": planned,
                    "end": datetime.fromisoformat("2026-08-01T09:53:00+02:00"),
                    "note": "morning",
                },
                {
                    "start": datetime.fromisoformat("2026-08-01T19:00:00+02:00"),
                    "end": datetime.fromisoformat("2026-08-01T20:30:00+02:00"),
                    "note": "evening",
                },
            ],
        )

        self.assertIn("53 min VO2MAX quality workout", split["guidance"])
        self.assertIn(
            "built-in warm-up, recoveries, and cool-down",
            split["guidance"],
        )
        self.assertIn("remaining 88 min VT1", split["guidance"])
        self.assertNotIn("both parts easy VT1", split["guidance"])

    def test_moves_complete_quality_workout_to_first_window_where_it_fits(self):
        planned = datetime.fromisoformat("2026-08-01T09:00:00+02:00")
        split = split_session_info(
            {
                "target_minutes": 141.0,
                "dose_composition": {
                    "selected_intensity": "vo2max",
                    "quality_base": {
                        "duration_minutes": 53.0,
                        "counted_in_remaining_plan": True,
                    },
                },
            },
            planned_at=planned,
            now=planned,
            available_windows=[
                {
                    "start": planned,
                    "end": datetime.fromisoformat("2026-08-01T09:30:00+02:00"),
                    "note": "short window",
                },
                {
                    "start": datetime.fromisoformat("2026-08-01T19:00:00+02:00"),
                    "end": datetime.fromisoformat("2026-08-01T20:30:00+02:00"),
                    "note": "evening",
                },
            ],
        )

        self.assertEqual(split["sessions"][0]["start"], "2026-08-01T19:00+02:00")
        self.assertEqual(
            split["sessions"][0]["segments"][0]["duration_minutes"],
            53.0,
        )
        self.assertIn("complete 53 min VO2MAX", split["guidance"])
        self.assertNotIn("09:00-09:30", split["guidance"])

    def test_allocates_vt1_across_all_windows_and_reports_true_shortfall(self):
        planned = datetime.fromisoformat("2026-08-01T09:00:00+02:00")
        split = split_session_info(
            {
                "target_minutes": 260.0,
                "dose_composition": {
                    "selected_intensity": "vo2max",
                    "quality_base": {
                        "duration_minutes": 53.0,
                        "xss": 71.9,
                        "counted_in_remaining_plan": True,
                    },
                    "vt1_filler": {
                        "duration_minutes": 207.0,
                        "assumed_xss_per_hour": 60.0,
                    },
                },
            },
            planned_at=planned,
            now=planned,
            available_windows=[
                {
                    "start": planned,
                    "end": datetime.fromisoformat("2026-08-01T09:53:00+02:00"),
                    "note": "quality",
                },
                {
                    "start": datetime.fromisoformat("2026-08-01T13:00:00+02:00"),
                    "end": datetime.fromisoformat("2026-08-01T14:00:00+02:00"),
                    "note": "midday",
                },
                {
                    "start": datetime.fromisoformat("2026-08-01T19:00:00+02:00"),
                    "end": datetime.fromisoformat("2026-08-01T20:30:00+02:00"),
                    "note": "evening",
                },
            ],
        )

        self.assertEqual(
            [session["duration_minutes"] for session in split["sessions"]],
            [53.0, 60.0, 90.0],
        )
        self.assertEqual(
            [allocation["role"] for allocation in split["allocations"]],
            ["vo2max", "vt1", "vt1"],
        )
        self.assertEqual(split["scheduled_minutes"], 203.0)
        self.assertEqual(split["unscheduled_minutes"], 57.0)
        self.assertIn("13:00-14:00", split["guidance"])
        self.assertIn("19:00-20:30", split["guidance"])
        self.assertIn("remaining 57 min VT1 is unscheduled", split["guidance"])

    def test_expired_window_has_no_executable_minutes(self):
        planned = datetime.fromisoformat("2026-07-24T09:30:00+02:00")
        split = split_session_info(
            {"target_minutes": 137.6},
            planned_at=planned,
            now=datetime.fromisoformat("2026-07-24T13:12:00+02:00"),
            available_windows=[
                {
                    "start": planned,
                    "end": datetime.fromisoformat("2026-07-24T12:00:00+02:00"),
                    "note": "before travel",
                }
            ],
        )

        self.assertEqual(split["available_minutes_from_planned"], 0.0)
        self.assertEqual(split["first_session_minutes"], 0.0)
        self.assertEqual(split["unscheduled_minutes"], 137.6)
        self.assertIn("from 13:12", split["guidance"])

    def test_readiness_caps_requested_hard_intensity(self):
        decision = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="easy_vt1",
            intensity_goal="vo2max",
            progression_advice={},
        )

        self.assertEqual(decision["selected_domain"], "easy_vt1")
        self.assertEqual(
            decision["selection_reason"], "goal_reduced_to_readiness_ceiling"
        )

    def test_normal_vt1_ceiling_does_not_raise_recovery_goal(self):
        decision = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="normal_vt1",
            intensity_goal="recovery",
            progression_advice={},
        )

        self.assertEqual(decision["selected_domain"], "active_recovery")
        self.assertEqual(decision["selection_reason"], "goal_within_readiness_ceiling")

    def test_easy_vt1_ceiling_does_not_raise_recovery_goal(self):
        decision = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="easy_vt1",
            intensity_goal="recovery",
            progression_advice={},
        )

        self.assertEqual(decision["selected_domain"], "active_recovery")
        self.assertEqual(decision["selection_reason"], "goal_within_readiness_ceiling")

    def test_recent_same_family_stimulus_reduces_hard_goal_to_vt1(self):
        decision = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="high_intensity_ok",
            intensity_goal="vt2",
            progression_advice={
                "vt2": {
                    "status": "progress",
                    "sessions_considered": [{"date": "2026-07-22"}],
                }
            },
        )

        self.assertEqual(decision["selected_domain"], "vt1")
        self.assertEqual(decision["selection_reason"], "recent_same_family_stimulus")

    def test_progression_goal_is_selected_inside_intensity_ready_ceiling(self):
        decision = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="high_intensity_ok",
            intensity_goal="vt2",
            progression_advice={
                "vt2": {
                    "status": "small_bridge_progression",
                    "sessions_considered": [{"date": "2026-07-01"}],
                    "next_step": {
                        "prescription": {
                            "type": "vt2",
                            "summary": "VT2 2x18 min + 10 min",
                        }
                    },
                }
            },
        )

        self.assertEqual(decision["selected_domain"], "vt2")
        self.assertEqual(decision["selection_reason"], "goal_within_readiness_ceiling")
        self.assertEqual(decision["progression_status"], "small_bridge_progression")

    def test_vt2_ceiling_caps_vo2max_but_allows_vt2_and_vt1(self):
        vt1 = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="vt2_ok",
            intensity_goal="vt1",
            progression_advice={},
        )
        vt2 = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="vt2_ok",
            intensity_goal="vt2",
            progression_advice={},
        )
        vo2max = select_intensity_domain(
            day="2026-07-23",
            readiness_ceiling="vt2_ok",
            intensity_goal="vo2max",
            progression_advice={},
        )

        self.assertEqual(vt1["selected_domain"], "vt1")
        self.assertEqual(vt2["selected_domain"], "vt2")
        self.assertEqual(vo2max["selected_domain"], "vt2")

    def test_high_intensity_ceiling_also_allows_vt1_and_vt2(self):
        for goal in ("vt1", "vt2", "vo2max", "sprint", "mixed"):
            with self.subTest(goal=goal):
                decision = select_intensity_domain(
                    day="2026-07-23",
                    readiness_ceiling="high_intensity_ok",
                    intensity_goal=goal,
                    progression_advice={},
                )
                self.assertEqual(decision["selected_domain"], goal)


class ExecutionModalityConstraintTests(unittest.TestCase):
    def test_gym_bike_caps_hard_execution_at_vt1_and_keeps_quality_queued(self):
        decision = {
            "requested_goal": "vo2max",
            "selected_domain": "vo2max",
            "selection_reason": "goal_within_readiness_ceiling",
        }

        apply_execution_modality_constraint(decision, indoor_gym_only=True)

        self.assertEqual(decision["selected_domain"], "vt1")
        self.assertEqual(decision["pre_modality_selected_domain"], "vo2max")
        self.assertEqual(
            decision["selection_reason"],
            "gym_bike_continuous_aerobic_only",
        )
        self.assertTrue(decision["quality_role_remains_queued"])
        self.assertEqual(decision["execution_control"], "heart_rate_breathing_rpe")

    def test_gym_bike_does_not_change_vt1_goal(self):
        decision = {
            "requested_goal": "vt1",
            "selected_domain": "vt1",
            "selection_reason": "goal_within_readiness_ceiling",
        }

        apply_execution_modality_constraint(decision, indoor_gym_only=True)

        self.assertEqual(decision["selected_domain"], "vt1")
        self.assertNotIn("pre_modality_selected_domain", decision)

    def test_gym_bike_summary_does_not_claim_erg_or_watt_targets(self):
        summary = format_summary(
            {
                "primary_decision": {
                    "action": "train",
                    "executable_now": {"minutes": 60, "intensity": "vt1"},
                    "intensity_decision": {
                        "readiness_ceiling": "high_intensity_ok",
                        "requested_goal": "vo2max",
                    },
                },
                "decision_inputs": {
                    "indoor_workouts": {
                        "source": "indoor_cycling_gym",
                        "available": True,
                        "recommended": {
                            "name": "Continuous aerobic gym-bike ride",
                            "duration_minutes": 60,
                        },
                    }
                },
            }
        )

        self.assertIn("watts and ERG instructions do not apply", summary)
        self.assertIn("not applicable for indoor_cycling_gym", summary)


class SourceRefreshPolicyTests(unittest.TestCase):
    def test_stale_xert_mcp_sources_are_requested_as_overrides(self):
        refresh = {
            "xert_activity_loads": {"refresh": True},
            "xert_recommended_training": {"refresh": True},
            "xert": {"refresh": True},
        }

        self.assertEqual(
            mcp_sources_requiring_refresh(refresh, indoor_available=True),
            {"xert_activity_loads", "xert_recommended_training"},
        )

    def test_garmin_refresh_is_mcp_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "garmin.json"
            plan = build_source_refresh_plan(
                {"garmin": source},
                required={"garmin"},
                refresh_spec=parse_refresh_json('{"mode":"selected","sources":["garmin"]}'),
                checked_at=datetime.now(timezone.utc),
            )

        self.assertTrue(plan["garmin"]["refresh"])
        self.assertEqual(plan["garmin"]["status"], "forced")

    def test_auto_reuses_fresh_source_and_fetches_missing_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            garmin = root / "garmin.json"
            garmin.write_text("{}", encoding="utf-8")
            plan = build_source_refresh_plan(
                {"garmin": garmin, "xert": root / "xert.json"},
                required={"garmin", "xert"},
                refresh_spec=parse_refresh_json('{"mode":"auto"}'),
                checked_at=datetime.now(timezone.utc),
            )

        self.assertEqual(plan["garmin"]["status"], "reused")
        self.assertFalse(plan["garmin"]["refresh"])
        self.assertEqual(plan["xert"]["reason"], "missing")
        self.assertTrue(plan["xert"]["refresh"])

    def test_selected_source_forces_only_that_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {"garmin": root / "garmin.json", "xert": root / "xert.json"}
            for path in paths.values():
                path.write_text("{}", encoding="utf-8")
            plan = build_source_refresh_plan(
                paths,
                required=set(paths),
                refresh_spec=parse_refresh_json('{"mode":"selected","sources":["garmin"]}'),
                checked_at=datetime.now(timezone.utc),
            )

        self.assertEqual(plan["garmin"]["status"], "forced")
        self.assertTrue(plan["garmin"]["refresh"])
        self.assertEqual(plan["xert"]["status"], "reused")

    def test_none_marks_old_or_missing_source_stale_offline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = build_source_refresh_plan(
                {"weather_home": root / "weather.json"},
                required={"weather_home"},
                refresh_spec=parse_refresh_json('{"mode":"none"}'),
                checked_at=datetime.now(timezone.utc),
            )

        self.assertEqual(plan["weather_home"]["status"], "stale_offline")
        self.assertFalse(plan["weather_home"]["refresh"])

    def test_explicit_override_is_not_refetched_in_auto_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "garmin.json"
            path.write_text("{}", encoding="utf-8")
            plan = build_source_refresh_plan(
                {"garmin": path},
                required={"garmin"},
                refresh_spec=parse_refresh_json('{"mode":"auto"}'),
                checked_at=datetime.now(timezone.utc),
                overrides={"garmin"},
            )

        self.assertEqual(plan["garmin"]["status"], "provided")
        self.assertFalse(plan["garmin"]["refresh"])


class SurfaceClassificationTests(unittest.TestCase):
    def test_checkpoint_alone_does_not_prove_gravel_surface(self):
        result = surface_classification(
            {
                "name": "Dokka",
                "description": "På piggdekk pga fortsatt litt snø og is på veiene.",
                "gear": {"id": "b11246236", "name": "Trek Checkpoint"},
            }
        )
        self.assertEqual(result["surface"], "unknown")
        self.assertEqual(result["bike_type"], "gravel")

    def test_explicit_gravel_text_is_surface_evidence(self):
        result = surface_classification(
            {
                "name": "Grusrunde",
                "description": "Fin grus hele veien",
                "gear": {"id": "b11246236", "name": "Trek Checkpoint"},
            }
        )
        self.assertEqual(result["surface"], "gravel")
        self.assertEqual(result["confidence"], "activity_text")


class WorkoutReadinessBiasTests(unittest.TestCase):
    def test_accepts_mcp_recommended_workout_shape(self):
        result = compact_xert_workout_recommendations(
            {
                "workouts": [{
                    "name": "XMB: VT1 30 min (165W)",
                    "path": "vt1",
                    "duration": 1800,
                    "xss": 24,
                    "max_power": 165,
                }]
            },
            target_minutes=30,
            target_load=24,
        )

        self.assertEqual(result["recommended"]["path"], "vt1")

    def test_easy_vt1_suppresses_openers_but_keeps_vt1(self):
        payload = {
            "exercises": [
                {
                    "exerciseType": "Workout",
                    "name": "XMB: Openers 3x2 min (260W)",
                    "path": "openers",
                    "duration": 2400,
                    "xss": 35,
                    "max_power": 260,
                },
                {
                    "exerciseType": "Workout",
                    "name": "XMB: VT1 30 min (165W)",
                    "path": "vt1",
                    "duration": 2700,
                    "xss": 30,
                    "max_power": 165,
                },
            ]
        }

        result = compact_xert_workout_recommendations(
            payload,
            target_minutes=45,
            target_load=30,
            readiness_bias="easy_vt1",
        )

        self.assertEqual(result["recommended"]["path"], "vt1")
        self.assertEqual(result["higher_intensity_candidates"], [])
        self.assertEqual(
            [row["path"] for row in result["suppressed_by_readiness_bias"]],
            ["openers"],
        )

    def test_rest_keeps_only_explicit_recovery_workouts(self):
        payload = {
            "exercises": [
                {
                    "exerciseType": "Workout",
                    "name": "XMB: Recovery 30 min",
                    "path": "recovery",
                    "duration": 1800,
                    "xss": 18,
                    "max_power": 150,
                },
                {
                    "exerciseType": "Workout",
                    "name": "XMB: VT1 30 min (165W)",
                    "path": "vt1",
                    "duration": 1800,
                    "xss": 24,
                    "max_power": 165,
                },
            ]
        }

        result = compact_xert_workout_recommendations(
            payload,
            target_minutes=30,
            target_load=20,
            readiness_bias="rest",
        )

        self.assertEqual(result["recommended"]["path"], "recovery")
        self.assertEqual(
            [row["path"] for row in result["suppressed_by_readiness_bias"]],
            ["vt1"],
        )


if __name__ == "__main__":
    unittest.main()
