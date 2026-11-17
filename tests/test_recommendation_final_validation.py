"""Offline integration tests for selection -> guards -> calculation -> decision."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recommend_training import (
    resolve_training_targets, initialize_plan_trace, finalize_plan_trace,
    apply_readiness_domain_target_cap, build_endurance_solver_request,
    apply_xert_endurance_duration_solution, apply_recovery_protection_capacity,
    build_primary_decision,
)


class FinalRecommendationValidationTests(unittest.TestCase):
    def prepare(self, minutes=90, load=80, domain='active_recovery'):
        target = resolve_training_targets(
            selection={'minutes':minutes, 'load':load, 'basis':'load',
                       'reason':'Synthetic reviewed prescription', 'evidence':['Offline test scenario']},
            readiness_packet={'recommendation_inputs':{'xert_training_advice':{'remaining_xss':{'low':300}}}},
            history_context={})
        initialize_plan_trace(target)
        decision = {'selected_domain':domain}
        apply_readiness_domain_target_cap(target, intensity_decision=decision)
        request = build_endurance_solver_request(target, structure={})
        return target, decision, request

    def solution(self, low=30, minutes=45):
        return {'source':'local_xert_segment_duration_solver', 'network_used':False,
                'matched_within_tolerance':True, 'feasibility':{'valid':True},
                'target_low_xss':low, 'tolerance_xss':0.05,
                'duration_seconds':minutes*60,
                'achieved_xss':{'total':low, 'low':low, 'high':0, 'peak':0}}

    def finish(self, target, decision, solution):
        apply_xert_endurance_duration_solution(target, calculation=solution,
            selected_intensity=decision['selected_domain'])
        apply_recovery_protection_capacity(target, selected_intensity=decision['selected_domain'],
            capacity={'workout_capacity_xss':{'low':100, 'high':10, 'peak':10}})
        finalize_plan_trace(target)
        return build_primary_decision(target_resolution=target, intensity_decision=decision, readiness_packet={})

    def test_capped_selection_calculated_within_limits_reaches_final_decision(self):
        target, decision, request = self.prepare()
        self.assertEqual(request['target_value'], 30)
        result = self.finish(target, decision, self.solution(low=request['target_value']))
        self.assertEqual(result['action'], 'train')
        self.assertEqual(result['physiological_remaining_dose'], {'minutes':45, 'load_xss':30})

    def test_solver_cannot_expand_45_minute_recovery_cap_to_55_minutes(self):
        target, decision, request = self.prepare()
        with self.assertRaisesRegex(ValueError, 'active_recovery minutes limit'):
            self.finish(target, decision, self.solution(low=request['target_value'], minutes=55))

    def test_recovery_cap_applies_when_original_dose_needed_no_reduction(self):
        target, decision, request = self.prepare(minutes=40, load=20)
        self.assertNotIn('readiness_domain_cap', target)
        with self.assertRaisesRegex(ValueError, 'active_recovery minutes limit'):
            self.finish(target, decision, self.solution(low=request['target_value'], minutes=55))

    def test_final_load_cannot_bypass_cap_at_acceptable_duration(self):
        target, decision, _ = self.prepare()
        self.finish(target, decision, self.solution())
        target['target_load'] = 35
        with self.assertRaisesRegex(ValueError, 'active_recovery load limit'):
            build_primary_decision(target_resolution=target, intensity_decision=decision, readiness_packet={})

    def test_reviewed_limit_remains_binding_even_if_domain_changes(self):
        target, decision, _ = self.prepare()
        decision['selected_domain'] = 'vt1'
        with self.assertRaisesRegex(ValueError, 'readiness_domain_cap minutes limit'):
            self.finish(target, decision, self.solution(minutes=55))

    def test_illness_and_readiness_limits_are_both_enforced(self):
        target, decision, _ = self.prepare()
        target['illness_return_guardrail'] = {'active':True, 'max_minutes':20, 'max_load':10}
        target.update(target_minutes=20, target_load=11)
        with self.assertRaisesRegex(ValueError, 'illness_return_guardrail load limit'):
            build_primary_decision(target_resolution=target, intensity_decision=decision, readiness_packet={})

    def test_claimed_match_with_wrong_achieved_load_is_rejected_without_mutation(self):
        target, decision, _ = self.prepare()
        before = copy.deepcopy(target)
        solution = self.solution()
        solution['achieved_xss'].update(low=29, total=29)
        with self.assertRaisesRegex(ValueError, 'achieved low XSS'):
            self.finish(target, decision, solution)
        self.assertEqual(target, before)

    def test_inconsistent_total_is_rejected(self):
        target, decision, _ = self.prepare()
        solution = self.solution(); solution['achieved_xss']['total'] = 32
        with self.assertRaisesRegex(ValueError, 'components do not sum'):
            self.finish(target, decision, solution)

    def test_invalid_solver_numbers_are_rejected(self):
        for field in ('low', 'high', 'peak', 'total', 'duration_seconds', 'target_low_xss', 'tolerance_xss'):
            for value in (float('nan'), float('inf'), -1, True):
                with self.subTest(field=field, value=value):
                    target, decision, _ = self.prepare()
                    solution = self.solution()
                    container = solution['achieved_xss'] if field in solution['achieved_xss'] else solution
                    container[field] = value
                    with self.assertRaises(ValueError):
                        self.finish(target, decision, solution)
        target, decision, _ = self.prepare()
        solution = self.solution(); solution['tolerance_xss'] = 0
        with self.assertRaises(ValueError): self.finish(target, decision, solution)

    def test_reported_and_achieved_targets_cannot_accumulate_tolerance(self):
        target, decision, _ = self.prepare()
        solution = self.solution(low=30.04)
        solution['achieved_xss'].update(low=30.08, total=30.08)
        with self.assertRaisesRegex(ValueError, 'coach-selected'):
            self.finish(target, decision, solution)

    def test_small_rounding_residual_is_accepted_for_mixed_workout(self):
        target, decision, _ = self.prepare(load=35, domain='vt2')
        target['selected_low_xss'] = 30
        solution = self.solution()
        solution['achieved_xss'].update(high=4, peak=1, total=35.01)
        apply_xert_endurance_duration_solution(target, calculation=solution, selected_intensity='vt2')
        self.assertEqual(target['target_load'], 35)

    def test_nonfinite_final_dose_is_rejected_without_coaching_selection(self):
        for field in ('target_minutes','target_load'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'finite nonnegative'):
                target = {'target_minutes':30, 'target_load':20, field:float('nan')}
                build_primary_decision(target_resolution=target, intensity_decision={'selected_domain':'vt1'}, readiness_packet={})

if __name__ == '__main__':
    unittest.main()
