import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from illness_return import assess_return, parse_illness_return_json
from readiness_snapshot import intervals_wellness_context, build_readiness_snapshot
from recommend_training import (recommendation_bias, apply_intervals_illness_target_guardrail,
                                apply_xert_endurance_duration_solution, build_primary_decision)

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def assessment(**changes):
    return dict(date='2026-11-17', assessed_at='2026-11-17T12:00:00Z',
                illness_started_on='2026-11-10', last_sick_date='2026-11-14',
                severity='mild', symptoms='none', red_flags=False, clinical_review=False,
                response='not_started', return_complete=False,
                reason='Symptoms resolved; short tolerance check after mild illness.',
                evidence=['athlete-report'], dose_minutes=15, dose_xss=8) | changes


def context(day='2026-11-17', sick='2026-11-14'):
    return intervals_wellness_context(day, [{'id': sick, 'comments': 'sick'}])


class IllnessReturnTests(unittest.TestCase):
    def evaluate(self, value, ctx=None):
        return assess_return(ctx or context(), value, day='2026-11-17', cutoff=NOW)

    def test_third_day_and_older_source_illness_do_not_clear_without_review(self):
        for sick in ('2026-11-14', '2026-11-01', '2026-10-01'):
            result = self.evaluate(None, context(sick=sick))
            self.assertTrue(result['illness_training_blocked'])
            self.assertTrue(result['return_to_training_active'])
            self.assertEqual(recommendation_bias(wellness={}, xert={}, intervals_events=result), 'rest')

    def test_short_challenge_requires_current_evidence_and_explicit_dose(self):
        result = self.evaluate(assessment())
        self.assertEqual(result['illness_return_phase'], 'exercise_challenge')
        self.assertEqual(recommendation_bias(wellness={}, xert={}, intervals_events=result), 'easy_vt1')
        target = {'target_minutes': 200, 'target_load': 180}
        apply_intervals_illness_target_guardrail(target, result)
        self.assertEqual((target['target_minutes'], target['target_load']), (15, 8))
        with self.assertRaises(ValueError):
            self.evaluate(assessment(dose_minutes=45))
        value = assessment(); del value['dose_xss']
        with self.assertRaises(ValueError):
            self.evaluate(value)

    def test_normal_response_needs_full_24_hours_not_calendar_date_change(self):
        for end in ('2026-11-17T10:00:00Z', '2026-11-16T12:01:00Z'):
            result = self.evaluate(assessment(response='normal', exercise_ended_at=end, return_complete=True))
            self.assertEqual(result['illness_return_phase'], 'awaiting_24h_response')
            self.assertTrue(result['illness_training_blocked'])
        result = self.evaluate(assessment(response='normal', exercise_ended_at='2026-11-16T12:00:00Z'))
        self.assertEqual(result['illness_return_phase'], 'graded_return')
        self.assertTrue(result['return_to_training_active'])

    def test_complete_requires_explicit_tolerance_review(self):
        result = self.evaluate(assessment(response='normal', exercise_ended_at='2026-11-16T12:00:00Z', return_complete=True))
        self.assertFalse(result['return_to_training_active'])
        self.assertFalse(result['illness_training_blocked'])
        result = self.evaluate(assessment(return_complete=True))
        self.assertEqual(result['illness_return_phase'], 'exercise_challenge')

    def test_warning_signs_systemic_symptoms_abnormal_response_and_unknowns_block(self):
        for change in ({'red_flags': True}, {'symptoms': 'systemic'}, {'response': 'abnormal'},
                       {'symptoms': 'unknown'}, {'severity': 'unknown'}):
            result = self.evaluate(assessment(**change))
            self.assertTrue(result['illness_training_blocked'])

    def test_moderate_and_severe_need_clinical_guidance(self):
        for severity in ('moderate', 'severe'):
            self.assertEqual(self.evaluate(assessment(severity=severity))['illness_return_phase'], 'clinical_review_required')
            self.assertEqual(self.evaluate(assessment(severity=severity, clinical_review=True))['illness_return_phase'], 'exercise_challenge')

    def test_current_sick_event_overrides_normal_return_report(self):
        result = self.evaluate(assessment(last_sick_date='2026-11-17'), context(sick='2026-11-17'))
        self.assertTrue(result['illness_training_blocked'])

    def test_future_stale_wrong_episode_and_unsupported_evidence_are_rejected(self):
        for change in ({'date': '2026-11-16'}, {'assessed_at': '2026-11-17T13:00:00Z'},
                       {'last_sick_date': '2026-11-13'}, {'evidence': []}, {'red_flags': 'false'},
                       {'dose_minutes': float('nan')},
                       {'response': 'normal', 'exercise_ended_at': '2026-11-13T12:00:00Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.evaluate(assessment(**change))

    def test_snapshot_uses_assessment_without_mutating_source(self):
        source = [{'id': '2026-11-14', 'comments': 'sick'}]; before = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as folder:
            packet = build_readiness_snapshot('2026-11-17', artifacts_dir=Path(folder), now=NOW,
                planned_at=NOW, local_timezone=ZoneInfo('Europe/Oslo'),
                intervals_wellness_input=source, illness_return_assessment=parse_illness_return_json(json.dumps(assessment())))
        self.assertEqual(source, before)
        self.assertEqual(packet['recommendation_inputs']['intervals_wellness_events']['illness_return_phase'], 'exercise_challenge')

    def test_solver_cannot_extend_challenge_to_fill_model_load(self):
        target = {'target_minutes': 200, 'target_load': 180, 'xert_recommended_target_xss': {'low': 180}}
        apply_intervals_illness_target_guardrail(target, self.evaluate(assessment()))
        calculation = {'source': 'local_xert_segment_duration_solver', 'network_used': False,
            'matched_within_tolerance': True, 'feasibility': {'valid': True},
            'achieved_xss': {'low': 8, 'high': 0, 'peak': 0, 'total': 8},
            'duration_seconds': 1800, 'target_low_xss': 8}
        with self.assertRaisesRegex(ValueError, 'reviewed illness-return duration'):
            apply_xert_endurance_duration_solution(target, calculation=calculation, selected_intensity='easy_vt1')

    def test_final_packet_rejects_later_dose_expansion(self):
        result = self.evaluate(assessment())
        target = {'target_minutes': 200, 'target_load': 180}
        apply_intervals_illness_target_guardrail(target, result)
        target['target_minutes'] = 30
        with self.assertRaisesRegex(ValueError, 'reviewed illness-return dose'):
            build_primary_decision(readiness_packet={'recommendation_inputs': {'intervals_wellness_events': result}},
                target_resolution=target, intensity_decision={'selected_domain': 'easy_vt1'})


if __name__ == '__main__':
    unittest.main()
