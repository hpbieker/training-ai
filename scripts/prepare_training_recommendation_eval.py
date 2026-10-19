#!/usr/bin/env python3
"""Prepare isolated, offline recommendation-composition model evaluations."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

from recommend_training import (recommendation_bias, select_intensity_domain,
    apply_xert_endurance_duration_solution, apply_quality_workout_vt1_composition,
    build_primary_decision)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / 'evals/training-analysis/recommendations'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_packet(case):
    inputs = {'wellness': case['wellness'], 'xert_recovery': {
        'projected_recovery_hours_at_planned_time': {'low': -12, 'high': -24, 'peak': -24}},
        'intervals_wellness_events': {'current_day_soreness': case['soreness']}}
    ceiling = recommendation_bias(wellness=inputs['wellness'], xert=inputs['xert_recovery'],
                                  intervals_events=inputs['intervals_wellness_events'])
    decision = select_intensity_domain(day='2026-10-18', readiness_ceiling=ceiling,
        intensity_goal=case['goal'], progression_advice={}, plan_progression={'vt2': {
            'anchor':'3 x 28 min @ 295 W', 'status':'hold',
            'next_step':'Repeat achieved dose when current response permits; do not increase watts.'}})
    quality = decision['selected_domain'] == 'vt2'
    target = {'source':'xert_training_advice_remaining_xss','target_minutes':0,
              'target_load':260, 'xert_recommended_target_xss':{'low':260,'high':4.9,'peak':0.2}}
    solution = json.loads((SUITE / 'fixtures' / ('quality-plus-endurance.json' if quality else 'endurance.json')).read_text())
    apply_xert_endurance_duration_solution(target, calculation=solution, selected_intensity=decision['selected_domain'])
    if quality:
        apply_quality_workout_vt1_composition(target,
            quality_calculation=json.loads((SUITE/'fixtures/quality.json').read_text()),
            selected_intensity='vt2')
    packet = {'date':'2026-10-18','planned_at':case['planned_at'],
        'scenario_context':case['context'], 'readiness':{'recommendation_inputs':inputs},
        'target_resolution':target,
        'primary_decision':build_primary_decision(readiness_packet={'recommendation_inputs':inputs},
            target_resolution=target,intensity_decision=decision),
        'plan_context':{'plan_name':'Test: durable VT2 with aerobic support',
            'next_role':case['goal'], 'next_day_role':'easy_aerobic',
            'recent_response':'Three days ago:2x30@295, stopped after second due to difficult late breathing; previous achieved3x28 retained. Yesterday aerobic spacing completed.',
            'volume_density':'Projected14/21day density12.8/12.5hours/week; target15-17 is diagnostic, no catch-up quota.'},
        'capacity':{'as_of':case['planned_at'],'fresh_at':'2026-10-19T09:15:00+02:00',
            'workout_capacity_xss':{'low':349.2855,'high':15.4379,'peak':2.8647},
            'same_structure_max_seconds':17431 if quality else json.loads((SUITE/'fixtures/endurance-capacity.json').read_text())['duration_seconds'],
            'meaning':'Frozen test evidence; independent capacities, no intervening training. This is a model ceiling, not the prescribed dose.'},
        'logistics':{'location':'Test location with indoor and outdoor cycling',
            'setup_minutes':15,'cleanup_minutes':15,'earliest_start':'09:00',
            'calendar':'No fixed events after selected start; dinner17:00-17:45 movable.',
            'weather':'Outdoor route -2C at09, dry, warming later; indoor equipment available.'},
        'fueling_test_values':{'drink_carbs_g_per_bottle':60,'bottle_ml':1000,
            'candy_carbs_g_per_piece':5,'target_carbs_g_per_hour':[60,80],
            'meaning':'Explicit synthetic product values for this test, not verified product facts or permanent preferences.'},
        'outdoor_alternative':{'role':'vt1','route':'Synthetic paved steady loop','reference_minutes':205.2,
            'prescribed_total_seconds':14729,'main_power_w':215,'warmup_seconds':720,'cooldown_seconds':180,
            'meaning':'Calculated constant-power duration; actual outdoor XSS is not guaranteed.'}}
    return packet


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(); out=args.output_dir.resolve()
    if out.exists(): parser.error('Choose a new output directory')
    cases=json.loads((SUITE/'cases.json').read_text())['cases']
    out.mkdir(parents=True)
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'model_runs':'not_run',
              'scope':'Offline post-calculation coaching; does not test live acquisition or full CLI orchestration.',
              'cases_sha256':digest(SUITE/'cases.json'),
              'generator_sha256':digest(Path(__file__)),
              'helper_sha256':digest(ROOT/'scripts/recommend_training.py'),
              'fixtures':{p.name:digest(p) for p in sorted((SUITE/'fixtures').glob('*.json'))},'cases':[]}
    for case in cases:
        folder=out/case['id'];folder.mkdir()
        shutil.copytree(ROOT/'.agents/skills/training-analysis',folder/'skill',
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        (folder/'packet.json').write_text(json.dumps(build_packet(case),ensure_ascii=False,indent=2)+'\n')
        prompt=('Bruk skill/SKILL.md og relevante referanser til å skrive et treningsforslag på norsk fra packet.json. '
                'Dette er en frakoblet evaluering av anbefalingen ETTER kildeinnhenting og beregning. '
                'Bruk den vedlagte ferdigberegnede pakken som testgrunnlag; ikke kjør live-workflowen, '
                'hent nye data, les originalrepoet eller andre mapper, eller endre filer. '
                'Testkonteksten i pakken overstyrer personlige standarder og dagens faktiske dato. '
                'Alle tider og produktverdier er eksplisitte scenariodata. '
                'Gi et praktisk, begrunnet treningsforslag med nødvendige forbehold og alternativer. '
                'Du har kun lesetilgang til denne testmappen; svar i chat.\n')
        (folder/'prompt.txt').write_text(prompt)
        manifest['cases'].append({'id':case['id'],'snapshot_files':{
            str(p.relative_to(folder)):digest(p) for p in sorted(folder.rglob('*')) if p.is_file()}})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(out/'manifest.json')

if __name__=='__main__':main()
