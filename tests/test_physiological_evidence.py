from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from physiological_evidence import quality, field_summary, matched_windows, prepare_windows
from analysis import summarize_block, summarize_rows
from activity_inspect import vt2_block_quality, hr_recovery_after_block, indoor_vt1_assessment


def ride(step=1, duration=1200):
    return [dict(time=str(t), watts='290', cadence='90', heartrate=str(140 if t < 600 else 150),
                 respiration='35', tidal_volume_min='80', smo2='5', core_temperature='39')
            for t in range(0, duration, step)]


class EvidenceTests(unittest.TestCase):
    def test_work_overview_keeps_each_blocks_windows_and_missing_fields(self):
        from activity_inspect import work_block_overview
        rows = ride(duration=1800)
        for row in rows:
            t = int(row['time'])
            row['heartrate'] = str(120 + t / 100 if t < 900 else 150 + (t - 900) / 50)
            if t >= 900:
                row.pop('respiration')
        blocks = [summarize_block(rows, start_index=a, end_index=b, label='work')
                  for a, b in [(0, 900), (900, 1800)]]
        views = [work_block_overview(b, index=i) for i, b in enumerate(blocks, 1)]
        for i, (block, view) in enumerate(zip(blocks, views)):
            self.assertEqual(view['work_block_number'], i + 1)
            self.assertEqual(view['detail_path'], f'work_blocks[{i}]')
            self.assertEqual(view['early_window']['start_s'], block['comparison']['early']['start_s'])
            hr = next(m for m in view['metrics'] if m['field'] == 'heartrate')
            self.assertEqual(hr['late_window_mean'], round(block['comparison']['fields']['heartrate']['late_avg'], 2))
            self.assertNotEqual(hr['block_mean'], hr['late_window_mean'])
        self.assertLess(views[0]['late_window']['end_s'], views[1]['early_window']['start_s'])
        absent = next(m for m in views[1]['metrics'] if m['field'] == 'respiration')
        self.assertEqual(absent['window_status'], 'unavailable')
        self.assertIsNone(absent['block_mean'])
        self.assertIsNone(absent['late_minus_early'])
        short = summarize_block(rows, start_index=0, end_index=60, label='short')
        self.assertTrue(all(m['late_minus_early'] is None for m in work_block_overview(short, index=1)['metrics']))

    def test_brief_preserves_source_work_and_detected_segment_scopes(self):
        from activity_inspect import brief_result
        rows = ride(duration=900)
        source = summarize_block(rows, start_index=60, end_index=780, label='WORK',
                                 detection={'source': 'intervals_icu'})
        source.update(type='WORK', index=2)
        detected = summarize_block(rows, start_index=90, end_index=750, label='stable')
        result = {
            'activity': {'name': 'test', 'type': 'Ride'},
            'streams': {'rows': len(rows), 'data_quality': {}},
            'total': {'summary': summarize_rows(rows), 'drift': {}, 'relative_to_power_drift': {}},
            'intervals': [source], 'auto_power_blocks': [detected], '_rows': rows,
        }
        report = brief_result(result)
        original = report['source_work_intervals'][0]
        selected = report['work_blocks'][0]
        self.assertEqual(original['statistics_scope'], 'source_work_interval')
        self.assertEqual((original['start_s'], original['end_s_exclusive'], original['duration_s']), (60, 780, 720))
        self.assertEqual(selected['statistics_scope'], 'detected_analysis_segment')
        self.assertEqual((selected['start_s'], selected['end_s_exclusive'], selected['duration_s']), (90, 750, 660))
        self.assertEqual(selected['overlapping_source_interval_indices'], [2])
        self.assertEqual(report['total']['statistics_scope'], 'whole_activity')
        self.assertEqual(selected['change_scope'], 'selected_comparison_windows_only')
        self.assertEqual(selected['comparison']['statistics_scope'], 'selected_comparison_windows_only')
        self.assertNotIn('comparison', original)
        self.assertNotIn('hr_drift', original)
        result.pop('intervals')
        no_source = brief_result(result)
        self.assertEqual(no_source['source_work_intervals_status'], 'not_included_or_absent')
        self.assertEqual(no_source['source_work_intervals'], [])
        self.assertEqual(no_source['work_blocks'][0]['overlapping_source_interval_indices'], [])
        result['intervals'] = [source]
        result.pop('auto_power_blocks')
        self.assertEqual(brief_result(result)['work_blocks'][0]['statistics_scope'], 'source_work_interval')

    def test_prescribed_power_is_independent_of_vt2_anchor(self):
        from activity_inspect import vt2_quality
        rows = ride()
        for row in rows:
            row['watts'] = '280'
        block = summarize_block(rows, start_index=0, end_index=len(rows), label='work')
        args = ({'name': 'VT2 test'}, rows, [block], [])
        explicit = vt2_quality(*args, vt2_watts=295, prescribed_watts=280)
        assessed = explicit['blocks'][0]
        self.assertEqual(explicit['anchor_watts'], 295)
        self.assertEqual(assessed['target_watts'], 280)
        self.assertEqual(assessed['target_source'], 'explicit_prescription')
        self.assertEqual(assessed['execution_score'], 100)
        self.assertEqual(assessed['power_control']['avg_delta_w'], 0)
        unknown = vt2_quality(*args, vt2_watts=295)
        unassessed = unknown['blocks'][0]
        self.assertEqual(unassessed['verdict'], 'target_attainment_unresolved')
        self.assertNotIn('execution_score', unassessed)
        self.assertNotIn('target_watts', unassessed)
        self.assertEqual(unassessed['power_control']['power_sd_w'], 0)
        self.assertEqual(unknown['session_quality']['target_attainment'], 'unresolved')
        self.assertNotIn('worst_execution_block', unknown['session_quality'])
        off_target = vt2_quality(*args, vt2_watts=295, prescribed_watts=310)['blocks'][0]
        self.assertIn('target_mismatch', off_target['limiter_hints'])

    def test_power_normalization_is_limited_to_descriptive_response_fields(self):
        rows = ride()
        changes = {
            'heartrate': (140, 154), 'respiration': (35, 38.5),
            'tidal_volume_min': (80, 88), 'tidal_volume': (2, 2.2),
            'core_temperature': (38, 39), 'skin_temperature': (30, 31),
            'temp': (20, 21), 'RuuviTemperature': (20, 21),
            'dewpoint_c': (-1, 0), 'smo2': (50, 55),
            'thb': (12, 13), 'Humidity': (40, 45), 'new_sensor': (10, 11),
        }
        for row in rows:
            for field, (early, late) in changes.items():
                row[field] = str(early if int(row['time']) < 600 else late)
        result = matched_windows(rows, list(changes) + ['watts', 'cadence'])
        normalized = {field for field, evidence in result['fields'].items()
                      if 'per_watt_change_pct' in evidence}
        self.assertEqual(normalized, {'heartrate', 'respiration', 'tidal_volume_min'})
        for field in normalized:
            self.assertAlmostEqual(result['fields'][field]['per_watt_change_pct'], 10)
        for field in ['core_temperature', 'skin_temperature', 'temp',
                      'RuuviTemperature', 'dewpoint_c']:
            self.assertEqual(result['fields'][field]['delta'], 1)
            self.assertEqual(result['fields'][field]['delta_unit'], 'degC')
        self.assertEqual(result['fields']['smo2']['delta'], 5)
        self.assertEqual(result['fields']['smo2']['delta_unit'], 'percentage_points')

    def test_beta_diagnostics_require_explicit_opt_in(self):
        from unittest.mock import patch
        from activity_inspect import brief_result
        rows = ride()
        block = summarize_block(rows, start_index=0, end_index=len(rows), label='work')
        source = {
            'activity': {'name': 'VT2 test', 'type': 'Ride'},
            'streams': {'rows': len(rows), 'data_quality': {}},
            'total': {'summary': summarize_rows(rows), 'drift': {},
                      'relative_to_power_drift': {}},
            'detected_power_blocks': [block], '_rows': rows, '_vt2_watts': 290,
        }
        with patch('activity_inspect.beta_stability_debug') as stability, \
             patch('activity_inspect.beta_vo2_debug') as vo2:
            normal = brief_result(source)
            stability.assert_not_called()
            vo2.assert_not_called()
        debug = brief_result(source, debug_beta=True)
        beta_keys = {'beta_stability', 'beta_vo2', 'beta_summary'}
        self.assertFalse(beta_keys & normal.keys())
        self.assertTrue(beta_keys <= debug.keys())
        self.assertEqual(normal, {k: v for k, v in debug.items() if k not in beta_keys})
        self.assertIn('vt2_quality', normal)
        self.assertIn('interpretation_limit', debug['beta_stability'])

    def test_block_boundary_shift_reuses_activity_windows(self):
        rows = ride(duration=1800)
        # A clipped transition used to reinitialize the running power baseline.
        for row in rows[:741]:
            row['watts'] = '120'
        for row in rows[741:750]:
            row['watts'] = '265'
        context = prepare_windows(rows)
        total = matched_windows(rows, ['heartrate'], window_context=context)
        for start in [741, 742, 750, 760]:
            block = summarize_block(rows, start_index=start, end_index=len(rows),
                                    label='work', window_context=context)
            self.assertEqual(block['comparison']['early'], total['early'])
            self.assertEqual(block['comparison']['late'], total['late'])
            self.assertEqual(block['drift']['heartrate'], total['fields']['heartrate']['delta'])
            self.assertEqual(block['comparison'], summarize_block(
                rows, start_index=start, end_index=len(rows), label='work')['comparison'])
            diagnostic = vt2_block_quality(rows, block, index=1,
                                           target_watts=290, anchor_watts=290)
            self.assertEqual(diagnostic['comparison'], block['comparison'])

    def test_context_windows_stay_inside_block_and_preserve_gaps(self):
        rows = ride()
        context = prepare_windows(rows)
        block = rows[181:959]
        result = matched_windows(block, ['heartrate'], window_context=context)
        self.assertGreaterEqual(result['early']['start_s'], 181)
        self.assertLessEqual(result['late']['end_s'], 959)
        # A filtered-out source sample must not silently reappear via context.
        filtered = [r for r in rows if int(r['time']) % 120 != 60]
        self.assertEqual(matched_windows(filtered, ['heartrate'],
                         window_context=context)['status'], 'unavailable')

    def test_sample_rate_does_not_change_comparison_or_coverage(self):
        a = matched_windows(ride(), ['heartrate'])
        b = matched_windows(ride(5), ['heartrate'])
        self.assertEqual(a['early'], b['early'])
        self.assertEqual(a['late'], b['late'])
        self.assertEqual(a['fields']['heartrate']['delta'], 10)
        self.assertEqual(a['fields']['heartrate'], b['fields']['heartrate'] | {
            'series_quality': a['fields']['heartrate']['series_quality'],
            'early_quality': a['fields']['heartrate']['early_quality'],
            'late_quality': a['fields']['heartrate']['late_quality']})
        self.assertEqual(quality(ride(), 'heartrate')['valid_seconds'], 1200)
        self.assertEqual(quality(ride(5), 'heartrate')['valid_seconds'], 1200)

    def test_irregular_sampling_is_time_weighted(self):
        rows = [dict(time=str(t), watts=str(w)) for t, w in [(0,100),(1,200),(6,200),(11,200)]]
        self.assertAlmostEqual(field_summary(rows, 'watts')['avg'], (100+15*200)/16)

    def test_missing_rows_are_counted_as_elapsed_gap(self):
        rows = [r for r in ride() if not 300 <= float(r['time']) < 360]
        q = quality(rows, 'heartrate')
        self.assertGreaterEqual(q['longest_gap_seconds'], 60)
        self.assertFalse(q['usable'])
        self.assertIsNone(field_summary(rows, 'heartrate'))

    def test_isolated_invalid_measurement_is_missing_not_a_series_veto(self):
        from activity_inspect import compact_quality
        for invalid in ['nan', 'inf', '-1', '0', 'bad']:
            rows = ride()
            rows[150]['heartrate'] = invalid
            q = quality(rows, 'heartrate')
            self.assertTrue(q['usable'])
            self.assertEqual(q['invalid'], 1)
            self.assertEqual(q['missing'], 1)
            self.assertEqual(q['longest_gap_seconds'], 1)
            self.assertEqual(field_summary(rows, 'heartrate')['count'], 1199)
            self.assertEqual(compact_quality({'heartrate': q})['heartrate']['invalid'], 1)
            self.assertEqual(matched_windows(rows, ['heartrate'])['fields']['heartrate']['status'], 'usable')

    def test_invalid_measurements_still_fail_gap_and_coverage_limits(self):
        for indices, reason in [(range(300, 330), 'long_gap'),
                                (range(0, 1200, 10), 'insufficient_time_coverage')]:
            rows = ride()
            for i in indices:
                rows[i]['heartrate'] = 'nan'
            q = quality(rows, 'heartrate')
            self.assertFalse(q['usable'])
            self.assertIn(reason, q['reasons'])
            self.assertIsNone(field_summary(rows, 'heartrate'))

    def test_valid_windows_explain_unusable_series(self):
        rows = ride()
        for row in rows[300:411]:
            row['heartrate'] = 'nan'
        evidence = matched_windows(rows, ['heartrate'])['fields']['heartrate']
        self.assertEqual(evidence['status'], 'usable')
        self.assertFalse(evidence['series_quality']['usable'])
        self.assertTrue(evidence['early_quality']['usable'])
        self.assertTrue(evidence['late_quality']['usable'])
        self.assertIn('both selected windows do', evidence['quality_note'])
        self.assertEqual(evidence['delta'], 10)

    def test_invalid_sensor_does_not_discard_valid_power(self):
        rows = ride()
        for row in rows[120:240]:
            row['heartrate'] = 'nan'
        result = matched_windows(rows, ['heartrate','respiration'])
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['fields']['heartrate']['status'], 'unavailable')
        self.assertEqual(result['fields']['respiration']['status'], 'usable')
        self.assertIsNotNone(summarize_rows(rows, ['watts'])['watts'])

    def test_invalid_clock_cannot_produce_drift(self):
        for kind in ['missing', 'duplicate', 'reverse']:
            rows = ride()
            if kind == 'missing':
                rows[2].pop('time')
            else:
                rows[2]['time'] = '1' if kind == 'duplicate' else '-1'
            result = matched_windows(rows, ['heartrate'])
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['fields'], {})

    def test_unmatched_power_or_cadence_is_not_compared(self):
        # Exactly two post-transition windows, with different workload.
        for field, value in [('watts','350'), ('cadence','120')]:
            rows = ride(duration=360)
            for row in rows[240:]:
                row[field] = value
            self.assertEqual(matched_windows(rows, ['heartrate'])['status'], 'unavailable')

    def test_transition_is_excluded_and_windows_are_reported(self):
        rows = ride(duration=360)
        for row in rows[:120]:
            row['heartrate'] = '180'
        result = matched_windows(rows, ['heartrate'])
        self.assertEqual(result['early']['start_s'], 120)
        self.assertEqual(result['late']['start_s'], 240)
        self.assertEqual(result['fields']['heartrate']['delta'], 0)

    def test_coasting_samples_are_not_stitched_into_work(self):
        rows = ride()
        for row in rows:
            if int(row['time']) % 60 < 30:
                row['watts'] = '0'
        self.assertEqual(matched_windows(rows, ['heartrate'])['status'], 'unavailable')

    def test_block_summary_exposes_windows_and_quality(self):
        result = summarize_block(ride(5), start_index=0, end_index=240, label='work')
        self.assertEqual(result['duration_seconds'], 1200)
        self.assertEqual(result['comparison']['status'], 'matched')
        self.assertEqual(result['drift']['heartrate'], 10)
        self.assertTrue(result['data_quality']['heartrate']['usable'])

    def test_missing_or_redundant_sensor_does_not_change_execution(self):
        results = []
        for extra in [False, True]:
            rows = ride()
            if not extra:
                for row in rows:
                    row.pop('tidal_volume_min')
                    row.pop('smo2')
                    row.pop('core_temperature')
            block = summarize_block(rows, start_index=0, end_index=len(rows), label='work')
            results.append(vt2_block_quality(rows, block, index=1, target_watts=290, anchor_watts=290))
        self.assertEqual(results[0]['execution_score'], results[1]['execution_score'])
        for result in results:
            self.assertEqual(result['verdict'], 'power_execution_controlled')
            self.assertNotIn('combined_score', result)
            self.assertNotIn('response_score', result['physiology'])
            self.assertNotIn('limiter_hints', result['physiology'])

    def test_no_physiology_does_not_become_good_response(self):
        rows = [dict(time=str(t), watts='290', cadence='90') for t in range(600)]
        block = summarize_block(rows, start_index=0, end_index=len(rows), label='work')
        result = vt2_block_quality(rows, block, index=1, target_watts=290, anchor_watts=290)
        self.assertEqual(result['comparison']['fields']['heartrate']['status'], 'unavailable')
        self.assertNotIn('hr_avg', result['physiology'])
        self.assertNotIn('response_score', result)

    def test_hr_recovery_window_is_seconds_not_samples(self):
        for step in [1,5]:
            rows = ride(step, duration=660)
            result = hr_recovery_after_block(rows, {'end_index':600//step})
            self.assertEqual(result['window_s'], 60)
            self.assertEqual(result['start_s'], 600)
            self.assertNotIn('recovery_score',result)

    def test_whole_pause_hr_drop_is_distinct_from_fixed_window(self):
        from activity_inspect import brief_recovery
        for step in [1, 5]:
            rows = ride(step, duration=900)
            for row in rows:
                t = int(row['time'])
                row['heartrate'] = str(160 if t < 600 else (140 if t < 630 else (150 if t < 660 else 100)))
            pause = summarize_block(rows, start_index=600//step, end_index=len(rows), label='RECOVERY')
            report = brief_recovery(pause, index=1, after_work_block=1, moxy_recovery=None)
            fixed = hr_recovery_after_block(rows, {'end_index':600//step})
            self.assertEqual(report['statistics_scope'], 'whole_recovery_block')
            self.assertEqual(report['hr_drop_scope'], 'start_to_minimum_over_whole_recovery_block')
            self.assertEqual((report['start_s'], report['end_s_exclusive'], report['duration_s']), (600, 900, 300))
            self.assertEqual(report['hr_drop_start_to_min'], 40)
            self.assertEqual(fixed['statistics_scope'], 'fixed_post_work_window')
            self.assertEqual((fixed['start_s'], fixed['end_s_exclusive'], fixed['window_s']), (600, 660, 60))
            self.assertEqual(fixed['drop_bpm'], 20)
            self.assertIn('not an endpoint HR difference', fixed['drop_definition'])

    def test_hot_indoor_session_is_not_automatically_costly(self):
        result = indoor_vt1_assessment(vt1_watts=215, rolling_60=[], moving_rows=ride(),
                                      pedaling_rows=ride(), stability={})
        self.assertEqual(result['verdict'], 'requires_physiological_synthesis')
        self.assertNotIn('rating', result)

    def test_separate_intervals_use_equivalent_elapsed_work(self):
        rows = ride(duration=1500)
        for row in rows:
            t = int(row['time'])
            if 600 <= t < 720:
                row['watts'] = '100'
        result = matched_windows(rows, ['heartrate'])
        self.assertEqual(result['work_phase_comparison'], 'equivalent_elapsed_work')
        self.assertLessEqual(abs(result['early']['elapsed_work_s']-result['late']['elapsed_work_s']), 60)

    def test_short_intervals_are_not_forced_into_steady_drift(self):
        rows = ride(duration=180)
        self.assertEqual(matched_windows(rows, ['heartrate'])['status'], 'unavailable')

    def test_trailing_empty_export_row_is_not_a_sample(self):
        from tempfile import TemporaryDirectory
        from analysis import load_streams_csv
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'streams.csv'
            path.write_text('time,watts\n0,200\n1,200\n,\n')
            rows = load_streams_csv(path)
            self.assertEqual(len(rows), 2)
            self.assertTrue(quality(rows, 'watts')['usable'])

    def test_report_consumers_use_mechanical_control_only(self):
        from analyze_indoor_activities import summarize_vt2, render_vt2_rows
        from analyze_outdoor_year import summarize_vt2 as outdoor_summary, render_rows
        rows = ride()
        work = summarize_block(rows, start_index=0, end_index=len(rows), label='work')
        block = vt2_block_quality(rows, work, index=1, target_watts=290, anchor_watts=290)
        vt2 = {'blocks': [block]}
        for summary, render in [(summarize_vt2(vt2, block), render_vt2_rows),
                                (outdoor_summary(vt2, block), lambda rows: render_rows(rows, mode='vt2'))]:
            self.assertNotIn('response_score', summary)
            report = render([{'date':'2026-10-17','name':'test','vt2':summary}])
            self.assertIn('power_execution_controlled', report)
            self.assertNotIn('Resp', report)


if __name__ == '__main__':
    unittest.main()
