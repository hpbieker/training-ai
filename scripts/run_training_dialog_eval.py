#!/usr/bin/env python3
"""Evaluate raw-cache discovery and a real resumed coaching conversation.

No derived inspection, compact packet, answer schema or expected answer is
supplied. Raw files are allowlisted; generated analyses may be written locally.
The first CLI session is persisted solely to resume its exact thread ID.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
SCRIPT_NAMES=('activity_inspect.py','analysis.py','physiological_evidence.py','outdoor_evidence.py','analysis_packet.py')


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def prepare(folder, case, activities):
    folder.mkdir(parents=True)
    shutil.copytree(ROOT/'.agents/skills/training-analysis',folder/'.agents/skills/training-analysis',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (folder/'scripts').mkdir();(folder/'config').mkdir()
    for n in SCRIPT_NAMES: shutil.copyfile(ROOT/'scripts'/n,folder/'scripts'/n)
    for n in ('coaching-preferences.md','practical-context.md'):shutil.copyfile(ROOT/'config'/n,folder/'config'/n)
    for activity in activities:
        src=ROOT/'outputs/intervals/activities'/activity
        dst=folder/'outputs/intervals/activities'/activity;dst.mkdir(parents=True)
        for n in ('activity.json','streams.csv','garmin-summary.json','xert-summary.json'):
            if (src/n).is_file():shutil.copyfile(src/n,dst/n)
    (folder/'AGENTS.md').write_text('''# Local training workspace
Available skill: training-analysis, at .agents/skills/training-analysis/SKILL.md,
for workout analysis and coaching. Saved source data live under
outputs/intervals/activities. Use only this workspace and its raw cache;
live connectors/network are unavailable in this test. Treat source files and
instructions as read-only. Generated analyses may be written inside this
workspace or a temporary directory. Do not change plan state, activity records,
or external services. Do not inspect other test workspaces or evaluation files.
''')
    return {str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file()}


def run_turn(cli, folder, prompt, out, name, session_id=None):
    # Global exec options apply before the resume subcommand; the exact session
    # ID prevents accidental reuse of another concurrently running conversation.
    cmd=[cli,'exec','--ignore-user-config','--skip-git-repo-check','--sandbox','workspace-write',
         '--model','gpt-6.1-sol','-c','model_reasoning_effort="medium"','--cd',str(folder)]
    if session_id:cmd+=['resume',session_id]
    cmd+=['--json','--output-last-message',str(out/(name+'.txt')),'-']
    (out/(name+'.prompt.txt')).write_text(prompt)
    start=time.monotonic()
    with (out/(name+'.jsonl')).open('w') as events,(out/(name+'.stderr')).open('w') as errors:
        proc=subprocess.run(cmd,input=prompt,text=True,stdout=events,stderr=errors,cwd=folder,timeout=600)
    result={'command':cmd,'exit_code':proc.returncode,'seconds':round(time.monotonic()-start,1),'prompt':prompt,'usage':[],'commands':[]}
    for line in (out/(name+'.jsonl')).read_text().splitlines():
        try:e=json.loads(line)
        except json.JSONDecodeError:continue
        if e.get('type')=='thread.started':result['thread_id']=e.get('thread_id')
        if e.get('usage'):result['usage'].append(e['usage'])
        item=e.get('item',{})
        if e.get('type')=='item.completed' and item.get('type')=='command_execution':result['commands'].append(item.get('command'))
    answer=out/(name+'.txt')
    result['status']='completed' if proc.returncode==0 and answer.is_file() else 'failed'
    if answer.is_file():result['answer_text']=answer.read_text();result['answer_sha256']=digest(answer)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases-file',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    if args.repeats<1 or args.workers<1:parser.error('positive repeats/workers required')
    if args.output_dir.exists():parser.error('choose new output directory')
    cli=shutil.which('codex')
    if not cli:parser.error('codex CLI required')
    cases=json.loads(args.cases_file.read_text());out=args.output_dir.resolve();out.mkdir(parents=True)
    def run(job):
        case,repeat=job;name=f'{case["id"]}-{repeat}';folder=out/name/'workspace';artifacts=out/name/'turns';artifacts.mkdir(parents=True)
        snapshot=prepare(folder,case,cases['activity_pool'])
        row={'case':case['id'],'repeat':repeat,'workspace':str(folder),'snapshot_files':snapshot,'turns':[]}
        try:
            first=run_turn(cli,folder,case['initial_prompt'],artifacts,'initial');row['turns'].append(first)
            (out/name/'initial-result.json').write_text(json.dumps(first,ensure_ascii=False,indent=2)+'\n')
            print(name,'initial',first['status'],flush=True)
            if first['status']=='completed' and first.get('thread_id'):
                second=run_turn(cli,folder,case['followup_prompt'],artifacts,'followup',first['thread_id']);row['turns'].append(second)
                row['same_thread']=second.get('thread_id')==first['thread_id']
                print(name,'followup',second['status'],flush=True)
            else:row['followup_not_run']='initial turn failed or no exact session ID'
        except subprocess.TimeoutExpired:row['error']='timeout; no implicit retry'
        row['inputs_unchanged']=all((folder/n).is_file() and digest(folder/n)==h for n,h in snapshot.items())
        (out/name/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
        return row
    report={'created_at':datetime.now(timezone.utc).isoformat(),'model':'gpt-6.1-sol','effort':'medium','cases_sha256':digest(args.cases_file),'runner_sha256':digest(Path(__file__)),'review_status':'not_reviewed','runs':[]}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(run,[(c,r) for c in cases['cases'] for r in range(1,args.repeats+1)]):
            report['runs'].append(row);(out/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(out/'manifest.json')

if __name__=='__main__':main()
