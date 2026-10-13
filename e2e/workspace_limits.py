#!/usr/bin/env python3
"""Verify workspace quotas with real Herdr and one configured model worker.

Creates two owned workspaces, shares an isolated task store, and retains a
rerunnable receipt outside the checkout. Never changes worker auth or trust.
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

HORCH = Path(__file__).resolve().parents[1] / 'skills/herdr-orchestrator/scripts/horch.py'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Run:
    def __init__(self, args, worker):
        self.args = args
        self.worker = worker
        self.root = Path(tempfile.mkdtemp(prefix='horch-workspace-limits-', dir=args.output))
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_STATE_HOME=str(self.root / 'state'))
        self.store = self.root / 'state/herdr-orchestrator/tasks'
        self.workspaces = {}
        self.tasks = []
        self.assertions = []
        self.observations = {}
        self.input_hash = None
        self.sequence = 0
        self.started = time.monotonic()
        self.hashes = {'horch_sha256': sha(HORCH), 'driver_sha256': sha(Path(__file__))}

    def check(self, name, ok):
        self.assertions.append({'name': name, 'ok': bool(ok)})
        print(f'{"PASS" if ok else "FAIL"}: {name}', flush=True)
        if not ok:
            raise RuntimeError(name)

    def invoke(self, label, argv, env=None, timeout=180):
        self.sequence += 1
        prefix = self.root / f'{self.sequence:03d}-{label}'
        proc = subprocess.run([str(a) for a in argv], env=env or self.env,
                              text=True, capture_output=True, timeout=timeout)
        prefix.with_suffix('.stdout').write_text(proc.stdout)
        prefix.with_suffix('.stderr').write_text(proc.stderr)
        return proc

    def herdr(self, label, *argv):
        proc = self.invoke(label, ['herdr', *argv], timeout=30)
        if proc.returncode:
            raise RuntimeError(label + '_failed')
        return json.loads(proc.stdout)['result']

    def context(self, label):
        item = self.workspaces[label]
        return dict(self.env, HERDR_ENV='1', HERDR_WORKSPACE_ID=item['workspace'],
                    HERDR_TAB_ID=item['tab'], HERDR_PANE_ID=item['pane'])

    def cli(self, label, workspace, *argv, timeout=180):
        proc = self.invoke(label, [sys.executable, HORCH, *argv],
                           self.context(workspace), timeout)
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        return proc, rows

    def records(self):
        return [read(p) for p in sorted(self.store.glob('t-*/task.json'))]

    def snapshot(self, task, label):
        state = read(Path(task['task_dir']) / 'state.json')
        (self.root / f'{label}-{task["task_id"]}-state.json').write_text(
            json.dumps(state, indent=2) + '\n')
        return {'state': state.get('state'), 'closed': state.get('closed'),
                'problem_present': bool(state.get('problem'))}

    def allocation(self):
        return {'tasks': sorted(t['task_id'] for t in self.records()),
                'panes': {name: sorted(p['pane_id'] for p in self.herdr(
                    'allocation-' + name, 'pane', 'list', '--workspace', item['workspace'])['panes'])
                          for name, item in self.workspaces.items()}}

    def start(self, workspace, index):
        brief = self.root / f'brief-{workspace}-{index}.md'
        brief.write_text(f'''Read {self.root / 'input.json'} and calculate the invoice total:
for every line compute gross = quantity * unit_price_cents, then subtract
floor(gross * discount_bp / 10000), sum all lines, and add shipping_cents once.
Verify the arithmetic with Python. Write the integer to answer.txt in your
task directory. Do not modify the checkout or input. Do not delegate or commit.
Use at most three shell calls, finish promptly, and write result.json last.
''')
        proc, rows = self.cli(f'run-{workspace}-{index}', workspace, 'run', self.args.worker,
                              '--cwd', self.args.cwd, '--brief', brief)
        row = rows[0] if len(rows) == 1 else {}
        if row.get('task_id'):
            self.tasks.append(row)
        self.observations[f'run_{workspace}_{index}'] = {
            'state': row.get('state'), 'error': row.get('error'), 'exit_code': proc.returncode}
        if row.get('task_id'):
            self.observations[f'run_{workspace}_{index}']['task_state'] = self.snapshot(row, 'started')
        self.check(f'{workspace} worker {index} starts', proc.returncode == 0 and row.get('state') == 'running')
        record = read(Path(row['task_dir']) / 'task.json')
        # This quota scenario gives each worker its own tab, avoiding shell
        # readiness in a freshly split pane as an unrelated startup variable.
        self.herdr(f'rename-{workspace}-{index}', 'tab', 'rename', record['tab_id'],
                   f'quota-worker-{workspace}-{index}')
        return row

    def refused(self, label):
        before = self.allocation()
        proc, rows = self.cli(label, 'A', 'run', self.args.worker, '--cwd', self.args.cwd,
                              '--brief', self.root / 'brief-A-1.md', timeout=30)
        self.check(label + ' reports worker_limit', proc.returncode != 0 and len(rows) == 1
                   and rows[0].get('error') == 'worker_limit')
        self.check(label + ' allocates nothing', before == self.allocation())

    def scenario(self):
        cfg = self.root / 'config/herdr-orchestrator/workers.toml'
        cfg.parent.mkdir(parents=True)
        text = 'max_active_workers = 2\n[workers.' + json.dumps(self.args.worker) + ']\n'
        text += ''.join(f'{key} = {json.dumps(value)}\n' for key, value in self.worker.items())
        cfg.write_text(text)
        (self.root / 'input.json').write_text(json.dumps({
            'lines': [{'quantity': 7, 'unit_price_cents': 137, 'discount_bp': 250},
                      {'quantity': 2, 'unit_price_cents': 1000, 'discount_bp': 500}],
            'shipping_cents': 55}))
        self.input_hash = sha(self.root / 'input.json')
        for label in ('A', 'B'):
            result = self.herdr('create-' + label, 'workspace', 'create', '--cwd', self.args.cwd,
                                '--label', 'quota-e2e-' + label, '--no-focus',
                                '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                                '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'])
            self.workspaces[label] = {'workspace': result['workspace']['workspace_id'],
                                      'tab': result['tab']['tab_id'],
                                      'pane': result['root_pane']['pane_id']}
        self.check('two distinct owned workspaces', len({w['workspace'] for w in self.workspaces.values()}) == 2)
        a = [self.start('A', i) for i in (1, 2)]
        self.refused('full-A')
        for task in a:
            path = Path(task['task_dir']) / 'task.json'
            record = read(path)
            record.pop('workspace_id', None)
            path.write_text(json.dumps(record, indent=2) + '\n')
        self.check('only A records converted to legacy format', len(self.records()) == 2
                   and all('workspace_id' not in t for t in self.records()))
        self.refused('legacy-full-A')
        before = self.allocation()
        proc, rows = self.cli('full-A-check', 'A', 'check', self.args.worker, '--cwd', self.args.cwd,
                              '--max-seconds', '10', timeout=30)
        self.check('full A check is not_checked', proc.returncode == 0 and len(rows) == 1
                   and rows[0].get('state') == 'not_checked' and rows[0].get('task_id') is None
                   and rows[0].get('ok') is False)
        self.check('full A check allocates nothing', before == self.allocation())
        b = [self.start('B', i) for i in (1, 2)]
        records = self.records()
        self.check('shared store holds four reservations', len(records) == 4
                   and all(not read(Path(t['task_dir']) / 'state.json')['closed'] for t in records))
        for label, tasks in (('A', a), ('B', b)):
            live = {p['pane_id'] for p in self.herdr('membership-' + label, 'pane', 'list',
                                                    '--workspace', self.workspaces[label]['workspace'])['panes']}
            self.check(label + ' has two worker panes', len(tasks) == 2 and all(t['pane_id'] in live for t in tasks))
        self.check('B persists launch workspace', all(read(Path(t['task_dir']) / 'task.json').get('workspace_id')
                   == self.workspaces['B']['workspace'] for t in b))
        pending = {t['task_id'] for t in [*a, *b]}
        deadline = time.monotonic() + self.args.max_seconds
        while pending and time.monotonic() < deadline:
            proc, rows = self.cli('wait', 'A', 'wait', *sorted(pending), '--max-seconds', '30', timeout=60)
            self.check('wait CLI succeeds', proc.returncode == 0)
            for row in rows:
                self.check('wait reports a normal lifecycle', row.get('state') in ('running', 'long_running', 'done'))
                if row.get('state') == 'done':
                    self.check('delivered worker is closed', row.get('closed') is True)
                    pending.discard(row['task_id'])
        self.check('all four tasks settle within cap', not pending)
        for task in [*a, *b]:
            directory = Path(task['task_dir'])
            record, result = read(directory / 'task.json'), read(directory / 'result.json')
            self.check('arithmetic result is correct', (directory / 'answer.txt').read_text().strip() == '2891')
            self.check('result identity and completion', result.get('task_id') == record['task_id']
                       and result.get('nonce') == record['nonce'] and result.get('status') == 'completed')
        before = len(self.records())
        proc, rows = self.cli('released-A-check', 'A', 'check', self.args.worker, '--cwd', self.args.cwd,
                              '--max-seconds', str(self.args.max_seconds), timeout=self.args.max_seconds + 90)
        self.check('released A check delivers and closes', proc.returncode == 0 and len(rows) == 1 and rows[0].get('ok') is True)
        self.check('released check allocates exactly one task', len(self.records()) == before + 1)

    def cleanup(self, failed):
        ok = True
        for task in self.records():
            try:
                self.observations.setdefault('before_cleanup', []).append({
                    'task_id': task['task_id'], **self.snapshot(task, 'before-cleanup')})
                state = read(Path(task['task_dir']) / 'state.json')
                if not state.get('closed'):
                    if failed:
                        self.invoke('problem-pane', ['herdr', 'pane', 'read', task['pane_id'],
                                                     '--source', 'recent', '--lines', '60'], timeout=30)
                    proc, _ = self.cli('cleanup-task', 'A', 'close', task['task_id'], timeout=30)
                    ok &= proc.returncode == 0
                proc = self.invoke('absent-worker', ['herdr', 'pane', 'get', task['pane_id']], timeout=30)
                row = json.loads(proc.stdout or proc.stderr)
                ok &= proc.returncode != 0 and row.get('error', {}).get('code') in (
                    'pane_not_found', 'tab_not_found', 'workspace_not_found')
            except Exception:
                ok = False
        for item in self.workspaces.values():
            try:
                proc = self.invoke('cleanup-workspace', ['herdr', 'workspace', 'close', item['workspace']], timeout=30)
                ok &= proc.returncode == 0
            except Exception:
                ok = False
        try:
            live = self.herdr('remaining-workspaces', 'workspace', 'list')['workspaces']
            ok &= not {w['workspace_id'] for w in live} & {w['workspace'] for w in self.workspaces.values()}
        except Exception:
            ok = False
        self.assertions.append({'name': 'owned worker panes and workspaces removed', 'ok': bool(ok)})
        return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', required=True, help='existing authenticated configured worker')
    parser.add_argument('--cwd', type=Path, default=Path.cwd(), help='existing trusted checkout; read only')
    parser.add_argument('--output', type=Path, required=True, help='artifact parent outside repository')
    parser.add_argument('--max-seconds', type=int, default=300, help='completion wait cap')
    args = parser.parse_args()
    if os.environ.get('HERDR_ENV') != '1':
        parser.error('run inside Herdr')
    args.cwd = args.cwd.expanduser().resolve(strict=True)
    args.output = args.output.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if args.output == repo or repo in args.output.parents or not args.cwd.is_dir() or args.max_seconds < 1:
        parser.error('require an existing cwd, positive cap, and output outside repository')
    cfg = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'herdr-orchestrator/workers.toml'
    worker = tomllib.loads(cfg.read_text()).get('workers', {}).get(args.worker)
    if not worker:
        parser.error('--worker must exist in workers.toml')
    config_hash = sha(cfg)
    args.output.mkdir(parents=True, exist_ok=True)
    run = Run(args, worker)
    print(f'Run directory: {run.root}', flush=True)
    problem = None
    try:
        run.scenario()
    except (Exception, KeyboardInterrupt) as exc:
        problem = type(exc).__name__
        (run.root / 'failure.txt').write_text(str(exc))
    finally:
        run.cleanup(problem is not None)
        run.assertions.append({'name': 'read-only input unchanged', 'ok': run.input_hash is not None
                               and sha(run.root / 'input.json') == run.input_hash})
        run.assertions.append({'name': 'real worker configuration unchanged', 'ok': sha(cfg) == config_hash})
        run.assertions.append({'name': 'verified source unchanged during run', 'ok': run.hashes == {
            'horch_sha256': sha(HORCH), 'driver_sha256': sha(Path(__file__))}})
        evidence = {'schema': 'horch/workspace-limits-e2e/v1',
                    'verdict': 'pass' if not problem and all(a['ok'] for a in run.assertions) else 'fail',
                    'source_hashes': run.hashes, 'worker': args.worker,
                    'input_sha256': run.input_hash,
                    'model': {key: worker.get(key) for key in ('harness', 'provider', 'model', 'effort')},
                    'seconds': round(time.monotonic() - run.started, 3),
                    'observations': run.observations, 'assertions': run.assertions, 'problem_category': problem}
        receipt = run.root / 'evidence.json'
        receipt.write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'Evidence: {receipt}\nVerdict: {evidence["verdict"]}', flush=True)
    return 0 if evidence['verdict'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
