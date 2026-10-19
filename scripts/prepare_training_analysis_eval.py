#!/usr/bin/env python3
"""Prepare local evidence for manual, end-to-end training-analysis evaluations."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from analysis_packet import build_packet

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_case(directory, source, skill):
    """Copy an allowlisted raw dataset and local tools, never derived analyses."""
    activity = directory / 'activity'
    activity.mkdir()
    for name in ('activity.json', 'streams.csv'):
        shutil.copyfile(source / name, activity / name)
    local_skill = directory / '.agents/skills/training-analysis'
    shutil.copytree(skill, local_skill, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    scripts = directory / 'scripts'
    scripts.mkdir()
    for name in ('activity_inspect.py', 'analysis.py', 'physiological_evidence.py', 'outdoor_evidence.py', 'analysis_packet.py'):
        shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
    config = directory / 'config'
    config.mkdir()
    for name in ('coaching-preferences.md', 'practical-context.md'):
        shutil.copyfile(ROOT / 'config' / name, config / name)
    return activity, local_skill, scripts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New directory for isolated evaluation artifacts')
    parser.add_argument('--cases-file', type=Path, default=ROOT / 'evals/training-analysis/cases.json')
    parser.add_argument('--compact-packet', action='store_true', help='Start from scoped numeric evidence with a checkable answer contract')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    case_file = args.cases_file.resolve()
    cases = json.loads(case_file.read_text())['cases']
    skill = ROOT / '.agents/skills/training-analysis'
    sources = {}
    for case in cases:
        activity = ROOT / 'outputs/intervals/activities' / case['activity']
        for name in ['activity.json', 'streams.csv', *case.get('support_files', [])]:
            path = activity / name
            if not path.is_file():
                parser.error(f'Missing evaluation input: {path}')
            sources[str(path.relative_to(ROOT))] = digest(path)
    if output.exists():
        parser.error('Output directory already exists; choose a new run directory')
    output.mkdir(parents=True)
    manifest = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'preparing', 'model_runs': 'not_run',
        'cases_sha256': digest(case_file), 'sources': sources,
        'skill_files': {str(p.relative_to(ROOT)): digest(p) for p in sorted(skill.rglob('*')) if p.is_file()},
        'script_files': {str(p.relative_to(ROOT)): digest(p) for p in
                         [ROOT / 'scripts' / n for n in ['activity_inspect.py', 'analysis.py',
                                                       'physiological_evidence.py', 'outdoor_evidence.py', 'analysis_packet.py', 'prepare_training_analysis_eval.py']]},
        'cases': [],
    }
    manifest_path = output / 'manifest.json'
    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    save()
    try:
        for case in cases:
            directory = output / case['id']
            directory.mkdir()
            source = ROOT / 'outputs/intervals/activities' / case['activity']
            activity, local_skill, scripts = snapshot_case(directory, source, skill)
            for name in case.get('support_files', []):
                if Path(name).name != name:
                    raise ValueError('support_files must be simple file names')
                shutil.copyfile(source / name, activity / name)
            evidence = directory / 'inspection.json'
            extra_options = ['--garmin-json', str(activity / 'garmin-summary.json')] if 'garmin-summary.json' in case.get('support_files', []) else []
            command = [sys.executable, '-B', str(scripts / 'activity_inspect.py'),
                       str(activity), '--brief', *case['options'], *extra_options, '--output', str(evidence)]
            run = subprocess.run(command, cwd=directory, text=True, capture_output=True, timeout=180)
            (directory / 'inspection.log').write_text(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError(f"Inspection failed for {case['id']}; see inspection.log")
            result = json.loads(evidence.read_text())
            if any(key.startswith('beta_') for key in result):
                raise RuntimeError('Standard evaluation evidence unexpectedly contains beta diagnostics')
            prompt = (
                f'Bruk training-analysis-skillen i {local_skill / "SKILL.md"} til å analysere denne økten.\n\n'
                f'Lagret aktivitet: {activity}\nForberedt scriptanalyse: {evidence}\n\n'
                f'Supplerende kildefiler i activity/: {", ".join(case.get("support_files", [])) or "ingen"}.\n\n'
                f'{case["context"]}\n\n'
                'Gi en kort, begrunnet vurdering av gjennomføring, fysiologisk respons og '
                'hva økten betyr for videre trening. Les relevante skillreferanser og kontroller '
                'rådata når det trengs. Den eksplisitte testkonteksten gjelder foran personlig '
                'konfigurasjon; ikke fyll inn forhold som er oppgitt som ukjente. '
                f'Les kun testpakken under {directory}; ikke oppsøk originalrepoet, '
                'andre testpakker eller tidligere avledede analyser. Bruk inspection.json '
                'som gjeldende beregningsgrunnlag og activity/streams.csv til rådatakontroll. '
                'Dette er en lokal evaluering: ikke hent nye kildedata, endre plan-state eller '
                'skriv til eksterne tjenester. Skriv eventuelle analysefiler bare i en midlertidig mappe. '
                'Ikke les evalueringsrubrikken eller cases.json. Svar på norsk.\n'
            )
            if args.compact_packet:
                packet = build_packet(result)
                packet['inspection_sha256'] = digest(evidence)
                (directory / 'analysis-packet.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2)+'\n')
                prompt = prompt.replace(f'Forberedt scriptanalyse: {evidence}',
                    'Start med analysis-packet.json. Full inspection.json og rådata er tilgjengelig ved behov; ikke les hele detaljfilen rutinemessig.')
                prompt += (
                    '\nReturner bare gyldig JSON med statements (liste av {text, claims}) og '
                    'follow_up_question (ett relevant spørsmål eller null). Hver text er et vanlig norsk '
                    'avsnitt; samlet skal de være en kort analyse. Ved ukjent opplevelse spør om det '
                    'som kan endre vurderingen. Ved kjent opplevelse skal du bruke den uten å spørre på nytt. '
                    'Hver tallverdi i avsnittene skal ha en claim: {fact_id, scope, unit, display}. '
                    'Kopier fact_id og scope fra analysis-packet.json. display er selve tallstrengen '
                    'som brukes i teksten, med vanlig avrunding. Bruk tid i minutter eller timer '
                    'som ett desimaltall, ikke klokkeslettformat. Enhetskonvertering fra s til min/h '
                    'eller min til h/s er tillatt. Ikke gjett faktareferanser. Modellnavn som VT1/VT2 '
                    'trenger ikke tallreferanse. Begrens tallene til dem som underbygger konklusjonen. '
                    'Øvrige observasjoner kan uttrykkes uten tall og kontrolleres manuelt. '
                    'Tallkontrollen beviser ikke at tolkningen eller koblingen mellom tekst og fakta er riktig.\n'
                )
            (directory / 'prompt.txt').write_text(prompt)
            manifest['cases'].append({'id': case['id'], 'command': command,
                                      'snapshot_files': {str(p.relative_to(directory)): digest(p)
                                                         for p in directory.rglob('*') if p.is_file()},
                                      'evidence_sha256': digest(evidence),
                                      'prompt_sha256': digest(directory / 'prompt.txt'),
                                      'preparation': 'passed', 'model_evaluation': 'not_run'})
            save()
        manifest['status'] = 'prepared'
    except Exception as exc:
        manifest['status'] = 'failed'
        manifest['error'] = str(exc)
        save()
        raise
    save()
    print(manifest_path)


if __name__ == '__main__':
    main()
