import math
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "xert" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from xert_load_model import (  # noqa: E402
    capped_recovery_load,
    calculate_load_projection,
    project_load,
    project_load_with_scheduled_impulse,
    training_status_from_total_load,
    summarize_signature_decay_analysis,
    readiness_class_from_recovery_days,
    recovery_demand_sensitivity,
    same_day_completed_and_planned_policy,
    simulate_calendar_sequence,
    validate_fitness_measures_history,
    validate_freshness_history,
    validate_signature_history,
    linear_daily_xss_distribution,
    xss_for_target_load,
)
from xert_recovery import RECOVERY_COMPONENTS, calc_activity_max  # noqa: E402


class XertLoadModelTests(unittest.TestCase):
    def test_linear_daily_distribution_hits_absolute_tp_target(self):
        result = linear_daily_xss_distribution(
            current_load=109.48852868226302,
            current_signature=296.3716452553383,
            target_signature=300.0,
            tau_days=60.0,
            responsiveness=0.4,
            horizon_days=146.67515873842592,
        )
        self.assertEqual(result["distribution"], "linear")
        self.assertEqual(result["frequency"], "daily")
        self.assertEqual(result["impulse_count"], 147)
        self.assertAlmostEqual(result["start_xss"], 111.328629, places=5)
        self.assertAlmostEqual(result["end_xss"], 124.974305, places=5)
        self.assertAlmostEqual(result["total_xss"], 17368.265653, places=4)
        self.assertAlmostEqual(result["projected_signature"], 300.0, places=9)
        self.assertFalse(result["recovery_load_and_status_projected"])

    def test_linear_daily_distribution_supports_explicit_start(self):
        result = linear_daily_xss_distribution(
            current_load=100,
            current_signature=295,
            target_signature=300,
            tau_days=60,
            responsiveness=0.4,
            horizon_days=30.5,
            start_xss=90,
        )
        self.assertEqual(result["start_policy"], "explicit")
        self.assertEqual(result["start_xss"], 90)
        self.assertGreater(result["end_xss"], result["start_xss"])

    def setUp(self):
        self.at_state = {
            "tl": {"ftp": 100.0, "hie": 1.0, "pp": 0.2},
            "rl": {"ftp": 90.0, "hie": 0.8, "pp": 0.15},
            "recovery_offset": 0.2,
        }
        self.params = {
            "ftp": {"tau1": 60, "tau2": 5, "k1": 0.4},
            "hie": {"tau1": 22, "tau2": 12, "k1": 0.75},
            "pp": {"tau1": 22, "tau2": 12, "k1": 50.0},
        }
        self.signature = {"ftp": 296.0, "hie": 14.0, "pp": 775.0}

    def test_target_load_inverse_matches_forward_projection(self):
        xss = xss_for_target_load(
            100,
            target_load=102,
            tau_days=60,
            horizon_days=1,
            impulse_after_days=0.5,
        )
        self.assertAlmostEqual(
            project_load_with_scheduled_impulse(
                100,
                xss=xss,
                tau_days=60,
                horizon_days=1,
                impulse_after_days=0.5,
            ),
            102,
        )

    def test_later_workout_has_less_post_workout_decay(self):
        early = project_load_with_scheduled_impulse(
            100, xss=100, tau_days=60, horizon_days=1, impulse_after_days=0
        )
        late = project_load_with_scheduled_impulse(
            100, xss=100, tau_days=60, horizon_days=1, impulse_after_days=1
        )
        self.assertGreater(late, early)

    def test_workout_time_must_be_inside_projection_horizon(self):
        with self.assertRaisesRegex(ValueError, "workout_after_days"):
            calculate_load_projection(
                at_state=self.at_state,
                ir_params=self.params,
                current_signature=self.signature,
                horizon_days=1,
                workout_after_days=1.1,
            )

    def test_zero_xss_decays_both_loads_and_signature_from_anchor(self):
        result = calculate_load_projection(
            at_state=self.at_state,
            ir_params=self.params,
            current_signature=self.signature,
            horizon_days=1,
        )
        low = result["systems"]["low"]
        self.assertAlmostEqual(low["training_load"]["projected"], 100 * math.exp(-1 / 60))
        self.assertLess(low["signature"]["projected"], 296)
        self.assertEqual(result["training_status"]["category"], "Competitive")
        self.assertTrue(result["state_sync"]["local_projection_must_not_cross_processed_activity_without_resync"])
        self.assertIn("refetch_signature", result["state_sync"]["required_action"])
        self.assertIn("current_live_tau_k1", result["evidence"]["forward_parameter_policy"])
        self.assertIn("do_not_reconstruct", result["evidence"]["signature_anchor_policy"])
        self.assertEqual(
            result["evidence"]["historical_data_role"],
            "verification_only_not_parameter_fitting_or_old_activity_explanation",
        )

    def test_calendar_transition_applies_previous_activity_then_decay(self):
        # Xert Fitness Measures rows for 5 and 6 August 2026. Each row is the
        # state before that row's activity; the 5 August activity was 86 XLSS.
        before_aug5 = 109.17574686508814
        expected_before_aug6 = 108.7014617422102
        elapsed_days = (24 * 3600 + 53 * 60 + 13) / 86400
        projected = project_load(
            before_aug5,
            xss=86.0,
            tau_days=60,
            days=elapsed_days,
        )
        self.assertAlmostEqual(projected, expected_before_aug6, places=2)

    def test_completed_activity_validation_declares_start_to_start_impulse_timing(self):
        first = {
            "start_date": "2026-01-01T08:00:00Z",
            "ltl": 100, "lrl": 90, "xlss": 60,
            "htl": 1, "hrl": .8, "xhss": 8,
            "ptl": .2, "prl": .16, "xpss": 2,
        }
        second = {"start_date": "2026-01-02T08:00:00Z", "xlss": 0, "xhss": 0, "xpss": 0}
        for tl_key, rl_key, xss_key, param_key in (
            ("ltl", "lrl", "xlss", "ftp"),
            ("htl", "hrl", "xhss", "hie"),
            ("ptl", "prl", "xpss", "pp"),
        ):
            params = self.params[param_key]
            second[tl_key] = project_load(first[tl_key], xss=first[xss_key], tau_days=params["tau1"], days=1)
            second[rl_key] = max(
                project_load(first[rl_key], xss=first[xss_key], tau_days=params["tau2"], days=1),
                second[tl_key] * math.exp(-1 / params["tau2"]),
            )
        history = [first, second]
        result = validate_fitness_measures_history(history, ir_params=self.params)
        self.assertEqual(result["impulse_timing"], "previous_activity_xss_at_previous_activity_start")
        self.assertEqual(result["elapsed_time_basis"], "exact_start_to_start_seconds")
        self.assertTrue(result["valid"])
        self.assertEqual(result["validation_scope"], "stored_historical_xss_recurrence_only")

    def test_breakthrough_new_signature_and_recalculated_xss_are_authoritative(self):
        # Live 2025-08-21 breakthrough row and OAuth activity detail.
        row_signature = {"ftp": 327.0628255755, "atc": 14926.167006200001, "pp": 817}
        activity_signature = {"ftp": 327.0628255755, "atc": 14926.167006200001, "pp": 817}
        row_xss = {"low": 111.1, "high": 7.7, "peak": 3.4}
        activity_xss = {"low": 111.10057688869914, "high": 7.726539356911285, "peak": 3.4424519966051417}
        self.assertEqual(row_signature, activity_signature)
        for system in row_xss:
            self.assertAlmostEqual(row_xss[system], activity_xss[system], places=1)
        self.assertLess(0.0018688577337926393, 0.01)

    def test_completed_and_later_planned_same_day_stay_distinct(self):
        result = same_day_completed_and_planned_policy(
            completed_xss={"low": 69, "high": 8.6, "peak": 1.8},
            remaining_xss={"low": 160, "high": 0, "peak": 0},
            planned_xss={"low": 40, "high": 6, "peak": 1},
        )
        self.assertEqual(result["dose_to_recommend"], {"low": 160, "high": 0, "peak": 0})
        self.assertEqual(result["additional_tl_impulse"], {"low": 40, "high": 6, "peak": 1})
        self.assertTrue(result["rules"]["do_not_subtract_completed_xss_again"])
        self.assertTrue(result["rules"]["planner_xss_does_not_reduce_remaining_xss"])

    def test_system_xss_updates_matching_system_and_required_build_is_solved(self):
        result = calculate_load_projection(
            at_state=self.at_state,
            ir_params=self.params,
            current_signature=self.signature,
            planned_xss={"high": 10},
            desired_signature_gain={"ftp": 1.0, "hie": 0.5, "pp": 5.0},
            horizon_days=1,
        )
        self.assertGreater(result["systems"]["high"]["training_load"]["projected"], 1.0)
        self.assertEqual(set(result["required_to_build"]), {"ftp", "hie", "pp"})
        self.assertAlmostEqual(
            result["required_to_build"]["ftp"]["required_training_load_increase"],
            2.5,
        )

        solved_xss = {
            values["system"]: values["single_impulse_xss_at_workout_time"]
            for values in result["required_to_build"].values()
        }
        immediate = calculate_load_projection(
            at_state=self.at_state,
            ir_params=self.params,
            current_signature=self.signature,
            planned_xss=solved_xss,
            horizon_days=0,
        )
        after_one_day = calculate_load_projection(
            at_state=self.at_state,
            ir_params=self.params,
            current_signature=self.signature,
            planned_xss=solved_xss,
            horizon_days=1,
        )
        desired = {"ftp": 1.0, "hie": .5, "pp": 5.0}
        for key, gain in desired.items():
            with self.subTest(signature=key):
                self.assertGreater(
                    immediate["signature_projection"][key] - self.signature[key], gain
                )
                self.assertAlmostEqual(
                    after_one_day["signature_projection"][key] - self.signature[key], gain
                )

    def test_published_star_boundaries(self):
        expected = [(24.9, 0), (25, 1), (50, 2), (75, 3), (110, 4), (150, 5)]
        for load, stars in expected:
            with self.subTest(load=load):
                self.assertEqual(training_status_from_total_load(load)["stars"], stars)

    def test_recovery_load_is_capped_at_one_recovery_day_below_training_load(self):
        self.assertAlmostEqual(
            capped_recovery_load(20, training_load=100, tau_days=5),
            100 * math.exp(-1 / 5),
        )
        self.assertEqual(capped_recovery_load(90, training_load=100, tau_days=5), 90)

    def test_signature_history_separates_tl_model_from_adjustments(self):
        history = [
            {"start_date": "2026-01-01T10:00:00Z", "ltl": 100, "htl": 2, "ptl": 1,
             "ftp": 300, "atc": 14000, "pp": 800, "medal": 1},
            {"start_date": "2026-01-02T10:00:00Z", "ltl": 102, "htl": 3, "ptl": 1.1,
             "ftp": 300.8, "atc": 14750, "pp": 805, "medal": 1},
            {"start_date": "2026-01-03T10:00:00Z", "ltl": 103, "htl": 3, "ptl": 1.1,
             "ftp": 294.2, "atc": 14750, "pp": 805, "medal": 1},
        ]
        validation = validate_signature_history(history, ir_params=self.params)
        self.assertAlmostEqual(validation["systems"]["tp"]["model_consistent_share"], 0.5)
        self.assertEqual(validation["systems"]["hie"]["model_consistent_count"], 2)
        self.assertEqual(len(validation["systems"]["tp"]["large_adjustment_candidates"]), 1)
        self.assertIn("not_usable", validation["interpretation"]["medal_field"])
        self.assertIn("recalculated_activity_xss", validation["interpretation"]["breakthrough_load_handling"])

        decay = summarize_signature_decay_analysis(validation, decay_method=1.03)
        self.assertEqual(decay["configured_decay_method_label"], "Small")
        self.assertFalse(decay["exact_decay_formula_identified"])
        self.assertFalse(decay["xert_write_required"])
        self.assertIn("activity_rows", decay["conclusion"])

    def test_decay_method_frontend_enum_labels(self):
        expected = {
            1: "None - Training Load Matched",
            1.03: "Small",
            1.1: "Optimal - Default",
            1.2: "Aggressive",
        }
        for value, label in expected.items():
            with self.subTest(value=value):
                self.assertEqual(
                    summarize_signature_decay_analysis({"systems": {}}, decay_method=value)["configured_decay_method_label"],
                    label,
                )

    def test_manual_signature_override_is_not_scored_as_model_error(self):
        history = [
            {"start_date": "2026-01-01T00:00:00Z", "ltl": 100, "htl": 1, "ptl": .2,
             "ftp": 300, "atc": 14000, "pp": 800},
            {"start_date": "2026-01-02T00:00:00Z", "ltl": 101, "htl": 1, "ptl": .2,
             "ftp": 350, "atc": 18000, "pp": 900, "manual": True},
            {"start_date": "2026-01-03T00:00:00Z", "ltl": 102, "htl": 1, "ptl": .2,
             "ftp": 350.4, "atc": 18000, "pp": 900},
        ]
        result = validate_signature_history(history, ir_params=self.params)
        tp = result["systems"]["tp"]
        self.assertEqual(tp["manual_override_transitions_excluded"], 1)
        self.assertEqual(tp["transition_count"], 1)
        self.assertAlmostEqual(tp["maximum_absolute_adjustment"], 0.0)
        self.assertEqual(tp["post_manual_transition_count"], 1)
        self.assertEqual(tp["post_manual_model_consistent_count"], 1)
        self.assertFalse(tp["persistent_lock_evidence"])

    def test_initial_signature_and_breakthrough_are_not_scored_as_errors(self):
        history = [
            {"start_date": "2026-01-01T00:00:00Z", "ltl": 100, "htl": 1, "ptl": .2,
             "ftp": 250, "atc": 12000, "pp": 700},
            {"start_date": "2026-01-02T00:00:00Z", "ltl": 101, "htl": 1, "ptl": .2,
             "ftp": 300, "atc": 14000, "pp": 800,
             "error": "No BT yet. Using first signature"},
            {"start_date": "2026-01-03T00:00:00Z", "ltl": 102, "htl": 1, "ptl": .2,
             "ftp": 320, "atc": 15000, "pp": 850},
            {"start_date": "2026-01-04T00:00:00Z", "ltl": 103, "htl": 1, "ptl": .2,
             "ftp": 320.4, "atc": 15000, "pp": 850},
        ]
        events = {
            "2026-01-03T00:00:00+00:00": {"breakthrough": 1, "medal": 2, "manual": False}
        }
        result = validate_signature_history(
            history, ir_params=self.params, activity_events=events
        )["systems"]["tp"]
        self.assertEqual(result["pre_first_signature_transitions_excluded"], 1)
        self.assertEqual(result["breakthrough_transitions_excluded"], 1)
        self.assertEqual(result["transition_count"], 1)
        self.assertAlmostEqual(result["maximum_absolute_adjustment"], 0.0)

    def test_pmcb_near_breakthrough_is_excluded_without_large_residual(self):
        history = [
            {"start_date": "2026-01-01T00:00:00Z", "ltl": 100, "htl": 1, "ptl": .2,
             "ftp": 300, "atc": 14000, "pp": 800},
            {"start_date": "2026-01-02T00:00:00Z", "ltl": 101, "htl": 1, "ptl": .2,
             "ftp": 300.4, "atc": 14000, "pp": 800, "pmcb": 99.0},
        ]
        result = validate_signature_history(history, ir_params=self.params)["systems"]["tp"]
        self.assertEqual(result["breakthrough_transitions_excluded"], 1)
        self.assertEqual(result["transition_count"], 0)

    def test_flagged_activity_and_invalid_following_anchor_are_excluded(self):
        history = [
            {"start_date": "2026-01-01T00:00:00Z", "ltl": 100, "htl": 1, "ptl": .2,
             "ftp": 300, "atc": 14000, "pp": 800},
            {"start_date": "2026-01-02T00:00:00Z", "ltl": 101, "htl": 1, "ptl": .2,
             "ftp": 3000, "atc": 14000, "pp": 2000},
            {"start_date": "2026-01-03T00:00:00Z", "ltl": 102, "htl": 1, "ptl": .2,
             "ftp": 300.8, "atc": 14000, "pp": 800},
            {"start_date": "2026-01-04T00:00:00Z", "ltl": 103, "htl": 1, "ptl": .2,
             "ftp": 301.2, "atc": 14000, "pp": 800},
        ]
        result = validate_signature_history(
            history,
            ir_params=self.params,
            flagged_activity_starts={"2026-01-02T00:00:00+00:00"},
        )["systems"]["tp"]
        self.assertEqual(result["flagged_activity_transitions_excluded"], 1)
        self.assertEqual(result["post_flagged_anchor_transitions_excluded"], 1)
        self.assertEqual(result["transition_count"], 1)
        self.assertAlmostEqual(result["maximum_absolute_adjustment"], 0.0)

    def test_multi_event_calendar_sequence_matches_live_xert_probe(self):
        initial = {
            "tl": {"low": 82.97961001225214, "high": .522279095457636, "peak": .15391765967693247},
            "rl": {"low": 67.93795859544844, "high": .48051996465345315, "peak": .14161108309857873},
        }
        signature = {"ftp": 285.4906096435235, "hie": 13.772205142790837, "pp": 768.591564590757}
        params = {key: dict(value) for key, value in self.params.items()}
        params["pp"]["k1"] = 51.41125657995846
        result = simulate_calendar_sequence(
            initial_time="2026-08-24T07:00:00Z",
            initial_state=initial,
            initial_signature=signature,
            ir_params=params,
            events=[
                {"at": "2026-08-24T07:00:00Z", "xss": {"low": 60, "high": 0, "peak": 0}},
                {"at": "2026-08-25T13:00:00Z", "xss": {"low": 10, "high": 8, "peak": 2}},
                {"at": "2026-08-27T06:00:00Z", "xss": {"low": 75, "high": 12, "peak": 3}},
            ],
            observation_time="2026-08-29T10:00:00Z",
        )
        final = result["final_state"]
        self.assertAlmostEqual(final["tl"]["low"], 78.44718419234968)
        self.assertAlmostEqual(final["tl"]["high"], 1.1950588457314624)
        self.assertAlmostEqual(final["rl"]["peak"], .4128914702853256)
        self.assertAlmostEqual(final["signature"]["ftp"], 283.67763931556254)
        self.assertAlmostEqual(final["signature"]["hie"], 14.276789955496206)
        self.assertAlmostEqual(final["signature"]["pp"], 776.9892336615648)

    def test_xert_forecast_aggregates_same_day_xss_at_last_event_time(self):
        initial = {
            "tl": {"low": 72.67198984783853, "high": .3637474057076683, "peak": .10719776052116813},
            "rl": {"low": 59.49879297579629, "high": .33466376895724664, "peak": .0986267008282725},
        }
        signature = {"ftp": 281.36756157775807, "hie": 13.65330637547836, "pp": 766.1896358678702}
        params = {key: dict(value) for key, value in self.params.items()}
        params["pp"]["k1"] = 51.41125657995846
        result = simulate_calendar_sequence(
            initial_time="2026-09-01T08:00:00+02:00",
            initial_state=initial,
            initial_signature=signature,
            ir_params=params,
            events=[
                {"at": "2026-09-01T08:00:00+02:00", "name": "AM", "xss": {"low": 20}},
                {"at": "2026-09-01T18:00:00+02:00", "name": "PM", "xss": {"low": 10, "high": 12, "peak": 3}},
            ],
            observation_time="2026-09-02T08:00:00+02:00",
        )
        self.assertEqual([event["name"] for event in result["coalesced_events"]], ["AM"])
        final = result["final_state"]
        self.assertAlmostEqual(final["tl"]["low"], 71.95962088061994, delta=.003)
        self.assertAlmostEqual(final["tl"]["high"], .8668739097872198)
        self.assertAlmostEqual(final["tl"]["peak"], .23225680111339003)

    def test_three_same_day_events_coalesce_but_after_midnight_is_separate(self):
        initial = {
            "tl": {"low": 70, "high": 1, "peak": .2},
            "rl": {"low": 60, "high": .8, "peak": .16},
        }
        events = [
            {"at": "2026-10-05T08:00:00+02:00", "name": "AM", "xss": {"low": 10}},
            {"at": "2026-10-05T18:00:00+02:00", "name": "PM", "xss": {"high": 2}},
            {"at": "2026-10-05T23:30:00+02:00", "name": "Late", "xss": {"peak": 1}},
            {"at": "2026-10-06T00:15:00+02:00", "name": "Next day", "xss": {"low": 4}},
        ]
        result = simulate_calendar_sequence(
            initial_time="2026-10-05T07:00:00+02:00",
            initial_state=initial,
            initial_signature=self.signature,
            ir_params=self.params,
            events=events,
            observation_time="2026-10-06T01:00:00+02:00",
        )
        equivalent = simulate_calendar_sequence(
            initial_time="2026-10-05T07:00:00+02:00",
            initial_state=initial,
            initial_signature=self.signature,
            ir_params=self.params,
            events=[
                {"at": "2026-10-05T23:30:00+02:00", "xss": {"low": 10, "high": 2, "peak": 1}},
                {"at": "2026-10-06T00:15:00+02:00", "xss": {"low": 4}},
            ],
            observation_time="2026-10-06T01:00:00+02:00",
        )
        self.assertEqual([event["name"] for event in result["coalesced_events"]], ["AM", "PM"])
        self.assertEqual(len(result["pre_event_states"]), 2)
        for system in ("low", "high", "peak"):
            self.assertAlmostEqual(
                result["final_state"]["tl"][system], equivalent["final_state"]["tl"][system]
            )

    def test_planner_impulse_occurs_immediately_after_start_not_at_end(self):
        before_tl = {"low": 41.23508037834068, "high": .07755637885126912, "peak": .02285616336098055}
        after_tl = {"low": 42.226785003443894, "high": .43305186087883024, "peak": .11173003204386635}
        before_signature = {"ftp": 268.7927977899589, "hie": 13.438663105336062, "pp": 761.8535283759043}
        after_signature = {"ftp": 269.18947964000023, "hie": 13.705284716856731, "pp": 766.4226456420137}
        params = {key: dict(value) for key, value in self.params.items()}
        params["pp"]["k1"] = 51.41125657995846
        for system, mapping in {"low": "ftp", "high": "hie", "peak": "pp"}.items():
            with self.subTest(system=system):
                observed_gain = after_signature[mapping] - before_signature[mapping]
                expected_gain = float(params[mapping]["k1"]) * (after_tl[system] - before_tl[system])
                self.assertAlmostEqual(observed_gain, expected_gain, places=9)

    def test_live_recovery_cap_status_and_required_build_probe(self):
        self.assertAlmostEqual(capped_recovery_load(50, training_load=72.67198984783853, tau_days=5), 59.49879297579629)
        self.assertEqual(training_status_from_total_load(78.32266297912426)["category"], "Competitive")
        self.assertEqual(readiness_class_from_recovery_days({"low": .1, "high": -1, "peak": -1})["model_status"], "Very Tired")
        before = {"ftp": 278.9023452054652, "hie": 13.793173152075935, "pp": 768.2576068637245}
        after = {"ftp": 279.9023452054652, "hie": 14.293173152075935, "pp": 773.2576068637245}
        self.assertAlmostEqual(after["ftp"] - before["ftp"], 1)
        self.assertAlmostEqual(after["hie"] - before["hie"], .5)
        self.assertAlmostEqual(after["pp"] - before["pp"], 5)

    def test_freshness_boundaries_use_system_recovery_and_caps(self):
        self.assertEqual(
            readiness_class_from_recovery_days({"low": 0.1, "high": -1, "peak": -1})["model_status"],
            "Very Tired",
        )
        self.assertEqual(
            readiness_class_from_recovery_days({"low": -1, "high": 0.1, "peak": -1})["model_status"],
            "Tired",
        )
        self.assertEqual(
            readiness_class_from_recovery_days(
                {"low": -1, "high": -1, "peak": -1},
                recovery_loads={"low": 8, "high": 4, "peak": 2},
                recovery_load_caps={"low": 8, "high": 4, "peak": 2},
            )["model_status"],
            "Very Fresh",
        )

    def test_workout_capacity_zero_is_exact_freshness_boundary(self):
        cases = {
            "lo": (100.0, 60.0, 5.0),
            "hi": (1.0, 22.0, 12.0),
            "pk": (.2, 22.0, 12.0),
        }
        recovery_demand = .2
        for component, (training_load, tau1, tau2) in cases.items():
            config = RECOVERY_COMPONENTS[component]
            divisor = float(config["tired_training_divisor"])
            base = float(config["tired_base"])
            scale = float(config["tired_recovery_scale"])
            boundary = training_load * (1 - 1 / divisor) + base - recovery_demand * scale
            args = {
                "next_workout_days": 0,
                "recovery_offset": recovery_demand,
                "training_load": training_load,
                "training_load_tau": tau1,
                "recovery_load_tau": tau2,
                "tired_training_divisor": divisor,
                "tired_base": base,
                "tired_recovery_scale": scale,
            }
            with self.subTest(component=component):
                self.assertAlmostEqual(calc_activity_max(recovery_load=boundary, **args), 0)
                self.assertGreater(calc_activity_max(recovery_load=boundary - 1e-6, **args), 0)
                self.assertLess(calc_activity_max(recovery_load=boundary + 1e-6, **args), 0)

    def test_recovery_demand_moves_boundary_toward_more_recovery(self):
        result = recovery_demand_sensitivity(
            at_state=self.at_state, ir_params=self.params, offsets=[-0.8, 1.2]
        )
        easy, conservative = result["scenarios"]
        self.assertGreater(
            easy["train_recover_rl_boundary"]["low"],
            conservative["train_recover_rl_boundary"]["low"],
        )
        self.assertEqual(result["slider"], {"min": -0.8, "max": 1.2, "step": 0.1})

    def test_historical_freshness_validator_matches_known_colors(self):
        caps = {
            "lrl-cap": 80.0,
            "hrl-cap": 0.8,
            "prl-cap": 0.16,
        }
        base = {"ltl": 100.0, "htl": 1.0, "ptl": 0.2, **caps}
        history = [
            {**base, "start_date": "2026-01-01T00:00:00Z", "lrl": 120, "hrl": 0.8, "prl": .16, "tsbColor": "#FF0000"},
            {**base, "start_date": "2026-01-02T00:00:00Z", "lrl": 80, "hrl": 2.0, "prl": .16, "tsbColor": "#F5A623"},
            {**base, "start_date": "2026-01-03T00:00:00Z", "lrl": 80, "hrl": .8, "prl": .16, "tsbColor": "#7ED321"},
        ]
        result = validate_freshness_history(history, ir_params=self.params, recovery_offset=.2)
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
