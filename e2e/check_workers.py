#!/usr/bin/env python3
"""Verify horch check deduplication, one-slot batching, skips, exits and cleanup.

Uses existing authenticated workers without changing their flags or trust.
Creates one owned workspace and private isolated config/state outside the repo.
Only evidence.json is a sanitized receipt; retained config/state are private.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib

REPO = Path(__file__).resolve().parents[1]
HORCH = REPO / 'skills/herdr-orchestrator/scripts/horch.py'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Run:
    def __init__(self, args, workers):
        self.args, self.workers = args, workers
        self.root = Path(tempfile.mkdtemp(prefix='horch-check-', dir=args.output))
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_STATE_HOME=str(self.root / 'state'))
        self.config = self.root / 'config/herdr-orchestrator/workers.toml'
        self.store = self.root / 'state/herdr-orchestrator/tasks'
        self.workspace = None
        self.process = None
        self.assertions, self.observations = [], {}
        self.versions = {'python': sys.version.split()[0]}
        self.hashes = {'horch_sha256': sha(HORCH), 'driver_sha256': sha(Path(__file__))}
        self.started = time.monotonic()

    def sanitize(self, value):
        text = json.dumps(value, ensure_ascii=False)
        for path, replacement in ((str(self.root), '<run>'), (str(REPO), '<repo>'),
                                  (str(Path.home()), '<home>')):
            text = text.replace(path, replacement)
        return json.loads(text)

    def check(self, name, ok):
        self.assertions.append({'name': name, 'ok': bool(ok)})
        print(f'{"PASS" if ok else "FAIL"}: {name}', flush=True)
        if not ok:
            raise RuntimeError(name)

    def command(self, argv, timeout=30):
        return subprocess.run([str(a) for a in argv], env=self.env, cwd=self.args.cwd,
                              capture_output=True, text=True, timeout=timeout)

    def herdr(self, *argv):
        proc = self.command(['herdr', *argv])
        if proc.returncode:
            raise RuntimeError('herdr_command_failed')
        return json.loads(proc.stdout)['result']

    def cli(self, *argv, timeout=60):
        return self.command([sys.executable, HORCH, *argv], timeout)

    def rows(self, label, proc):
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.observations[label] = {'exit_code': proc.returncode, 'rows': [
            {k: (v[:400] if isinstance(v, str) else v) for k, v in row.items()
             if k in ('worker', 'task_id', 'state', 'ok', 'pane_id', 'seconds', 'message', 'error')}
            for row in rows]}
        return rows

    def records(self):
        # Invalid records are errors, never silently omitted from quota evidence.
        return {p.parent.name: read(p) for p in self.store.glob('t-*/task.json')}

    def panes(self):
        return {p['pane_id'] for p in self.herdr(
            'pane', 'list', '--workspace', self.workspace['workspace_id'])['panes']}

    def allocation(self):
        return set(self.records()), self.panes()

    def configure(self, limit):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        text = f'max_active_workers = {limit}\n'
        for name, spec in self.workers.items():
            text += '\n[workers.' + json.dumps(name) + ']\n'
            # The supported worker fields are strings and arrays of strings.
            text += ''.join(f'{json.dumps(k)} = {json.dumps(v)}\n' for k, v in spec.items())
        self.config.write_text(text, encoding='utf-8')
        parsed = tomllib.loads(self.config.read_text())
        if parsed != {'max_active_workers': limit, 'workers': self.workers}:
            raise RuntimeError('isolated_config_roundtrip_failed')

    def close_tasks(self):
        for task_id in self.records():
            if not read(self.store / task_id / 'state.json').get('closed'):
                proc = self.cli('close', task_id)
                if proc.returncode:
                    raise RuntimeError('owned_task_close_failed')

    def scenario(self):
        for tool in dict.fromkeys(['herdr', *(w['harness'] for w in self.workers.values())]):
            proc = self.command([tool, '--version'])
            self.versions[tool] = {'exit_code': proc.returncode,
                                   'output': (proc.stdout or proc.stderr).strip()[:300]}
        caller = self.herdr('pane', 'current', '--current')['pane']
        if any(not isinstance(caller.get(k), str) or not caller[k].strip()
               for k in ('workspace_id', 'tab_id', 'pane_id')):
            raise RuntimeError('invalid_live_caller_context')
        self.configure(1)
        result = self.herdr('workspace', 'create', '--cwd', str(self.args.cwd),
                            '--label', 'check-workers-e2e', '--no-focus',
                            '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                            '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'])
        self.workspace = result['workspace']
        self.env.update(HERDR_WORKSPACE_ID=self.workspace['workspace_id'],
                        HERDR_TAB_ID=result['tab']['tab_id'], HERDR_PANE_ID=result['root_pane']['pane_id'])
        baseline = self.panes()
        names = list(self.workers)
        selected = [names[0], *names]  # repeat first worker; unique count exceeds one-slot limit
        proc = self.cli('check', *selected, '--cwd', self.args.cwd,
                        '--max-seconds', self.args.max_seconds, timeout=self.args.max_seconds + 180)
        rows = self.rows('batch', proc)
        self.check('C001 check exits successfully', proc.returncode == 0)
        self.check('C002 selected workers deduplicated in order', [r.get('worker') for r in rows] == names)
        self.check('C003 all workers deliver done and ok', all(r.get('ok') is True and r.get('state') == 'done' for r in rows))
        records = self.records()
        self.check('C004 exactly one real task per unique selection', len(records) == len(names)
                   and {r.get('task_id') for r in rows} == set(records)
                   and all(records[r['task_id']]['worker'] == r['worker'] for r in rows))
        states = [read(self.store / t / 'state.json') for t in records]
        self.check('C005 every batch task closed and done', all(s.get('closed') is True and s.get('state') == 'done' for s in states))
        self.check('C006 check leaves exactly baseline panes', self.panes() == baseline)
        results = {t: read(self.store / t / 'result.json') for t in records}
        self.check('C007 matching completion identities', all(v.get('task_id') == t
                   and v.get('nonce') == records[t]['nonce'] and v.get('status') == 'completed'
                   for t, v in results.items()))
        self.check('C008 isolated tasks retain selected models and workspace', all(
            r.get('workspace_id') == self.workspace['workspace_id']
            and r.get('harness') == self.workers[r['worker']]['harness']
            and r.get('model') == self.workers[r['worker']]['model'] for r in records.values()))

        self.configure(0)
        before = self.allocation()
        proc = self.cli('check', *names, '--cwd', self.args.cwd)
        rows = self.rows('zero_slots', proc)
        fields = {'worker', 'task_id', 'state', 'ok', 'pane_id', 'seconds', 'message'}
        self.check('C010 zero slots report complete skip fields', proc.returncode == 0
                   and [r.get('worker') for r in rows] == names and all(fields <= set(r)
                   and r['state'] == 'not_checked' and r['ok'] is False and r['task_id'] is None
                   and r['pane_id'] is None and r['seconds'] is None
                   and 'no free worker slot' in r['message'] for r in rows))
        self.check('C011 zero slots allocate nothing', self.allocation() == before)

        self.configure(1)
        argv = [sys.executable, str(HORCH), 'check', names[0], '--cwd', str(self.args.cwd),
                '--max-seconds', str(self.args.max_seconds)]
        self.process = subprocess.Popen(argv, env=self.env, cwd=self.args.cwd,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        victim = None
        deadline = time.monotonic() + min(90, self.args.max_seconds)
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                for task_id, record in self.records().items():
                    if task_id in before[0]:
                        continue
                    state = read(self.store / task_id / 'state.json')
                    if state.get('state') == 'running' and state.get('saw_working') and not state.get('closed'):
                        victim = record
                        break
            except (FileNotFoundError, json.JSONDecodeError):
                pass  # publication race only; final reads remain strict
            if victim:
                break
            time.sleep(0.1)
        self.check('C020 exit probe reaches acknowledged worker', victim is not None)
        self.herdr('pane', 'close', victim['pane_id'])
        stdout, stderr = self.process.communicate(timeout=self.args.max_seconds + 180)
        proc = subprocess.CompletedProcess(argv, self.process.returncode, stdout, stderr)
        self.process = None
        rows = self.rows('injected_exit', proc)
        self.check('C021 worker exit has concrete diagnostic', proc.returncode == 0 and len(rows) == 1
                   and rows[0].get('task_id') == victim['task_id'] and rows[0].get('state') == 'exited'
                   and rows[0].get('ok') is False and 'gone' in str(rows[0].get('message')))
        self.check('C022 exit probe creates exactly one task', set(self.records()) - before[0] == {victim['task_id']})

        self.close_tasks()
        before = self.allocation()
        proc = self.cli('check', names[0], '--cwd', self.args.cwd, '--max-seconds', '0')
        rows = self.rows('exhausted_budget', proc)
        self.check('C030 exhausted budget skips with wait-limit reason', proc.returncode == 0 and len(rows) == 1
                   and rows[0].get('worker') == names[0] and rows[0].get('state') == 'not_checked'
                   and rows[0].get('ok') is False and 'wait limit' in str(rows[0].get('message')))
        self.check('C031 exhausted budget allocates nothing', self.allocation() == before)
        self.check('scenario complete', True)

    def cleanup(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()
        ok = True
        if self.workspace is not None:
            try:
                self.close_tasks()
                live = self.panes()
                self.check('C100 all owned worker panes removed',
                           all(r['pane_id'] not in live for r in self.records().values()))
            except Exception:
                ok = False
            try:
                self.herdr('workspace', 'close', self.workspace['workspace_id'])
                live = self.herdr('workspace', 'list')['workspaces']
                ok &= self.workspace['workspace_id'] not in {w['workspace_id'] for w in live}
            except Exception:
                ok = False
        self.assertions.append({'name': 'owned workspace cleanup confirmed', 'ok': ok})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='append', required=True,
                        help='existing authenticated worker; repeat for at least two distinct names')
    parser.add_argument('--cwd', type=Path, default=Path.cwd(), help='existing trusted checkout, read only')
    parser.add_argument('--output', type=Path, required=True, help='private artifact parent outside checkout')
    parser.add_argument('--max-seconds', type=int, default=300, help='per-check wait cap (positive)')
    args = parser.parse_args()
    if os.environ.get('HERDR_ENV') != '1' or not os.environ.get('HERDR_PANE_ID', '').strip():
        parser.error('run inside Herdr with a verified live caller pane ID')
    args.cwd = args.cwd.expanduser().resolve(strict=True)
    args.output = args.output.expanduser().resolve()
    names = list(dict.fromkeys(args.worker))
    if len(names) < 2 or args.max_seconds < 1 or not args.cwd.is_dir():
        parser.error('require two distinct workers, an existing cwd and a positive cap')
    if args.output == REPO or REPO in args.output.parents:
        parser.error('--output must be outside checkout')
    cfg = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'herdr-orchestrator/workers.toml'
    config_hash = sha(cfg)
    configured = tomllib.loads(cfg.read_text()).get('workers', {})
    if any(name not in configured for name in names):
        parser.error('every --worker must exist in workers.toml')
    workers = {name: configured[name] for name in names}
    args.output.mkdir(parents=True, exist_ok=True)
    run = Run(args, workers)
    print(f'Run directory: {run.root}', flush=True)
    problem = None
    try:
        run.scenario()
    except (Exception, KeyboardInterrupt) as exc:
        problem = type(exc).__name__  # no exception text or transcripts in receipt
    finally:
        run.cleanup()
        for name, condition in (
            ('real configuration unchanged', lambda: sha(cfg) == config_hash),
            ('verified sources unchanged', lambda: run.hashes == {
                'horch_sha256': sha(HORCH), 'driver_sha256': sha(Path(__file__))})):
            try:
                ok = condition()
            except OSError:
                ok = False
            run.assertions.append({'name': name, 'ok': ok})
        evidence = run.sanitize({
            'schema': 'horch/check-workers-e2e/v1',
            'verdict': 'pass' if problem is None and all(a['ok'] for a in run.assertions) else 'fail',
            'source_hashes': run.hashes, 'versions': run.versions,
            'workers': {n: {k: s.get(k) for k in ('harness', 'model', 'provider', 'effort')}
                        for n, s in workers.items()},
            'batch_limit': 1, 'selections': [names[0], *names],
            'rerun': ['python3', 'e2e/check_workers.py', *sum((['--worker', n] for n in names), []),
                      '--cwd', str(args.cwd), '--output', str(args.output), '--max-seconds', str(args.max_seconds)],
            'seconds': round(time.monotonic() - run.started, 3),
            'observations': run.observations, 'assertions': run.assertions, 'problem_category': problem})
        receipt = run.root / 'evidence.json'
        receipt.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        print(f'Evidence: {receipt}\nVerdict: {evidence["verdict"]}', flush=True)
    return 0 if evidence['verdict'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
