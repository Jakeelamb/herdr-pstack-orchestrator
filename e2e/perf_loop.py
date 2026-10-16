#!/usr/bin/env python3
"""Live original Perf issue and Opening a PR E2E against a private fixture.

--prepare-fixture writes portable local files only. Live mode retains an owned
branch, disjoint readers, fresh profiles, immutable probes and a ready child PR.
It never retries, merges, changes worker flags, or answers trust dialogs.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import traceback

import playbook_loop as core
import forge_loop as forge_helpers

ROOT = Path(__file__).resolve().parents[1]
Failure = core.Failure
horch = core.horch
READS = ('poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
         'pstack-herdr/references/herdr-tools.md', 'herdr-orchestrator/SKILL.md',
         'poteto-mode/playbooks/perf-issue.md', 'benchmark-checklist/SKILL.md',
         'control-cli/SKILL.md', 'how/SKILL.md', 'how/references/explainer-prompt.md',
         'poteto-mode/playbooks/opening-a-pr.md', 'deslop/SKILL.md',
         'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md',
         'principle-sequence-verifiable-units/SKILL.md')
MANTRAS = ("Don't do it. Stop work whose result nothing uses rather than cheapening it.",
           "Do it, but don't do it again.", 'Do it less.', 'Do it later.',
           "Do it when they're not looking.", 'Do it concurrently.', 'Do it cheaper.')
APP = '''def lookup_reference(references, account):
    for key, value in references:
        if key == account:
            return value
    raise KeyError(account)


def reconcile_linear(references, payments):
    return sum(lookup_reference(references, account) * amount for account, amount in payments)
'''
CLI = '''import argparse
import json
from pathlib import Path
import sys
from reconcile import reconcile_linear


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text())
        references, payments = data["references"], data["payments"]
        seen = set()
        for account, value in references:
            if not isinstance(account, str) or account in seen or type(value) is not int or value < 0:
                raise ValueError("invalid or duplicate reference")
            seen.add(account)
        for account, amount in payments:
            if account not in seen or type(amount) is not int or amount < 0:
                raise ValueError("invalid payment")
        total = reconcile_linear(references, payments)
        print(json.dumps({"total_units": total, "references": len(references),
                          "payments": len(payments), "errors": 0}, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError) as error:
        print(json.dumps({"errors": 1, "error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
'''
ORACLE = r'''#!/usr/bin/env python3
"""Drive the actual reconciliation CLI and retain independent arithmetic checks."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
d = a.output.resolve()
if d == root or root in d.parents:
    p.error('output must be outside the application checkout')
d.mkdir(parents=True, exist_ok=False, mode=0o700)
workload = json.loads((root / 'workload.json').read_text())
small = {'references': [['a', 3], ['b', 11], ['c', 0]],
         'payments': [['b', 7], ['a', 9], ['b', 2], ['c', 17]]}
flows = [('full-workload', workload, 0), ('repeated-and-zero', small, 0),
         ('empty-payments', {'references': small['references'], 'payments': []}, 0),
         ('duplicate-reference', {'references': [['a', 1], ['a', 2]], 'payments': [['a', 3]]}, 2),
         ('missing-account', {'references': [['a', 1]], 'payments': [['b', 3]]}, 2),
         ('invalid-amount', {'references': [['a', 1]], 'payments': [['a', -1]]}, 2)]
results = []
for label, data, code in flows:
    source = d / (label + '.json')
    source.write_text(json.dumps(data, sort_keys=True) + '\n')
    proc = subprocess.run([sys.executable, '-B', str(root / 'cli.py'), str(source)],
                          cwd=root, text=True, capture_output=True, timeout=30)
    (d / (label + '.stdout')).write_text(proc.stdout)
    (d / (label + '.stderr')).write_text(proc.stderr)
    try:
        actual = json.loads(proc.stdout)
    except ValueError:
        actual = None
    if code == 0:
        refs = dict(data['references'])
        total = int(sum((Decimal(refs[account]) * Decimal(amount)
                         for account, amount in data['payments']), Decimal(0)))
        expected = {'total_units': total, 'references': len(data['references']),
                    'payments': len(data['payments']), 'errors': 0}
        ok = proc.returncode == code and actual == expected and not proc.stderr
    else:
        ok = (proc.returncode == code and isinstance(actual, dict)
              and actual.get('errors') == 1 and bool(actual.get('error')) and not proc.stderr)
    results.append({'name': label, 'exit_code': proc.returncode, 'ok': ok, 'output': actual})
passed = all(item['ok'] for item in results)
receipt = {'schema': 'reconcile/cli-e2e/v1', 'verdict': 'pass' if passed else 'fail',
           'flows': results, 'workload_sha256': hashlib.sha256((root / 'workload.json').read_bytes()).hexdigest()}
(d / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'verdict': receipt['verdict'], 'flows': len(results)}))
sys.exit(0 if passed else 1)
'''
# Profiles are separate from reported unprofiled end-to-end timing. Every run
# launches the real CLI, consumes its JSON and checks independent arithmetic.
PROBE = r'''#!/usr/bin/env python3
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
import time

p = argparse.ArgumentParser()
p.add_argument('--mode', choices=['capture', 'compare'], required=True)
p.add_argument('--repo', type=Path)
p.add_argument('--before', type=Path)
p.add_argument('--after', type=Path)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--nonce', required=True)
a = p.parse_args()
d = a.output.resolve()
d.mkdir(parents=True, exist_ok=False, mode=0o700)
files = ('reconcile.py', 'cli.py', 'e2e_reconcile.py', 'workload.json', 'contract.json')
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def source(root):
    return {name: sha(root / name) for name in files}
def expected(root):
    data = json.loads((root / 'workload.json').read_text())
    refs = dict(data['references'])
    return {'total_units': int(sum((Decimal(refs[k]) * Decimal(v) for k,v in data['payments']), Decimal(0))),
            'references': len(data['references']), 'payments': len(data['payments']), 'errors': 0}
def invoke(root, output, profile=None):
    argv = [sys.executable, '-B']
    if profile:
        argv += ['-m', 'cProfile', '-o', str(profile)]
    argv += [str(root / 'cli.py'), str(root / 'workload.json')]
    start = time.perf_counter_ns()
    proc = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=60)
    elapsed = (time.perf_counter_ns() - start) / 1000000
    output.with_suffix('.stdout').write_text(proc.stdout)
    output.with_suffix('.stderr').write_text(proc.stderr)
    value = json.loads(proc.stdout)
    if proc.returncode != 0 or proc.stderr or value != expected(root):
        raise ValueError('CLI outcome failed independent workload oracle')
    return elapsed, value
def summary(values):
    return {'median_ms': statistics.median(values), 'minimum_ms': min(values), 'maximum_ms': max(values),
            'samples_ms': values, 'runs': len(values)}
def profile(root, label):
    path = d / (label + '.prof')
    _, value = invoke(root, d / (label + '-profile'), path)
    rows = []
    for (file, line, name), (_, calls, own, cumulative, _) in pstats.Stats(str(path)).stats.items():
        rows.append({'file': file, 'line': line, 'function': name, 'calls': calls,
                     'self_seconds': own, 'cumulative_seconds': cumulative})
    rows.sort(key=lambda row: row['self_seconds'], reverse=True)
    (d / (label + '-frames.json')).write_text(json.dumps(rows, indent=2))
    return {'profile_sha256': sha(path), 'frames_sha256': sha(d / (label + '-frames.json')),
            'lookup_calls': sum(row['calls'] for row in rows if row['function'] == 'lookup_reference'
                                and Path(row['file']).resolve() == root / 'reconcile.py'),
            'reconcile_calls': sum(row['calls'] for row in rows if row['function'] == 'reconcile_linear'
                                   and Path(row['file']).resolve() == root / 'reconcile.py'),
            'lookup_self_seconds': sum(row['self_seconds'] for row in rows if row['function'] == 'lookup_reference'
                                       and Path(row['file']).resolve() == root / 'reconcile.py'),
            'profile_self_seconds': sum(row['self_seconds'] for row in rows), 'result': value}
result = {'schema': 'reconcile/measurement/v1', 'mode': a.mode, 'nonce': a.nonce,
          'python': sys.version.split()[0], 'cpu_count': os.cpu_count(),
          'load_average': list(os.getloadavg()), 'unit': 'ms', 'errors': 0,
          'timed_surface': 'fresh CLI process: startup, JSON input, validation, reconciliation, JSON output',
          'profiling_in_reported_timing': False}
if a.mode == 'capture':
    root = a.repo.resolve()
    initial = source(root)
    prof = profile(root, 'capture')
    values = [invoke(root, d / ('run-' + str(index)))[0] for index in range(5)]
    result.update(source_sha256=initial, workload_sha256=sha(root / 'workload.json'),
                  profile=prof, timing=summary(values), result=expected(root))
    if initial != source(root):
        raise ValueError('source changed during capture')
else:
    before, after = a.before.resolve(), a.after.resolve()
    snapshots = {'before': source(before), 'after': source(after)}
    if snapshots['before']['workload.json'] != snapshots['after']['workload.json']:
        raise ValueError('workloads differ')
    values = {'before': [], 'after': []}
    observations = []
    for index in range(5):
        for label, root in (('before', before), ('after', after)):
            elapsed, value = invoke(root, d / (label + '-' + str(index)))
            values[label].append(elapsed)
            observations.append({'side': label, 'index': index, 'elapsed_ms': elapsed, 'result': value})
    result.update(sources=snapshots, workload_sha256=snapshots['before']['workload.json'],
                  timings={label: summary(rows) for label,rows in values.items()}, observations=observations,
                  profiles={'before': profile(before, 'before'), 'after': profile(after, 'after')})
    result['speedup_fraction'] = 1 - result['timings']['after']['median_ms'] / result['timings']['before']['median_ms']
    result['primary_number'] = ('%.3f ms -> %.3f ms (%.1f%% reduction)' %
        (result['timings']['before']['median_ms'], result['timings']['after']['median_ms'],
         100 * result['speedup_fraction']))
    report = ['# Reconciliation measurement', '',
              'End-to-end wall time: ' + result['primary_number'] + '.', '',
              'Five alternating before/after runs per side. A fresh Python CLI process includes startup, JSON input, validation, reconciliation and JSON output. Profiles are separate from wall measurements.',
              '', '| State | Median ms | Minimum ms | Maximum ms | Lookup calls |',
              '| --- | ---: | ---: | ---: | ---: |']
    for label in ('before', 'after'):
        t = result['timings'][label]
        report.append('| %s | %.3f | %.3f | %.3f | %d |' % (label, t['median_ms'],
            t['minimum_ms'], t['maximum_ms'], result['profiles'][label]['lookup_calls']))
    report += ['', 'Every observation processed 2,500 unique references and 6,000 payments, returned the independently computed integer total, and reported zero errors.',
               '', 'Workload SHA-256: ' + result['workload_sha256'],
               'Baseline reconcile.py SHA-256: ' + snapshots['before']['reconcile.py'],
               'Final reconcile.py SHA-256: ' + snapshots['after']['reconcile.py'],
               '', 'The baseline lookup_reference frame was measured 6,000 times; the optimized trace has zero such calls. Each trace has one reconcile_linear call. Index construction trades O(reference count) memory for eliminating repeated linear scans.',
               '', 'Scope: this deterministic local workload, one function, this Python and host. Warm filesystem and interpreter startup are included; no production ceiling, sustained Hillclimb, concurrency scaling or general workload speedup is claimed.']
    result['portable_report'] = '\n'.join(report) + '\n'
    if snapshots != {'before': source(before), 'after': source(after)}:
        raise ValueError('source changed during comparison')
(d / 'observation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
'''


def workload():
    return {'references': [[f'account-{i}', i % 31 + 1] for i in range(2500)],
            'payments': [[f'account-{(i * 173) % 2500}', i % 19 + 1] for i in range(6000)]}


def fixture_files():
    return {'reconcile.py': APP, 'cli.py': CLI, 'e2e_reconcile.py': ORACLE,
            'workload.json': json.dumps(workload(), sort_keys=True) + '\n',
            'contract.json': json.dumps({'references': 2500, 'payments': 6000, 'reference_keys': 'unique',
                'values_and_amounts': 'nonnegative integers', 'result': 'sum of referenced value times amount',
                'errors': 'invalid input exits 2 with a JSON error', 'timing_surface': 'complete CLI process'}, indent=2) + '\n',
            'AGENTS.md': 'Write code and documentation in English. Preserve the public CLI and input/output contract.\nUse the retained CLI E2E oracle to verify behavior. Keep generated inputs, profiles and reports outside Git.\nUse the existing Git identity, hooks and signing configuration.\n',
            '.gitignore': '__pycache__/\n*.py[cod]\n*.prof\nartifacts/\n',
            'README.md': '''# Reconciliation CLI

This Python standard-library application reconciles account references and payments.
References use unique string account keys and nonnegative integer values. Payments
use known account keys and nonnegative integer amounts. The CLI consumes one JSON
file and emits the integer total, input work counts and error count as JSON.
Invalid input exits with status 2 and a JSON error. No external services are used.

Run the application with python3 -B cli.py workload.json. The frozen workload
contains 2,500 references and 6,000 payments. Run the real CLI regression oracle
with python3 -B e2e_reconcile.py --output /tmp/reconcile-proof-UNIQUE.
The resulting artifact contains replayable inputs and CLI outputs.

To collaborate privately, initialize your own private repository and commit these
files on a baseline branch. Open one ready baseline PR without merging it. Supply
that clone, repository identity, branch and PR number explicitly to the live driver.
Do not commit raw profiles, worker configuration, transcripts, or private paths.
''',
            '.github/workflows/verify.yml': '''name: Verify reconciliation CLI
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python3 -B e2e_reconcile.py --output "$RUNNER_TEMP/reconciliation-proof"
'''}


def prepare_fixture(directory):
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    files = fixture_files()
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print(json.dumps({'files': sorted(files), 'sha256': {name: core.sha(directory / name) for name in files}}, indent=2))
    return 0


def identity():
    paths = [*ROOT.joinpath('skills').rglob('*'), ROOT / 'e2e/playbook_loop.py',
             ROOT / 'e2e/playbook_cases.py', ROOT / 'e2e/forge_loop.py', Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)): core.sha(path) for path in paths
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def outside_function(text):
    tree = ast.parse(text)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'reconcile_linear']
    if len(functions) != 1:
        raise Failure('allowed_function_missing')
    target = functions[0]
    if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for statement in target.body for node in ast.walk(statement)):
        raise Failure('nested_function_boundary_change')
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:target.body[0].lineno - 1]) + '    pass\n' + ''.join(lines[target.end_lineno:])


def measurement_ok(value, before=None):
    if (value.get('schema') != 'reconcile/measurement/v1' or value.get('unit') != 'ms'
            or value.get('errors') != 0 or value.get('profiling_in_reported_timing') is not False):
        return False
    expected = {'references': 2500, 'payments': 6000, 'errors': 0,
                'total_units': sum((i % 31 + 1) * amount for account, amount in workload()['payments']
                                   for i in [int(account.split('-')[1])])}
    if value.get('mode') == 'capture':
        return (value.get('result') == expected and value.get('profile', {}).get('result') == expected
                and value['profile'].get('reconcile_calls') == 1
                and value['profile'].get('lookup_calls') == (6000 if before else 0)
                and value.get('timing', {}).get('runs') == 5 and value['timing']['minimum_ms'] > 0)
    if value.get('mode') != 'compare':
        return False
    observations = value.get('observations', [])
    return (len(observations) == 10 and [row['side'] for row in observations] == ['before', 'after'] * 5
            and all(row.get('result') == expected and row.get('elapsed_ms', 0) > 0 for row in observations)
            and value.get('profiles', {}).get('before', {}).get('lookup_calls') == 6000
            and value.get('profiles', {}).get('after', {}).get('lookup_calls') == 0
            and all(value['profiles'][label].get('reconcile_calls') == 1 for label in ('before', 'after'))
            and value.get('speedup_fraction', 0) >= .5
            and value['timings']['after']['maximum_ms'] < value['timings']['before']['minimum_ms'])


class Run(core.Run):
    """One original Perf issue, with an explicit private fixture/forge boundary."""

    def __init__(self, args):
        args.scenario = 'perf-issue'
        super().__init__(args)
        self.branch = 'e2e/perf-' + secrets.token_hex(8)
        self.nonce = secrets.token_hex(24)
        self.probe = self.directory / 'measurement.py'
        self.stage_proof, self.snapshot = {}, {}
        self.config_path = self.original_fixture = self.pr = self.base = None

    def git(self, *args, repo=None, cleanup=False):
        return self.call(['git', '-C', repo or self.worktree, *args], cleanup=cleanup).strip()

    def forge(self, *args):
        return json.loads(self.call(['gh', *args]))

    def preflight(self):
        self.check('positive_deadline', self.args.max_seconds > 0)
        self.check('inventory_23_unchanged', set(self.inventory_names) == set(core.INVENTORY) and len(self.inventory_names) == 23)
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.repo)).resolve() == ROOT)
        self.revision = self.git('rev-parse', 'HEAD', repo=ROOT)
        self.source_status = self.git('status', '--porcelain=v1', '--untracked-files=all', repo=ROOT)
        self.hashes = identity()
        self.config_path = horch.config_path()
        self.config_hash = core.sha(self.config_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane)
        self.spec = self.config['workers'].get(self.args.controller, {})
        self.check('controller_is_existing_pi', self.spec.get('harness') == 'pi')
        self.role_workers = {}
        for role in ('perf-issue', 'how explainer'):
            selection = self.config.get('roles', {}).get(role)
            names = selection if isinstance(selection, list) else [selection]
            self.check('configured_single_' + role.replace(' ', '_'), len(names) == 1
                       and names[0] in self.config['workers'] and self.config['workers'][names[0]].get('harness') == 'pi')
            self.role_workers[role] = names
        self.check('fixture_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.fixture_repo)).resolve() == self.args.fixture_repo)
        self.fixture_refs = self.git('for-each-ref', '--format=%(objectname)%09%(refname)',
                                     repo=self.args.fixture_repo).splitlines()
        self.original_fixture = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo),
                                 self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo))
        self.check('fixture_clean', not self.original_fixture[1])
        origin = self.git('remote', 'get-url', 'origin', repo=self.args.fixture_repo)
        match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', origin)
        self.check('explicit_fixture_origin', bool(match) and match[1].lower() == self.args.forge_repo.lower())
        repo = self.forge('repo', 'view', self.args.forge_repo, '--json', 'nameWithOwner,isPrivate')
        self.check('explicit_private_forge', repo.get('isPrivate') is True
                   and repo.get('nameWithOwner', '').lower() == self.args.forge_repo.lower())
        rows = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.args.base_ref, repo=self.args.fixture_repo).splitlines()
        self.check('one_remote_baseline', len(rows) == 1)
        self.base = rows[0].split()[0]
        self.check('pinned_pristine_baseline', self.original_fixture[0] == self.base
                   and self.git('rev-parse', self.args.base_ref, repo=self.args.fixture_repo) == self.base)
        self.check('portable_fixture_matches', all((self.args.fixture_repo / name).is_file()
                   and core.sha(self.args.fixture_repo / name) == hashlib.sha256(value.encode()).hexdigest()
                   for name, value in fixture_files().items()))
        self.bootstrap = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo,
                                    '--json', 'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('explicit_parent_pr_ready_open', self.bootstrap.get('state') == 'OPEN'
                   and self.bootstrap.get('isDraft') is False and self.bootstrap.get('headRefOid') == self.base
                   and self.bootstrap.get('headRefName') == self.args.base_ref)
        self.remote_heads = self.git('ls-remote', '--heads', 'origin', repo=self.args.fixture_repo).splitlines()
        self.prs_before = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000',
                                    '--json', 'number,state,headRefName,baseRefName,isDraft')

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.probe.write_text(PROBE)
        self.probe_hash = core.sha(self.probe)
        self.probe.chmod(0o444)
        self.baseline = self.directory / 'snapshot-before'
        self.baseline.mkdir()
        for name in fixture_files():
            if '/' not in name:
                shutil.copy2(self.args.fixture_repo / name, self.baseline / name)
        self.git('worktree', 'add', '-b', self.branch, self.worktree, self.base, repo=self.args.fixture_repo)
        self.reader = self.worktree.parent / 'how-reader'
        self.git('worktree', 'add', '--detach', self.reader, self.base, repo=self.args.fixture_repo)
        env = [item for key in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'MISE_CONFIG_DIR', 'MISE_STATE_DIR', 'GIT_CONFIG_GLOBAL', 'GH_CONFIG_DIR')
               for item in ('--env', key + '=' + self.env[key])]
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'perf-e2e', '--no-focus', *env)
        self.pane = tab['root_pane']['pane_id']
        brief = self.directory / 'controller-brief.md'
        brief.write_text(self.prompt())
        sessions = self.directory / 'native-sessions'
        sessions.mkdir()
        flags = horch.launch_args(self.spec, self.directory) + ['--session-dir', str(sessions)]
        self.check('controller_started', self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', self.pane,
                   '--timeout', '90000', '--', *flags).get('type') == 'agent_started')
        ready = min(self.deadline, time.monotonic() + 90)
        while time.monotonic() < ready:
            entry = self.herdr('agent', 'get', self.agent)['agent']
            session = entry.get('agent_session') or {}
            if session.get('agent') == 'pi' and session.get('source') == 'herdr:pi' and session.get('value') and entry.get('agent_status') in ('idle', 'done'):
                self.session = session
                break
            if entry.get('agent_status') == 'blocked':
                raise Failure('controller_start_blocked')
            time.sleep(1)
        else:
            raise Failure('controller_session_not_ready')
        self.check('controller_prompted', self.herdr('agent', 'prompt', self.agent, f'Read {brief} in full and execute it.',
                   '--wait', '--until', 'working', '--timeout', '30000').get('type') == 'agent_prompted')

    def probe_argv(self, label, *, compare=False, repo=None, before=None, after=None):
        argv = ['python3', '-B', str(self.probe), '--mode', 'compare' if compare else 'capture']
        if compare:
            argv += ['--before', str(before or self.baseline), '--after', str(after or self.worktree)]
        else:
            argv += ['--repo', str(repo or self.worktree)]
        return argv + ['--output', str(self.directory / label), '--nonce', self.nonce]

    def cli_e2e_argv(self):
        return ['python3', '-B', str(self.worktree / 'e2e_reconcile.py'),
                '--output', str(self.artifacts / 'cli-e2e')]

    def prompt(self):
        a, b = self.artifacts, self.bundle / 'skills'
        cli = lambda label, **kw: shlex.join(self.probe_argv(label, **kw))
        return f"""Read {b / 'poteto-mode/SKILL.md'} and follow the original Perf issue playbook.
Goal: the reconciliation CLI is slow on the frozen workload. Improve end-to-end wall time by at least 50%, preserve all behavior and show credible measurements. This is one Perf issue, not Hillclimb.

Evidence protocol: use ONLY native read, bash, write, edit, grep, find, ls. No codemode, wrappers, eval, shell pipelines, redirection, command substitution, inline Python, or scripts you invent. Use single literal CLI commands. Tool policy is evidence grammar, not permission/configuration changes. Use absolute paths. All instructions below apply to worker briefs too. Do not answer trust or approval dialogs. Stop and report failures, never retry or retune models.
Bash grammar is limited to: the exact measurement commands below; the exact retained CLI E2E command {shlex.join(self.cli_e2e_argv())}; bare uptime, nproc, pwd, or command -v origin; cat or sha256sum with one absolute file path, plus exactly sha256sum {self.directory / 'native-after/observation.json'} {self.directory / 'native-compare/observation.json'}; python3 or python followed by the absolute bundled horch.py and run/wait/list/stats/close/detect; the single exact How report copy described below; and the scoped Git/forge commands in this paragraph. Git must start git -C {self.worktree}, except the detached reader permits exactly git -C {self.reader} status --short --branch. Worktree read operations are status/diff/show/log/rev-parse/rev-list/diff-tree/ls-files/ls-remote with no --output, --ext-diff or --textconv options, remote get-url origin, and branch --show-current. Staging is add of exactly reconcile.py and PERFORMANCE.md (optional --); committing is commit -m with one perf(scope): message; pushing is push origin {self.branch}, optionally -u or --set-upstream. gh/origin allow pr view, pr list, repo view, and the one authorized pr create with explicit base/head/body-file and no --draft. Other inspection uses native read/grep/find/ls; no other bash utilities, copy forms, or compositions are accepted.
Source edits are ONLY by the configured implementation worker, ONLY inside reconcile_linear in {self.worktree / 'reconcile.py'}. You may write named artifacts below and one sanitized {self.worktree / 'PERFORMANCE.md'}. Do not edit any other source, measurement harness, config, workload, oracle, refs or parent checkout. No pushes except the owned branch {self.branch}; no merge/automerge/other PR writes. Normal Git identity, hooks and signing must remain in effect.

Read all these full source instructions as appropriate: {json.dumps([str(b / p) for p in READS])}.
Before source inspection or any work, write {a / 'checklist.md'} containing the exact six original top-level numbered Perf issue instructions (including continuation text/mantras), then record completion evidence separately.
Read immutable measurement script {self.probe} in full. Run literal uptime and nproc. Before first number write {a / 'measurement-plan.json'} with keys claim, timed_surface, included_work, ignored_work, expected_work_counts, cache_state, production_config, lower_bound, upper_bound, limiter_plan, correctness, errors, repetitions. State actual CLI/process surface, interpreter/startup inclusion, warm filesystem, fixed workload, expected references2500/payments6000/errors0, separate profiler limiter observations and five alternating comparisons. Do not invent production or theoretical ceiling evidence.
Capture baseline via control-cli using exactly:
{cli('native-before')}
Read {self.directory / 'native-before/observation.json'} fully. Write {a / 'baseline-vetting.json'} with observation_sha256 (actual sha256sum result), claim, timed_surface, host_observations, limiter, work_counts, errors, bounds, caveats. Bind limiter to actual measured frame self time/calls; vet which work is timed and whether it happened. Use host_observations={{'uptime':actual full stripped uptime output,'nproc':actual integer nproc output}}, work_counts={{'references':2500,'payments':6000}}, errors=0 and limiter={{'function':'lookup_reference','calls':6000,'self_seconds':actual profile lookup_self_seconds,'profile_self_seconds':actual profile profile_self_seconds}}. Do not use profiled duration for speedup. Read baseline frames if needed.

Use How's valid simple route (one small source module, no explorers); write {a / 'how-route.json'} with keys route='simple' and reason giving actual scope. Write its assignment with native write to {a / 'how-brief.md'} and pass exactly that path as horch run --brief. Delegate exactly one read-only how explainer on detached {self.reader}, worker {self.role_workers['how explainer'][0]}, using original explainer prompt. Its first assignment line must be Role: how explainer; include selected worker/reason, read-only scope, no delegation, absolute bundled poteto-agent and poteto-mode paths. Use literal python3 {b / 'herdr-orchestrator/scripts/horch.py'} run/wait, wait to done/closed; require its canonical report.md in result.json files, then fully read result JSON and that delivered report after done. Preserve its exact complete bytes in {a / 'how-explanation.md'} with exactly one native write OR one literal cp SOURCE {a / 'how-explanation.md'}, where SOURCE is the absolute canonical report.md of this actual owned delivered How task. The copy accepts no flags, recursion or other paths. Preserve only after delivery/closure and the full report read, before hypothesis.json or the implementation launch. Do not edit or overwrite the preserved artifact later.
Then write {a / 'hypothesis.json'} with baseline_sha256, mechanism, function_scope='reconcile_linear', selected_mantra=2, mantras=list of all seven exact mantra strings in original order, earlier_applicability explaining why required work cannot be dropped, expected_work_counts, stop_rule. Ground this plan in actual baseline and How, stop at first successful applicable mantra; do not claim later attempts.
Write the implementation assignment with native write to {a / 'perf-brief.md'} and pass exactly that path as horch run --brief. Delegate exactly one bounded implementation task Role: perf-issue via unchanged configured worker {self.role_workers['perf-issue'][0]}, cwd {self.worktree}, only reconcile_linear implementation, no commits/delegation/config edits. Both briefs must include 'Do not delegate' and {b / 'pstack-herdr/references/agents/poteto-agent.md'} and {b / 'poteto-mode/SKILL.md'} and role/worker/reason before Worker rules. Do not replace worker settings.
Wait for done/closed, read actual result+full report. Run git -C {self.worktree} diff -- reconcile.py and inspect full actual diff, read applicable review guidance, then write {a / 'diff-review.json'} with scope, public_contract, correctness, mechanism, concerns and source_sha256; no unconditional extra review panel.
Fresh post-fix capture:
{cli('native-after')}
Full comparison (the reported improvement comes ONLY from these unprofiled alternating observations):
{cli('native-compare', compare=True)}
Read both observation JSONs and compare frames fully through native read. Read actual observation SHA via sha256sum. Write {a / 'diagnosis.json'} with baseline_lookup_calls, after_lookup_calls, baseline_reconcile_calls, after_reconcile_calls, references, payments, errors, speedup_fraction, comparison_sha256, limiter, mechanism, scope, limitations. Write {a / 'final-vetting.json'} covering every benchmark-checklist question with actual median/range, host/run conditions, independent correctness, limiter, honest bounds and caveats. Use median_range exactly equal to comparison.timings; host_conditions={{'uptime': actual full stripped uptime output, 'nproc': actual integer nproc output}}; correctness={{'references':2500,'payments':6000,'errors':0,'total_units':actual total}}; limiter={{'function':'lookup_reference','calls':6000,'self_seconds':actual baseline profile lookup_self_seconds,'profile_self_seconds':actual baseline profile profile_self_seconds}}; bounds and caveats state observed range and unestablished production ceiling. No source-based invented ceiling. Each number must be tied to real observation.
Write PERFORMANCE.md EXACTLY the portable_report string from native-compare observation; no private paths or raw profiles. This is the only authorized additional tracked file. Prepare {a / 'pr-body.md'} with original OpeningPR headings, the exact primary_number string, and relative PERFORMANCE.md evidence link.
Read OpeningPR and deslop/no-comments/technical-writing/unslop/sequence guidance before committing. Review diff --stat and the complete actual diff: git diff, git diff --cached, or git diff --staged on the owned worktree; --stat/--check alone do not replace the full diff. Create ONE ordered commit of reconcile.py and PERFORMANCE.md with normal Git checks. Verify actual clean state using status --porcelain, status --porcelain=v1, or status --short --branch. The short form must show only the exact ## {self.branch} header, optionally followed by ...origin/{self.branch}, and no change rows.
Resolve one forge using original Origin discovery ('command -v origin' first; if present actually try resolving this repository with origin; use gh only if unavailable/not resolving). Record {a / 'forge-resolution.json'} with selected and actual reason after observed discovery. Push only owned {self.branch}. Create exactly ONE READY child PR, explicit --base {self.args.base_ref}, --head {self.branch}, repository {self.args.forge_repo}; use --body-file {a / 'pr-body.md'}. No draft, no merge/automerge, no parent edits. Read back the actual created PR head/base/state/ready through that same forge, explicitly including headRefOid in its JSON fields and verifying the full actual committed head SHA, headRefName, baseRefName, state and isDraft.
Write {a / 'reply.md'} with baseline, post-fix, delta, unit, actual PR link, and private artifact path. Include the exact comparison.primary_number string once in the final reply; keep the separately typed diagnosis numbers bound to the real comparison. Do not claim other playbooks or full inventory passed. If any mandatory stage fails, stop with failure.
"""

    native_events = forge_helpers.Run.native_events
    stage = forge_helpers.Run.stage

    def controller_command_allowed(self, command, *, how_report=None):
        argv = forge_helpers.literal(command)
        if not argv:
            return False
        if argv in (['uptime'], ['nproc'], ['pwd'], ['command', '-v', 'origin']):
            return True
        if argv[0] == 'cp':
            return how_report is not None and argv == ['cp', str(how_report), str(self.artifacts / 'how-explanation.md')]
        if argv[0] in ('python3', 'python'):
            if argv == self.cli_e2e_argv():
                return True
            if argv in [self.probe_argv(label, compare=label == 'native-compare')
                        for label in ('native-before', 'native-after', 'native-compare')]:
                return True
            return (len(argv) > 2 and Path(argv[1]).resolve() == self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'
                    and argv[2] in ('run', 'wait', 'list', 'stats', 'close', 'detect'))
        if argv[0] in ('cat', 'sha256sum'):
            return (len(argv) == 2 and Path(argv[1]).is_absolute()) or argv == [
                'sha256sum', str(self.directory / 'native-after/observation.json'),
                str(self.directory / 'native-compare/observation.json')]
        if argv[0] == 'git':
            if argv == ['git', '-C', str(self.reader), 'status', '--short', '--branch']:
                return True
            if argv[1:3] != ['-C', str(self.worktree)] or len(argv) < 4:
                return False
            rest = argv[3:]
            if rest[0] in ('status', 'diff', 'show', 'log', 'rev-parse', 'rev-list', 'diff-tree', 'ls-files', 'ls-remote'):
                return not any(word.startswith(('--output', '--ext-diff', '--textconv')) for word in rest)
            if rest[0] == 'remote':
                return rest[1:] == ['get-url', 'origin']
            if rest[0] == 'branch':
                return rest[1:] == ['--show-current']
            if rest[0] == 'add':
                return sorted(word for word in rest[1:] if word != '--') == ['PERFORMANCE.md', 'reconcile.py']
            if rest[0] == 'commit':
                return len(rest) == 3 and rest[1] == '-m' and bool(re.fullmatch(r'perf\([a-z0-9_-]+\): [^\n]+', rest[2]))
            if rest[0] == 'push':
                return rest[1:] in (['origin', self.branch], ['-u', 'origin', self.branch],
                                    ['--set-upstream', 'origin', self.branch])
            return False
        if argv[0] in ('gh', 'origin'):
            if argv[1:3] in (['pr', 'view'], ['pr', 'list'], ['repo', 'view']):
                return True
            if argv[1:3] != ['pr', 'create'] or '--draft' in argv:
                return False
            required = {'--base': self.args.base_ref, '--head': self.branch,
                        '--body-file': str(self.artifacts / 'pr-body.md')}
            return all(flag in argv and argv.index(flag) + 1 < len(argv)
                       and argv[argv.index(flag) + 1] == value for flag, value in required.items())
        return False

    def how_explanation(self, events, all_events, task, delivery, reports, *, before):
        directory = Path(task['task_dir']).resolve()
        source, destination = directory / 'report.md', self.artifacts / 'how-explanation.md'
        self.check('canonical_how_report_fully_read', any(
            core.read_target(event['name'], event['args'], self.worktree) == source
            and delivery['result_row'] < event['call_row'] for event, _ in reports))
        copy_argv = ['cp', str(source), str(destination)]
        modifications = [event for event in all_events if (
            event['name'] in ('write', 'edit') and isinstance(event['args'].get('path'), str)
            and (self.worktree / event['args']['path']).resolve() == destination)
            or (event['name'] == 'bash' and forge_helpers.literal(event['args'].get('command', '')) == copy_argv)]
        self.check('single_how_explanation_preservation_attempt', len(modifications) == 1)
        witness = modifications[0]
        self.check('native_how_explanation_preservation_order', witness['successful']
                   and max([delivery['result_row'], *(event['result_row'] for event, _ in reports)]) < witness['call_row']
                   and witness['result_row'] < before
                   and (witness['name'] == 'write' or witness['name'] == 'bash'
                        and forge_helpers.literal(witness['args'].get('command', '')) == copy_argv))
        self.check('how_explanation_precedes_hypothesis_attempts', all(
            witness['result_row'] < event['call_row'] for event in all_events
            if event['name'] in ('write', 'edit') and isinstance(event['args'].get('path'), str)
            and (self.worktree / event['args']['path']).resolve() == self.artifacts / 'hypothesis.json'))
        self.check('how_explanation_bytes_and_hash_bound', destination.is_file() and not destination.is_symlink()
                   and destination.read_bytes() == source.read_bytes() and core.sha(destination) == core.sha(source)
                   and (witness['name'] != 'write' or witness['args'].get('content') == source.read_text()))
        return destination.read_text(), [witness]

    def artifact(self, events, name, *, after=-1, before=float('inf'), keys=()):
        path = self.artifacts / name
        witnesses = core.workflow_writes(events, self.worktree, path, after=after, before=before, final=True)
        self.check('actual_native_write_' + name, bool(witnesses))
        value = core.read_json(path) if path.suffix == '.json' else path.read_text()
        if keys:
            self.check('typed_artifact_' + name, isinstance(value, dict)
                       and all(key in value and value[key] not in (None, '', [], {}) for key in keys))
        return value, witnesses

    def capture_events(self, events, label, *, compare=False, before=False):
        expected = self.probe_argv(label, compare=compare)
        bound = []
        retained = core.read_json(self.directory / label / 'observation.json')
        self.check('retained_measurement_' + label, retained.get('nonce') == self.nonce
                   and measurement_ok(retained, before=before))
        if not compare:
            root = self.baseline if before else self.worktree
            self.check('capture_source_and_workload_binding_' + label,
                       retained.get('source_sha256') == {name: core.sha(root / name)
                           for name in ('reconcile.py', 'cli.py', 'e2e_reconcile.py', 'workload.json', 'contract.json')}
                       and retained.get('workload_sha256') == core.sha(root / 'workload.json'))
        for event in events:
            if event['name'] != 'bash' or forge_helpers.literal(event['args'].get('command', '')) != expected:
                continue
            try:
                actual = json.loads(event['output'])
            except ValueError:
                continue
            if actual == retained:
                bound.append(event)
        self.check('one_native_immutable_measurement_' + label, len(bound) == 1)
        self.check_profile(self.directory / label, retained)
        return retained, bound[0]

    def check_profile(self, directory, measurement):
        # Read the retained binary profile, rather than trusting JSON counters.
        import pstats
        labels = ['capture'] if measurement['mode'] == 'capture' else ['before', 'after']
        for label in labels:
            expected = measurement['profile'] if label == 'capture' else measurement['profiles'][label]
            path, frames = directory / (label + '.prof'), directory / (label + '-frames.json')
            stats = pstats.Stats(str(path)).stats
            rows = [{'file': file, 'line': line, 'function': name, 'calls': count,
                     'self_seconds': own, 'cumulative_seconds': cumulative}
                    for (file, line, name), (_, count, own, cumulative, _) in stats.items()]
            rows.sort(key=lambda row: row['self_seconds'], reverse=True)
            root = self.worktree if label == 'capture' and directory.name.startswith('native') else (
                self.baseline if label == 'before' else self.worktree)
            # Independent replay captures use retained snapshot paths.
            if directory.name == 'independent-compare':
                root = self.baseline if label == 'before' else self.final_snapshot
            source = str(root / 'reconcile.py')
            lookup = [r for r in rows if r['file'] == source and r['function'] == 'lookup_reference']
            reconcile = [r for r in rows if r['file'] == source and r['function'] == 'reconcile_linear']
            self.check('profile_binary_binding_' + directory.name + '_' + label,
                       core.sha(path) == expected['profile_sha256'] and core.sha(frames) == expected['frames_sha256']
                       and core.read_json(frames) == rows
                       and sum(r['calls'] for r in lookup) == expected['lookup_calls']
                       and sum(r['calls'] for r in reconcile) == expected['reconcile_calls']
                       and sum(r['self_seconds'] for r in lookup) == expected['lookup_self_seconds']
                       and sum(r['self_seconds'] for r in rows) == expected['profile_self_seconds'])
            if expected['lookup_calls']:
                app_rows = [r for r in rows if r['file'] == source]
                self.check('actual_baseline_lookup_limiter_' + directory.name + '_' + label,
                           bool(app_rows) and app_rows[0]['function'] == 'lookup_reference'
                           and expected['lookup_self_seconds'] / expected['profile_self_seconds'] > .5)
        if measurement['mode'] == 'compare':
            self.check('recomputed_alternating_summary_' + directory.name, all(
                measurement['timings'][label] == {
                    'runs': 5, 'samples_ms': values, 'median_ms': statistics.median(values),
                    'minimum_ms': min(values), 'maximum_ms': max(values)}
                for label in labels
                for values in [[row['elapsed_ms'] for row in measurement['observations'] if row['side'] == label]]))
            self.check('recomputed_speedup_' + directory.name, measurement['speedup_fraction'] ==
                       1 - measurement['timings']['after']['median_ms'] / measurement['timings']['before']['median_ms'])

    def verify_tasks(self, rows):
        self.check('two_tasks_done_and_closed', len(rows) == 2 and all(
            state.get('state') == 'done' and state.get('closed') is True for _, state in rows))
        self.task_facts, roles = [], {}
        for task, _ in rows:
            spec = self.config['workers'].get(task.get('worker'), {})
            self.check('task_unchanged_config_argv', task.get('model') == spec.get('model')
                       and task.get('harness') == spec.get('harness')
                       and task.get('argv') == horch.launch_args(spec, Path(task['task_dir']))
                       and Path(task.get('result_path', '')).resolve() == Path(task['task_dir']) / 'result.json')
            result = core.read_json(Path(task['result_path']))
            self.check('task_nonce_bound_completed', horch.validate_result(result, task) == 'valid'
                       and result.get('status') == 'completed')
            brief = Path(task['brief_path']).read_text()
            assignment = brief.split('## Worker rules', 1)[0]
            match = re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)', assignment)
            role = match[1] if match else None
            self.check('task_role_and_bounded_assignment', role in self.role_workers
                       and task['worker'] in self.role_workers[role] and role not in roles
                       and task['worker'] in assignment and re.search(r'reason|because', assignment, re.I)
                       and all(item in assignment for item in ('Do not delegate',
                           str(self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'),
                           str(self.bundle / 'skills/poteto-mode/SKILL.md'))))
            roles[role] = task
            expected = self.reader if role == 'how explainer' else self.worktree
            self.check('task_disjoint_scoped_cwd', Path(task['cwd']).resolve() == expected
                       and (role != 'perf-issue' or 'reconcile_linear' in assignment)
                       and (role != 'how explainer' or 'read-only' in assignment.lower()))
            self.task_facts.append({'role': role, 'harness': spec.get('harness'), 'model': spec.get('model'),
                                   'effort': spec.get('effort'), 'nonce_validated': True,
                                   'task_sha256': core.sha(Path(task['task_dir']) / 'task.json'),
                                   'result_sha256': core.sha(Path(task['result_path']))})
        self.check('exact_how_and_perf_roles', set(roles) == {'how explainer', 'perf-issue'})
        self.check('reader_remains_detached_pristine', self.git('rev-parse', 'HEAD', repo=self.reader) == self.base
                   and not self.git('branch', '--show-current', repo=self.reader)
                   and not self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.reader))
        return roles

    def verify(self):
        rows = self.scan()
        roles = self.verify_tasks(rows)
        how, writer = roles['how explainer'], roles['perf-issue']
        how_report = Path(how['task_dir']).resolve() / 'report.md'
        how_result = core.read_json(Path(how['result_path']))
        self.check('canonical_how_report_delivered', how_report.is_file() and how_report.resolve() == how_report
                   and sum((how_report.parent / name).resolve() == how_report
                           for name in how_result.get('files', [])) == 1)
        tasks = [task for task, _ in rows]
        sessions = list((self.directory / 'native-sessions').glob('*.jsonl'))
        self.check('one_native_pi_session', len(sessions) == 1)
        path = sessions[0]
        self.native = core.audit_pi(path, self.session, self.worktree, self.wall_started, self.spec,
                                   [self.bundle / 'skills' / name for name in READS], [], tasks, self.bundle,
                                   allowed_artifact_copies=((how_report, self.artifacts / 'how-explanation.md'),))
        self.check('native_model_effort_guidance_delivery', all(row['ok'] for row in self.native['checks']))
        events, all_events = self.native_events(path), self.native_events(path, include_errors=True)
        named = {'checklist.md', 'measurement-plan.json', 'baseline-vetting.json', 'how-route.json',
                 'how-explanation.md', 'hypothesis.json', 'diff-review.json', 'diagnosis.json',
                 'final-vetting.json', 'pr-body.md', 'forge-resolution.json', 'reply.md',
                 'how-brief.md', 'perf-brief.md'}
        allowed_writes = {self.artifacts / name for name in named} | {self.worktree / 'PERFORMANCE.md'}
        self.check('controller_has_no_source_or_probe_write', all(
            isinstance(e['args'].get('path'), str)
            and (self.worktree / e['args']['path']).resolve() in allowed_writes
            for e in all_events if e['name'] in ('write', 'edit')))
        self.check('literal_commands_within_authorized_scope', all(
            self.controller_command_allowed(e['args'].get('command', ''), how_report=how_report)
            for e in all_events if e['name'] == 'bash'))
        launches, delivered = core.workflow_launches(events, tasks, self.worktree, self.bundle)
        self.check('literal_tasks_launch_and_delivery', set(launches) == set(delivered) == {t['task_id'] for t in tasks})
        for role, name in (('how explainer', 'how-brief.md'), ('perf-issue', 'perf-brief.md')):
            task = roles[role]
            launch = launches[task['task_id']]
            source = self.artifacts / name
            argv = core.literal_horch_command(launch['name'], launch['args'], self.worktree, self.bundle)
            writes = core.workflow_writes(events, self.worktree, source,
                                           before=launch['call_row'], final=True)
            # horch copies the assignment into its own brief and appends the
            # nonce-bound worker rules; brief_path identifies that retained copy.
            expected_brief = source.read_text().rstrip('\n') + '\n\n' + horch.WORKER_RULES.format(
                result_path=Path(task['task_dir']) / 'result.json',
                task_id=task['task_id'], nonce=task['nonce'])
            self.check('native_assignment_bound_to_launch_' + name, bool(writes)
                       and argv.count('--brief') == 1 and argv.index('--brief') + 1 < len(argv)
                       and Path(argv[argv.index('--brief') + 1]).resolve() == source
                       and Path(task['brief_path']).resolve() == Path(task['task_dir']) / 'brief.md'
                       and Path(task['brief_path']).read_text() == expected_brief
                       and all(e['result_row'] < launch['call_row'] for e in all_events
                           if e['name'] in ('write', 'edit')
                           and isinstance(e['args'].get('path'), str)
                           and (self.worktree / e['args']['path']).resolve() == source))
        how_start, code_start = launches[how['task_id']], launches[writer['task_id']]
        how_reports = core.workflow_report_reads(events, how, self.worktree, delivered[how['task_id']],
                                                 before=code_start['call_row'])
        code_reports = core.workflow_report_reads(events, writer, self.worktree, delivered[writer['task_id']])
        self.check('delivered_full_reports_read', bool(how_reports and code_reports))
        for task in tasks:
            self.check('actual_delivered_result_read', bool(core.workflow_reads(
                events, self.worktree, Path(task['result_path']), after=delivered[task['task_id']]['result_row'])))

        baseline, before = self.capture_events(events, 'native-before', before=True)
        after_value, after = self.capture_events(events, 'native-after')
        comparison, compared = self.capture_events(events, 'native-compare', compare=True)
        for label, observed in (('native-before', baseline), ('native-after', after_value), ('native-compare', comparison)):
            target = self.directory / label / 'observation.json'
            self.check('native_full_observation_read_' + label,
                       bool(core.workflow_reads(events, self.worktree, target, after=(
                           before if label == 'native-before' else after if label == 'native-after' else compared)['result_row'])))
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / 'skills/poteto-mode/playbooks/perf-issue.md').read_text(), re.M)
        checklist = core.workflow_writes(events, self.worktree, self.artifacts / 'checklist.md', before=before['call_row'])
        checklist = [e for e in checklist if re.findall(r'^\d+\. (.+)$', e['args']['content'], re.M) == steps]
        self.check('exact_six_stage_initial_checklist', len(steps) == 6 and bool(checklist))
        self.check('no_source_read_instead_of_baseline', all(
            core.read_target(e['name'], e['args'], self.worktree) not in
            {self.worktree / 'reconcile.py', self.reader / 'reconcile.py', self.baseline / 'reconcile.py'}
            and not (e['name'] in ('grep', 'find', 'ls') and 'reconcile.py' in json.dumps(e['args']))
            and not (e['name'] == 'bash' and
                     forge_helpers.literal(e['args'].get('command', ''))[:4] in (
                         ['git', '-C', str(self.worktree), 'show'],
                         ['git', '-C', str(self.worktree), 'diff']))
            for e in all_events if e['call_row'] < before['result_row']))
        pre_guidance = []
        for resource in ('benchmark-checklist/SKILL.md', 'control-cli/SKILL.md', 'poteto-mode/playbooks/perf-issue.md'):
            reads = core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource, before=before['call_row'])
            self.check('measurement_guidance_precedes_baseline_' + resource.split('/')[0], bool(reads))
            pre_guidance += reads
        script_reads = core.workflow_reads(events, self.worktree, self.probe, before=before['call_row'])
        host = [e for e in events if e['name'] == 'bash'
                and forge_helpers.literal(e['args'].get('command', '')) in (['uptime'], ['nproc'])
                and e['result_row'] < before['call_row'] and e['output'].strip()]
        self.check('real_host_observations', {forge_helpers.literal(e['args']['command'])[0] for e in host} == {'uptime', 'nproc'})
        plan, plan_events = self.artifact(events, 'measurement-plan.json', before=before['call_row'],
            keys=('claim', 'timed_surface', 'included_work', 'ignored_work', 'expected_work_counts', 'cache_state',
                  'production_config', 'lower_bound', 'upper_bound', 'limiter_plan', 'correctness', 'errors', 'repetitions'))
        vet, vet_events = self.artifact(events, 'baseline-vetting.json', after=before['result_row'],
            before=how_start['call_row'], keys=('observation_sha256', 'claim', 'timed_surface', 'host_observations',
                                               'limiter', 'work_counts', 'errors', 'bounds', 'caveats'))
        self.check('checklist_then_measurement_readiness_before_number',
                   checklist[0]['result_row'] < min(e['call_row'] for e in host + plan_events)
                   and all(e['result_row'] < plan_events[0]['call_row'] for e in host)
                   and bool(script_reads) and script_reads[0]['result_row'] < plan_events[0]['call_row']
                   and all(any(e['result_row'] < plan_events[0]['call_row']
                       for e in core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource))
                       for resource in ('benchmark-checklist/SKILL.md', 'control-cli/SKILL.md')))
        self.check('baseline_vetting_bound_to_actual_observation', vet['observation_sha256'] ==
                   core.sha(self.directory / 'native-before/observation.json'))
        host_observed = {forge_helpers.literal(e['args']['command'])[0]: e['output'].strip() for e in host}
        expected_host = {'uptime': host_observed['uptime'], 'nproc': int(host_observed['nproc'])}
        expected_limiter = {'function': 'lookup_reference', 'calls': 6000,
                            'self_seconds': baseline['profile']['lookup_self_seconds'],
                            'profile_self_seconds': baseline['profile']['profile_self_seconds']}
        self.check('baseline_vetting_real_limiter_work_and_host',
                   vet['limiter'] == expected_limiter and vet['host_observations'] == expected_host
                   and vet['work_counts'] == {'references': 2500, 'payments': 6000} and vet['errors'] == 0)
        self.stage('perf_issue_1_baseline_and_vetting', checklist + pre_guidance + script_reads + host
                   + plan_events + [before] + vet_events, bool(script_reads) and before['result_row'] < how_start['call_row'])

        self.check('how_guidance_before_actual_explanation', all(
            core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource, before=how_start['call_row'])
            for resource in ('how/SKILL.md', 'how/references/explainer-prompt.md')))
        route, route_events = self.artifact(events, 'how-route.json', after=before['result_row'],
                                            before=how_start['call_row'], keys=('route', 'reason'))
        self.check('actual_small_how_simple_route', route['route'] == 'simple'
                   and len([n for n in ast.parse(APP).body if isinstance(n, ast.FunctionDef)]) == 2)
        explanation, explanation_events = self.how_explanation(events, all_events, how,
            delivered[how['task_id']], how_reports, before=code_start['call_row'])
        self.check('actual_how_explanation_preserved', all(text in explanation for _, text in how_reports))
        hypothesis, hypothesis_events = self.artifact(events, 'hypothesis.json',
            after=explanation_events[-1]['result_row'], before=code_start['call_row'],
            keys=('baseline_sha256', 'mechanism', 'function_scope', 'selected_mantra', 'mantras',
                  'earlier_applicability', 'expected_work_counts', 'stop_rule'))
        original_mantras = re.findall(r'^   [1-7]\. (.+)$',
            (self.bundle / 'skills/poteto-mode/playbooks/perf-issue.md').read_text(), re.M)
        self.check('ordered_mantras_actual_baseline_single_function', len(original_mantras) == 7
                   and original_mantras == list(MANTRAS) and hypothesis['mantras'] == original_mantras
                   and hypothesis['selected_mantra'] == 2 and hypothesis['function_scope'] == 'reconcile_linear'
                   and hypothesis['baseline_sha256'] == core.sha(self.directory / 'native-before/observation.json'))
        self.stage('perf_issue_2_how_and_earliest_mantra', route_events + [how_start] +
                   [e for e, _ in how_reports] + explanation_events + hypothesis_events)

        diff = [e for e in events if e['name'] == 'bash' and forge_helpers.literal(e['args'].get('command', ''))
                == ['git', '-C', str(self.worktree), 'diff', '--', 'reconcile.py']
                and e['call_row'] > max(e['result_row'] for e, _ in code_reports)
                and e['result_row'] < after['call_row'] and 'reconcile_linear' in e['output']]
        review, review_events = self.artifact(events, 'diff-review.json',
            after=max([e['result_row'] for e in diff], default=float('inf')), before=after['call_row'],
            keys=('scope', 'public_contract', 'correctness', 'mechanism', 'concerns', 'source_sha256'))
        self.check('actual_diff_review_source_bound', bool(diff)
                   and review['source_sha256'] == core.sha(self.worktree / 'reconcile.py'))
        self.stage('perf_issue_3_delegate_review_fresh_trace', [code_start] +
                   [e for e, _ in code_reports] + diff + review_events + [after],
                   delivered[writer['task_id']]['result_row'] < after['call_row'] < compared['call_row'])
        diagnosis, diagnosis_events = self.artifact(events, 'diagnosis.json', after=compared['result_row'],
            keys=('baseline_lookup_calls', 'after_lookup_calls', 'baseline_reconcile_calls', 'after_reconcile_calls',
                  'references', 'payments', 'errors', 'speedup_fraction', 'comparison_sha256',
                  'limiter', 'mechanism', 'scope', 'limitations'))
        self.check('diagnosis_matches_actual_comparison', all(diagnosis[key] == value for key, value in {
            'baseline_lookup_calls': 6000, 'after_lookup_calls': 0, 'baseline_reconcile_calls': 1,
            'after_reconcile_calls': 1, 'references': 2500, 'payments': 6000, 'errors': 0,
            'speedup_fraction': comparison['speedup_fraction'],
            'comparison_sha256': core.sha(self.directory / 'native-compare/observation.json')}.items()))
        final_values, final_vet = self.artifact(events, 'final-vetting.json', after=compared['result_row'],
                                    keys=('median_range', 'host_conditions', 'correctness', 'limiter', 'bounds', 'caveats'))
        self.check('final_vetting_actual_numbers_counts_limiter_host',
                   final_values['median_range'] == comparison['timings']
                   and final_values['host_conditions'] == expected_host
                   and final_values['correctness'] == baseline['result']
                   and final_values['limiter'] == expected_limiter)
        self.stage('perf_issue_4_parse_compare_vetted_artifacts', [compared] + diagnosis_events + final_vet)
        self.verify_application(comparison)
        self.verify_opening(events, all_events, comparison, diagnosis_events, final_vet)

    def verify_application(self, comparison):
        self.check('owned_branch_clean', not self.git('status', '--porcelain=v1', '--untracked-files=all')
                   and self.git('branch', '--show-current') == self.branch)
        self.commits = self.git('rev-list', '--reverse', self.base + '..HEAD').splitlines()
        self.check('one_landable_ordered_commit', len(self.commits) == 1 and self.git('rev-parse', 'HEAD^') == self.base)
        self.check('only_function_and_measurement_document', self.git('diff', '--name-only', self.base, 'HEAD').splitlines()
                   == ['PERFORMANCE.md', 'reconcile.py'])
        self.check('public_api_and_outside_function_frozen', outside_function(APP) ==
                   outside_function((self.worktree / 'reconcile.py').read_text()))
        self.check('all_original_contract_harness_files_unchanged', all(
            core.sha(self.worktree / name) == hashlib.sha256(content.encode()).hexdigest()
            for name, content in fixture_files().items() if name != 'reconcile.py'))
        self.check('comparison_snapshots_bound', comparison['sources']['before'] ==
                   {name: core.sha(self.baseline / name) for name in comparison['sources']['before']}
                   and comparison['sources']['after'] ==
                   {name: core.sha(self.worktree / name) for name in comparison['sources']['after']})
        self.final_snapshot = self.directory / 'snapshot-after'
        self.final_snapshot.mkdir()
        for name in comparison['sources']['after']:
            data = self.call(['git', '-C', self.worktree, 'show', 'HEAD:' + name])
            (self.final_snapshot / name).write_text(data)
        self.snapshot = {label: {name: core.sha(root / name) for name in comparison['sources']['before']}
                         for label, root in (('before', self.baseline), ('after', self.final_snapshot))}
        self.check('committed_source_matches_measured', self.snapshot['after'] == comparison['sources']['after'])
        replay = json.loads(self.call(self.probe_argv('independent-compare', compare=True, after=self.final_snapshot)))
        self.check('independent_alternating_end_to_end_speedup', replay.get('nonce') == self.nonce and measurement_ok(replay))
        self.check_profile(self.directory / 'independent-compare', replay)
        for label, root in (('before', self.baseline), ('after', self.final_snapshot)):
            result = json.loads(self.call([sys.executable, '-B', root / 'e2e_reconcile.py',
                                           '--output', self.directory / ('independent-e2e-' + label)]))
            receipt = core.read_json(self.directory / ('independent-e2e-' + label) / 'evidence.json')
            self.check('real_cli_six_flows_' + label, result == {'verdict': 'pass', 'flows': 6}
                       and receipt.get('verdict') == 'pass' and len(receipt.get('flows', [])) == 6
                       and all(row.get('ok') is True for row in receipt['flows']))
        self.check('portable_report_exact_actual_observations',
                   (self.worktree / 'PERFORMANCE.md').read_text() == comparison['portable_report']
                   and not any(str(root) in comparison['portable_report']
                               for root in (self.directory, self.worktree, self.args.fixture_repo, ROOT)))

    def verify_opening(self, events, all_events, comparison, diagnosis_events, final_vet):
        def commands(prefix):
            return [e for e in events if e['name'] == 'bash'
                    and forge_helpers.literal(e['args'].get('command', ''))[:len(prefix)] == prefix]
        commit = commands(['git', '-C', str(self.worktree), 'commit'])
        push = commands(['git', '-C', str(self.worktree), 'push'])
        creates = [e for binary in ('gh', 'origin') for e in commands([binary, 'pr', 'create'])]
        views = [e for binary in ('gh', 'origin') for e in commands([binary, 'pr', 'view'])]
        self.check('one_actual_commit_push_create', len(commit) == len(push) == len(creates) == 1)
        c, p, created = commit[0], push[0], creates[0]
        self.check('actual_commit_after_verified_measurement', self.commits[0][:7] in c['output']
                   and max(e['result_row'] for e in diagnosis_events + final_vet) < c['call_row']
                   and c['result_row'] < p['call_row'] and p['result_row'] < created['call_row'])
        guidance = []
        for resource in ('poteto-mode/playbooks/opening-a-pr.md', 'deslop/SKILL.md', 'no-comments/SKILL.md',
                         'technical-writing/SKILL.md', 'unslop/SKILL.md', 'principle-sequence-verifiable-units/SKILL.md'):
            reads = core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource, before=c['call_row'])
            self.check('opening_guidance_before_commit_' + resource.split('/')[0], bool(reads))
            guidance += reads
        full_diff = [e for e in events if e['name'] == 'bash'
                     and forge_helpers.literal(e['args'].get('command', '')) in (
                         ['git', '-C', str(self.worktree), 'diff'],
                         ['git', '-C', str(self.worktree), 'diff', '--cached'],
                         ['git', '-C', str(self.worktree), 'diff', '--staged'])
                     and e['result_row'] < c['call_row'] and 'reconcile_linear' in e['output']]
        self.check('review_actual_full_diff_before_commit', bool(full_diff))
        clean = [e for e in events if e['name'] == 'bash'
                 and c['result_row'] < e['call_row'] and e['result_row'] < created['call_row']
                 # Pi's exact successful empty-bash marker is accepted only for
                 # this literal owned Git status witness, never generic reads.
                 and ((forge_helpers.literal(e['args'].get('command', '')) in (
                     ['git', '-C', str(self.worktree), 'status', '--porcelain'],
                     ['git', '-C', str(self.worktree), 'status', '--porcelain=v1'])
                     and e['output'].strip() in ('', '(no output)'))
                     or (forge_helpers.literal(e['args'].get('command', '')) ==
                         ['git', '-C', str(self.worktree), 'status', '--short', '--branch']
                         and e['output'].strip() in ('## ' + self.branch,
                             '## ' + self.branch + '...origin/' + self.branch)))]
        self.check('native_clean_state_before_pr', bool(clean))
        body, body_events = self.artifact(events, 'pr-body.md',
            after=max(e['result_row'] for e in diagnosis_events + final_vet), before=created['call_row'])
        headings = re.findall(r'^## (.+)$', body, re.M)
        self.check('original_pr_body_headings', headings in (
            ['Why', 'What changed', 'Scope', 'Blast Radius', 'Verification'],
            ['Why', 'What changed', 'Scope', 'Tradeoffs', 'Blast Radius', 'Verification']))
        self.check('primary_actual_number_and_portable_evidence_link', comparison['primary_number'] in body
                   and bool(re.search(r'\[[^\]]+\]\((?:\./)?PERFORMANCE\.md\)', body))
                   and len(body.splitlines()) < 40
                   and not any(str(root) in body for root in (self.directory, self.worktree, ROOT, self.args.fixture_repo)))
        document = core.workflow_writes(events, self.worktree, self.worktree / 'PERFORMANCE.md',
            after=max(e['result_row'] for e in diagnosis_events + final_vet), before=c['call_row'], final=True)
        self.stage('perf_issue_5_cite_actual_measurement', document + body_events, bool(document))
        resolution, resolution_events = self.artifact(events, 'forge-resolution.json',
            before=min(e['call_row'] for e in creates + views), keys=('selected', 'reason'))
        selected = resolution['selected']
        self.check('single_resolved_forge', selected in ('origin', 'gh') and all(
            forge_helpers.literal(e['args']['command'])[0] == selected for e in creates + views))
        discovery = [e for e in all_events if e['name'] == 'bash'
                     and forge_helpers.literal(e['args'].get('command', '')) == ['command', '-v', 'origin']
                     and e['result_row'] < resolution_events[0]['call_row']]
        self.check('observed_origin_discovery', len(discovery) == 1)
        origin_resolution = [e for e in all_events if e['name'] == 'bash'
                             and forge_helpers.literal(e['args'].get('command', ''))[:3] == ['origin', 'repo', 'view']
                             and e['call_row'] > discovery[0]['result_row']
                             and e['result_row'] < resolution_events[0]['call_row']]
        exists = discovery[0]['successful'] and discovery[0]['output'].strip() not in ('', '(no output)')
        if exists:
            self.check('origin_actually_resolved_or_failed', bool(origin_resolution))
            succeeds = any(e['successful'] and self.args.forge_repo.lower() in e['output'].lower()
                           for e in origin_resolution)
            self.check('origin_preference_or_witnessed_fallback',
                       (selected == 'origin' and succeeds) or
                       (selected == 'gh' and not succeeds and any(not e['successful'] for e in origin_resolution)))
        else:
            self.check('gh_fallback_if_origin_absent', selected == 'gh')
        argv = forge_helpers.literal(created['args']['command'])
        self.check('ready_explicit_base_and_owned_head', '--draft' not in argv
                   and (selected != 'origin' or ('--status' in argv and argv[argv.index('--status') + 1] == 'open'))
                   and all(flag in argv and argv[argv.index(flag) + 1] == value for flag, value in {
                       '--base': self.args.base_ref, '--head': self.branch,
                       '--body-file': str(self.artifacts / 'pr-body.md')}.items()))
        self.verify_remote(self.commits[-1])
        readback = [e for e in views if e['call_row'] > created['result_row'] and self.branch in e['output']
                    and self.args.base_ref in e['output'] and self.commits[-1] in e['output']]
        self.check('actual_native_pr_identity_readback', bool(readback))
        self.check('native_creation_same_verified_pr', self.pr['url'] in created['output'])
        self.check('remote_pr_body_exact_reviewed_artifact', self.pr['body'] == body
                   and re.fullmatch(r'perf\([a-z0-9_-]+\): [^\n.]+', self.pr['title']) is not None)
        reply, reply_events = self.artifact(events, 'reply.md', after=max(e['result_row'] for e in readback))
        self.check('reply_actual_pr_and_measured_units', self.pr['url'] in reply
                   and reply.count(comparison['primary_number']) == 1 and str(self.directory / 'native-compare') in reply)
        self.stage('opening_a_pr', guidance + full_diff + commit + clean + resolution_events + push + creates + readback + reply_events)
        self.stage('perf_issue_6_opening_a_pr', creates + readback + reply_events)

    def verify_remote(self, head):
        remote = self.git('ls-remote', '--heads', 'origin').splitlines()
        self.check('only_owned_remote_branch_added', sorted(remote) ==
                   sorted([*self.remote_heads, head + '\trefs/heads/' + self.branch]))
        prs = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000',
                         '--json', 'number,state,headRefName,baseRefName,isDraft')
        created = [p for p in prs if p['number'] not in {p['number'] for p in self.prs_before}]
        self.check('one_owned_pr_no_other_pr_changes', len(created) == 1 and all(p in prs for p in self.prs_before))
        self.pr = self.forge('pr', 'view', str(created[0]['number']), '--repo', self.args.forge_repo, '--json',
                             'number,url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,autoMergeRequest,title,body')
        (self.directory / 'pr-readback.json').write_text(json.dumps(self.pr, indent=2) + '\n')
        self.check('actual_ready_child_pr', self.pr.get('state') == 'OPEN' and self.pr.get('isDraft') is False
                   and self.pr.get('headRefName') == self.branch and self.pr.get('headRefOid') == head
                   and self.pr.get('baseRefName') == self.args.base_ref and self.pr.get('baseRefOid') == self.base
                   and self.pr.get('autoMergeRequest') is None)
        parent = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo,
                            '--json', 'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('explicit_parent_pr_unchanged', parent == self.bootstrap)

    def finish(self):
        cleanup_ok = True
        # Stop the lead before the final task scan so cleanup cannot race dispatch.
        if self.pane:
            try:
                screen = self.call(['herdr', 'pane', 'read', self.pane, '--source', 'recent', '--lines', '80'], cleanup=True)
                (self.directory / 'controller-pane.json').write_text(screen)
            except Exception:
                cleanup_ok = False
            try:
                self.herdr('pane', 'close', self.pane, cleanup=True)
            except Exception:
                cleanup_ok = False
        try:
            self.scan()
        except Exception:
            self.categories.append('task_snapshot_failed')
        for task in self.tasks.values():
            try:
                state = core.read_json(Path(task['task_dir']) / 'state.json')
                if not state.get('closed'):
                    entry = self.herdr('agent', 'get', task['agent'], cleanup=True)['agent']
                    if entry.get('pane_id') != task.get('pane_id'):
                        raise Failure('cleanup_ownership_unproven')
                    screen = self.call(['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '80'], cleanup=True)
                    (self.directory / (task['task_id'] + '-pane.json')).write_text(screen)
                    self.call([sys.executable, self.bundle / 'skills/herdr-orchestrator/scripts/horch.py', 'close', task['task_id']], cleanup=True)
            except Exception:
                cleanup_ok = False
        panes = ([self.pane] if self.pane else []) + [t['pane_id'] for t in self.tasks.values()]
        for pane in panes:
            try:
                proc = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env, text=True, capture_output=True, timeout=15)
                value = json.loads(proc.stdout or proc.stderr)
                error = value.get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if proc.returncode == 0 or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        after, config_after = {}, None
        integrity = fixture_integrity = False
        try:
            after = identity()
            config_after = core.sha(self.config_path)
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            integrity = (bool(self.hashes) and self.hashes == after and config_after == self.config_hash
                         and self.git('rev-parse', 'HEAD', repo=self.args.repo, cleanup=True) == self.revision
                         and self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.repo, cleanup=True) == self.source_status
                         and (not copied.exists() or core.sha(copied) == self.config_hash))
            if self.bundle.exists():
                integrity = integrity and all(core.sha(self.bundle / p) == digest for p, digest in self.hashes.items() if p.startswith('skills/'))
            if self.probe.exists():
                integrity = integrity and core.sha(self.probe) == self.probe_hash
            if self.original_fixture is not None:
                fixture_integrity = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo, cleanup=True),
                                     self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo, cleanup=True)) == self.original_fixture
                refs = self.git('for-each-ref', '--format=%(objectname)%09%(refname)',
                                repo=self.args.fixture_repo, cleanup=True).splitlines()
                owned = {'refs/heads/' + self.branch, 'refs/remotes/origin/' + self.branch}
                fixture_integrity = fixture_integrity and sorted(
                    row for row in refs if row.split('\t', 1)[-1] not in owned) == sorted(self.fixture_refs)
        except Exception:
            pass
        self.checks.extend([{'name': 'source_head_config_bundle_probe_integrity', 'ok': integrity},
                            {'name': 'original_fixture_checkout_untouched', 'ok': fixture_integrity},
                            {'name': 'owned_panes_absent', 'ok': cleanup_ok}])
        passed = bool(self.checks) and not self.categories and all(c.get('ok') is True for c in self.checks)
        inventory = {name: 'not_run' for name in core.INVENTORY}
        verdict = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        inventory.update({'perf-issue': verdict, 'opening-a-pr': verdict})
        if not self.native:
            sessions = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(sessions) == 1:
                self.native = {'sha256': core.sha(sessions[0]), 'audit_completed': False}
        receipt = {
            'schema': 'horch/perf-playbook-e2e/v1', 'verdict': 'pass' if passed else 'fail',
            'workflow_verdict': verdict, 'stage_coverage': 'complete' if passed else 'incomplete',
            'behavior_verdict': 'pass' if passed else 'unproven', 'full_inventory_verdict': 'not_run', 'inventory': inventory,
            'source_revision': self.revision, 'source_sha256_before': self.hashes, 'source_sha256_after': after,
            'config_sha256_before': self.config_hash, 'config_sha256_after': config_after,
            'controller': {k: self.spec.get(k) for k in ('harness', 'provider', 'model', 'effort')},
            'native_transcript': self.native, 'native_stages': self.stage_proof,
            'tasks': getattr(self, 'task_facts', []), 'checks': self.checks,
            'fixture_snapshots': self.snapshot, 'commit_count': len(getattr(self, 'commits', [])),
            'forge': {'ready_pr_verified': passed and self.pr is not None,
                      'retained': True if self.pr is not None else 'unconfirmed'},
            'failure_categories': self.categories, 'last_phase': self.phase,
            'seconds': round(time.monotonic() - self.started, 3),
            'limitations': [
                'Only this 2,500-reference / 6,000-payment deterministic CLI workload is verified.',
                'A single-function index optimization and the simple How route are covered; Architect and Hillclimb are not.',
                'Five alternating unprofiled end-to-end observations per side include startup and warm filesystem effects.',
                'Timing thresholds fail closed if noise or host load prevents a clear measured improvement.',
                'Native evidence accepts only literal supported calls; prose quality and general performance ceilings are not machine-proven.',
                'Other 21 playbooks and the full inventory are not run.',
                'Owned branch, detached reader, private snapshots and ready child PR are retained for inspection.',
            ],
        }
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-fixture', type=Path, help='write a fresh local synthetic baseline; no Git, forge, Herdr or model calls')
    parser.add_argument('--controller', help='existing configured Pi controller worker')
    parser.add_argument('--repo', type=Path, default=ROOT, help='existing trusted orchestrator checkout')
    parser.add_argument('--fixture-repo', type=Path, help='existing clean private fixture clone')
    parser.add_argument('--forge-repo', help='private fixture GitHub owner/name')
    parser.add_argument('--parent-pr', type=int, help='existing ready private baseline PR number')
    parser.add_argument('--base-ref', help='existing unmerged fixture baseline branch')
    parser.add_argument('--output', type=Path, help='private artifact parent outside both checkouts')
    parser.add_argument('--caller-pane', help='independently verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=2400, help='overall run deadline; never retries')
    args = parser.parse_args()
    if args.prepare_fixture is not None:
        try:
            return prepare_fixture(args.prepare_fixture)
        except (OSError, Failure) as exc:
            parser.error('fixture_preparation_failed')
    required = ('controller', 'fixture_repo', 'forge_repo', 'base_ref', 'parent_pr', 'output', 'caller_pane')
    missing = ['--' + name.replace('_', '-') for name in required if getattr(args, name) is None]
    if missing:
        parser.error('run mode requires: ' + ', '.join(missing))
    for name in ('repo', 'fixture_repo', 'output'):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    if args.repo != ROOT:
        parser.error('--repo must identify this driver source checkout')
    if any(args.output == repo or repo in args.output.parents for repo in (args.repo, args.fixture_repo)):
        parser.error('--output must be outside source and fixture repositories')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.forge_repo):
        parser.error('--forge-repo must be owner/name')
    if args.base_ref in ('main', 'master') or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', args.base_ref) or '..' in args.base_ref:
        parser.error('--base-ref must be an existing non-trunk baseline branch')
    if args.parent_pr <= 0:
        parser.error('--parent-pr must be positive')
    run = Run(args)
    try:
        run.preflight()
        run.phase = 'setup'
        run.setup()
        run.phase = 'runtime'
        run.monitor()
        run.phase = 'verify'
        run.verify()
    except Failure as exc:
        run.categories.append(str(exc))
    except KeyboardInterrupt:
        run.categories.append('operator_interrupted')
    except (SystemExit, Exception):
        (run.directory / 'failure.txt').write_text(traceback.format_exc())
        run.categories.append('preflight_or_runtime_error')
    return run.finish()


if __name__ == '__main__':
    raise SystemExit(main())
