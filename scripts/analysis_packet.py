#!/usr/bin/env python3
"""Build a small outdoor evidence packet; validate declared numeric claims.

Validation checks citation/value/unit/scope consistency, not prose meaning or
physiological correctness. Detailed evidence remains available on demand.

Answer contract (all numeric literals in statement text need a citation):
{"statements": [{"text": "Bevegelsestiden var 302 minutter.", "claims": [
 {"fact_id": "ride.moving", "scope": "whole_ride", "unit": "min", "display": "302"}
]}], "follow_up_question": null}
Do not present the audit structure as the coaching answer; render its text only
following numeric and semantic review.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def temperature_context(data):
    """Expose source meaning separately from whole-record and segment quality."""
    meanings = {
        'temp': 'device temperature; environmental proxy, not core or confirmed shaded air temperature',
        'core_temperature': 'wearable estimate of body-core temperature, not direct invasive measurement',
        'skin_temperature': 'local skin temperature, not body-core temperature',
    }
    issues = data.get('streams', {}).get('data_quality_issues', {})
    ignored = data.get('streams', {}).get('ignored_fields', [])
    segments = data.get('outdoor_evidence', {}).get('segments', [])
    sources = {}
    for field, meaning in meanings.items():
        quality = issues.get(field, {})
        eligible = any(seg.get('fields', {}).get(field, {}).get('mean') is not None for seg in segments)
        if field in ignored:
            status = 'ignored'
        elif quality.get('present') == 0:
            status = 'no_valid_values'
        elif quality.get('present', 0) > 0 or eligible:
            status = 'present'
        else:
            status = 'unknown_in_compact_evidence'
        sources[field] = {'status': status, 'meaning': meaning,
            'eligible_segments_available': eligible and status not in ('ignored', 'no_valid_values'),
            'whole_record_quality': quality or None,
            'detail_path': 'outdoor_evidence.segments[].fields.'+field}
    return {'sources': sources,
            'interpretation': 'Identify the source when using a temperature trend. Device temperature cannot substitute for absent core estimates. Presence does not establish thermal limitation; inspect segment quality and sensor context.'}


def build_packet(data):
    overview = data.get('analysis_overview')
    if not overview:
        raise ValueError('Outdoor analysis_overview required')
    facts = {}
    def add(key, value, unit, scope, path):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            facts[key] = dict(value=value, unit=unit, scope=scope, source_path=path)
    for key, field in [('moving', 'moving_min'), ('elapsed', 'duration_min')]:
        add('ride.'+key, data['activity'].get(field), 'min', 'whole_ride', 'activity.'+field)
    outdoor = data.get('outdoor_evidence', {})
    add('ride.work', outdoor.get('observed_work_kj'), 'kJ', 'observed_recording', 'outdoor_evidence.observed_work_kj')
    for anchor in ('vt1', 'vt2'):
        add('anchor.'+anchor, data.get('provenance', {}).get('options', {}).get(anchor+'_watts'), 'W', 'caller_supplied_power_reference_not_verified_threshold', 'provenance.options.'+anchor+'_watts')
    for key, effort in data.get('key_efforts', {}).items():
        if key.endswith('_power'):
            scope='continuous_'+str(effort['window_seconds'])+'s'
            add('effort.'+key, effort.get('avg'), 'W', scope, 'key_efforts.'+key+'.avg')
            add('effort.'+key+'.duration', effort.get('window_seconds'), 's', scope, 'key_efforts.'+key+'.window_seconds')
    for i, gap in enumerate(overview.get('recording_interruptions', [])):
        for field in ('start_s', 'end_s', 'unrecorded_seconds'):
            add(f'gap.{i}.{field}', gap.get(field), 's', f'recording_gap_{i}', f'analysis_overview.recording_interruptions.{i}.{field}')
    for i, row in enumerate(overview.get('power_exposure_60s_mean', [])):
        scope=f'pedaling_60s_mean_above_{row["threshold_w"]}W'
        for field, unit in [('threshold_w','W'), ('minutes_over_during_pedaling','min'), ('percent_of_pedaling','%')]:
            add(f'exposure.{i}.{field}', row.get(field), unit, scope, f'analysis_overview.power_exposure_60s_mean.{i}.{field}')
    comparison = overview.get('variable_work_comparison', {})
    for field in ('selected_window_count', 'eligible_pair_count'):
        add('comparison.'+field, comparison.get(field), 'count', field, 'analysis_overview.variable_work_comparison.'+field)
    units={'watts':'W','heartrate':'bpm','cadence':'rpm','respiration':'breaths/min','tidal_volume':'source_volume','tidal_volume_min':'source_ventilation','core_temperature':'C','smo2':'%','temp':'C'}
    windows=[]
    for i, window in enumerate(comparison.get('selected_windows', [])):
        scope=f'variable_window_{i}'
        windows.append({k:window.get(k) for k in ('position','unavailable_fields','mechanics')})
        for field, unit in [('start_s','s'),('end_s_exclusive','s'),('observed_work_before_kj','kJ')]:
            add(f'window.{i}.{field}', window.get(field), unit, scope, f'analysis_overview.variable_work_comparison.selected_windows.{i}.{field}')
        for field,value in window.get('means', {}).items():
            add(f'window.{i}.{field}', value, units.get(field,'source_units'), scope, f'analysis_overview.variable_work_comparison.selected_windows.{i}.means.{field}')
    pc=overview.get('performance_condition') or {}
    drop=pc.get('largest_peak_to_later_trough_drop') or {}
    for side in ('from','to'):
        for field,unit in [('elapsed_seconds','s'),('value','score')]:
            add(f'pc.{side}.{field}', drop.get(side,{}).get(field),unit,'largest_PC_fall',f'analysis_overview.performance_condition.largest_peak_to_later_trough_drop.{side}.{field}')
    return {'schema_version':1,'reference_interpretation': 'Power options are caller-supplied references, not independently verified physiological thresholds. A configured training target does not establish VT1/VT2. Exposure cutoffs describe measured power only; require dated source evidence before interpreting threshold crossings.', 'activity':{k:data['activity'].get(k) for k in ('id','name','type')},
            'workload_interpretation': 'With usable power, prioritize measured work, duration and power distribution. Do not add climbing as a separate energetic load on top of measured work. Terrain is optional context when it explains cadence, coasting, posture or cooling beyond power; omission of elevation alone is not a defect.',
            'temperature_context': temperature_context(data),
            'time_overview': {
                'moving': facts.get('ride.moving'),
                'elapsed': facts.get('ride.elapsed'),
                'recording_gaps': [
                    {field: facts.get(f'gap.{i}.{field}') for field in ('start_s','end_s','unrecorded_seconds')}
                    for i, _ in enumerate(overview.get('recording_interruptions', []))],
                'citation_ids': {'moving':'ride.moving','elapsed':'ride.elapsed','gaps':'gap.<index>.<field>'},
                'meaning': 'Moving duration and elapsed start-to-finish duration are distinct. Recording gaps are unobserved intervals and need not coincide with non-moving duration. These measures need not reconcile: do not infer moving time or leftover stationary time by subtracting gaps.',
                'reporting': 'When interruptions materially affect the ride, state moving and elapsed duration together and explain the interruption.'},
            'completion_review': [
                'Does the verdict assess the established purpose, rather than infer a prescription from anchors?',
                'Does it explain this ride through relevant workload and qualified physiological response?',
                'Does it use the athlete report and preserve unknown recovery/intake where material?',
                'Are material timing differences, interruptions and sensor limits accounted for?',
                'Does the next-training consequence follow from the evidence without invented causes or progression?'
            ],
            'facts':facts,'comparison':{'strict_status':overview.get('strict_stable_comparison',{}).get('status'),
                'variable_status':comparison.get('status'),'scope':comparison.get('scope'),'windows':windows},
            'limits':overview.get('interpretation_limits',[])+[
                'Later selected window is not necessarily the finish; times are elapsed from start.',
                'Clock interruptions and sensor-specific loss are different.',
                'Narrative athlete experience is evidence; missing numeric RPE does not erase it.',
                'No causal diagnosis or recovery duration follows from these facts.'],
            'detail_files':['inspection.json','activity/activity.json','activity/streams.csv'],
            'validation_boundary':'Numeric citation consistency only; prose meaning and coaching need manual review.'}


NUMBER=re.compile(r'(?<![\w])[-+]?\d+(?:[.,]\d+)?')


def validate(packet, answer):
    errors=[]; count=0
    statements=answer.get('statements') if isinstance(answer,dict) else None
    if not isinstance(statements,list) or not statements:
        return {'passed':False,'errors':['statements must be a nonempty list'],'checked_claims':0}
    for i, statement in enumerate(statements):
        if not isinstance(statement,dict) or not isinstance(statement.get('text'),str) or not isinstance(statement.get('claims'),list):
            errors.append(f'{i}: invalid statement schema');continue
        text=statement['text']; covered=[]
        for claim in statement['claims']:
            count+=1
            if not isinstance(claim,dict): errors.append(f'{i}: invalid claim');continue
            fact_id=claim.get('fact_id')
            if not isinstance(fact_id,str): errors.append(f'{i}: invalid fact_id');continue
            fact=packet['facts'].get(fact_id)
            if fact is None: errors.append(f'{i}: unknown fact');continue
            if claim.get('scope')!=fact['scope']: errors.append(f'{i}: scope mismatch')
            value=fact['value']; unit=claim.get('unit')
            if not isinstance(unit,str): errors.append(f'{i}: invalid unit');continue
            if unit!=fact['unit']:
                factor={('s','min'):1/60,('min','s'):60,('min','h'):1/60,('s','h'):1/3600}.get((fact['unit'],unit))
                if factor is None: errors.append(f'{i}: unit mismatch');continue
                value*=factor
            display=claim.get('display','')
            if not isinstance(display,str) or not re.fullmatch(r'-?\d+(?:[.,]\d+)?',display):
                errors.append(f'{i}: display must be one numeric literal');continue
            decimals=len(re.split('[.,]',display)[1]) if re.search('[.,]',display) else 0
            if abs(float(display.replace(',','.'))-value)>0.5*10**(-decimals)+1e-8:
                errors.append(f'{i}: value mismatch for {claim.get("fact_id")}')
            matches=[m for m in NUMBER.finditer(text) if m.group()==display]
            if not matches: errors.append(f'{i}: display absent from text')
            covered.extend(m.span() for m in matches)
        for match in NUMBER.finditer(text):
            if match.span() not in covered: errors.append(f'{i}: uncited numeric literal {match.group()}')
    question=answer.get('follow_up_question')
    if question is not None and not isinstance(question,str): errors.append('invalid follow_up_question')
    return {'passed':not errors,'errors':errors,'checked_claims':count,
            'boundary':'Declared numeric citations only. Does not prove prose semantics, completeness, or physiology.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inspection',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--answer',type=Path)
    args=parser.parse_args()
    data=json.loads(args.inspection.read_text());packet=build_packet(data)
    packet['inspection_sha256']=hashlib.sha256(args.inspection.read_bytes()).hexdigest()
    result=validate(packet,json.loads(args.answer.read_text())) if args.answer else packet
    rendered=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output: args.output.write_text(rendered)
    else: print(rendered,end='')
    if args.answer and not result['passed']: raise SystemExit(1)

if __name__=='__main__': main()
