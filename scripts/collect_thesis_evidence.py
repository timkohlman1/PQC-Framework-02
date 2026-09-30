#!/usr/bin/env python3
"""Linux host driver: all framework work uses the established Docker wrappers.

plan is offline; run performs sequential gateway campaigns and isolated OTA tests.
Run again to resume. Reports never assert that all research questions are complete.
"""
from __future__ import annotations

import argparse
import codecs
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from framework.run_console import terminal_environment

ROOT = Path(__file__).resolve().parents[1]

TERMINAL = {'completed', 'completed_with_failures'}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def container_path(path):
    return '/workspace/' + Path(path).relative_to(ROOT).as_posix()


def run_command(command, log=None):
    """Stream normal framework progress. Preserve logs; do not set a lock timeout."""
    if log is None:
        return subprocess.call(command, cwd=ROOT)
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with Path(log).open('xb') as stream:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   env={**os.environ, **terminal_environment()})
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        try:
            while chunk := process.stdout.read1(4096):
                sys.stdout.write(decoder.decode(chunk))
                sys.stdout.flush()
                stream.write(chunk)
                stream.flush()
            sys.stdout.write(decoder.decode(b'', final=True))
            sys.stdout.flush()
            return process.wait()
        except KeyboardInterrupt:
            # The child retains the gateway lease until framework cleanup finishes.
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            # Keep draining the pipe while the child releases its lease and
            # records cleanup; waiting first can block on a full output pipe.
            while chunk := process.stdout.read1(4096):
                sys.stdout.write(decoder.decode(chunk))
                sys.stdout.flush()
                stream.write(chunk)
                stream.flush()
            sys.stdout.write(decoder.decode(b'', final=True))
            sys.stdout.flush()
            process.wait()
            raise


def helper(action, output, extra=()):
    return [str(ROOT/'scripts/dev.sh'), 'python', 'scripts/collect_thesis_evidence.py',
            '_internal', action, '--output', str(output.relative_to(ROOT)), *extra]


def campaign_manifest(output, name):
    candidates = sorted((output/'campaigns'/name).glob('*/campaign-manifest.json'))
    if len(candidates) > 1:
        raise ValueError('ambiguous campaign history for '+name)
    return candidates[0] if candidates else None


def campaign_verdict(path, returncode, expected_attempts=None):
    if path is None:
        return 'blocked', False, {'reason':'campaign_manifest_missing'}
    data = read(path)
    safe = data.get('cleanup', {}).get('status') == 'passed'
    state = data.get('state')
    final = data.get('final_index', {})
    payload = {k:v for k,v in data.items() if k != 'final_index'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    if state not in TERMINAL or final.get('status') != 'finalized' or final.get('sha256') != digest:
        return 'blocked', False, {'reason':'campaign_not_finalized_or_cleanup_failed', 'recorded_state':state}
    summary = data.get('summary', {})
    if expected_attempts is not None and summary.get('planned') != expected_attempts:
        return 'blocked', False, {'reason':'campaign_plan_count_mismatch'}
    if returncode not in (0,1) or not safe:
        return 'blocked', False, {'reason':'campaign_process_or_cleanup_failed', 'summary':summary}
    if summary.get('completed',0)+summary.get('failed',0)+summary.get('blocked',0) != summary.get('planned'):
        return 'blocked', False, {'reason':'campaign_attempt_count_mismatch'}
    # Retain failed/blocked attempts as attempts, never as successful measurements.
    verdict = 'completed' if state == 'completed' and returncode == 0 and not summary.get('failed') and not summary.get('blocked') else 'completed_with_failures'
    return verdict, True, summary


def ota_verdict(xml, returncode):
    if not xml.is_file():
        return 'blocked', {'reason':'missing_pytest_verdict'}
    cases = ET.parse(xml).getroot().findall('.//testcase')
    counts = {'collected':len(cases), 'failed':sum(c.find('failure') is not None for c in cases),
              'errors':sum(c.find('error') is not None for c in cases), 'skipped':sum(c.find('skipped') is not None for c in cases)}
    okay = returncode == 0 and len(cases) == 8 and not any(counts[k] for k in ('failed','errors','skipped'))
    return ('completed' if okay else 'completed_with_failures'), counts


def execute(output, retry_failed=False, runner=run_command):
    plan = read(output/'plan.json')
    path = output/'state.json'
    state = read(path) if path.exists() else {'schema':'pqc-thesis-collection-state', 'steps':{}, 'history':[]}
    if runner(helper('check',output)):
        return 2
    for step in plan['steps']:
        name = step['id']
        previous = state['steps'].get(name, {})
        if previous.get('status') in TERMINAL:
            if step['kind'] == 'campaign':
                saved = campaign_manifest(output,name)
                verdict,safe,_ = campaign_verdict(saved,previous['return_code'],step['attempts'])
            else:
                saved = output/previous['junit']
                verdict,_ = ota_verdict(saved,previous['return_code'])
                safe = True
            if not saved or not saved.is_file() or sha(saved) != previous.get('verdict_sha256') or not safe or verdict != previous['status']:
                raise ValueError('retained step verdict changed or disappeared: '+name)
        if previous.get('status') in TERMINAL and not (retry_failed and previous['status'] != 'completed'):
            print(name+': retained '+previous['status'], flush=True)
            continue
        if runner(helper('check',output)):
            return 2
        attempt = len([r for r in state['history'] if r['step'] == name]) + 1
        entry = {'step':name,'attempt':attempt,'status':'running','started_at':time.time()}
        state['history'].append(entry)
        state['steps'][name] = entry
        write(path,state)
        if step['kind'] == 'campaign':
            saved = campaign_manifest(output,name)
            command = [str(ROOT/'scripts/dev.sh'),'campaign-gateway']
            if saved:
                command += ['--resume',container_path(saved)]
            else:
                command += ['/workspace/'+step['source'],'--results-root',container_path(output/'campaigns'/name)]
        else:
            owned = output/'ota'/name/f'attempt-{attempt:04d}'
            owned.mkdir(parents=True,exist_ok=False)
            xml = owned/'junit.xml'
            command = [str(ROOT/'scripts/dev.sh'),'pytest-hardware',
                'tests/hardware/test_ota_dualbank_hw.py','-k','not request17',
                '--pqc-require-hardware','--pqc-test-results-root',container_path(owned),
                '--junitxml',container_path(xml),'-ra']
        entry['command'] = command
        write(path,state)
        try:
            rc = runner(command, output/'logs'/f'{name}-{attempt:04d}.log')
            entry['return_code'] = rc
            if step['kind'] == 'campaign':
                manifest = campaign_manifest(output,name)
                verdict, safe, details = campaign_verdict(manifest,rc,step['attempts'])
                entry['campaign_manifest'] = str(manifest.relative_to(output)) if manifest else None
                entry['verdict_sha256'] = sha(manifest) if manifest else None
            else:
                verdict, details = ota_verdict(xml,rc)
                entry['junit'] = str(xml.relative_to(output))
                entry['verdict_sha256'] = sha(xml) if xml.exists() else None
                # Do not automatically continue into another hardware action after an OTA failure.
                safe = verdict == 'completed'
            entry.update(status=verdict, details=details, finished_at=time.time())
            write(path,state)
            if not safe:
                print('Collection stopped; inspect retained failure/cleanup evidence before resuming.',flush=True)
                return 1
        except BaseException:
            entry.update(status='interrupted',finished_at=time.time())
            write(path,state)
            raise
    # The offline report uses only the collection's bounded roots, including failures.
    if runner(helper('report',output)):
        return 2
    return 1 if any(v['status'] != 'completed' for v in state['steps'].values()) else 0


def main(argv=None):
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] == ['_internal']:
        from framework.thesis_collection import main as internal
        return internal(args_list[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan','run','report','status'])
    parser.add_argument('--output', required=True, type=Path, help='collection directory under results/')
    parser.add_argument('--repetitions', type=int, default=None, help='plan only; reset attempts per condition, default 10')
    parser.add_argument('--only', nargs='+', help='plan only; selected campaign IDs (OTA also included unless --skip-ota)')
    parser.add_argument('--skip-ota', action='store_true', help='plan only; omit lifecycle scenarios explicitly')
    parser.add_argument('--retry-failed', action='store_true', help='run only; append attempts for failed terminal steps')
    parser.add_argument('--reanalyze', action='store_true', help='report only; preserve captures and record a new analysis source revision')
    args = parser.parse_args(args_list)
    if args.reanalyze and args.action != 'report':
        parser.error('--reanalyze requires report')
    output = Path(os.path.abspath(ROOT/args.output))
    if not output.is_relative_to(ROOT/'results') or output == ROOT/'results' or any(p.is_symlink() for p in [output,*output.parents]):
        parser.error('output must be a non-symlink directory below results/')
    if args.action != 'plan' and (args.repetitions is not None or args.only or args.skip_ota):
        parser.error('collection choices are frozen by plan; these options are plan-only')
    if args.retry_failed and args.action != 'run':
        parser.error('--retry-failed requires run')
    try:
        if args.action == 'plan':
            extra = ['--repetitions',str(10 if args.repetitions is None else args.repetitions)]
            if args.only: extra += ['--only',*args.only]
            if args.skip_ota: extra += ['--skip-ota']
            return run_command(helper('plan',output,extra))
        if not (output/'plan.json').is_file():
            parser.error('create this collection with plan first')
        if args.action == 'status':
            plan = read(output/'plan.json')
            state = read(output/'state.json') if (output/'state.json').exists() else {'steps':{}}
            print(json.dumps({'planned_campaign_attempts':plan['planned_campaign_attempts'],
                'steps':{s['id']:state['steps'].get(s['id'],{}).get('status','pending') for s in plan['steps']},
                'limitations':plan['limitations']},indent=2))
            return 0
        # Lock is local to this collection. Every hardware subprocess separately
        # acquires the established gateway lease through dev.sh.
        with (output/'collection.lock').open('a') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('this collection is already in use')
            if args.action == 'report':
                return run_command(helper('report',output,['--reanalyze'] if args.reanalyze else []))
            return execute(output,args.retry_failed)
    except KeyboardInterrupt:
        print('Interrupted; evidence retained. Repeat run to resume.',file=sys.stderr)
        return 130
    except (ValueError,OSError,KeyError,ET.ParseError) as exc:
        print('Thesis collection: '+str(exc),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
