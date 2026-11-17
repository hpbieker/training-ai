"""Native calculation binding and independent schedule-horizon regression tests."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'plugins/xert')]
from recommendation_binding import bind_workout_calculation, validate_capacity_horizon
from recommend_training import (apply_recovery_protection_capacity,
    apply_xert_endurance_duration_solution, resolve_training_targets, build_primary_decision)
from xert_strain_model import calculate_workout, solve_segment_duration


class WorkoutBindingTests(unittest.TestCase):
    def structure(self):
        return {'signature':{'tp':300, 'hie':14000, 'pp':900},
                'segments':[{'duration_seconds':120, 'power':100, 'end_power':150},
                            {'duration_seconds':600, 'power':200},
                            {'duration_seconds':120, 'power':100}],
                'adjustable_segment_index':1}

    def native(self, structure):
        return calculate_workout(signature=structure['signature'], segments=structure['segments'], include_series=False)

    def test_native_duration_calculation_binds_and_reaches_final_recommendation(self):
        structure = self.structure(); native = self.native(structure)
        bound = bind_workout_calculation(native, structure)
        target = resolve_training_targets(selection={'minutes':14, 'load':native['xss']['total'],
            'basis':'duration', 'reason':'Synthetic aerobic prescription', 'evidence':['Test']},
            readiness_packet={}, history_context={})
        apply_xert_endurance_duration_solution(target, calculation=bound, selected_intensity='vt1')
        primary = build_primary_decision(target_resolution=target, readiness_packet={}, intensity_decision={'selected_domain':'vt1'})
        self.assertEqual(primary['action'], 'train')
        self.assertEqual(primary['executable_now']['timeline']['status'], 'complete')
        self.assertEqual(target['endurance_duration_solution']['calculation_binding']['status'], 'verified')

    def test_changed_power_ramp_rest_order_count_or_signature_is_rejected(self):
        original = self.structure(); native = self.native(original)
        for change in ('power','ramp','rest','order','count','signature','duration'):
            proposed = copy.deepcopy(original)
            if change == 'power': proposed['segments'][1]['power'] += 1
            elif change == 'ramp': proposed['segments'][0]['end_power'] += 1
            elif change == 'rest': proposed['segments'][2]['power'] += 1
            elif change == 'order': proposed['segments'].reverse()
            elif change == 'count': proposed['segments'].append(proposed['segments'][2])
            elif change == 'signature': proposed['signature']['hie'] += 100
            elif change == 'duration': proposed['segments'][0]['duration_seconds'] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                bind_workout_calculation(native, proposed)

    def test_same_duration_different_power_cannot_reuse_xss_even_if_metadata_changed(self):
        structure = self.structure(); native = self.native(structure)
        structure['segments'][1]['power'] = 250
        forged = self.native(structure); forged['xss'] = native['xss']
        with self.assertRaisesRegex(ValueError, 'XSS does not match'):
            bind_workout_calculation(forged, structure)

    def test_summary_without_inputs_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'complete native'):
            bind_workout_calculation({'source':'xert_workout_calculate', 'duration_minutes':14, 'xss':10}, self.structure())

    def test_solver_changes_only_authorized_duration(self):
        structure = self.structure()
        result = solve_segment_duration(signature=structure['signature'], segments=structure['segments'],
            adjustable_segment_index=1, target_metric='low_xss', target_value=15,
            minimum_duration_seconds=1, maximum_duration_seconds=3600, absolute_tolerance=0.05)
        bound = bind_workout_calculation(result, structure)
        self.assertEqual(bound['calculation_binding']['status'], 'verified')
        self.assertNotEqual(bound['adjustable_duration_seconds'], 600)
        for field in ('power','duration_seconds'):
            changed = copy.deepcopy(structure); changed['segments'][0][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                bind_workout_calculation(result, changed)
        changed = copy.deepcopy(structure); changed['adjustable_segment_index'] = 2
        with self.assertRaisesRegex(ValueError, 'adjustable segment index'):
            bind_workout_calculation(result, changed)

    def test_names_do_not_change_physiological_identity(self):
        structure = self.structure(); native = self.native(structure)
        structure['segments'][0]['name'] = 'New display label'
        self.assertEqual(bind_workout_calculation(native, structure)['calculation_binding']['status'], 'verified')


class CapacityHorizonTests(unittest.TestCase):
    def capacity(self):
        return {'as_of':'2026-11-17T10:00:00+01:00', 'fresh_at':'2026-11-18T10:00:00+01:00',
                'workout_capacity_xss':{'low':100, 'high':10, 'peak':1}}

    def check(self, capacity=None, **changes):
        arguments = {'planned_at':'2026-11-17T10:00:00+01:00', 'next_workout_at':'2026-11-18T10:00:00+01:00', **changes}
        return validate_capacity_horizon(capacity or self.capacity(), **arguments)

    def test_exact_horizon_and_timezone_equivalence(self):
        self.assertEqual(self.check()['status'], 'exact')
        self.assertEqual(self.check(planned_at='2026-11-17T09:00:00Z')['status'], 'exact')

    def test_moving_either_workout_requires_recalculation(self):
        for change in ({'planned_at':'2026-11-17T11:00:00+01:00'},
                       {'next_workout_at':'2026-11-18T11:00:00+01:00'}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'timestamps differ'):
                self.check(**change)
        capacity = self.capacity(); capacity['fresh_at'] = '2026-11-18T11:00:00+01:00'
        self.assertEqual(self.check(capacity, next_workout_at=capacity['fresh_at'])['status'], 'exact')

    def test_equivalent_horizon_requires_reason_evidence_and_same_interval(self):
        new = {'planned_at':'2026-11-17T11:00:00+01:00', 'next_workout_at':'2026-11-18T11:00:00+01:00'}
        with self.assertRaises(ValueError): self.check(**new)
        approximation = {'reason':'Source has no exact scheduled projection', 'evidence':['Model limitation reviewed']}
        self.assertEqual(self.check(**new, approximation=approximation)['status'], 'equivalent_horizon_approximation')
        with self.assertRaisesRegex(ValueError, 'exact recovery interval'):
            self.check(planned_at=new['planned_at'], approximation=approximation)
        with self.assertRaisesRegex(ValueError, 'evidence'):
            self.check(**new, approximation={'reason':'Test'})

    def test_missing_naive_or_reversed_timestamps_are_rejected(self):
        for field in ('as_of','fresh_at'):
            for value in (None,'2026-11-17T10:00:00','bad'):
                capacity = self.capacity(); capacity[field] = value
                with self.subTest(field=field,value=value), self.assertRaises(ValueError): self.check(capacity)
        with self.assertRaises(ValueError): self.check(next_workout_at='2026-11-17T09:00:00+01:00')

    def test_invalid_capacity_values_are_rejected_at_both_boundaries(self):
        for system in ('low','high','peak'):
            for value in (float('nan'),float('inf'),-1,True,None):
                capacity = self.capacity(); capacity['workout_capacity_xss'][system] = value
                with self.subTest(system=system,value=value):
                    with self.assertRaises(ValueError): self.check(capacity)
                    with self.assertRaises(ValueError):
                        apply_recovery_protection_capacity({'target_load':30}, capacity=capacity, selected_intensity='vt1')

if __name__ == '__main__': unittest.main()
