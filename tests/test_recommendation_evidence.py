import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recommend_training import readiness_evidence_status, recommendation_bias, executable_timeline
from readiness_snapshot import intervals_wellness_context


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
                                            intervals_events={}), 'readiness_unknown')

    def test_xert_timer_keeps_plan_available_on_both_sides_of_four_hours(self):
        from recommend_training import select_intensity_domain
        for hours in (0.1, 4, 4.1, 18):
            with self.subTest(hours=hours):
                inputs = self.inputs({'sleep_score': 90})
                inputs['xert_recovery']['projected_recovery_hours_at_planned_time']['low'] = hours
                bias = recommendation_bias(wellness=inputs['wellness'], xert=inputs['xert_recovery'],
                                           intervals_events={})
                self.assertEqual(bias, 'review_recovery')
                evidence = readiness_evidence_status(inputs)
                self.assertIn('xert_low_recovery', evidence['observed_cautions'])
                self.assertEqual(evidence['observed_limitations'], [])
                choice = select_intensity_domain(readiness_ceiling=bias,
                                                 intensity_goal='vt2', progression_advice={})
                self.assertEqual(choice['selected_domain'], 'vt2')
                self.assertEqual(choice['selection_reason'], 'planned_goal_pending_readiness_review')

    def test_valid_signals_and_soreness_are_separate(self):
        inputs = self.inputs({'sleep_score': 90, 'hrv_last_night_avg': 70,
            'hrv_balanced_low': 60, 'hrv_balanced_upper': 80,
            'resting_hr': 42, 'resting_hr_7day': 42}, soreness=3)
        evidence = readiness_evidence_status(inputs)
        self.assertEqual(evidence['direct_signal_coverage'], 'complete')
        self.assertIn('high_soreness', evidence['observed_limitations'])
        self.assertTrue(evidence['soreness_reported'])

    def test_movable_event_only_cancels_its_own_practical_stop(self):
        from zoneinfo import ZoneInfo
        from recommend_training import parse_calendar_context_payload
        timezone = ZoneInfo("Europe/Oslo")
        at = "2026-11-19T17:00:00+01:00"
        end = "2026-11-19T18:00:00+01:00"
        event = dict(subject="Dinner", classification="movable_event", start=at, end=end)
        hard = dict(subject="Departure", at=end)
        payload = dict(day_start=at, day_end=end, events=[event], hard_stop=hard)
        for subject, expected in [("dinner", None), ("Other", dict(subject="Other", at=at))]:
            calendar = parse_calendar_context_payload(
                dict(payload, practical_stop=dict(subject=subject, at=at)), local_timezone=timezone)
            self.assertEqual(calendar["practical_stop"], expected)
            self.assertEqual(calendar["hard_stop"], hard)

    def test_movable_meal_respects_setup_and_cleanup_for_each_session(self):
        from zoneinfo import ZoneInfo
        from recommend_training import parse_calendar_context_payload, place_movable_events
        timezone = ZoneInfo("Europe/Oslo")
        day = "2026-11-20"

        def at(clock):
            return f"{day}T{clock}:00+01:00"

        sessions = [dict(start=at("10:40"), end=at("11:43")),
                    dict(start=at("13:00"), end=at("13:30"))]
        for original, end, expected in [("11:30", "12:15", "11:58"),
                                        ("12:15", "13:00", "11:58"),
                                        ("13:35", "14:20", "13:45")]:
            with self.subTest(original=original):
                meal = dict(subject="Lunch", classification="movable_event",
                            start=at(original), end=at(end))
                calendar = parse_calendar_context_payload(
                    dict(day_start=at("10:25"), day_end=at("16:00"), events=[meal],
                         setup_buffer_minutes=15, cleanup_buffer_minutes=15),
                    local_timezone=timezone)
                result = place_movable_events(calendar, sessions=sessions, local_timezone=timezone, day=day)
                placed, = result["placements"]
                self.assertEqual(placed["start"], at(expected))
                self.assertEqual(placed["duration_minutes"], 45)

    def test_partial_observations_stay_partial(self):
        evidence = readiness_evidence_status(self.inputs({'sleep_score': 90}))
        self.assertEqual(evidence['direct_signal_coverage'], 'partial')
        self.assertEqual(evidence['assessed_direct_signals'], ['sleep'])

    def test_athlete_report_reaches_intensity_selection(self):
        from recommend_training import intensity_signal_agreement, intervals_wellness_events_line, select_intensity_domain
        day = '2026-11-17'
        inputs = self.inputs({'sleep_score': 92})
        for report in ({'fatigue': 4}, {'comments': 'Uvanlig utmattet, orket knapt oppvarmingen i går'},
                       {'comments': 'Muligens syk?'}):
            with self.subTest(report=report):
                events = intervals_wellness_context(day, [{'id': day, 'soreness': 0, **report}])
                params = dict(wellness=inputs['wellness'], xert=inputs['xert_recovery'], intervals_events=events)
                bias = recommendation_bias(**params)
                self.assertEqual(bias, 'review_recovery')
                self.assertIsNone(intensity_signal_agreement(**params)['high_intensity_allowed'])
                prompt = intervals_wellness_events_line(events)
                self.assertIn('who has symptoms' if 'illness_comment_status' in events['current_day']
                              else 'easy power', prompt)
                choice = select_intensity_domain(readiness_ceiling=bias, intensity_goal='vt2', progression_advice={})
                self.assertEqual(choice['selection_reason'], 'planned_goal_pending_readiness_review')

    def test_illness_subject_negation_and_structured_event(self):
        day = '2026-11-17'
        for comment, sick in [('Jeg er ikke syk', False), ('Barnet mitt er sykt', False),
                              ('I am not sick today', False), ('Jeg er syk', True),
                              ('Jeg har feber, hviler i dag', True),
                              ('Jeg er syk og har vondt i halsen', True)]:
            with self.subTest(comment=comment):
                events = intervals_wellness_context(day, [{'id': day, 'comments': comment}])
                self.assertEqual(events['current_day_illness'], sick)
                self.assertEqual(events['current_day_review_signals'], [])
        events = intervals_wellness_context(day, [{'id': day, 'comments': 'Jeg er ikke syk'}],
            events_payload=[{'category': 'SICK', 'start_date_local': day, 'end_date_local': '2026-11-18'}])
        self.assertTrue(events['current_day_illness'])
        events = intervals_wellness_context(day, [
            {'id': '2026-11-16', 'comments': 'Jeg er syk'},
            {'id': day, 'comments': 'Jeg er ikke syk'},
        ])
        self.assertTrue(events['illness_training_blocked'])
        self.assertTrue(events['illness_followup_needed'])
        uncertain = {'id': '2026-11-16', 'comments': 'Muligens syk?'}
        events = intervals_wellness_context(day, [uncertain])
        self.assertIn('clarify_current_illness_comment', events['current_day_review_signals'])
        events = intervals_wellness_context(day, [uncertain, {'id': day, 'comments': 'Jeg er frisk'}])
        self.assertEqual(events['current_day_review_signals'], [])

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
        self.assertFalse(remaining['completed_activities_already_accounted_for'])  # No completed-activity source in this frozen fixture.
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
