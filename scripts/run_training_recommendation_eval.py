#!/usr/bin/env python3
"""Run fresh read-only Codex sessions on a prepared recommendation eval package."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--models', nargs='+', required=True)
    parser.add_argument('--cases', nargs='+', help='Optional case IDs for targeted reruns')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--effort', default='medium')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 1 or args.workers < 1: parser.error('repeats/workers must be positive')
    cli = shutil.which('codex')
    if not cli: parser.error('codex CLI is required')
    source = args.inputs.resolve(); out = args.output_dir.resolve()
    if out.exists(): parser.error('Choose a new output directory')
    manifest_path = source/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    selected = manifest['cases']
    if args.cases:
        unknown = set(args.cases) - {case['id'] for case in selected}
        if unknown: parser.error(f'Unknown case IDs: {sorted(unknown)}')
        selected = [case for case in selected if case['id'] in args.cases]
    # Fail before spending model calls if input/skill snapshots changed.
    for case in manifest['cases']:
        for name, expected in case['snapshot_files'].items():
            if digest(source/case['id']/name) != expected:
                parser.error(f"Input hash mismatch: {case['id']}/{name}")
    out.mkdir(parents=True)
    report = {'created_at':datetime.now(timezone.utc).isoformat(),
              'input_manifest_sha256':digest(manifest_path), 'reasoning_effort':args.effort,
              'review_status':'not_reviewed', 'runs':[]}
    jobs = [(model, case, repeat) for model in args.models for case in selected
            for repeat in range(1,args.repeats+1)]
    def run(job):
        model, case, repeat = job
        name = f"{model}-{case['id']}-{repeat}"
        folder = source/case['id']; answer = out/(name+'.txt'); events = out/(name+'.jsonl')
        command = [cli,'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check',
                   '--sandbox','read-only','--model',model,'-c',f'model_reasoning_effort="{args.effort}"',
                   '--cd',str(folder),'--json','--output-last-message',str(answer),'-']
        start=time.monotonic()
        result={'model':model,'case':case['id'],'repeat':repeat,'command':command,
                'answer':str(answer),'events':str(events)}
        try:
            with events.open('w') as stdout, (out/(name+'.stderr')).open('w') as stderr:
                proc=subprocess.run(command,input=(folder/'prompt.txt').read_text(),text=True,
                                    stdout=stdout,stderr=stderr,timeout=600)
            result.update(exit_code=proc.returncode,status='completed' if proc.returncode==0 and answer.is_file() else 'failed')
        except subprocess.TimeoutExpired:
            result.update(status='timeout')
        result['seconds']=round(time.monotonic()-start,1)
        if answer.is_file(): result['answer_sha256']=digest(answer)
        result['inputs_unchanged']=all(digest(folder/n)==h for n,h in case['snapshot_files'].items())
        print(name,result['status'],flush=True)
        return result
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(run,jobs):
            report['runs'].append(result)
            (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(out/'manifest.json')

if __name__=='__main__': main()
