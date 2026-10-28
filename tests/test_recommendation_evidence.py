import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recommend_training import readiness_evidence_status, recommendation_bias, executable_timeline


class RecommendationEvidenceTests(unittest.TestCase):
    def inputs(self, wellness=None, soreness=None):
        return {'wellness': wellness or {}, 'xert_recovery': {
            'projected_recovery_hours_at_planned_time': {'low': -12, 'high': -12, 'peak': -12}},
            'intervals_wellness_events': {'current_day_soreness': soreness}}

    def test_missing_signals_preserve_policy_but_not_confirmed_recovery(self):
        inputs = self.inputs()
        evidence = readiness_evidence_status(inputs)
        self.assertEqual(evidence['direct_signal_coverage'], 'unavailable')
        self.assertEqual(evidence['assessed_direct_signals'], [])
        self.assertEqual(evidence['observed_limitations'], [])
        self.assertEqual(recommendation_bias(wellness={}, xert=inputs['xert_recovery'],
                                            intervals_events={}), 'high_intensity_ok')

    def test_valid_signals_and_soreness_are_separate(self):
        inputs = self.inputs({'sleep_score': 90, 'hrv_last_night_avg': 70,
            'hrv_balanced_low': 60, 'hrv_balanced_upper': 80,
            'resting_hr': 42, 'resting_hr_7day': 42}, soreness=3)
        evidence = readiness_evidence_status(inputs)
        self.assertEqual(evidence['direct_signal_coverage'], 'complete')
        self.assertIn('high_soreness', evidence['observed_limitations'])
        self.assertTrue(evidence['soreness_reported'])

    def test_partial_observations_stay_partial(self):
        evidence = readiness_evidence_status(self.inputs({'sleep_score': 90}))
        self.assertEqual(evidence['direct_signal_coverage'], 'partial')
        self.assertEqual(evidence['assessed_direct_signals'], ['sleep'])

    def target(self):
        return {'endurance_duration_solution': {'duration_seconds': 12437,
            'segments': [{'name': 'warmup', 'duration_seconds': 720, 'power': 165, 'end_power': 204},
                         {'name': 'quality and pauses', 'duration_seconds': 5640, 'power': 295},
                         {'name': 'VT1', 'duration_seconds': 5897, 'power': 215},
                         {'name': 'cooldown', 'duration_seconds': 180, 'power': 150}]}}

    def test_cooldown_stays_after_filler_without_duplicate_minutes(self):
        t = executable_timeline(self.target(), executable_minutes=207.3, action='train')
        self.assertEqual(t['duration_seconds'], 12437)
        self.assertEqual(t['segments'][2]['start_seconds'], 6360)
        self.assertEqual(t['segments'][-1]['end_seconds'], 12437)
        self.assertEqual(t['segments'][-1]['name'], 'cooldown')

    def test_split_does_not_publish_unsplit_timeline(self):
        t = executable_timeline(self.target(), executable_minutes=109, action='train')
        self.assertEqual(t['status'], 'requires_session_specific_calculation')
        self.assertNotIn('segments', t)

    def test_bad_timeline_fails_and_rest_has_no_executable_timeline(self):
        target = self.target()
        target['endurance_duration_solution']['duration_seconds'] += 30
        with self.assertRaises(ValueError):
            executable_timeline(target, executable_minutes=12467 / 60, action='train')
        self.assertEqual(executable_timeline(self.target(), executable_minutes=0,
                                            action='rest')['status'], 'unavailable')

class RecommendationScenarioTests(unittest.TestCase):
    def test_prepared_scenarios_use_production_decisions(self):
        import json
        from prepare_training_recommendation_eval import build_packet, SUITE
        cases = json.loads((SUITE / 'cases.json').read_text())['cases']
        packets = {c['id']: build_packet(c) for c in cases}
        for name in ('missing_recovery', 'normal_recovery', 'later_complete_window'):
            primary = packets[name]['primary_decision']
            self.assertEqual(primary['selected_intensity'], 'vt2')
            self.assertAlmostEqual(primary['physiological_remaining_dose']['load_xss'], 260)
            self.assertEqual(primary['executable_now']['timeline']['duration_seconds'], 12437)
        adverse = packets['adverse_response']['primary_decision']
        self.assertEqual(adverse['selected_intensity'], 'vt1')
        self.assertIn('high_soreness', adverse['readiness_evidence']['observed_limitations'])
        remaining = packets['remaining_after_quality']['primary_decision']
        self.assertEqual(remaining['selected_intensity'], 'vt1')
        self.assertEqual(remaining['physiological_remaining_dose']['load_xss'], 260)
        self.assertTrue(remaining['completed_activities_already_accounted_for'])
        self.assertEqual(remaining['executable_now']['timeline']['duration_seconds'], 14729)
        for name in ('isolated_hrv_drop', 'isolated_hrv_missing_history'):
            packet = packets[name]
            self.assertEqual(packet['date'], '2026-10-22')
            self.assertIn(packet['primary_decision']['selected_intensity'], ('vt1', 'easy_vt1'))
            self.assertNotIn('acute_readiness_guardrail', packet['target_resolution'])
            self.assertTrue(packet['target_resolution']['hrv_dose_review']['isolated_hrv_caution'])
            self.assertAlmostEqual(packet['target_resolution']['target_load'], 219, places=1)


if __name__ == '__main__':
    unittest.main()
