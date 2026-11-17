"""Regression tests for explicit dose selection instead of automatic Xert quotas."""
import argparse
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recommend_training import (
    resolve_training_targets, parse_training_target_json,
    apply_quality_workout_vt1_composition, apply_recovery_protection_capacity,
    apply_xert_endurance_duration_solution, require_resolved_capacity_review,
    build_primary_decision, build_endurance_solver_request,
)


class CoachingDoseTests(unittest.TestCase):
    def selection(self, **changes):
        return dict(minutes=60, load=50, basis='duration', reason='Aerobic support before quality tomorrow',
                    evidence=['Reviewed recent response and next session'], **changes)

    def target(self, selection=None, advice=300):
        return resolve_training_targets(selection=selection or self.selection(), history_context={},
            readiness_packet={'recommendation_inputs': {'xert_training_advice': {'remaining_xss': {'low': advice}}}})

    def calculation(self):
        return {'submit': 'calculate', 'result': {'stats': {'duration': 3600, 'xss': 50, 'xlss': 50, 'xhss': 0, 'xpss': 0}}}

    def test_missing_selection_stops_even_with_xert_advice(self):
        with self.assertRaisesRegex(SystemExit, 'Dose requires assessment'):
            resolve_training_targets(selection=None, history_context={}, readiness_packet={'recommendation_inputs': {'xert_training_advice': {'remaining_xss': {'low': 300}}}})

    def test_xert_advice_cannot_change_selected_dose_or_solver_target(self):
        for advice in (20, 300, 1000):
            target = self.target(advice=advice)
            self.assertEqual((target['target_minutes'], target['target_load']), (60, 50))
            target['coaching_selection']['basis'] = 'load'
            request = build_endurance_solver_request(target, structure={})
            self.assertEqual(request['target_value'], 50)

    def test_requires_reason_and_evidence_and_finite_values(self):
        for field, value in [('reason',''), ('evidence',[]), ('minutes',float('nan')), ('load',True), ('low_xss',100)]:
            selection = self.selection(); selection[field] = value
            with self.subTest(field=field), self.assertRaises(argparse.ArgumentTypeError):
                parse_training_target_json(json.dumps(selection))

    def test_extension_requires_separate_justification(self):
        selection = self.selection(endurance_extension={'reason':'Because XATA says so'})
        with self.assertRaisesRegex(argparse.ArgumentTypeError, 'evidence'):
            parse_training_target_json(json.dumps(selection))

    def test_no_extension_even_with_large_target_and_existing_solution(self):
        target = self.target(); target['target_load'] = 300
        target['endurance_duration_solution'] = {'duration_minutes': 250, 'achieved_xss': {'total': 300, 'low':300}}
        result = apply_quality_workout_vt1_composition(target, quality_calculation=self.calculation(), selected_intensity='vt2')
        self.assertEqual(result['vt1_filler']['duration_minutes'], 0)
        self.assertEqual(result['estimated_total'], {'duration_minutes':60, 'xss':50})

    def test_completed_quality_without_extension_has_no_remaining_workout(self):
        target = self.target()
        result = apply_quality_workout_vt1_composition(target, quality_calculation=self.calculation(), selected_intensity='vt1', quality_workout_status='completed')
        self.assertEqual(result['estimated_total'], {'duration_minutes':0, 'xss':0})

    def test_capacity_conflict_never_cuts_and_blocks_final_recommendation(self):
        target = self.target()
        apply_recovery_protection_capacity(target, capacity={'workout_capacity_xss': {'low':30, 'high':1, 'peak':1}}, selected_intensity='vt1')
        self.assertEqual((target['target_minutes'], target['target_load']), (60, 50))
        with self.assertRaisesRegex(SystemExit, 'conflict requires review'):
            build_primary_decision(target_resolution=target, readiness_packet={}, intensity_decision={'selected_domain':'vt1'})

    def test_acceptance_is_explicit_but_declared_move_or_cut_does_not_resolve_conflict(self):
        for action in ('reduce_dose', 'move_next_workout', 'accept_model_conflict'):
            target = self.target(self.selection(capacity_decision={'action':action, 'reason':'Reviewed model tradeoff', 'evidence':['Next session and response assessed']}))
            apply_recovery_protection_capacity(target, capacity={'workout_capacity_xss': {'low':30, 'high':1, 'peak':1}}, selected_intensity='vt1')
            if action == 'accept_model_conflict':
                require_resolved_capacity_review(target)
                self.assertEqual(target['recovery_protection_capacity']['status'], 'model_conflict')
            else:
                with self.assertRaises(SystemExit): require_resolved_capacity_review(target)

    def test_recalculated_capacity_resolves_conflict(self):
        target = self.target(self.selection(capacity_decision={'action':'move_next_workout', 'reason':'Later start chosen', 'evidence':['Updated schedule']}))
        apply_recovery_protection_capacity(target, capacity={'workout_capacity_xss': {'low':60, 'high':1, 'peak':1}}, selected_intensity='vt1')
        require_resolved_capacity_review(target)
        self.assertEqual(target['target_load'], 50)

    def test_duration_first_uses_calculation_without_extending_duration(self):
        target = self.target()
        result = apply_xert_endurance_duration_solution(target, calculation=self.calculation(), selected_intensity='vt1')
        self.assertEqual(result['source'], 'xert_workout_calculate')
        self.assertEqual((target['target_minutes'], target['target_load']), (60, 50))
        primary = build_primary_decision(target_resolution=target, readiness_packet={}, intensity_decision={'selected_domain':'vt1'})
        self.assertEqual(primary['xert_comparison']['difference_xss'], -250)

    def test_duration_calculation_rejects_changed_duration_or_wrong_load(self):
        for field, value in [('duration',7200), ('xss',70), ('xhss',2)]:
            calculation = self.calculation(); calculation['result']['stats'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                apply_xert_endurance_duration_solution(self.target(), calculation=calculation, selected_intensity='vt1')

    def test_duration_first_quality_extension_keeps_canonical_structure(self):
        selection = self.selection(endurance_extension={'reason':'Selected aerobic support', 'evidence':['Reviewed plan']})
        target = self.target(selection)
        calculation = self.calculation()
        calculation['canonical_structure'] = {'signature':{'tp':300}, 'adjustable_segment_index':1,
            'segments':[{'duration_seconds':2400, 'power':250}, {'duration_seconds':1200, 'power':200}]}
        apply_xert_endurance_duration_solution(target, calculation=calculation, selected_intensity='vt2')
        quality = {'submit':'calculate', 'result':{'stats':{'duration':2400, 'xss':35, 'xlss':35, 'xhss':0, 'xpss':0}}}
        composition = apply_quality_workout_vt1_composition(target, quality_calculation=quality, selected_intensity='vt2')
        self.assertEqual(composition['vt1_filler']['duration_minutes'], 20)
        self.assertEqual(composition['estimated_total'], {'duration_minutes':60, 'xss':50})
        primary = build_primary_decision(target_resolution=target, readiness_packet={}, intensity_decision={'selected_domain':'vt2'})
        self.assertEqual(primary['executable_now']['timeline']['status'], 'complete')

    def test_final_workout_must_match_chosen_dose(self):
        target = self.target(); target['target_minutes'] = 90
        with self.assertRaisesRegex(ValueError, 'differs from the coach-selected dose'):
            build_primary_decision(target_resolution=target, readiness_packet={}, intensity_decision={'selected_domain':'vt1'})

if __name__ == '__main__':
    unittest.main()
