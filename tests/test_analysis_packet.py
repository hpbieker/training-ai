import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analysis_packet import build_packet,validate,temperature_context

class PacketTest(unittest.TestCase):
    def setUp(self):
        self.packet=build_packet({'activity':{'moving_min':302.2,'duration_min':384.5},'analysis_overview':{'variable_work_comparison':{'selected_window_count':2,'eligible_pair_count':4}}})
    def answer(self,display='302',fact='ride.moving',scope='whole_ride',unit='min'):
        return {'statements':[{'text':f'Bevegelsestiden var {display} minutter.','claims':[{'fact_id':fact,'scope':scope,'unit':unit,'display':display}]}],'follow_up_question':None}
    def test_time_overview_does_not_invent_moving_from_gaps(self):
        packet=build_packet({'activity':{'moving_min':100,'duration_min':180},
            'analysis_overview':{'recording_interruptions':[{'start_s':4000,'end_s':5800,'unrecorded_seconds':1800}]}})
        time=packet['time_overview']
        self.assertEqual(time['moving']['value'],100)
        self.assertEqual(time['elapsed']['value'],180)
        self.assertEqual(time['recording_gaps'][0]['unrecorded_seconds']['value'],1800)
        self.assertNotEqual(time['moving']['value'],180-1800/60)
    def test_missing_time_stays_unknown(self):
        packet=build_packet({'activity':{},'analysis_overview':{'strict_stable_comparison':{}}})
        self.assertIsNone(packet['time_overview']['moving'])
        self.assertIsNone(packet['time_overview']['elapsed'])
    def test_effort_duration_has_own_citable_fact(self):
        packet=build_packet({'activity':{},'analysis_overview':{'strict_stable_comparison':{}},
            'key_efforts':{'best_5m_power':{'avg':273,'window_seconds':300}}})
        answer=self.answer('5,0','effort.best_5m_power.duration','continuous_300s','min')
        answer['statements'][0]['text']='Beste sammenhengende 5,0 minutter.'
        self.assertTrue(validate(packet,answer)['passed'])
    def test_device_temperature_does_not_fill_absent_core(self):
        context=temperature_context({'streams':{'data_quality_issues':{
            'temp':{'present':100,'usable':False},'core_temperature':{'present':0,'usable':False}}},
            'outdoor_evidence':{'segments':[{'fields':{'temp':{'mean':30}}}]}})
        self.assertEqual(context['sources']['temp']['status'],'present')
        self.assertTrue(context['sources']['temp']['eligible_segments_available'])
        self.assertFalse(context['sources']['temp']['whole_record_quality']['usable'])
        self.assertEqual(context['sources']['core_temperature']['status'],'no_valid_values')
        self.assertFalse(context['sources']['core_temperature']['eligible_segments_available'])
    def test_temperature_unknown_and_ignored_are_distinct(self):
        context=temperature_context({'streams':{'ignored_fields':['core_temperature']}})
        self.assertEqual(context['sources']['temp']['status'],'unknown_in_compact_evidence')
        self.assertEqual(context['sources']['core_temperature']['status'],'ignored')
    def test_rounding(self):
        self.assertTrue(validate(self.packet,self.answer())['passed'])
    def test_wrong_moving_time(self):
        self.assertFalse(validate(self.packet,self.answer('202'))['passed'])
    def test_scope_cannot_be_substituted(self):
        self.assertFalse(validate(self.packet,self.answer(scope='window_1'))['passed'])
    def test_count_confusion(self):
        self.assertFalse(validate(self.packet,self.answer('4','comparison.selected_window_count','selected_window_count','count'))['passed'])
    def test_unit_conversion(self):
        self.assertTrue(validate(self.packet,self.answer('5.04',unit='h'))['passed'])
        self.assertFalse(validate(self.packet,self.answer('302',unit='W'))['passed'])
    def test_caller_training_power_is_not_promoted_to_verified_threshold(self):
        packet=build_packet({'activity':{},'analysis_overview':{'recording_interruptions':[]},
            'provenance':{'options':{'vt1_watts':215,'vt2_watts':295}}})
        fact=packet['facts']['anchor.vt1']
        self.assertEqual(fact['value'],215)
        self.assertEqual(fact['scope'],'caller_supplied_power_reference_not_verified_threshold')
        claimed=self.answer('215','anchor.vt1','physiological_anchor_not_prescription','W')
        self.assertFalse(validate(packet,claimed)['passed'])
        self.assertIn('configured training target',packet['reference_interpretation'])

    def test_unknown_anchor_not_filled(self):
        self.assertNotIn('anchor.vt1',self.packet['facts'])
        self.assertFalse(validate(self.packet,self.answer('215','anchor.vt1'))['passed'])
    def test_uncited_and_absent_display(self):
        a=self.answer();a['statements'][0]['text']+=' Puls var 140.'
        self.assertFalse(validate(self.packet,a)['passed'])
        a=self.answer();a['statements'][0]['text']='Lang tur.'
        self.assertFalse(validate(self.packet,a)['passed'])
    def test_null_fields_omitted(self):
        self.assertNotIn('ride.work',self.packet['facts'])
    def test_attached_units_require_citation(self):
        for text in ('Turen var 202min.', 'Effekten var 999W.'):
            self.assertFalse(validate(self.packet,{'statements':[{'text':text,'claims':[]}]})['passed'])
    def test_malformed_fact_id_fails_closed(self):
        self.assertFalse(validate(self.packet,self.answer(fact=[]))['passed'])
        self.assertFalse(validate(self.packet,self.answer(unit=[]))['passed'])
    def test_pc_scope_preserves_late_timing_without_inference(self):
        packet=build_packet({'activity':{},'analysis_overview':{'performance_condition':{
            'largest_peak_to_later_trough_drop':{'from':{'elapsed_seconds':18000,'value':0},'to':{'elapsed_seconds':19000,'value':-5}}}}})
        fact=packet['facts']['pc.to.elapsed_seconds']
        self.assertEqual(fact['value'],19000)
        self.assertEqual(fact['scope'],'largest_PC_fall')
    def test_empty_answer_rejected(self):
        self.assertFalse(validate(self.packet,{'statements':[]})['passed'])
    def test_prose_semantics_are_not_certified(self):
        a=self.answer();a['statements'][0]['text']='Du sov 302 minutter.'
        result=validate(self.packet,a)
        self.assertTrue(result['passed'])
        self.assertIn('Does not prove prose semantics',result['boundary'])

if __name__=='__main__': unittest.main()
