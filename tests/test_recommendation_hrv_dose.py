"""Regression coverage for source composition and the October 22 dose cap."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recommend_training import (
    apply_acute_readiness_target_guardrail, compose_garmin_source_overrides,
    normalize_source_override_payload, parse_source_overrides_json, source_paths,
    validate_source_override_payload,
)
from readiness_snapshot import compact_hrv_history, load_garmin_input
from zoneinfo import ZoneInfo


def history(days=('20', '21', '22'), values=(71, 71, 61)):
    return {'source': 'garmin_connect_gccli', 'days': [
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
        apply_acute_readiness_target_guardrail(target, {'recommendation_inputs': inputs})
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

    def test_corrobated_poor_recovery_still_caps_dose(self):
        inputs = self.inputs()
        inputs['wellness'].update(sleep_score=45, resting_hr=49)
        inputs['xert_recovery']['projected_recovery_hours_at_planned_time']['low'] = 18
        result = self.run_guardrail(inputs)
        self.assertEqual(result['target_load'], 30)
        self.assertEqual(result['acute_readiness_guardrail']['level'], 'recovery_day')

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


if __name__ == '__main__':
    unittest.main()
