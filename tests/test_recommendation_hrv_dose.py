"""Regression coverage for source composition and the October 22 dose cap."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recommend_training import (
    annotate_readiness_dose_review, compose_garmin_source_overrides,
    normalize_source_override_payload, parse_source_overrides_json, source_paths,
    validate_source_override_payload,
)
from readiness_snapshot import compact_hrv_history, load_garmin_input
from zoneinfo import ZoneInfo


def history(days=('20', '21', '22'), values=(71, 71, 61)):
    return {'source': 'garmin_connect', 'days': [
        {'date': '2026-10-' + day, 'sources': {'hrv': {'lastNightAvg': value}}}
        for day, value in zip(days, values)]}


class HrvDoseTests(unittest.TestCase):
    def inputs(self, with_history=True):
        wellness = {'hrv_last_night_avg': 61, 'hrv_balanced_low': 72,
                    'hrv_balanced_upper': 86, 'sleep_score': 82,
                    'resting_hr': 43, 'resting_hr_7day': 41,
                    'body_battery_at_wake': 88}
        if with_history:
            wellness.update(hrv_3day_mean=67.667, hrv_nights_used_3d=3)
        return {'wellness': wellness, 'xert_recovery': {
            'training_load': {'low': 121.258}, 'recovery_load': {'low': 112.769},
            'projected_recovery_hours_at_planned_time': {'low': -20.2}}}

    def run_guardrail(self, inputs):
        target = {'source': 'xert_training_advice_target_xss',
                  'target_minutes': 210, 'target_load': 219}
        annotate_readiness_dose_review(target, {'recommendation_inputs': inputs})
        return target

    def test_actual_day_and_missing_history_do_not_impose_fixed_dose(self):
        for complete in (True, False):
            with self.subTest(complete=complete):
                result = self.run_guardrail(self.inputs(complete))
                self.assertEqual(result['target_load'], 219)
                self.assertNotIn('acute_readiness_guardrail', result)
                self.assertTrue(result['hrv_dose_review']['isolated_hrv_caution'])
                self.assertEqual(result['hrv_dose_review']['history_status'],
                                 'three_nights' if complete else 'last_night_fallback')

    def test_increasing_tl_over_rl_cannot_increase_recovery_risk(self):
        risks = []
        for tl in (80, 120, 160):
            inputs = self.inputs()
            inputs['xert_recovery']['training_load']['low'] = tl
            result = self.run_guardrail(inputs)
            risks.append(result['xert_recovery_training_diagnostic']['modeled_recovery_risk'])
            self.assertEqual(result['target_load'], 219)
        self.assertEqual(risks, [0, 0, 0])

    def test_planned_recovery_timer_wins_over_current_timer(self):
        inputs = self.inputs()
        inputs['xert_recovery']['recovery_hours'] = {'low': 18}
        result = self.run_guardrail(inputs)
        self.assertEqual(result['xert_recovery_training_diagnostic']['modeled_recovery_risk'], 0)

    def test_hrv_with_model_recovery_alone_does_not_set_exact_dose(self):
        inputs = self.inputs(False)
        inputs['xert_recovery']['projected_recovery_hours_at_planned_time']['low'] = 18
        self.assertEqual(self.run_guardrail(inputs)['target_load'], 219)

    def test_corroborated_poor_recovery_requires_review_without_exact_dose(self):
        inputs = self.inputs()
        inputs['wellness'].update(sleep_score=45, resting_hr=49)
        inputs['xert_recovery']['projected_recovery_hours_at_planned_time']['low'] = 18
        result = self.run_guardrail(inputs)
        self.assertEqual(result['target_load'], 219)
        self.assertTrue(result['readiness_dose_review']['required'])
        self.assertIn('concordant_recovery_signals', result['readiness_dose_review']['intensity_blockers'])

    def test_raw_mcp_history_reaches_existing_readiness_consumer(self):
        raw = history()
        before = copy.deepcopy(raw)
        with tempfile.TemporaryDirectory() as directory:
            paths = source_paths(Path(directory), '2026-10-22')
            day = {'health_day': {'date': '2026-10-22', 'sources': {}}}
            paths['garmin'].write_text(json.dumps(normalize_source_override_payload('garmin', day)))
            paths['garmin_hrv_history'].write_text(json.dumps(raw))
            overrides = parse_source_overrides_json(json.dumps({
                k: str(paths[k]) for k in ('garmin', 'garmin_hrv_history')}))
            validate_source_override_payload('garmin_hrv_history', raw)
            compose_garmin_source_overrides(paths, overridden_sources=set(overrides))
            loaded = load_garmin_input(str(paths['garmin']), local_timezone=ZoneInfo('Europe/Oslo'))
            compact = compact_hrv_history('2026-10-22', loaded)
            self.assertEqual(loaded['hrv_history'], raw)
            self.assertEqual(json.loads(paths['garmin_hrv_history'].read_text()), before)
            self.assertEqual(compact['mean_3d'], 67.667)
            self.assertEqual(compact['nights_used_3d'], 3)

    def test_history_requires_same_run_day_and_valid_shape(self):
        with self.assertRaisesRegex(ValueError, 'requires a garmin override'):
            compose_garmin_source_overrides({}, overridden_sources={'garmin_hrv_history'})
        with self.assertRaisesRegex(ValueError, 'days array'):
            validate_source_override_payload('garmin_hrv_history', {'days': None})

    def test_combined_garmin_response_supplies_day_and_history(self):
        raw = history()
        combined = {'date': '2026-10-22', 'sources': {}, 'hrv_history': raw}
        day = normalize_source_override_payload('garmin', combined)
        nightly = normalize_source_override_payload('garmin_hrv_history', combined)
        validate_source_override_payload('garmin_hrv_history', nightly)
        self.assertEqual(nightly, raw)
        self.assertEqual(compact_hrv_history('2026-10-22', day)['mean_3d'], 67.667)

    def test_stale_gapped_or_duplicate_nights_do_not_make_three_current_nights(self):
        for days in [('19', '20', '21'), ('19', '21', '22'), ('21', '21', '22')]:
            with self.subTest(days=days):
                result = compact_hrv_history('2026-10-22', {'hrv_history': history(days)})
                self.assertIsNone(result['mean_3d'])
                self.assertEqual(result['nights_used_3d'], 2)

    def test_future_and_invalid_values_are_excluded(self):
        raw = history(('20', '21', '22', '23'), (71, False, float('nan'), 100))
        result = compact_hrv_history('2026-10-22', {'hrv_history': raw})
        self.assertEqual(result['nights_used_3d'], 1)


class ReadinessDecisionTests(unittest.TestCase):
    def healthy(self):
        return {'hrv_3day_mean': 70, 'hrv_nights_used_3d': 3,
                'hrv_last_night_avg': 70, 'hrv_balanced_low': 67,
                'hrv_balanced_upper': 83, 'sleep_score': 90,
                'resting_hr': 45, 'resting_hr_7day': 45}

    def recovered(self):
        return {'projected_recovery_hours_at_planned_time': {'low': 0, 'high': 0, 'peak': 0}}

    def test_each_isolated_deviation_reviews_without_intensity_or_duration_cap(self):
        from recommend_training import recommendation_bias, readiness_evidence_status, intensity_guardrails
        for change in ({'hrv_last_night_avg': 50}, {'hrv_3day_mean': 50},
                       {'sleep_score': 57}, {'resting_hr': 55}, {'sleep_time_seconds': 18000}):
            with self.subTest(change=change):
                wellness = self.healthy() | change
                inputs = {'wellness': wellness, 'xert_recovery': self.recovered()}
                self.assertEqual(recommendation_bias(wellness=wellness, xert=self.recovered(),
                    intervals_events={}), 'high_intensity_ok')
                evidence = readiness_evidence_status(inputs)
                self.assertTrue(evidence['review_required'])
                self.assertEqual(evidence['observed_limitations'], [])
                target = {'source': 'xert', 'target_minutes': 180, 'target_load': 180}
                annotate_readiness_dose_review(target, {'recommendation_inputs': inputs})
                self.assertEqual(target['target_minutes'], 180)
                self.assertEqual(target['target_load'], 180)
                self.assertTrue(target['readiness_dose_review']['required'])
                self.assertFalse(target['readiness_dose_review']['automatic_dose_cap'])
                flags = intensity_guardrails(wellness=wellness, freshness={})
                self.assertFalse(any(flag.startswith(('avoid_', 'limit_')) for flag in flags))

    def test_single_night_fallback_is_not_two_votes(self):
        from recommend_training import recommendation_bias, intensity_signal_agreement
        wellness = self.healthy() | {'hrv_last_night_avg': 50, 'hrv_nights_used_3d': 2}
        agreement = intensity_signal_agreement(wellness=wellness, xert=self.recovered(), intervals_events={})
        self.assertTrue(agreement['review_required'])
        self.assertEqual(agreement['blockers'], [])
        self.assertEqual(recommendation_bias(wellness=wellness, xert=self.recovered(), intervals_events={}), 'high_intensity_ok')

    def test_concordant_poor_recovery_lowers_intensity_but_does_not_quantify_dose(self):
        from recommend_training import recommendation_bias
        wellness = self.healthy() | {'sleep_score': 45, 'resting_hr': 55, 'hrv_3day_mean': 50}
        self.assertEqual(recommendation_bias(wellness=wellness, xert=self.recovered(), intervals_events={}), 'easy_vt1')
        target = {'source': 'xert', 'target_minutes': 180, 'target_load': 180}
        annotate_readiness_dose_review(target, {'recommendation_inputs': {'wellness': wellness, 'xert_recovery': self.recovered()}})
        self.assertEqual(target['target_minutes'], 180)
        self.assertTrue(target['readiness_dose_review']['required'])
        self.assertIn('concordant_recovery_signals', target['readiness_dose_review']['intensity_blockers'])

    def test_illness_soreness_and_model_constraints_are_retained(self):
        from recommend_training import recommendation_bias
        self.assertEqual(recommendation_bias(wellness=self.healthy(), xert=self.recovered(),
            intervals_events={'current_day_illness': True}), 'rest')
        self.assertEqual(recommendation_bias(wellness=self.healthy(), xert=self.recovered(),
            intervals_events={'current_day_soreness': 3}), 'normal_vt1')
        self.assertEqual(recommendation_bias(wellness=self.healthy(),
            xert={'projected_recovery_hours_at_planned_time': {'low': 0, 'high': 2, 'peak': 0}},
            intervals_events={}), 'review_recovery')

    def test_explicit_dose_still_carries_review_requirement(self):
        target = {'source': 'explicit_cli', 'target_minutes': 100, 'target_load': 90}
        annotate_readiness_dose_review(target, {'recommendation_inputs': {'wellness': {'sleep_score': 45}}})
        self.assertEqual(target['target_minutes'], 100)
        self.assertTrue(target['readiness_dose_review']['required'])

    def test_missing_measurements_are_unknown_not_adverse(self):
        from recommend_training import readiness_evidence_status
        evidence = readiness_evidence_status({})
        self.assertEqual(evidence['direct_signal_coverage'], 'unavailable')
        self.assertTrue(evidence['review_required'])
        self.assertEqual(evidence['observed_limitations'], [])


if __name__ == '__main__':
    unittest.main()
