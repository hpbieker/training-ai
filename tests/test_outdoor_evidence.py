import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from outdoor_evidence import outdoor_evidence
from activity_inspect import outdoor_analysis_overview


def row(t,p=200,hr=130):
    return {'time':t,'watts':p,'cadence':85,'heartrate':hr,'velocity_smooth':8,'distance':t*8}


class OutdoorEvidenceTests(unittest.TestCase):
    def test_overview_distinguishes_selected_pair_and_strict_unavailability(self):
        e=outdoor_evidence([row(t) for t in range(7200)])
        summary=outdoor_analysis_overview({'outdoor_evidence':e,'total':{'comparison':{'status':'unavailable'}},
            'outdoor_vt1_pacing':{'rolling_power_cap_compliance':{'60s':{'225':{'time_over_pedaling':{'min':88.4,'pct':32.8}}}}}})
        self.assertEqual(summary['strict_stable_comparison']['status'],'unavailable')
        self.assertEqual(summary['variable_work_comparison']['selected_window_count'],2)
        self.assertGreater(summary['variable_work_comparison']['eligible_pair_count'],1)
        self.assertEqual(summary['power_exposure_60s_mean'][0]['threshold_w'],225)

    def test_pause_does_not_add_work_or_suppress_valid_segments(self):
        rows = [row(t) for t in range(600)] + [row(t) for t in range(4200,4800)]
        r = outdoor_evidence(rows)
        self.assertEqual(r['observed_work_kj'],240)
        self.assertEqual(r['recorded_seconds'],1200)
        self.assertEqual(r['interruptions'][0]['unrecorded_seconds'],3600)
        self.assertEqual(len(r['segments']),2)
        self.assertTrue(all(x['fields']['heartrate']['mean']==130 for x in r['segments']))

    def test_matching_is_mechanical_and_reports_eligible_response_only(self):
        rows=[row(t,200,130 if t<3600 else 145) for t in range(7200)]
        for r in rows:
            r['smo2']=None
        c=outdoor_evidence(rows)['variable_work_comparison']
        self.assertEqual(c['status'],'descriptive_match')
        self.assertEqual(c['late_minus_early']['heartrate'],15)
        self.assertNotIn('smo2',c['late_minus_early'])

    def test_equal_average_different_work_distribution_is_not_match(self):
        rows=[row(t,200 if t<1800 else (100 if t%2 else 300)) for t in range(7200)]
        # Restrict to two short sections so pairs cannot come from the same regime.
        rows=rows[:600]+rows[-600:]
        self.assertEqual(outdoor_evidence(rows)['variable_work_comparison']['status'],'unavailable')

    def test_ignored_power_and_hr_are_not_reintroduced(self):
        r=outdoor_evidence([row(t) for t in range(7200)],fields=['cadence'])
        self.assertIsNone(r['observed_work_kj'])
        self.assertIsNone(r['segments'][0]['observed_work_before_kj'])
        self.assertTrue(r['work_is_partial'])
        self.assertNotIn('heartrate',r['segments'][0]['fields'])
        self.assertEqual(r['variable_work_comparison']['candidate_windows'],0)

    def test_absent_power_is_unknown_but_measured_zero_is_zero(self):
        missing=outdoor_evidence([row(t,p=None) for t in range(600)])
        zero=outdoor_evidence([row(t,p=0) for t in range(600)])
        self.assertIsNone(missing['observed_work_kj'])
        self.assertIsNone(missing['segments'][0]['observed_work_kj'])
        self.assertIsNone(missing['segments'][0]['observed_work_before_kj'])
        self.assertEqual(zero['observed_work_kj'],0)
    def test_sparse_sampling_integrates_seconds_not_rows(self):
        a=outdoor_evidence([row(t) for t in range(600)])
        b=outdoor_evidence([row(t) for t in range(0,600,2)])
        self.assertEqual(a['observed_work_kj'],b['observed_work_kj'])
        self.assertEqual(b['recorded_seconds'],600)

    def test_window_selection_is_independent_of_response_direction(self):
        rows=[row(t,200,120+t/1000) for t in range(7200)]
        before=outdoor_evidence(rows)['variable_work_comparison']
        for r in rows:
            r['heartrate']=180-r['time']/1000
        after=outdoor_evidence(rows)['variable_work_comparison']
        self.assertEqual(before['early']['start_s'],after['early']['start_s'])
        self.assertEqual(before['late']['start_s'],after['late']['start_s'])
        self.assertGreater(before['late_minus_early']['heartrate'],0)
        self.assertLess(after['late_minus_early']['heartrate'],0)


if __name__=='__main__': unittest.main()
