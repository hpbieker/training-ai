#!/usr/bin/env python3
"""Prepare local evidence for manual, end-to-end training-analysis evaluations."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New directory for isolated evaluation artifacts')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    case_file = ROOT / 'evals/training-analysis/cases.json'
    cases = json.loads(case_file.read_text())['cases']
    skill = ROOT / '.agents/skills/training-analysis'
    sources = {}
    for case in cases:
        activity = ROOT / 'outputs/intervals/activities' / case['activity']
        for name in ['activity.json', 'streams.csv']:
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
                                                       'physiological_evidence.py', 'prepare_training_analysis_eval.py']]},
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
            activity = ROOT / 'outputs/intervals/activities' / case['activity']
            evidence = directory / 'inspection.json'
            command = [sys.executable, '-B', str(ROOT / 'scripts/activity_inspect.py'),
                       str(activity), '--brief', *case['options'], '--output', str(evidence)]
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
            (directory / 'inspection.log').write_text(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError(f"Inspection failed for {case['id']}; see inspection.log")
            result = json.loads(evidence.read_text())
            if any(key.startswith('beta_') for key in result):
                raise RuntimeError('Standard evaluation evidence unexpectedly contains beta diagnostics')
            prompt = (
                f'Bruk training-analysis-skillen i {skill / "SKILL.md"} til å analysere denne økten.\n\n'
                f'Lagret aktivitet: {activity}\nForberedt scriptanalyse: {evidence}\n\n'
                f'{case["context"]}\n\n'
                'Gi en kort, begrunnet vurdering av gjennomføring, fysiologisk respons og '
                'hva økten betyr for videre trening. Les relevante skillreferanser og kontroller '
                'rådata når det trengs. Den eksplisitte testkonteksten gjelder foran personlig '
                'konfigurasjon; ikke fyll inn forhold som er oppgitt som ukjente. '
                'Dette er en lokal evaluering: ikke hent nye kildedata, endre plan-state eller '
                'skriv til eksterne tjenester. Skriv eventuelle analysefiler bare i en midlertidig mappe. '
                'Ikke les evalueringsrubrikken eller cases.json. Svar på norsk.\n'
            )
            (directory / 'prompt.txt').write_text(prompt)
            manifest['cases'].append({'id': case['id'], 'command': command,
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
