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
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone

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
        self.wall_started = time.time()
        self.complete = False
        self.selected = []
        self.sequence = 0
        self.diagnostics = self.root / 'diagnostics'
        self.diagnostics.mkdir(mode=0o700)

    def sanitize(self, value):
        text = json.dumps(value, ensure_ascii=False)
        paths = {str(Path.home()): '<home>', str(REPO): '<repo>',
                 str(self.args.cwd): '<cwd>', str(self.args.output): '<output>',
                 str(self.root): '<run>', str(self.args.source_config): '<workers-config>'}
        for path in sorted(paths, key=len, reverse=True):
            text = text.replace(json.dumps(path, ensure_ascii=False)[1:-1], paths[path])
        return json.loads(text)

    def check(self, name, ok):
        self.assertions.append({'name': name, 'ok': bool(ok)})
        print(f'{"PASS" if ok else "FAIL"}: {name}', flush=True)
        if not ok:
            raise RuntimeError(name)

    def streams(self, stdout, stderr):
        self.sequence += 1
        for suffix, value in (('stdout', stdout), ('stderr', stderr)):
            if isinstance(value, bytes):
                value = value.decode('utf-8', errors='replace')
            (self.diagnostics / f'{self.sequence:03d}.{suffix}').write_text(value or '', encoding='utf-8')

    def failure(self, exc):
        with (self.diagnostics / 'failure.txt').open('a', encoding='utf-8') as stream:
            stream.write(f'{type(exc).__name__}: {exc}\n')

    def command(self, argv, timeout=30):
        try:
            proc = subprocess.run([str(a) for a in argv], env=self.env, cwd=self.args.cwd,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self.streams(exc.stdout, exc.stderr)
            raise
        self.streams(proc.stdout, proc.stderr)
        return proc

    @staticmethod
    def version(value):
        # Publish only a version number, never arbitrary CLI diagnostics.
        match = re.search(r'\b\d+\.\d+\.\d+\b', str(value))
        return match.group(0) if match else None

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
             if k in ('worker', 'task_id', 'state', 'ok', 'pane_id', 'seconds')}
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
            def encode(value):
                # TOML accepts Unicode scalars, not JSON surrogate pairs or raw DEL.
                return json.dumps(value, ensure_ascii=False).replace('\x7f', '\\u007f')
            text += '\n[workers.' + encode(name) + ']\n'
            # The supported worker fields are strings and arrays of strings.
            text += ''.join(f'{encode(k)} = {encode(v)}\n' for k, v in spec.items())
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
            self.versions['herdr_cli' if tool == 'herdr' else tool] = {
                'exit_code': proc.returncode, 'version': self.version(proc.stdout or proc.stderr)}
        # `herdr status server --json` prints the status object itself, without a "result" envelope.
        proc = self.command(['herdr', 'status', 'server', '--json'])
        if proc.returncode:
            raise RuntimeError('herdr_command_failed')
        server = json.loads(proc.stdout)
        version = self.version(server.get('version')) if isinstance(server, dict) else None
        self.versions['herdr_server'] = {'version': version}
        if self.versions['herdr_server']['version'] is None:
            raise RuntimeError('herdr_server_version_unavailable')
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
        self.selected = [names[0], *names]  # repeat first worker; unique count exceeds one-slot limit
        proc = self.cli('check', *self.selected, '--cwd', self.args.cwd,
                        '--max-seconds', self.args.max_seconds, timeout=self.args.max_seconds + 180)
        rows = self.rows('batch', proc)
        self.check('C001 check exits successfully', proc.returncode == 0)
        self.check('C002 selected workers deduplicated in order', self.selected == [names[0], *names]
                   and [r.get('worker') for r in rows] == list(dict.fromkeys(self.selected)))
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

        # Independent filesystem observations, before any driver cleanup.
        # Strict ordering fails closed on coarse timestamps instead of hiding overlap.
        lifecycle = [{'task_id': row['task_id'],
                      'published_ns': (self.store / row['task_id'] / 'task.json').stat().st_mtime_ns,
                      'closed_ns': (self.store / row['task_id'] / 'state.json').stat().st_mtime_ns}
                     for row in rows]
        self.observations['batch_lifecycle'] = lifecycle
        self.check('C009 each reservation begins after previous slot release', all(
            later['published_ns'] > earlier['closed_ns']
            for earlier, later in zip(lifecycle, lifecycle[1:])))

        self.configure(0)
        before = self.allocation()
        proc = self.cli('check', *names, '--cwd', self.args.cwd)
        rows = self.rows('zero_slots', proc)
        fields = {'worker', 'task_id', 'state', 'ok', 'pane_id', 'seconds', 'message'}
        self.check('C010 zero slots report complete skip fields', proc.returncode == 0
                   and [r.get('worker') for r in rows] == names and all(fields <= set(r)
                   and r['state'] == 'not_checked' and r['ok'] is False and r['task_id'] is None
                   and r['pane_id'] is None and r['seconds'] is None for r in rows))
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
        self.streams(stdout, stderr)
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
        self.stats_phase(names)
        self.complete = True

    def stats_phase(self, names):
        real = self.records()
        wall_end = time.time()
        unused = next(f'stats-unused{i}' for i in range(len(self.workers) + 1)
                      if f'stats-unused{i}' not in self.workers)
        self.workers[unused] = dict(self.workers[names[0]])
        self.configure(1)
        unknown = next(f'stats-removed{i}' for i in range(len(self.workers) + 1)
                       if f'stats-removed{i}' not in self.workers)
        # Select unused IDs without relying on the randomly allocated task IDs.
        ids = [f't-{n:06x}' for n in range(1, len(real) + 3) if f't-{n:06x}' not in real]
        invalid_id, removed_id = ids[:2]
        created = datetime.fromtimestamp(wall_end - 3600, timezone.utc).isoformat()
        fixture = {'task_id': removed_id, 'nonce': 'stats-fixture', 'worker': unknown,
                   'agent': 'stats-fixture', 'pane_id': 'stats-fixture-no-pane',
                   'created_at': created, 'workspace_id': 'stats-other-workspace'}
        for task_id in (invalid_id, removed_id):
            directory = self.store / task_id
            directory.mkdir()
            task = dict(fixture, task_id=task_id, result_path=str(directory / 'result.json'))
            if task_id == invalid_id:
                task['nonce'] = None
            (directory / 'task.json').write_text(json.dumps(task))
            (directory / 'state.json').write_text(json.dumps({'state': 'done', 'closed': True}))
            (directory / 'result.json').write_text(json.dumps({
                'task_id': task_id, 'nonce': 'stats-fixture', 'status': 'blocked',
                'summary': 'fixture', 'files': [], 'question': 'Fixture specification question?'}))
            os.utime(directory / 'result.json', (wall_end - 900, wall_end - 900))
        before = {str(p.relative_to(self.root)): sha(p) for p in self.root.rglob('*')
                  if p.is_file() and self.diagnostics not in p.parents}
        proc = self.cli('stats')
        scoped_proc = self.cli('stats', '--workspace', self.workspace['workspace_id'])
        self.check('C040 stats commands return single JSON objects', proc.returncode == scoped_proc.returncode == 0
                   and len(proc.stdout.splitlines()) == len(scoped_proc.stdout.splitlines()) == 1)
        whole, scoped = json.loads(proc.stdout), json.loads(scoped_proc.stdout)
        self.observations['stats'] = whole
        self.observations['stats_workspace'] = scoped
        self.check('C041 stats task counts match real dispatches and fixture',
                   whole['task_count'] == len(real) + 1 and scoped['task_count'] == len(real)
                   and all(obj['workers'][n]['task_count'] == sum(r['worker'] == n for r in real.values())
                           for n in names for obj in (whole, scoped)))
        self.check('C042 stats states and problem rates match scenario', all(
            obj['workers'][n]['states'] == ({'done': 1, 'exited': 1} if n == names[0] else {'done': 1})
            and obj['workers'][n]['problem_count'] == (1 if n == names[0] else 0)
            and obj['workers'][n]['problem_rate'] == (0.5 if n == names[0] else 0)
            for n in names for obj in (whole, scoped)))
        self.check('C043 stats delivered result statuses exclude exited probe', all(
            obj['workers'][n]['result_statuses'] == {'completed': 1} for n in names for obj in (whole, scoped))
            and whole['workers'][unknown]['result_statuses'] == {'blocked': 1})
        self.check('C044 stats invalid record listed and excluded in both scopes',
                   whole['invalid_task_ids'] == scoped['invalid_task_ids'] == [invalid_id])
        self.check('C045 stats removed worker is unconfigured and workspace filtered',
                   whole['workers'][unknown]['configured'] is False
                   and whole['workers'][unknown]['task_count'] == 1 and unknown not in scoped['workers']
                   and whole['workers'][unknown]['workspaces'] == {'stats-other-workspace': 1})
        self.check('C046 stats configured unused worker retained in both scopes', all(
            obj['configured_unused_workers'] == [unused]
            and obj['workers'][unused]['configured'] is True
            and obj['workers'][unused]['duration_minutes']['sample_size'] == 0
            and obj['workers'][unused]['task_count'] == 0 for obj in (whole, scoped)))
        states = {t: read(self.store / t / 'state.json') for t in real}
        self.check('C047 new records retain observed first settlement timestamps', all(
            self.wall_started - 1 <= datetime.fromisoformat(s['settled_at'].replace('Z', '+00:00')).timestamp() <= wall_end
            for s in states.values()))
        bounds = {}
        for task_id, record in real.items():
            if states[task_id]['state'] != 'done':
                continue
            directory = self.store / task_id
            created_at = datetime.fromisoformat(record['created_at'].replace('Z', '+00:00')).timestamp()
            bounds[record['worker']] = (
                max(0, (directory.joinpath('result.json').stat().st_mtime - created_at - 1) / 60),
                (directory.joinpath('state.json').stat().st_mtime - created_at + 1) / 60)
        self.observations['stats_duration_bounds_minutes'] = bounds
        self.check('C048 stats durations fit independently observed filesystem bounds', all(
            obj['workers'][n]['duration_minutes']['sample_size'] == 1
            and obj['workers'][n]['duration_minutes']['sources'] == {'settled_at': 1}
            and obj['workers'][n]['duration_minutes']['max'] <= (wall_end - self.wall_started + 1) / 60
            and all(bounds[n][0] <= obj['workers'][n]['duration_minutes'][key] <= bounds[n][1]
                    for key in ('median', 'p90', 'max')) for n in names for obj in (whole, scoped))
            and whole['workers'][unknown]['duration_minutes'] == {
                'sample_size': 1, 'median': 45.0, 'p90': 45.0, 'max': 45.0, 'sources': {'result_mtime': 1}})
        def contains_args(value):
            if isinstance(value, dict):
                return 'args' in value or any(contains_args(v) for v in value.values())
            return isinstance(value, list) and any(contains_args(v) for v in value)
        self.check('C049 stats never exposes worker args', not contains_args([whole, scoped]))
        self.check('C050 stats workspace counts and reminder denominator match deliveries',
                   all(scoped['workers'][n]['workspaces'] == {
                       self.workspace['workspace_id']: 2 if n == names[0] else 1} for n in names)
                   and whole['notify_after_minutes']['timed_task_count'] == len(names) + 1
                   and scoped['notify_after_minutes']['timed_task_count'] == len(names))
        after = {str(p.relative_to(self.root)): sha(p) for p in self.root.rglob('*')
                 if p.is_file() and self.diagnostics not in p.parents}
        self.check('C051 stats leaves isolated config and task store unchanged', before == after)

        # Real cancellation, after the original checks so their coverage stays intact.
        brief = self.root / 'cancel-brief.md'
        brief.write_text('This is a cancellation probe. Run sleep 120 before writing any result. '
                         'Do not edit the checkout. The controller will close your pane.\n')
        proc = self.cli('run', names[0], '--brief', brief, '--cwd', self.args.cwd, timeout=180)
        rows = self.rows('cancel_run', proc)
        self.check('C052 cancellation probe starts one real running worker',
                   proc.returncode == 0 and len(rows) == 1
                   and set(self.records()) - set(real) - {invalid_id, removed_id} == {rows[0]['task_id']})
        task_id = rows[0]['task_id']
        directory = self.store / task_id
        state = read(directory / 'state.json')
        self.check('C053 cancellation probe is open and running before close',
                   state['state'] == 'running' and not state['closed']
                   and not (directory / 'result.json').exists()
                   and self.records()[task_id]['pane_id'] in self.panes())
        proc = self.cli('close', task_id)
        self.rows('cancel_close', proc)
        state = read(directory / 'state.json')
        self.check('C054 close cancels running probe without settling it',
                   proc.returncode == 0 and state['closed'] is True and state['state'] == 'running'
                   and state.get('settled_at') is None
                   and self.records()[task_id]['pane_id'] not in self.panes())
        for check_id, label, previous, argv in (
                ('C055', 'stats_after_cancel', whole, ()),
                ('C056', 'stats_workspace_after_cancel', scoped, ('--workspace', self.workspace['workspace_id']))):
            proc = self.cli('stats', *argv)
            current = json.loads(proc.stdout)
            self.observations[label] = current
            # Compare the entire output: only the cancellation count, task totals,
            # workspace count, last-use and the all-task problem denominator change.
            expected = json.loads(json.dumps(previous))
            expected['task_count'] += 1
            row = expected['workers'][names[0]]
            row['task_count'] += 1
            row['states']['closed_before_done'] = 1
            row['workspaces'][self.workspace['workspace_id']] += 1
            row['last_use'] = self.records()[task_id]['created_at']
            row['problem_rate'] = row['problem_count'] / row['task_count']
            self.check(f'{check_id} {label} counts cancellation, not running or problems',
                       proc.returncode == 0 and current == expected)

    def cleanup(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                stdout, stderr = self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                stdout, stderr = self.process.communicate()
            self.streams(stdout, stderr)
        ok = True
        if self.workspace is not None:
            try:
                self.close_tasks()
                live = self.panes()
                self.check('C100 all owned worker panes removed',
                           all(r['pane_id'] not in live for r in self.records().values()))
            except Exception as exc:
                self.failure(exc)
                ok = False
            try:
                self.herdr('workspace', 'close', self.workspace['workspace_id'])
                live = self.herdr('workspace', 'list')['workspaces']
                ok &= self.workspace['workspace_id'] not in {w['workspace_id'] for w in live}
            except Exception as exc:
                self.failure(exc)
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
    args.source_config = cfg.expanduser().resolve()
    config_hash = None
    workers = {}
    args.output.mkdir(parents=True, exist_ok=True)
    run = Run(args, workers)
    print(f'Run directory: {run.root}', flush=True)
    problem = None
    try:
        config_hash = sha(cfg)
        configured = tomllib.loads(cfg.read_text(encoding='utf-8')).get('workers', {})
        if not isinstance(configured, dict) or any(
                not isinstance(configured.get(name), dict) for name in names):
            raise RuntimeError('selected_worker_not_configured')
        workers.update({name: configured[name] for name in names})
        run.scenario()
    except (Exception, KeyboardInterrupt) as exc:
        run.failure(exc)
        problem = type(exc).__name__  # no exception text or transcripts in receipt
    finally:
        try:
            run.cleanup()
        except (Exception, KeyboardInterrupt) as exc:
            run.failure(exc)
            problem = type(exc).__name__
        for name, condition in (
            ('real configuration unchanged', lambda: config_hash is not None and sha(cfg) == config_hash),
            ('verified sources unchanged', lambda: run.hashes == {
                'horch_sha256': sha(HORCH), 'driver_sha256': sha(Path(__file__))})):
            try:
                ok = condition()
            except OSError:
                ok = False
            run.assertions.append({'name': name, 'ok': ok})
        evidence = run.sanitize({
            'schema': 'horch/check-workers-e2e/v1',
            'verdict': 'pass' if run.complete and problem is None and all(a['ok'] for a in run.assertions) else 'fail',
            'scenario_complete': run.complete,
            'diagnostics': str(run.diagnostics),
            'source_hashes': run.hashes, 'versions': run.versions,
            'workers': {n: {k: s.get(k) for k in ('harness', 'model', 'provider', 'effort')}
                        for n, s in workers.items()},
            'batch_limit': 1, 'selections': run.selected,
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
