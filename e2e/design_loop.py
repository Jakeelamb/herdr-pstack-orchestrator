#!/usr/bin/env python3
"""Real writable Feature/Refactoring playbooks with Architect and private PRs.

Requires an existing clean private invoice fixture, exact base branch and open
parent PR. Prepare a portable baseline with forge_loop.py --prepare-fixture;
create its private repository and ready baseline PR yourself. This driver never
seeds, merges, answers trust, retries failures, or substitutes configured workers.
Private artifacts/worktrees and the ready child PR are retained for inspection.
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
import shutil
import subprocess
import sys
import time
import traceback
import uuid

import forge_loop as support
import playbook_loop as core

ROOT = Path(__file__).resolve().parents[1]
horch = core.horch
Failure = core.Failure
SOURCE_FILES = ('money.py', 'storage.py', 'cli.py', 'e2e_import.py')
THROUGHPUT = ('Blocking first steps', 'Independent workstreams',
              'Shared mutable state', 'Smallest safe decomposition')
READS = (
    'poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
    'pstack-herdr/references/herdr-tools.md', 'herdr-orchestrator/SKILL.md',
    'how/SKILL.md', 'how/references/explorer-prompt.md', 'how/references/explainer-prompt.md',
    'architect/SKILL.md', 'architect/references/runner-prompt.md',
    'architect/references/rationale-template.md', 'architect/references/design-red-flags.md',
    'arena/SKILL.md', 'control-cli/SKILL.md', 'poteto-mode/playbooks/opening-a-pr.md',
    'deslop/SKILL.md', 'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md',
    'principle-model-the-domain/SKILL.md', 'principle-foundational-thinking/SKILL.md',
    'principle-redesign-from-first-principles/SKILL.md',
    'principle-subtract-before-you-add/SKILL.md', 'principle-minimize-reader-load/SKILL.md',
    'principle-prove-it-works/SKILL.md', 'principle-migrate-callers-then-delete-legacy-apis/SKILL.md',
    'principle-separate-before-serializing-shared-state/SKILL.md',
    'principle-sequence-verifiable-units/SKILL.md', 'principle-exhaust-the-design-space/SKILL.md',
    'pstack-herdr/references/agents/comment-sicko.md',
)

# An external immutable oracle witnesses real application failures as JSON data,
# so successful native tool results can bind both before and after observations.
ORACLE = r'''#!/usr/bin/env python3
import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--mode', choices=['characterize', 'feature'], required=True)
a = p.parse_args()
r, d = a.repo.resolve(), a.output.resolve()
d.mkdir(parents=True, exist_ok=False, mode=0o700)
checks, record, raw = [], [], []
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def row(identity, quantity, price, discount=0):
    return {'id': identity, 'quantity': quantity, 'unit_price_cents': price, 'discount_bp': discount}
def charged(value):
    total = Decimal(value['quantity']) * Decimal(value['unit_price_cents']) * (Decimal(1) - Decimal(value['discount_bp']) / Decimal(10000))
    return dict(value, total_cents=int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
def check(name, ok):
    checks.append({'name': name, 'ok': bool(ok)})
def invoke(label, command, store, groups=(), dry=False):
    files = []
    for index, group in enumerate(groups):
        path = d / (label + '-' + str(index) + '.json')
        path.write_text(json.dumps(group, sort_keys=True) + '\n')
        files.append(path)
    before = store.read_bytes() if store.exists() else None
    pending = store.with_suffix('.pending')
    pending_before = pending.read_bytes() if pending.exists() else None
    argv = [sys.executable, '-B', str(r / 'cli.py'), command]
    if dry:
        argv.append('--dry-run')
    argv += [str(store), *map(str, files)]
    x = subprocess.run(argv, cwd=r, capture_output=True, text=True, timeout=30)
    after = store.read_bytes() if store.exists() else None
    raw.append({'label': label, 'argv': argv, 'exit_code': x.returncode, 'stdout': x.stdout, 'stderr': x.stderr})
    error = x.stderr.replace(str(r), '<repo>').replace(str(d), '<artifacts>')
    if error.startswith('Traceback (most recent call last):'):
        error = error.rstrip().splitlines()[-1] + '\n'
    observed = {'label': label, 'exit_code': x.returncode, 'stdout': x.stdout, 'stderr': error,
                'store_before_hex': before.hex() if before is not None else None,
                'store_after_hex': after.hex() if after is not None else None,
                'pending_exists': pending.exists(),
                'pending_before_hex': pending_before.hex() if pending_before is not None else None,
                'pending_after_hex': pending.read_bytes().hex() if pending.exists() else None}
    record.append(observed)
    try:
        value = json.loads(x.stdout)
    except ValueError:
        value = None
    return observed, value
sources = {name: digest(r / name) for name in ['money.py', 'storage.py', 'cli.py', 'e2e_import.py']}
failure = None
try:
    store = d / 'ledger.json'
    old = row('persisted', 2, 49)
    x, value = invoke('seed', 'import', store, [[old]])
    check('seed through CLI', x['exit_code'] == 0 and value == {'count': 1, 'total_cents': 98})
    first = [row('txn-z', 1, 101, 5000), row('txn-a', 2, 333, 3333)]
    second = [row('txn-m', 3, 137, 250), row('txn-0', 0, 999), row('free', 7, 101, 10000)]
    expected = sorted(map(charged, [old, *first, *second]), key=lambda item: item['id'])
    summary = {'count': len(expected), 'total_cents': sum(item['total_cents'] for item in expected)}
    if a.mode == 'feature':
        x, value = invoke('dry-two-files', 'import', store, [first, second], True)
        check('dry run has exact independent Decimal totals', x['exit_code'] == 0 and value == summary)
        check('successful dry run preserves persisted bytes', x['store_before_hex'] == x['store_after_hex'] and not x['pending_exists'])
        pending_store = d / 'pending-ledger.json'
        pending_store.write_bytes(store.read_bytes())
        pending_store.with_suffix('.pending').write_bytes(b'preexisting pending evidence\n')
        x, value = invoke('dry-preexisting-pending', 'import', pending_store, [first, second], True)
        check('dry run preserves preexisting pending state', x['exit_code'] == 0 and value == summary
              and x['store_before_hex'] == x['store_after_hex']
              and x['pending_before_hex'] == x['pending_after_hex'] and x['pending_exists'])
        fresh = d / 'absent.json'
        x, value = invoke('dry-absent-store', 'import', fresh, [first, second], True)
        check('dry run does not create absent ledger', x['exit_code'] == 0 and value == {
            'count': len(first) + len(second), 'total_cents': sum(charged(item)['total_cents'] for item in [*first, *second])}
            and x['store_before_hex'] is None and x['store_after_hex'] is None and not x['pending_exists'])
    x, value = invoke('normal-two-files', 'import', store, [first, second])
    check('normal imports retain exact totals', x['exit_code'] == 0 and value == summary)
    x, value = invoke('export-after-import', 'export', store)
    check('normal export remains sorted and complete', x['exit_code'] == 0 and value == expected)
    rejected = [
        ('persisted-duplicate', [[row('candidate', 1, 200), old]], 'duplicate transaction'),
        ('within-file-duplicate', [[row('new-dup', 1, 200), row('new-dup', 2, 300)]], 'duplicate transaction'),
        ('across-file-duplicate', [[row('cross-dup', 1, 200)], [row('cross-dup', 2, 300)]], 'duplicate transaction'),
        ('late-invalid-discount', [[row('valid-first', 1, 101, 5000)], [row('invalid-last', 1, 200, 10001)]], 'invalid discount'),
    ]
    for label, groups, error in rejected:
        normal_store = d / (label + '-normal.json')
        normal_store.write_bytes(store.read_bytes())
        normal, normal_value = invoke(label + '-normal', 'import', normal_store, groups)
        check(label + ' normal rejection', normal['exit_code'] == 2 and isinstance(normal_value, dict)
              and error in normal_value.get('error', '') and normal['store_before_hex'] == normal['store_after_hex'] and not normal['pending_exists'])
        if a.mode == 'feature':
            x, value = invoke(label + '-dry', 'import', store, groups, True)
            check(label + ' dry rejection matches normal', (x['exit_code'], value, x['stderr']) == (normal['exit_code'], normal_value, normal['stderr'])
                  and x['store_before_hex'] == x['store_after_hex'] and not x['pending_exists'])
    missing_groups = [[row('before-missing', 1, 101, 5000)], [{'id': 'missing-last', 'quantity': 1, 'unit_price_cents': 200}]]
    missing_store = d / 'missing-normal.json'
    missing_store.write_bytes(store.read_bytes())
    normal, normal_value = invoke('late-missing-normal', 'import', missing_store, missing_groups)
    missing_fixed = normal['exit_code'] == 2 and isinstance(normal_value, dict) and bool(normal_value.get('error'))
    check('missing field retains bytes', normal['store_before_hex'] == normal['store_after_hex'] and not normal['pending_exists'])
    if a.mode == 'feature':
        x, value = invoke('late-missing-dry', 'import', store, missing_groups, True)
        check('dry missing field matches real normal contract', (x['exit_code'], value, x['stderr']) == (normal['exit_code'], normal_value, normal['stderr'])
              and x['store_before_hex'] == x['store_after_hex'] and not x['pending_exists'])
    x, value = invoke('final-export', 'export', store)
    check('all rejected imports leave full export intact', x['exit_code'] == 0 and value == expected)
    suite = subprocess.run([sys.executable, '-B', str(r / 'e2e_import.py'), '--output', str(d / 'original-suite')], cwd=r,
                           capture_output=True, text=True, timeout=90)
    raw.append({'label': 'original-suite', 'exit_code': suite.returncode, 'stdout': suite.stdout, 'stderr': suite.stderr})
    suite_receipt = json.loads((d / 'original-suite/evidence.json').read_text())
    check('original seven or eight flows pass', suite.returncode == 0 and suite_receipt.get('verdict') == 'pass'
          and len(suite_receipt.get('flows', [])) in (7, 8) and all(item.get('ok') is True for item in suite_receipt.get('checks', [])))
except Exception as error:
    failure = type(error).__name__
    missing_fixed = False
check('source unchanged during behavior observations', sources == {name: digest(r / name) for name in sources})
result = {'mode': a.mode, 'verdict': 'pass' if failure is None and all(item['ok'] for item in checks) else 'fail',
          'failure_category': failure, 'source_sha256': sources, 'checks': checks, 'record': record,
          'missing_field_fixed': missing_fixed}
(d / 'raw.json').write_text(json.dumps(raw, indent=2) + '\n')
(d / 'observation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
'''


def digest_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def role_header(task):
    match = re.match(r'\A\s*Role: ([^\r\n]+)\r?\nPhase: ([^\r\n]+)\r?\nSlot: ([^\r\n]+)(?:\r?\n|\Z)',
                     Path(task['brief_path']).read_text())
    return match.groups() if match else (None, None, None)


def structure(path):
    """Compare sketch structure, ignoring renames and placeholder bodies."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = [item for item in node.body if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str))]
            if any(not isinstance(item, (ast.Pass, ast.Raise)) and not (
                isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and item.value.value is Ellipsis) for item in body):
                raise Failure('design_sketch_contains_implementation')
            node.name, node.body = 'function', [ast.Pass()]
        if isinstance(node, ast.ClassDef):
            node.name = 'type'
        if isinstance(node, ast.arg):
            node.arg = 'argument'
        if isinstance(node, ast.Name) and node.id not in ('str', 'int', 'bool', 'list', 'dict', 'tuple', 'Path', 'None'):
            node.id = 'symbol'
    return ast.dump(tree, include_attributes=False)


class Run(core.Run):
    """Shared process lifecycle, with independent design-specific evaluation."""

    git = support.Run.git
    forge = support.Run.forge
    native_events = support.Run.native_events
    stage = support.Run.stage

    def __init__(self, args):
        super().__init__(args)
        self.branch = 'e2e/' + args.scenario + '-' + format(time.time_ns(), 'x')
        self.probe = self.directory / 'design-oracle.py'
        self.stage_proof, self.task_facts, self.slots = {}, [], {}
        self.base = self.pr = self.config_path = self.original_fixture = None
        self.baseline, self.snapshots = {}, {}
        self.role_workers = {}
        self.worker_sessions = {}
        self.comment_native = {}
        self.agent_dir = Path(self.env.get('PI_CODING_AGENT_DIR') or Path.home() / '.pi/agent').expanduser().resolve()
        self.comment_settings = {}

    def preflight(self):
        self.check('positive_duration', self.args.max_seconds > 0)
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.repo)).resolve() == ROOT)
        self.revision = self.git('rev-parse', 'HEAD', repo=ROOT)
        self.source_status = self.git('status', '--porcelain=v1', '--untracked-files=all', repo=ROOT)
        self.hashes = support.identity()
        self.config_path = horch.config_path()
        self.config_hash = core.sha(self.config_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane)
        self.spec = self.config['workers'].get(self.args.controller, {})
        self.check('controller_is_pi', self.spec.get('harness') == 'pi')
        roles = ['how explorer', 'how explainer', 'architect runners', 'arena cross-judge pool',
                 'feature, refactoring', 'interrogate reviewers', 'judgment and prose']
        if self.args.scenario == 'feature':
            roles.append('arena runners')
        for role in roles:
            value = self.config.get('roles', {}).get(role)
            names = value if isinstance(value, list) else [value]
            self.check('role_' + role.replace(' ', '_'), bool(names) and all(name in self.config['workers']
                       and self.config['workers'][name].get('harness') == 'pi' for name in names))
            self.role_workers[role] = names
        self.check('single_explorer_explainer_implementer_comment', all(len(self.role_workers[r]) == 1 for r in (
            'how explorer', 'how explainer', 'feature, refactoring', 'judgment and prose')))
        comment_spec = self.config['workers'][self.role_workers['judgment and prose'][0]]
        overrides = ('--session', '--session-dir', '--session-id', '--no-session', '--continue', '--resume', '-c', '-r')
        self.check('comment_default_scoped_sessions', not any(arg == flag or arg.startswith(flag + '=')
                   for arg in comment_spec.get('args', []) for flag in overrides))
        self.check('comment_session_environment_supported', not self.env.get('PI_CODING_AGENT_SESSION_DIR')
                   and (not self.env.get('PI_CODING_AGENT_DIR')
                        or Path(self.env['PI_CODING_AGENT_DIR']).expanduser().is_absolute()))
        for path in (self.agent_dir / 'settings.json', self.args.fixture_repo / '.pi/settings.json'):
            self.comment_settings[path] = core.sha(path) if path.is_file() else None
            self.check('comment_default_session_setting_' + str(len(self.comment_settings)),
                       not path.is_file() or not core.read_json(path).get('sessionDir'))
        self.check('architect_panel_and_independent_judge', len(self.role_workers['architect runners']) >= 2
                   and bool(set(self.role_workers['arena cross-judge pool']) - set(self.role_workers['architect runners'])))
        if self.args.scenario == 'feature':
            self.check('arena_panel_and_independent_judge', len(self.role_workers['arena runners']) >= 2
                       and bool(set(self.role_workers['arena cross-judge pool']) - set(self.role_workers['arena runners'])))
        self.check('fixture_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.fixture_repo)).resolve() == self.args.fixture_repo)
        self.original_fixture = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo),
                                 self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo))
        self.check('clean_fixture', not self.original_fixture[1])
        origin = self.git('remote', 'get-url', 'origin', repo=self.args.fixture_repo)
        match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', origin)
        self.check('fixture_origin', bool(match) and match[1].lower() == self.args.forge_repo.lower())
        remote = self.forge('repo', 'view', self.args.forge_repo, '--json', 'nameWithOwner,isPrivate')
        self.check('private_forge', remote.get('isPrivate') is True and remote.get('nameWithOwner', '').lower() == self.args.forge_repo.lower())
        remote_base = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.args.base_ref, repo=self.args.fixture_repo).splitlines()
        self.check('one_remote_base', len(remote_base) == 1)
        self.base = remote_base[0].split()[0]
        self.check('exact_existing_baseline', self.original_fixture[0] == self.base
                   and self.git('rev-parse', self.args.base_ref, repo=self.args.fixture_repo) == self.base)
        self.parent_pr = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo, '--json',
                                    'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('explicit_open_parent', self.parent_pr.get('state') == 'OPEN' and self.parent_pr.get('headRefName') == self.args.base_ref
                   and self.parent_pr.get('headRefOid') == self.base and self.parent_pr.get('isDraft') is False)
        self.baseline = {name: core.sha(self.args.fixture_repo / name) for name in SOURCE_FILES}
        self.remote_heads = self.git('ls-remote', '--heads', 'origin', repo=self.args.fixture_repo).splitlines()
        self.prs_before = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json',
                                    'number,state,headRefName,baseRefName,isDraft')

    def observe(self, repo, label, mode):
        return json.loads(self.call([sys.executable, self.probe, '--repo', repo, '--output', self.directory / label, '--mode', mode]))

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.probe.write_text(ORACLE)
        self.probe.chmod(0o444)
        self.probe_hash = core.sha(self.probe)
        self.before = self.observe(self.args.fixture_repo, 'independent-before', 'characterize')
        self.check('baseline_real_cli_pin', self.before.get('verdict') == 'pass' and self.before.get('source_sha256') == self.baseline)
        self.git('worktree', 'add', '-b', self.branch, self.worktree, self.base, repo=self.args.fixture_repo)
        definitions = [('how-a', 'how explorer', 'how-explore'), ('how-b', 'how explorer', 'how-explore'),
                       ('how-summary', 'how explainer', 'how-explain')]
        definitions += [(f'design-{i}', 'architect runners', 'architect') for i in range(len(self.role_workers['architect runners']))]
        definitions += [('design-judge', 'arena cross-judge pool', 'architect-judge')]
        if self.args.scenario == 'feature':
            definitions += [(f'implementation-{i}', 'arena runners', 'implementation') for i in range(len(self.role_workers['arena runners']))]
            definitions += [('implementation-judge', 'arena cross-judge pool', 'implementation-judge')]
        else:
            definitions += [('implementation', 'feature, refactoring', 'implementation'), ('reader-load', 'how explainer', 'reader-load')]
        definitions += [(f'review-{i}', 'interrogate reviewers', 'interrogate') for i in range(len(self.role_workers['interrogate reviewers']))]
        definitions += [('comment-review', 'judgment and prose', 'no-comments')]
        for slot, role, phase in definitions:
            cwd = self.worktree if slot in ('implementation', 'comment-review') else self.worktree.parent / slot
            if cwd != self.worktree:
                self.git('worktree', 'add', '--detach', cwd, self.base, repo=self.args.fixture_repo)
            self.slots[slot] = {'role': role, 'phase': phase, 'cwd': str(cwd)}
        (self.directory / 'slots.json').write_text(json.dumps(self.slots, indent=2) + '\n')
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'design-e2e', '--no-focus', *sum((['--env', key + '=' + self.env[key]] for key in
                         ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'MISE_CONFIG_DIR', 'MISE_STATE_DIR', 'GIT_CONFIG_GLOBAL', 'GH_CONFIG_DIR')), []),
                         *(['--env', 'PI_CODING_AGENT_DIR=' + self.env['PI_CODING_AGENT_DIR']]
                           if self.env.get('PI_CODING_AGENT_DIR') else []))
        self.pane = tab['root_pane']['pane_id']
        brief = self.directory / 'controller-brief.md'
        brief.write_text(self.prompt())
        sessions = self.directory / 'native-sessions'
        sessions.mkdir()
        flags = horch.launch_args(self.spec, self.directory) + ['--session-dir', str(sessions)]
        self.check('native_controller_started', self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', self.pane,
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

    def scan(self):
        rows = super().scan()
        for task, _ in rows:
            if task['task_id'] not in self.worker_sessions:
                try:
                    entry = self.herdr('agent', 'get', task['agent'])['agent']
                    session = entry.get('agent_session') or {}
                    if (session.get('agent') == 'pi' and session.get('source') == 'herdr:pi' and session.get('value')
                            and (role_header(task)[2] != 'comment-review' or entry.get('agent_status') == 'working')):
                        self.worker_sessions[task['task_id']] = session
                        (self.directory / 'worker-sessions.json').write_text(json.dumps(self.worker_sessions, indent=2) + '\n')
                except Failure:
                    pass
        return rows

    def prompt(self):
        goal = ('''Add import --dry-run. The option is immediately after import and before the
store path. It validates and calculates exactly like normal import across all
input files, with the same count/totals and errors, but never changes ledger bytes
or creates an absent ledger. It never creates, changes or removes a pending file;
preexisting pending bytes stay unchanged. Keep all normal CLI behavior.
Implement this with the REAL implementation Arena: each configured arena runner
owns its entire independent candidate in its allocated source worktree. Do not
replace Arena with a single writer and a claimed comparison.''' if self.args.scenario == 'feature' else '''Separate pure row staging/validation from persistence inside storage.py.
Keep apply_batch's public signature, CLI results, error codes and exact ledger
bytes unchanged. Name the target data shape and show the call graph. Do not add
wrapper layers or a second validation policy. Delegate the mechanical move to
the configured feature, refactoring worker in the integration worktree. Review
reduced reader load concretely, with baseline and final source citations.''')
        return f'''Read {self.bundle / 'skills/poteto-mode/SKILL.md'} in full first. You are the
native lead for original {self.args.scenario} and Opening a PR. Source bundle:
{self.bundle}. Full-read every applied source separately with native read (no
offset/limit) or literal cat of one file. Required relative skills: {json.dumps(list(READS))}
plus poteto-mode/playbooks/{self.args.scenario}.md. Write its exact eight original
numbered checklist items to {self.artifacts / 'checklist.md'} before delegation.
Also write {self.artifacts / 'phases.json'} with architect [Ground, Sketch, Agree,
Implement, Scrap] and arena [Frame, Fan out, Cross-judge, Pick, Graft, Verify],
with each value a JSON string. Do not skip a mandatory phase or claim an absent
capability. Default Architect Agree has no human checkpoint.

Evaluation tool protocol, also in EVERY brief: use only direct native read,
bash, write, edit, grep, find, ls; no codemode, wrappers or native subagents.
Nested tool results cannot be bound by this evaluator. Preserve configured
models, effort, permission flags, Git hooks/signatures and original Mise roots.
No trust answers, config/auth changes, model substitutions or failure retries.
Controller Bash uses ONE literal command per call: no newline, ; | & > <,
backtick, dollar sign or backslash anywhere, even quoted. No pipelines, shell
expansion, printf/test/ls wrappers or inline interpreters. Use native read/ls/
grep/find for inspection. Actual unchanged isolated worker config is
{self.directory / 'config/herdr-orchestrator/workers.toml'}; do not expand XDG.
Accepted controller forms: python/python3 PROBE --repo PATH --output PATH --mode
MODE; python/python3 BUNDLED_HORCH run|wait|list|close|stats|detect ARGS (no -B);
git (optional -C EXACT_INTEGRATION_CWD) status/diff/show/log/blame/rev-parse/
rev-list/diff-tree/ls-files/ls-remote with no --output; git add [--] cli.py and/or
storage.py; git commit without -n or hook/signature bypass; git push [-u or
--set-upstream] origin {self.branch}; git branch --show-current; git remote get-url
origin; gh/origin repo view, pr list/view/create (create exact base/head/repo,
ready); cat ONE_FILE without flags; pwd; command -v origin; which origin;
exactly sha256sum ABSOLUTE_COMMENT_TASK_DIR/report.md for the actual slot
comment-review's canonical report only, after its native horch wait proves done
and closed. No flags, extra operands, other task reports/results or review.json
hashes. Hash output never replaces the required complete report/result reads.
No other command is accepted. Use native-written --body-file for multiline PRs.
Use only bundled {self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'} for
delegation; run includes --caller-pane {self.pane}. Literal standalone horch wait
must report done before reading each result.json and ALL its listed artifacts.
Workers must return a Markdown report, list every output in result.json, and
close on successful delivery. Never edit horch task/state/result files.
Every brief's first three nonblank lines are exactly:
Role: <exact configured role>
Phase: <exact phase from slot map>
Slot: <exact slot key>
Then worker, concrete selection reason, scope, absolute mode and poteto-agent
references, and: Do not delegate, use native subagents, or run a whole playbook.
Complete this assignment yourself. Workers cannot commit or write forge state.
Configured roles: {json.dumps(self.role_workers)}.
Allocated independent worktrees: {json.dumps(self.slots)}. Use each slot once;
no replacements/retries. All non-implementation worktrees remain source-frozen.
The mandatory comment-review slot is the one exception to baseline reader cwds:
it reads the stable actual integration worktree, with NO source writes.
Only cli.py/storage.py may change for Feature; only storage.py for Refactoring.
Never change money.py, e2e_import.py or other tracked files. No generated files
or private artifacts in Git. Keep notes under {self.artifacts} and worker outputs
inside actual task directories. All source coding is delegated except the
explicit Feature base-import/graft protocol below.

Goal: {goal}
Integration branch {self.branch} at {self.worktree}, exact baseline {self.base}.
Explicit parent PR {self.args.parent_pr} remains ready/open/unmerged; its head
{self.args.base_ref} is the ONLY authorized base. You may push ONLY {self.branch}
and create ONE ready child PR on {self.args.forge_repo}, targeting {self.args.base_ref}.
No merges, auto-merge, babysit, branch deletes or other forge writes. No mutation
of original fixture clone or public source checkout. Resolve one forge from
actual command -v origin and repository resolution; record forge + reason in
{self.artifacts / 'forge.json'} before first PR operation. If absent/unresolvable,
record gh fallback; do not substitute fake commands. Use the same forge for all
PR commands. Read deslop/no-comments/technical-writing/unslop and sequence principle
before commits and diff review. Use conventional titles and original PR sections.
After create, actual PR view JSON includes headRefOid,headRefName,baseRefName,isDraft.
Use literal standalone git, forge, horch and external-oracle commands. Git add
names files explicitly. No inline interpreters, shell chaining or source scripts.
Native reads/searches handle inspection. No Git signing/hook bypass flags.

After winner integration and the successful final behavior oracle (and any
reader-load/formal review), BEFORE final diff review, ANY commit or PR, run the
mandatory no-comments child review. Read original no-comments and CommentSicko
guides yourself; write exactly this body to {self.artifacts / 'comment-brief.md'}
then launch slot comment-review once on its integration cwd, configured worker
{self.role_workers['judgment and prose'][0]}. No other replacement or retry.
--- BEGIN EXACT COMMENT BRIEF ---
{self.comment_brief()}--- END EXACT COMMENT BRIEF ---
Wait for actual done/closed, then full-read result.json, report.md and review.json.
Run literal sha256sum on ONLY this task's absolute canonical report.md path to
obtain report_sha256; no hash before its actual native done/closed delivery.
Write {self.artifacts / 'comment-disposition.json'} with actual task_id,
report_sha256, decision ('accept' or 'unresolved'), summary, findings_assessment,
deletion_count, restored_comments, reruns, architect_sketch, fixes, encoding_offers,
encodings, unenforced_constraints, skips, open_work. All are arrays except the
first four strings and deletion_count integer. Assess real findings against the
original rules, not invented zero findings. A source revision, rejected report,
rerun, deeper How/Why/Architect, encoding approval or unresolved constraint means
STOP unresolved BEFORE commit/PR; retain evidence, no retries or source changes.
The bounded pass path requires no findings needing revision, flags or open work;
then findings_assessment/reruns/architect_sketch/fixes/encodings are empty arrays.
Freeze the inspected source through commit. Preserve complete disposition JSON
verbatim under a No-comments heading in final reply, including all summary fields.

Behavior oracle is immutable {self.probe}; invoke it with standalone python3
--repo PATH --output NEW_EXTERNAL_DIRECTORY --mode characterize|feature. It
runs only the real CLI, derives independent Decimal totals, saves actual output,
exit codes, complete ledger bytes/pending state and original suite. It returns
zero with JSON even when app assertions fail. Do not modify/copy it or write an
evidence.json. After full How delivery, before Architect design/code fan-out, run mode characterize in integration,
output {self.directory / 'native-before'} and full-read observation.json; this is
the frozen behavior pin. Original seven/eight flows must pass. Retain it unchanged.
Final output is {self.directory / 'native-after'} with mode {self.args.scenario if self.args.scenario == 'feature' else 'characterize'}.

HOW: full complex route, two fresh how explorer tasks in how-a/how-b before
first wait, angles cli-contract and staging-persistence. Read all delivered
findings before how-summary. Its brief includes BOTH complete explorer report
bodies and angle keys. Read the delivered full explanation; preserve it in
{self.artifacts / 'grounding.md'} without dropping content. This is Architect
Ground. Do not redefine ownership/layering; persistence remains storage-owned.
If evidence shows a change to ownership is needed, report the required why
investigation as unresolved rather than quietly skipping it.

ARCHITECT: before runners write {self.artifacts / 'architect-task.md'} with common
task + grounding, {self.artifacts / 'architect-rubric.json'} as {{"criteria": [{{"id":
"unique-key", "description": "concrete gradeable criterion"}}]}} (3–6 criteria),
and a todo for all Arena phases. Rubric stays HIDDEN from candidates: do not put
its path/body into candidate briefs. Every candidate gets the exact whole common
task body in its brief and the same grounding path, then only its own output/cwd.
Use ALL architect runners concurrently, before the first wait. Each produces
sketch.py with placeholder bodies (pass/raise NotImplementedError/ellipsis),
usage-first report.md per original rationale template and design.json describing
boundaries, data shape and call graph. Require >=2 structurally distinct whole
sketches, not renamed variations, and screen red flags/interface depth.
After ALL candidate deliveries choose one cross-judge from configured pool,
whose worker is NOT any runner for this round, in design-judge. Give it the
hidden rubric and every actual candidate artifact by anonymous slot label. It
returns judgment.json with scores {{task_id: {{criterion_id: 0..5}}}}, recommendation
(actual candidate task_id) and reason. In parallel read EVERY candidate artifact
end to end; freeze YOUR independent score table in
{self.artifacts / 'architect-scores.json'} (same scores schema) BEFORE reading
judge artifacts. After reading the actual judgment write
{self.artifacts / 'architect-decision.json'} with base_task, scores, judge_task,
comparison, grafts (list), rejected (one per loser), interface_depth, red_flags,
contested (boolean), reason and model_the_domain. Use task IDs for identities.
Compare criterion by criterion, choose a base, assess EACH loser for graft/reject,
explain disagreement rather than copying judge scores. Write the synthesized
usage/signature/module/call-graph package + rationale to
{self.artifacts / 'rationale.md'}. Proceed directly through Agree by default.

BEFORE CODE fan-out write exactly four todo items in
{self.artifacts / 'throughput.md'}, titled {json.dumps(THROUGHPUT)} with concrete
routing and shared-state boundaries. Keep nonapplicable items with n/a + reason.
Refactoring must state target shape and subtraction assessment in its rationale.
Feature repeats a REAL Arena for implementation-0..N and implementation-judge:
use implementation-task.md, implementation-rubric.json, implementation-scores.json,
implementation-decision.json with the SAME schemas and phase rules. Candidates
get exact shared implementation task and synthesized design, never the rubric.
The common implementation task and EVERY candidate brief must include both the
absolute rationale.md path and its complete exact bytes. Read rationale.md back
in full after its write and before framing that task; freeze it through final
verification. Candidates implement and verify independently in disjoint worktrees,
no integration writes, and report actual changes and rejected alternatives. This
conservative driver requires every implementation candidate to pass the real
Feature CLI oracle; a failed candidate leaves the run unresolved. Cross-judge
starts after all are done. Read every candidate source file in full after delivery.
Assess every loser honestly even when no graft is worthwhile.

FEATURE BASE IMPORT/GRAFT protocol: after implementation-decision.json ONLY,
controller native write imports cli.py/storage.py with content EXACTLY equal to
chosen delivered candidate file. No other source writes. Optional grafts must be
listed in that decision as objects: source_task (loser task_id), path (cli.py or
storage.py), old_text (unique existing fragment), new_text (exact fragment from
read loser file), reason (coherent adaptation rationale). Apply each once with
native edit oldText/newText, in manifest order. No invented implementation code,
no general rewrite; if a necessary coherent adaptation cannot fit this protocol,
report synthesis unresolved. Refactoring has NO controller source-write permission.

Run final oracle yourself on same CLI after implementation. Refactoring must
normalize-and-compare its record with frozen before (exit/stdout/stderr, every
ledger byte and pending state), including missing-field when baseline fixed.
Then reader-load slot uses configured how explainer read-only to compare actual
baseline/final source; it returns reader_load.json with worth_keeping boolean,
improvements (concrete list), regressions (list), citations [{{side: before|after,
path: storage.py, line: integer, text: exact source line}}]. It must explain reader
load at named boundaries, not count files. Revert/report unresolved if no gain.

Write {self.artifacts / 'scrap.json'} after implementation with required boolean,
observations list and reason. If repeated architecture friction requires Scrap,
stop unresolved: this bounded run does not silently accept it or auto-retry.
Write {self.artifacts / 'review.json'} with scope, decision and actual diff findings
after the reader-load assessment and any formal review, before committing.
If design remains contested, run FULL configured interrogate reviewers in all
review slots, read the actual interrogate skill/rubric/lenses, use one common
intent/revision/rubric (interrogate-task.md, including exact baseline SHA and
full actual diff text) and all delivered findings; write interrogate.json with
resolved boolean and rationale. Unresolved findings block shipping. Do not
relable a partial review. If not contested record the concrete assessment.
Review actual full git diff. Each small ordered commit must already have a
successful native final oracle run; keep commit count <=3. Final source and pin
stay frozen after verification. Ready child PR must use exact owned head/base.
Write {self.artifacts / 'reply.md'} only after actual ready PR readback, with
original reply fields, alternative table, full throughput items, verification,
retained artifacts and real PR URL. No broader inventory/Interrogate/Scrap claim
beyond what actually ran. Preserve failures; never report a missing stage passed.
'''

    def comment_scope(self):
        return ('cli.py', 'storage.py') if self.args.scenario == 'feature' else ('storage.py',)

    def comment_diff_argv(self):
        return ['git', '-C', str(self.worktree), 'diff', '--src-prefix=a/', '--dst-prefix=b/',
                self.base, '--', *self.comment_scope()]

    def comment_brief(self):
        return f'''Role: judgment and prose
Phase: no-comments
Slot: comment-review
Worker: {self.role_workers['judgment and prose'][0]}
Reason: configured judgment and prose role fits this bounded CommentSicko audit.
Use only direct native read/bash/write/edit/grep/find/ls, no codemode or wrappers.
Do not delegate, use native subagents, or run a whole playbook. Complete this
assignment yourself. No config/model/trust changes, retries, commits or forge.
Full-read original bundled guides, without restating or replacing their rules:
{self.bundle / 'skills/no-comments/SKILL.md'}
{self.bundle / 'skills/pstack-herdr/references/agents/comment-sicko.md'}
{self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'}
{self.bundle / 'skills/poteto-mode/SKILL.md'}
Your first nonempty assistant text block must be EXACTLY the original agent's
greeting, with no extra prose: Yes... Ha ha ha... Yes!
Scope: actual integration files {json.dumps(self.comment_scope())}, cwd
{self.worktree}, base {self.base}; NOT a detached baseline. Full-read each scoped
file and inspect the complete real diff with exactly this standalone command:
{' '.join(self.comment_diff_argv())}
Bind actual source with exactly this standalone command:
sha256sum {' '.join(str(self.worktree / name) for name in SOURCE_FILES)}
Bash accepts ONLY those two exact commands or literal cat ONE_DECLARED_FILE.
No newline, ; | & > < backtick, dollar sign or backslash anywhere, even quoted;
no shell expansion, pipelines, wrappers, extra flags, CLI execution or Git writes.
Native read/grep/find/ls may inspect only scoped files, the four declared guides
or your own task directory. All source is read-only; write/edit ONLY report.md,
review.json and result.json in your actual own horch task directory. Never edit
brief.md, task.json, state.json, application/source/skill or evaluator artifacts.
Return normal actual nonce, question null; result.files lists exactly report.md
and review.json, in either order. Report actual findings, no invented zero flags.
report.md contains scoped touched files, deletion count, MUST KILL flags and skips.
review.json contains inspections (one object per scoped relative path, with path,
excerpt verbatim at least 20 characters and conclusion grounded in that file),
source_sha256 (all four actual source digests), findings (actual path/excerpt/
reason/action objects), deletion_count (nonnegative integer), restored_comments,
must_kill, skips, encoding_offers, unenforced_constraints, open_work (arrays).
This is report-only: recommended changes, rejected/ambiguous findings or any need
for a deeper How/Why/Architect/encoding/approval go into open_work, never edits or
nested delegation. Follow the original CommentSicko scope and report honestly.
'''

    def comment_session(self, task):
        session = self.worker_sessions.get(task['task_id'], {})
        cwd = Path(task['cwd']).resolve()
        encoded = '--' + re.sub(r'[/\\:]', '-', str(cwd).lstrip('/\\')) + '--'
        directory = self.agent_dir / 'sessions' / encoded
        value = session.get('value', '')
        if session.get('kind') == 'path':
            path = Path(value).expanduser().resolve()
            self.check('comment_session_exact_owned_directory', path.parent == directory)
            identity = path.stem.rsplit('_', 1)[-1]
        else:
            identity = value
        try:
            canonical = str(uuid.UUID(identity))
        except (ValueError, AttributeError):
            raise Failure('comment_native_uuid_unavailable') from None
        self.check('comment_canonical_session_uuid', canonical == identity)
        # Only this captured UUID in this exact cwd; no unrelated session scan.
        paths = list(directory.glob('*_' + canonical + '.jsonl'))
        self.check('comment_one_owned_native_session', len(paths) == 1 and (
            session.get('kind') != 'path' or paths[0].resolve() == Path(value).resolve()))
        return paths[0]

    def verify_comment(self, record, events, all_events, final_sources):
        task, launch = record['task'], record['launch']
        self.check('comment_after_stable_verified_implementation', launch['call_row'] > self.review_complete_row)
        for resource in ('no-comments/SKILL.md', 'pstack-herdr/references/agents/comment-sicko.md'):
            self.check('comment_lead_guidance_' + resource, bool(core.workflow_reads(events, self.worktree,
                       self.bundle / 'skills' / resource, before=launch['call_row'])))
        worker = self.config['workers'][task['worker']]
        source = self.comment_session(task)
        saved = self.directory / 'comment-native.jsonl'
        shutil.copy2(source, saved)
        guides = [self.bundle / 'skills' / name for name in ('no-comments/SKILL.md',
                  'pstack-herdr/references/agents/comment-sicko.md',
                  'pstack-herdr/references/agents/poteto-agent.md', 'poteto-mode/SKILL.md')]
        audit = core.audit_pi(source, self.worker_sessions[task['task_id']], self.worktree,
                              core.stamp(task['created_at']), worker, guides, [], [], self.bundle)
        self.check('comment_native_identity_model_effort_guides', all(item['ok'] for item in audit['checks'])
                   and core.sha(saved) == audit['sha256'])
        rows = [json.loads(line) for line in saved.read_text().splitlines() if line.strip()]
        texts = [block.get('text', '') for row in rows if row.get('message', {}).get('role') == 'assistant'
                 for block in row['message'].get('content', []) if block.get('type') == 'text'
                 and block.get('text', '').strip()]
        self.check('comment_original_exact_first_output', bool(texts) and texts[0].strip() == 'Yes... Ha ha ha... Yes!')
        calls = self.native_events(saved, include_errors=True)
        successful = [event for event in calls if event['successful']]
        directory = record['directory'].resolve()
        scoped = {self.worktree / name for name in self.comment_scope()}
        outputs = {directory / name for name in ('report.md', 'review.json', 'result.json')}
        readable = {*guides, *scoped, *outputs, directory / 'brief.md', directory / 'task.json'}
        sha_argv = ['sha256sum', *(str(self.worktree / name) for name in SOURCE_FILES)]
        diff_output = self.call(['git', '-C', self.worktree, 'diff', '--src-prefix=a/', '--dst-prefix=b/',
                                 self.base, 'HEAD', '--', *self.comment_scope()])
        diffs, hashes = [], []
        for event in calls:
            args = event['args']
            if event['name'] in ('write', 'edit'):
                self.check('comment_all_attempt_writes_owned_reports', isinstance(args.get('path'), str)
                           and (self.worktree / args['path']).resolve() in outputs)
            elif event['name'] in ('read', 'grep', 'find', 'ls'):
                raw = args.get('path', '.')
                self.check('comment_read_argument_known', isinstance(raw, str))
                target = (self.worktree / raw).resolve()
                self.check('comment_all_attempt_reads_scoped', target in readable or target == directory or directory in target.parents)
            elif event['name'] == 'bash':
                argv = support.literal(args.get('command', ''))
                self.check('comment_all_attempt_literal_commands', argv in (self.comment_diff_argv(), sha_argv)
                           or len(argv) == 2 and argv[0] == 'cat' and (self.worktree / argv[1]).resolve() in readable)
                if event['successful'] and argv == self.comment_diff_argv():
                    self.check('comment_full_diff_bound_to_final_commit', event['output'].rstrip('\n') == diff_output.rstrip('\n'))
                    diffs.append(event)
                if event['successful'] and argv == sha_argv:
                    expected = '\n'.join(final_sources[name] + '  ' + str(self.worktree / name) for name in SOURCE_FILES)
                    self.check('comment_source_hashes_bound_to_final_commit', event['output'].rstrip('\n') == expected)
                    hashes.append(event)
        self.check('comment_actual_diff_and_hash_observations', bool(diffs) and bool(hashes))
        writes = []
        for name in ('report.md', 'review.json'):
            native = core.workflow_writes(successful, self.worktree, directory / name, final=True)
            self.check('comment_complete_native_report_' + name, len(native) == 1
                       and native[0]['args']['content'] == (directory / name).read_text())
            writes.append(native[0])
        start = min(event['call_row'] for event in writes)
        for path in [*guides, *scoped]:
            self.check('comment_complete_native_scope_read_' + path.name, bool(core.workflow_reads(
                successful, self.worktree, path, before=start)))
        self.check('comment_observations_before_report', max(diffs[0]['result_row'], hashes[0]['result_row']) < start)
        facts = core.read_json(directory / 'review.json')
        inspections = facts.get('inspections', [])
        self.check('comment_real_scope_evidence', isinstance(inspections, list) and len(inspections) == len(scoped)
                   and {item.get('path') for item in inspections if isinstance(item, dict)} == set(self.comment_scope())
                   and all(isinstance(item.get('excerpt'), str) and len(item['excerpt']) >= 20
                           and item['excerpt'] in (self.worktree / item['path']).read_text()
                           and isinstance(item.get('conclusion'), str) and bool(item['conclusion'].strip()) for item in inspections)
                   and facts.get('source_sha256') == final_sources)
        self.check('comment_typed_actual_findings', type(facts.get('deletion_count')) is int
                   and facts['deletion_count'] >= 0 and all(isinstance(facts.get(key), list) for key in (
                       'findings', 'restored_comments', 'must_kill', 'skips', 'encoding_offers', 'unenforced_constraints', 'open_work')))
        self.check('comment_no_revision_or_unresolved_work', facts['deletion_count'] == 0
                   and all(not facts[key] for key in ('findings', 'restored_comments', 'must_kill',
                                                     'encoding_offers', 'unenforced_constraints', 'open_work')))
        report = (directory / 'report.md').read_text()
        self.check('comment_original_report_fields', all(name in report for name in self.comment_scope())
                   and all(word in report.lower() for word in ('deletion', 'must kill', 'skip')))
        disposition = self.written(events, 'comment-disposition.json', after=self.read_before(record))
        resolved = json.loads(disposition['args']['content'])
        self.check('comment_evidence_bound_lead_disposition', resolved.get('task_id') == task['task_id']
                   and resolved.get('report_sha256') == core.sha(directory / 'report.md') and resolved.get('decision') == 'accept'
                   and isinstance(resolved.get('summary'), str) and bool(resolved['summary'].strip())
                   and all(resolved.get(key) == facts[key] for key in ('deletion_count', 'restored_comments', 'skips',
                       'encoding_offers', 'unenforced_constraints', 'open_work'))
                   and all(resolved.get(key) == [] for key in ('findings_assessment', 'reruns', 'architect_sketch', 'fixes', 'encodings')))
        source_targets = {self.worktree / name for name in SOURCE_FILES}
        self.check('comment_source_frozen_after_launch', not any(event['name'] in ('write', 'edit')
                   and isinstance(event['args'].get('path'), str) and (self.worktree / event['args']['path']).resolve() in source_targets
                   and event['call_row'] > launch['call_row'] for event in all_events))
        self.comment_native = dict(audit, source_sha256=final_sources, diff_sha256=digest_text(diff_output),
                                   report_sha256=core.sha(directory / 'report.md'), audit_completed=True)
        self.comment_disposition = disposition['args']['content']
        self.review_complete_row = max(self.review_complete_row, disposition['result_row'])
        self.stage('no_comments_fresh_review', [launch, record['delivery'], *record['reads'], disposition])

    def task_records(self, tasks, events):
        launches, deliveries = core.workflow_launches(events, tasks, self.worktree, self.bundle)
        self.check('native_launch_and_delivery_binding', set(launches) == set(deliveries) == {t['task_id'] for t in tasks})
        records = {}
        for task in tasks:
            role, phase, slot = role_header(task)
            definition = self.slots.get(slot, {})
            self.check('exact_own_role_phase_slot', definition.get('role') == role and definition.get('phase') == phase
                       and task['worker'] in self.role_workers.get(role, []) and task.get('cwd') == definition.get('cwd') and slot not in records)
            worker = self.config['workers'][task['worker']]
            self.check('worker_config_argv', task.get('model') == worker.get('model') and task.get('harness') == worker.get('harness')
                       and task.get('argv') == horch.launch_args(worker, Path(task['task_dir'])))
            result_path = Path(task['result_path'])
            self.check('worker_result_path', result_path.resolve() == Path(task['task_dir']) / 'result.json')
            result = core.read_json(result_path)
            self.check('worker_result_nonce_identity', horch.validate_result(result, task) == 'valid' and result.get('status') == 'completed')
            session = self.worker_sessions.get(task['task_id'], {})
            self.check('worker_live_session_identity', session.get('agent') == 'pi' and session.get('source') == 'herdr:pi' and bool(session.get('value')))
            brief = Path(task['brief_path']).read_text()
            self.check('worker_bounded_protocol', all(word in brief for word in ('Do not delegate', 'codemode', task['worker'],
                       str(self.bundle / 'skills/poteto-mode/SKILL.md'),
                       str(self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'))) and bool(re.search(r'reason|because', brief, re.I)))
            if slot == 'comment-review':
                expected = self.comment_brief().rstrip('\n') + '\n\n' + horch.WORKER_RULES.format(
                    result_path=Path(task['result_path']), task_id=task['task_id'], nonce=task['nonce'])
                self.check('comment_exact_bounded_brief', brief == expected)
                self.check('comment_exact_unique_report_files', isinstance(result.get('files'), list)
                           and len(result['files']) == 2 and all(isinstance(name, str) for name in result['files'])
                           and set(result['files']) == {'report.md', 'review.json'} and result.get('question') is None)
            reads = []
            for path in [result_path, *(Path(task['task_dir']) / name for name in result.get('files', []))]:
                self.check('result_artifact_scope', path.resolve() == result_path.resolve() or Path(task['task_dir']).resolve() in path.resolve().parents)
                proof = core.workflow_reads(events, self.worktree, path, after=deliveries[task['task_id']]['result_row'])
                self.check('all_delivered_artifacts_fully_read', bool(proof))
                reads.append(proof[0])
            reports = core.workflow_report_reads(events, task, self.worktree, deliveries[task['task_id']])
            self.check('worker_report_delivered_read', bool(reports))
            records[slot] = {'task': task, 'launch': launches[task['task_id']], 'delivery': deliveries[task['task_id']],
                             'reads': reads, 'reports': reports, 'directory': Path(task['task_dir']), 'brief': brief}
            self.task_facts.append({'task_id_sha256': digest_text(task['task_id']), 'slot': slot,
                                    'role': role, 'model': worker.get('model'), 'effort': worker.get('effort'),
                                    'session_sha256': digest_text(session['value']), 'argv_sha256': digest_text(json.dumps(task['argv'])),
                                    'result_sha256': core.sha(result_path), 'nonce_validated': True})
        return records

    def written(self, events, filename, before=float('inf'), after=-1):
        matches = core.workflow_writes(events, self.worktree, self.artifacts / filename, after=after, before=before, final=True)
        self.check('native_artifact_' + filename, len(matches) == 1)
        return matches[0]

    def read_before(self, record):
        return max(event['result_row'] for event in record['reads'])

    def panel(self, records, prefix, role):
        selected = [records[f'{prefix}-{i}'] for i in range(len(self.role_workers[role])) if f'{prefix}-{i}' in records]
        self.check('complete_panel_' + prefix, len(selected) == len(self.role_workers[role])
                   and [r['task']['worker'] for r in selected] == self.role_workers[role])
        self.check('parallel_panel_' + prefix, max(r['launch']['result_row'] for r in selected) < min(r['delivery']['call_row'] for r in selected))
        return selected

    def competition(self, events, records, kind, candidates, judge_slot, lower):
        first = min(r['launch']['call_row'] for r in candidates)
        resources = ['arena/SKILL.md']
        if kind == 'architect':
            resources += ['architect/SKILL.md', 'architect/references/runner-prompt.md',
                          'architect/references/rationale-template.md', 'architect/references/design-red-flags.md']
        for resource in resources:
            self.check('guidance_before_' + kind + '_' + resource.replace('/', '_'), bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource, before=first)))
        common = self.written(events, kind + '-task.md', before=first, after=lower)
        rubric_event = self.written(events, kind + '-rubric.json', before=first, after=lower)
        common_text = common['args']['content']
        rubric_path = self.artifacts / (kind + '-rubric.json')
        rubric = core.read_json(rubric_path)
        criteria = rubric.get('criteria', [])
        keys = {item.get('id') for item in criteria}
        self.check('hidden_gradeable_rubric_' + kind, 3 <= len(criteria) <= 6 and len(keys) == len(criteria)
                   and all(isinstance(key, str) and key for key in keys) and all(item.get('description') for item in criteria))
        self.check('common_task_and_hidden_rubric_' + kind, all(common_text in r['brief']
                   and str(self.artifacts / 'grounding.md') in r['brief']
                   and str(rubric_path) not in r['brief'] and rubric_event['args']['content'] not in r['brief'] for r in candidates))
        if kind == 'implementation':
            package = self.design_package
            package_path = self.artifacts / 'rationale.md'
            package_text = package['args']['content']
            self.check('implementation_uses_frozen_architect_package',
                       str(package_path) in common_text and package_text in common_text
                       and all(str(package_path) in r['brief'] and package_text in r['brief'] for r in candidates)
                       and core.sha(package_path) == self.design_package_hash
                       and bool(core.workflow_reads(events, self.worktree, package_path,
                                after=package['result_row'], before=common['call_row'])))
        judge = records.get(judge_slot)
        self.check('fresh_independent_crossjudge_' + kind, judge is not None and judge['task']['worker'] not in {r['task']['worker'] for r in candidates}
                   and judge['launch']['call_row'] > max(r['delivery']['result_row'] for r in candidates)
                   and str(rubric_path) in judge['brief'] and all(str(r['directory']) in judge['brief'] for r in candidates))
        own = self.written(events, kind + '-scores.json', before=min(e['call_row'] for e in judge['reads']),
                           after=max(self.read_before(r) for r in candidates))
        own_scores = json.loads(own['args']['content']).get('scores', {})
        judgment = core.read_json(judge['directory'] / 'judgment.json')
        identities = {r['task']['task_id'] for r in candidates}
        for label, table in (('parent', own_scores), ('judge', judgment.get('scores', {}))):
            self.check(label + '_criterion_scores_' + kind, set(table) == identities and all(
                set(scores) == keys and all(type(score) is int and 0 <= score <= 5 for score in scores.values()) for scores in table.values()))
        self.check('judge_actual_recommendation_' + kind, judgment.get('recommendation') in identities and bool(judgment.get('reason')))
        decision_event = self.written(events, kind + '-decision.json', after=max(self.read_before(judge), *(self.read_before(r) for r in candidates)))
        decision = json.loads(decision_event['args']['content'])
        base = decision.get('base_task')
        losers = identities - {base}
        self.check('parent_selection_' + kind, base in identities and decision.get('scores') == own_scores
                   and decision.get('judge_task') == judge['task']['task_id'] and decision.get('comparison') and decision.get('reason')
                   and type(decision.get('contested')) is bool and isinstance(decision.get('grafts'), list)
                   and {item.get('source_task') for item in decision.get('rejected', [])} == losers
                   and all(item.get('reason') for item in decision.get('rejected', [])))
        if kind == 'architect':
            self.check('architect_interface_screen', decision.get('model_the_domain')
                       and {item.get('task') for item in decision.get('interface_depth', [])} == identities
                       and {item.get('task') for item in decision.get('red_flags', [])} == identities)
            shapes = []
            for candidate in candidates:
                sketch = candidate['directory'] / 'sketch.py'
                self.check('full_sketch_and_design_read', sketch.is_file() and (candidate['directory'] / 'design.json').is_file()
                           and bool(core.workflow_reads(events, self.worktree, sketch, after=candidate['delivery']['result_row'], before=decision_event['call_row'])))
                shapes.append(structure(sketch))
            self.check('distinct_structural_designs', len(set(shapes)) >= 2)
        self.stage(kind + '_arena', [common, rubric_event, own, decision_event, judge['launch'], judge['delivery']]
                   + [event for candidate in candidates for event in (candidate['launch'], candidate['delivery'])])
        return decision, decision_event

    def native_probe(self, events, directory, mode, expected_sources):
        matches = []
        for event in events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if (len(argv) != 8 or Path(argv[0]).name not in ('python', 'python3')
                    or (self.worktree / argv[1]).resolve() != self.probe
                    or argv[2:4] != ['--repo', str(self.worktree)]
                    or argv[4:6] != ['--output', str(directory)] or argv[6:] != ['--mode', mode]):
                continue
            try:
                value = json.loads(event['output'])
                saved = core.read_json(directory / 'observation.json')
            except (OSError, ValueError):
                continue
            if value == saved and value.get('verdict') == 'pass' and value.get('source_sha256') == expected_sources:
                matches.append(event)
        self.check('native_real_cli_' + directory.name, len(matches) == 1)
        return matches[0]

    def authorized_sources(self, all_events, records, decision, selection):
        allowed = {'cli.py', 'storage.py'} if self.args.scenario == 'feature' else {'storage.py'}
        roots = {self.worktree, self.args.fixture_repo, *(Path(slot['cwd']) for slot in self.slots.values())}
        protected = {root / name for root in roots for name in SOURCE_FILES}
        source_events = []
        for event in all_events:
            if event['name'] not in ('write', 'edit'):
                continue
            value = event['args'].get('path')
            self.check('native_write_path_known', isinstance(value, str))
            target = (self.worktree / value).resolve()
            if target in protected:
                self.check('source_write_is_authorized_arena_import', self.args.scenario == 'feature'
                           and target.parent == self.worktree and target.name in allowed
                           and event['call_row'] > selection['result_row'] and event['successful'])
                source_events.append((event, target.name))
            else:
                self.check('controller_notes_outside_source', self.artifacts in target.parents)
        if self.args.scenario == 'refactoring':
            self.check('all_refactoring_source_delegated', not source_events)
            return
        selected = next(r for r in records.values() if r['task']['task_id'] == decision['base_task'])
        chosen = {name: (Path(selected['task']['cwd']) / name).read_text() for name in allowed}
        state = {name: self.git('show', self.base + ':' + name) + '\n' for name in allowed}
        imported, applied = set(), []
        grafts = decision['grafts']
        for event, name in source_events:
            if event['name'] == 'write':
                self.check('chosen_candidate_exact_import', name not in imported and event['args'].get('content') == chosen[name])
                imported.add(name)
                state[name] = event['args']['content']
            else:
                index = len(applied)
                self.check('graft_listed_once', index < len(grafts))
                graft = grafts[index]
                source = next((r for r in records.values() if r['task']['task_id'] == graft.get('source_task')), None)
                old, new = event['args'].get('oldText'), event['args'].get('newText')
                self.check('graft_exact_provenance', source is not None and source['task']['task_id'] != decision['base_task']
                           and source['task']['task_id'] in {r['task']['task_id'] for slot, r in records.items() if slot.startswith('implementation-') and slot != 'implementation-judge'}
                           and name in imported and graft.get('path') == name and graft.get('reason')
                           and isinstance(old, str) and old and isinstance(new, str) and new
                           and graft.get('old_text') == old and graft.get('new_text') == new
                           and state[name].count(old) == 1 and new in (Path(source['task']['cwd']) / name).read_text())
                state[name] = state[name].replace(old, new, 1)
                applied.append(graft)
        self.check('complete_selected_import_and_grafts', imported == allowed and len(applied) == len(grafts)
                   and all((self.worktree / name).read_text() == text for name, text in state.items()))

    def command_allowed(self, command, *, comment_report=None):
        argv = support.literal(command)
        if not argv or any(word in ('--no-verify', '--no-gpg-sign') for word in argv):
            return False
        if comment_report is not None and argv == ['sha256sum', str(comment_report)]:
            return True
        binary = Path(argv[0]).name
        if binary in ('python', 'python3'):
            return len(argv) >= 3 and ((self.worktree / argv[1]).resolve() == self.probe or (
                (self.worktree / argv[1]).resolve() == self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'
                and argv[2] in ('run', 'wait', 'list', 'close', 'stats', 'detect')))
        if binary == 'git':
            rest = argv[1:]
            if rest[:1] == ['-C'] and len(rest) > 2:
                if Path(rest[1]).resolve() != self.worktree:
                    return False
                rest = rest[2:]
            if not rest:
                return False
            if rest[0] in ('status', 'diff', 'show', 'log', 'blame', 'rev-parse', 'rev-list', 'diff-tree', 'ls-files', 'ls-remote'):
                return not any(word.startswith('--output') for word in rest)
            if rest[0] == 'add':
                return bool(rest[1:]) and all(word in ('--', 'cli.py', 'storage.py') for word in rest[1:])
            if rest[0] == 'push':
                return [word for word in rest[1:] if word not in ('-u', '--set-upstream')] == ['origin', self.branch]
            if rest[0] == 'commit':
                return '-n' not in rest[1:]
            return rest == ['branch', '--show-current'] or rest == ['remote', 'get-url', 'origin']
        if binary in ('gh', 'origin'):
            if argv[1:3] == ['pr', 'create']:
                return ('--base' in argv and argv.index('--base') + 1 < len(argv)
                        and argv[argv.index('--base') + 1] == self.args.base_ref and '--draft' not in argv
                        and ('--head' not in argv or argv.index('--head') + 1 < len(argv)
                             and argv[argv.index('--head') + 1] == self.branch)
                        and ('--repo' not in argv or argv.index('--repo') + 1 < len(argv)
                             and argv[argv.index('--repo') + 1] == self.args.forge_repo))
            return argv[1:3] in (['repo', 'view'], ['pr', 'view'], ['pr', 'list'])
        return argv in (['command', '-v', 'origin'], ['which', 'origin'], ['pwd']) or binary == 'cat' and len(argv) == 2 and not argv[1].startswith('-')

    def source_snapshot(self, revision, label):
        directory = self.directory / ('snapshot-' + label)
        directory.mkdir()
        for name in SOURCE_FILES:
            data = subprocess.run(['git', '-C', str(self.worktree), 'show', revision + ':' + name],
                                  capture_output=True, timeout=20, check=True).stdout
            (directory / name).write_bytes(data)
        self.snapshots[label] = {name: core.sha(directory / name) for name in SOURCE_FILES}
        return directory

    def verify(self):
        rows = self.scan()
        self.check('all_actual_tasks_done_closed', bool(rows) and all(s.get('state') == 'done' and s.get('closed') is True for _, s in rows))
        tasks = [task for task, _ in rows]
        paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
        self.check('one_native_controller_session', len(paths) == 1)
        native_path = paths[0]
        required = [self.bundle / 'skills' / path for path in (*READS, f'poteto-mode/playbooks/{self.args.scenario}.md')]
        events, all_events = self.native_events(native_path), self.native_events(native_path, include_errors=True)
        records = self.task_records(tasks, events)
        self.check('unique_comment_hash_owner', 'comment-review' in records)
        comment_report = Path(records['comment-review']['task']['task_dir']).resolve() / 'report.md'
        self.native = core.audit_pi(native_path, self.session, self.worktree, self.wall_started, self.spec,
                                    required, [], tasks, self.bundle, allowed_artifact_hashes=(comment_report,))
        self.check('native_model_effort_reads_delivery', all(c.get('ok') is True for c in self.native['checks']))
        self.check('controller_shell_authorization', all(self.command_allowed(e['args'].get('command', ''),
                   comment_report=comment_report) for e in all_events if e['name'] == 'bash'))
        required_slots = set(self.slots) - {slot for slot in self.slots if slot.startswith('review-')}
        self.check('all_mandatory_slots_used_once', required_slots <= set(records))
        first_launch = min(r['launch']['call_row'] for r in records.values())
        checklist = self.written(events, 'checklist.md', before=first_launch)
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / f'skills/poteto-mode/playbooks/{self.args.scenario}.md').read_text(), re.M)
        self.check('exact_original_eight_step_checklist', len(steps) == 8 and re.findall(r'^\d+\. (.+)$', checklist['args']['content'], re.M) == steps)
        for resource in ('poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
                         'pstack-herdr/references/herdr-tools.md', 'herdr-orchestrator/SKILL.md',
                         f'poteto-mode/playbooks/{self.args.scenario}.md'):
            self.check('initial_full_read_' + resource.replace('/', '_'), bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource, before=checklist['call_row'])))
        phases = self.written(events, 'phases.json', before=first_launch)
        self.check('architect_and_arena_phase_todos', json.loads(phases['args']['content']) == {
            'architect': ['Ground', 'Sketch', 'Agree', 'Implement', 'Scrap'],
            'arena': ['Frame', 'Fan out', 'Cross-judge', 'Pick', 'Graft', 'Verify']})
        before = self.native_probe(events, self.directory / 'native-before', 'characterize', self.baseline)
        explorers = [records['how-a'], records['how-b']]
        explanation = records['how-summary']
        self.check('how_loaded_before_exploration', bool(core.workflow_reads(events, self.worktree,
                   self.bundle / 'skills/how/SKILL.md', before=min(r['launch']['call_row'] for r in explorers))))
        self.check('full_how_parallel_exploration', max(r['launch']['result_row'] for r in explorers) < min(r['delivery']['call_row'] for r in explorers)
                   and all(self.read_before(r) < explanation['launch']['call_row'] for r in explorers)
                   and all(body in explanation['brief'] for r in explorers for _, body in r['reports'])
                   and all(key in explanation['brief'] for key in ('cli-contract', 'staging-persistence')))
        grounding = self.written(events, 'grounding.md', after=self.read_before(explanation))
        self.check('full_how_explanation_preserved', all(body in grounding['args']['content'] for _, body in explanation['reports']))
        self.stage('how_ground', [before, checklist, phases, grounding, explanation['launch'], explanation['delivery']])
        designs = self.panel(records, 'design', 'architect runners')
        self.check('characterization_after_how_before_architect', before['call_row'] > self.read_before(explanation)
                   and before['result_row'] < min(r['launch']['call_row'] for r in designs))
        design, selection = self.competition(events, records, 'architect', designs, 'design-judge', max(grounding['result_row'], before['result_row']))
        rationale = self.written(events, 'rationale.md', after=selection['result_row'])
        self.design_package = rationale
        self.design_package_hash = digest_text(rationale['args']['content'])
        package_path = self.artifacts / 'rationale.md'
        self.check('architect_package_frozen_after_selection', core.sha(package_path) == self.design_package_hash
                   and not any(e['name'] in ('write', 'edit') and isinstance(e['args'].get('path'), str)
                               and (self.worktree / e['args']['path']).resolve() == package_path
                               and e['call_row'] > rationale['result_row'] for e in all_events))
        self.check('usage_first_synthesized_rationale', all(heading in rationale['args']['content'] for heading in (
            '## Problem', '## Usage', '## Shape', '## Synthesis decision', '## Alternatives considered')))
        if self.args.scenario == 'feature':
            implementations = self.panel(records, 'implementation', 'arena runners')
        else:
            implementations = [records['implementation']]
        first_code = min(r['launch']['call_row'] for r in implementations)
        throughput = self.written(events, 'throughput.md', before=first_code, after=rationale['result_row'])
        self.check('four_actual_throughput_dimensions', all(re.search(
            r'^[-*] (?:\[ \] )?(?:\*\*)?' + re.escape(label) + r'\.?(?:\*\*)?:?\s+\S.+$',
            throughput['args']['content'], re.M) for label in THROUGHPUT)
            and len(re.findall(r'^[-*] ', throughput['args']['content'], re.M)) == 4)
        if self.args.scenario == 'feature':
            implementation, imported_at = self.competition(events, records, 'implementation', implementations,
                                                          'implementation-judge', throughput['result_row'])
            implementation_scores = self.written(events, 'implementation-scores.json')
            for record in implementations:
                for name in ('cli.py', 'storage.py'):
                    self.check('delivered_candidate_source_read', bool(core.workflow_reads(events, self.worktree, Path(record['task']['cwd']) / name,
                               after=record['delivery']['result_row'], before=implementation_scores['call_row'])))
        else:
            implementation, imported_at = design, selection
            self.check('refactor_follows_target_shape', first_code > throughput['result_row']
                       and str(self.artifacts / 'rationale.md') in implementations[0]['brief'])
        self.authorized_sources(all_events, records, implementation, imported_at)
        self.verify_worktrees(records)
        self.check('integration_clean_and_owned_branch', not self.git('status', '--porcelain=v1', '--untracked-files=all')
                   and self.git('branch', '--show-current') == self.branch)
        commits = self.git('rev-list', '--reverse', self.base + '..HEAD').splitlines()
        self.check('bounded_ordered_commits', 1 <= len(commits) <= 3 and all(
            self.git('rev-parse', commit + '^') == (self.base if index == 0 else commits[index - 1]) for index, commit in enumerate(commits)))
        self.commits = commits
        final_sources = {name: core.sha(self.worktree / name) for name in SOURCE_FILES}
        self.check('original_oracle_and_money_frozen', all(final_sources[name] == self.baseline[name] for name in ('money.py', 'e2e_import.py')))
        mode = 'feature' if self.args.scenario == 'feature' else 'characterize'
        after = self.native_probe(events, self.directory / 'native-after', mode, final_sources)
        self.check('native_final_after_implementation', after['call_row'] > max(self.read_before(r) for r in implementations)
                   and (self.args.scenario != 'feature' or after['call_row'] > imported_at['result_row']))
        final = core.read_json(self.directory / 'native-after/observation.json')
        self.check('frozen_before_receipt', core.read_json(self.directory / 'native-before/observation.json') == self.before)
        if self.args.scenario == 'refactoring':
            self.check('native_exact_cli_equivalence', final['record'] == self.before['record'] and final['missing_field_fixed'] == self.before['missing_field_fixed'])
            self.verify_reader_load(records['reader-load'], events, after)
            self.verify_staging_shape()
        self.stage('implementation_verify', [throughput, after] + [r['launch'] for r in implementations])
        scrap = self.written(events, 'scrap.json', after=after['result_row'])
        scrap_data = json.loads(scrap['args']['content'])
        self.check('actual_scrap_assessment', type(scrap_data.get('required')) is bool and isinstance(scrap_data.get('observations'), list) and scrap_data.get('reason'))
        if scrap_data['required']:
            raise Failure('architecture_scrap_required_unresolved')
        self.stage('architect_agree_implement_scrap', [selection, rationale, throughput, after, scrap])
        self.verify_interrogate(records, events, bool(design['contested'] or implementation['contested']), after)
        self.verify_comment(records['comment-review'], events, all_events, final_sources)
        self.verify_commits(events, commits, final_sources, after, mode)
        self.verify_opening(events, all_events, commits[-1], after)
        self.check('oracle_and_baseline_integrity', core.sha(self.probe) == self.probe_hash)

    def verify_worktrees(self, records):
        for slot, record in records.items():
            cwd = Path(record['task']['cwd'])
            if cwd == self.worktree:
                self.check('integration_slot_scope_' + slot, slot in ('implementation', 'comment-review'))
                continue
            mutable = self.args.scenario == 'feature' and slot.startswith('implementation-') and slot != 'implementation-judge'
            changed = set(self.git('diff', '--name-only', self.base, repo=cwd).splitlines())
            self.check('isolated_source_scope_' + slot, self.git('rev-parse', 'HEAD', repo=cwd) == self.base
                       and (bool(changed) and changed <= {'cli.py', 'storage.py'} if mutable else not changed)
                       and not self.git('ls-files', '--others', '--exclude-standard', repo=cwd))
            if mutable:
                self.snapshots[slot] = {name: core.sha(cwd / name) for name in SOURCE_FILES}
                observation = self.observe(cwd, 'independent-' + slot, 'feature')
                matches_source = observation.get('source_sha256') == self.snapshots[slot]
                if not hasattr(self, 'candidate_outcomes'):
                    self.candidate_outcomes = {}
                self.candidate_outcomes[slot] = {
                    'verdict': 'pass' if observation.get('verdict') == 'pass' and matches_source else 'fail',
                    'source_sha256': observation.get('source_sha256'),
                    'observation_sha256': core.sha(self.directory / ('independent-' + slot) / 'observation.json'),
                }
                self.check('candidate_real_cli_pass_' + slot, observation.get('mode') == 'feature'
                           and observation.get('verdict') == 'pass' and matches_source)

    def verify_reader_load(self, record, events, after):
        self.check('reader_load_reviews_actual_final', record['launch']['call_row'] > after['result_row']
                   and str(self.worktree / 'storage.py') in record['brief'])
        report = core.read_json(record['directory'] / 'reader_load.json')
        self.check('concrete_reader_load_gain', report.get('worth_keeping') is True and bool(report.get('improvements'))
                   and isinstance(report.get('regressions'), list))
        citations = report.get('citations', [])
        self.check('before_and_after_reader_load_citations', {item.get('side') for item in citations} == {'before', 'after'})
        before = self.git('show', self.base + ':storage.py').splitlines()
        final = (self.worktree / 'storage.py').read_text().splitlines()
        for cite in citations:
            lines = before if cite['side'] == 'before' else final
            number = cite.get('line')
            self.check('reader_load_citation_resolves', cite.get('path') == 'storage.py' and type(number) is int
                       and 1 <= number <= len(lines) and bool(cite.get('text')) and cite['text'].strip() == lines[number - 1].strip())
        self.reader_load_end = self.read_before(record)
        self.stage('reader_load_gain', [record['launch'], record['delivery'], *record['reads']])

    def verify_staging_shape(self):
        original = ast.parse(self.git('show', self.base + ':storage.py'))
        changed = ast.parse((self.worktree / 'storage.py').read_text())
        before = next(node for node in original.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_batch')
        after = next(node for node in changed.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_batch')
        self.check('public_signature_preserved', ast.dump(before.args) == ast.dump(after.args))
        old_names = {node.name for node in ast.walk(original) if isinstance(node, ast.FunctionDef)}
        helpers = [node for node in ast.walk(changed) if isinstance(node, ast.FunctionDef) and node.name not in old_names]
        called = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr for node in ast.walk(after)
                  if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
        pure_staging = []
        for helper in helpers:
            calls = [node.func.id if isinstance(node.func, ast.Name) else node.func.attr for node in ast.walk(helper)
                     if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))]
            if (helper.name in called and any(isinstance(node, ast.For) for node in ast.walk(helper))
                    and any(isinstance(node, ast.Return) for node in ast.walk(helper))
                    and not set(calls) & {'Path', 'open', 'read_text', 'read_bytes', 'write_text', 'write_bytes', 'replace', 'unlink'}):
                pure_staging.append(helper)
        self.check('staging_separate_from_persistence', bool(pure_staging))

    def verify_interrogate(self, records, events, contested, after):
        reviews = [r for slot, r in records.items() if slot.startswith('review-')]
        self.interrogate_used = bool(reviews)
        self.review_complete_row = max(after['result_row'], getattr(self, 'reader_load_end', -1))
        if contested or reviews:
            panel = self.panel(records, 'review', 'interrogate reviewers')
            self.check('formal_review_after_stable_implementation', all(r['launch']['call_row'] > after['result_row'] for r in panel))
            for resource in ('interrogate/SKILL.md', 'interrogate/references/reviewer-prompt.md',
                             'interrogate/references/rubric.md', 'interrogate/references/code-quality-review.md',
                             'interrogate/references/lead-judgment.md'):
                self.check('formal_review_guidance_' + resource.replace('/', '_'), bool(core.workflow_reads(
                    events, self.worktree, self.bundle / 'skills' / resource, before=min(r['launch']['call_row'] for r in panel))))
            common = self.written(events, 'interrogate-task.md', before=min(r['launch']['call_row'] for r in panel), after=after['result_row'])
            self.check('formal_review_common_target', self.base in common['args']['content']
                       and self.git('diff', self.base, 'HEAD') in common['args']['content']
                       and all(common['args']['content'] in r['brief'] for r in panel))
            verdict = self.written(events, 'interrogate.json', after=max(self.read_before(r) for r in panel))
            data = json.loads(verdict['args']['content'])
            self.check('formal_review_findings_resolved', data.get('resolved') is True and data.get('rationale'))
            self.review_complete_row = max(self.review_complete_row, verdict['result_row'])
            self.stage('formal_interrogate', [common, verdict, *[r['delivery'] for r in panel]])

    def verify_commits(self, events, commits, final_sources, after, mode):
        allowed = {'cli.py', 'storage.py'} if self.args.scenario == 'feature' else {'storage.py'}
        commit_events = []
        for event in events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if argv and argv[0] == 'git' and 'commit' in argv:
                commit_events.append(event)
        self.check('all_actual_commits_witnessed', len(commit_events) == len(commits))
        for index, (commit, event) in enumerate(zip(commits, commit_events)):
            changed = set(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', commit).splitlines())
            self.check('commit_scope_and_output', bool(changed) and changed <= allowed and commit[:7] in event['output'])
            snapshot = self.source_snapshot(commit, 'commit-' + str(index))
            replay = self.observe(snapshot, 'replay-commit-' + str(index), mode)
            self.check('every_committed_unit_cli_passes', replay.get('verdict') == 'pass')
            if self.args.scenario == 'refactoring':
                self.check('every_committed_unit_equivalent', replay.get('record') == self.before['record'])
            matches = []
            for observation in events:
                argv = support.literal(observation['args'].get('command', '')) if observation['name'] == 'bash' else []
                if len(argv) != 8 or (self.worktree / argv[1]).resolve() != self.probe or argv[6:] != ['--mode', mode]:
                    continue
                try:
                    value = json.loads(observation['output'])
                except ValueError:
                    continue
                if value.get('verdict') == 'pass' and value.get('source_sha256') == self.snapshots['commit-' + str(index)] and observation['result_row'] < event['call_row']:
                    matches.append(observation)
            self.check('native_verification_before_each_commit', bool(matches))
        self.check('final_source_matches_committed_snapshot', self.snapshots['commit-' + str(len(commits) - 1)] == final_sources)
        review = self.written(events, 'review.json', before=commit_events[0]['call_row'], after=self.review_complete_row)
        self.check('actual_diff_review', bool(json.loads(review['args']['content']).get('decision')))
        expected = self.git('diff', self.base, 'HEAD')
        diffs = []
        for event in events:
            if event['name'] != 'bash':
                continue
            argv = support.literal(event['args'].get('command', ''))
            if len(argv) > 3 and argv[:2] == ['git', '-C'] and argv[2] == str(self.worktree):
                argv = ['git', *argv[3:]]
            if (argv[:2] == ['git', 'diff'] and event['output'].strip() == expected.strip()
                    and event['result_row'] < review['call_row']):
                diffs.append(event)
        self.check('native_full_diff_reviewed', bool(diffs))
        for resource in ('deslop/SKILL.md', 'no-comments/SKILL.md', 'technical-writing/SKILL.md',
                         'unslop/SKILL.md', 'principle-sequence-verifiable-units/SKILL.md'):
            self.check('guidance_before_first_commit_' + resource.split('/')[0], bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource, before=min(review['call_row'], commit_events[0]['call_row']))))
        self.stage('ordered_verified_commits', [review, *commit_events])

    def verify_opening(self, events, all_events, head, after):
        creates, views, pushes, discoveries = [], [], [], []
        for event in all_events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if not argv:
                continue
            if argv in (['command', '-v', 'origin'], ['which', 'origin']):
                discoveries.append(event)
            if event['successful']:
                if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'create']:
                    creates.append(event)
                if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'view']:
                    views.append(event)
                if argv[0] == 'git' and 'push' in argv:
                    pushes.append(event)
        self.check('one_real_ready_child_creation', len(creates) == len(pushes) == 1 and bool(discoveries))
        create, push = creates[0], pushes[0]
        choice = self.written(events, 'forge.json', before=min(e['call_row'] for e in creates + views))
        selected = json.loads(choice['args']['content'])
        chosen = selected.get('forge')
        self.check('forge_resolution', chosen in ('gh', 'origin') and selected.get('reason')
                   and discoveries[0]['result_row'] < choice['call_row']
                   and all(support.literal(e['args']['command'])[0] == chosen for e in creates + views))
        if chosen == 'origin':
            self.check('origin_available_before_selection', discoveries[0]['successful'] and bool(discoveries[0]['output'].strip()))
        if chosen == 'gh' and discoveries[0]['successful'] and discoveries[0]['output'].strip():
            self.check('actual_origin_fallback_failure', any(e['name'] == 'bash' and support.literal(e['args'].get('command', ''))[:1] == ['origin']
                       and not e['successful'] and e['result_row'] < choice['call_row'] for e in all_events))
        argv = support.literal(create['args']['command'])
        self.check('explicit_ready_base', '--base' in argv and argv[argv.index('--base') + 1] == self.args.base_ref
                   and '--draft' not in argv and (chosen != 'origin' or ['--status', 'open'] == argv[-2:]))
        pushed = support.literal(push['args']['command'])
        self.check('only_owned_branch_pushed', 'origin' in pushed and self.branch in pushed
                   and not any(word in ('--all', '--mirror', '--delete', '--tags', '-f') or word.startswith('--force') for word in pushed)
                   and max(after['result_row'], self.review_complete_row) < push['call_row'] < create['call_row'])
        readback = [e for e in views if e['call_row'] > create['result_row'] and head in e['output']
                    and self.branch in e['output'] and self.args.base_ref in e['output']]
        self.check('native_real_head_base_readback', bool(readback))
        remote = self.git('ls-remote', '--heads', 'origin').splitlines()
        self.check('remote_scope_unchanged', sorted(remote) == sorted([*self.remote_heads, head + '\trefs/heads/' + self.branch]))
        current = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json',
                             'number,state,headRefName,baseRefName,isDraft')
        added = [p for p in current if p['number'] not in {p['number'] for p in self.prs_before}]
        self.check('one_child_pr_only', len(added) == 1 and all(p in current for p in self.prs_before))
        self.pr = self.forge('pr', 'view', str(added[0]['number']), '--repo', self.args.forge_repo, '--json',
                             'url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,autoMergeRequest')
        (self.directory / 'pr-readback.json').write_text(json.dumps(self.pr, indent=2) + '\n')
        self.check('independent_real_ready_stacked_pr', self.pr.get('state') == 'OPEN' and self.pr.get('isDraft') is False
                   and self.pr.get('headRefName') == self.branch and self.pr.get('headRefOid') == head
                   and self.pr.get('baseRefName') == self.args.base_ref and self.pr.get('baseRefOid') == self.base
                   and self.pr.get('autoMergeRequest') is None)
        parent = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo, '--json',
                            'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('original_parent_pr_unchanged', parent == self.parent_pr)
        reply = self.written(events, 'reply.md', after=readback[-1]['result_row'])
        self.check('reply_bound_to_real_pr', self.pr['url'] in reply['args']['content']
                   and all(label in reply['args']['content'] for label in THROUGHPUT))
        self.check('reply_preserves_no_comments_disposition', 'No-comments' in reply['args']['content']
                   and self.comment_disposition in reply['args']['content'])
        self.stage('opening_a_pr', [choice, push, create, *readback, reply])

    def finish(self):
        cleanup_ok = True
        if self.pane:
            try:
                screen = self.call(['herdr', 'pane', 'read', self.pane, '--source', 'recent', '--lines', '80'], cleanup=True)
                (self.directory / 'controller-pane.json').write_text(screen)
                self.herdr('pane', 'close', self.pane, cleanup=True)
            except Exception:
                cleanup_ok = False
        try:
            # The core scan is sufficient here; do not discover unrelated agents.
            core.Run.scan(self)
        except Exception:
            self.categories.append('task_snapshot_failed')
        for task in self.tasks.values():
            if role_header(task)[2] == 'comment-review' and task['task_id'] in self.worker_sessions:
                try:
                    shutil.copy2(self.comment_session(task), self.directory / 'retained-comment-native.jsonl')
                except Exception:
                    self.categories.append('comment_native_snapshot_failed')
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
        for pane in ([self.pane] if self.pane else []) + [task['pane_id'] for task in self.tasks.values()]:
            try:
                value = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env, capture_output=True, text=True, timeout=15)
                error = json.loads(value.stdout or value.stderr).get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if value.returncode == 0 or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        after, config_after, integrity, fixture_integrity = {}, None, False, False
        try:
            after = support.identity()
            config_after = core.sha(self.config_path)
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            integrity = (bool(self.hashes) and self.hashes == after and config_after == self.config_hash
                         and self.git('rev-parse', 'HEAD', repo=ROOT, cleanup=True) == self.revision
                         and self.git('status', '--porcelain=v1', '--untracked-files=all', repo=ROOT, cleanup=True) == self.source_status
                         and (not copied.exists() or core.sha(copied) == self.config_hash))
            if self.bundle.exists():
                integrity = integrity and all(core.sha(self.bundle / path) == digest for path, digest in self.hashes.items() if path.startswith('skills/'))
            if self.probe.exists():
                integrity = integrity and core.sha(self.probe) == self.probe_hash
            integrity = integrity and all((core.sha(path) if path.is_file() else None) == digest
                                          for path, digest in self.comment_settings.items())
            if self.original_fixture is not None:
                fixture_integrity = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo, cleanup=True),
                                     self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo, cleanup=True)) == self.original_fixture
        except Exception:
            pass
        self.checks += [{'name': 'public_source_config_bundle_oracle_integrity', 'ok': integrity},
                        {'name': 'original_fixture_unchanged', 'ok': fixture_integrity},
                        {'name': 'owned_panes_absent', 'ok': cleanup_ok}]
        passed = bool(self.checks) and not self.categories and all(check.get('ok') is True for check in self.checks)
        verdict = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        inventory = {name: 'not_run' for name in core.INVENTORY}
        inventory[self.args.scenario] = verdict
        if 'opening_a_pr' in self.stage_proof:
            inventory['opening-a-pr'] = verdict
        if not self.native:
            paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(paths) == 1:
                self.native = {'sha256': core.sha(paths[0]), 'audit_completed': False}
        receipt = {'schema': 'horch/design-playbook-e2e/v1', 'scenario': self.args.scenario,
                   'verdict': 'pass' if passed else 'fail', 'workflow_verdict': verdict,
                   'full_inventory_verdict': 'not_run', 'inventory': inventory,
                   'source_revision': self.revision, 'source_sha256_before': self.hashes, 'source_sha256_after': after,
                   'config_sha256_before': self.config_hash, 'config_sha256_after': config_after,
                   'fixture_baseline_sha256': self.baseline, 'source_snapshots': self.snapshots,
                   'architect_package_sha256': getattr(self, 'design_package_hash', None),
                   'candidate_outcomes': getattr(self, 'candidate_outcomes', {}),
                   'native_transcript': self.native, 'native_stages': self.stage_proof, 'tasks': self.task_facts,
                   'comment_native': self.comment_native,
                   'mandatory_comment_review_verified': 'no_comments_fresh_review' in self.stage_proof,
                   'controller': {key: self.spec.get(key) for key in ('harness', 'provider', 'model', 'effort')},
                   'checks': self.checks, 'failure_categories': self.categories, 'last_phase': self.phase,
                   'commit_count': len(getattr(self, 'commits', [])), 'interrogate_used': getattr(self, 'interrogate_used', False),
                   'forge': {'ready_pr_verified': passed and self.pr is not None, 'retained': True if self.pr else 'unconfirmed'},
                   'seconds': round(time.monotonic() - self.started, 3),
                   'limitations': [
                       'Only the selected Feature or Refactoring route is run; other inventory entries remain not_run.',
                       'Full complex How and Architect are required; Feature additionally requires real implementation Arena.',
                       'Controller imports must exactly match a delivered base; each graft replacement must be a read loser fragment with coherent rationale.',
                       'A necessary synthesis edit outside that conservative provenance protocol remains unresolved.',
                       'Architecture requiring Scrap/reframing remains unresolved; this bounded driver never invents a replacement design round.',
                       'Formal Interrogate runs the entire configured panel only when contested or explicitly used; unresolved review blocks shipping.',
                       'A fresh configured judgment and prose worker performs the mandatory CommentSicko review on the stable integration diff; any required revision, rejected report, rerun or deeper follow-up leaves this bounded run unresolved.',
                       'CLI equivalence normalizes traceback locations to their final exception line; raw complete stderr remains private.',
                       'Worktrees, owned branch, private artifacts and ready PR are retained; no merge or auto-merge is authorized.',
                   ]}
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', required=True, choices=('feature', 'refactoring'))
    parser.add_argument('--controller', required=True, help='existing configured Pi worker')
    parser.add_argument('--repo', type=Path, default=ROOT, help='trusted orchestrator source root')
    parser.add_argument('--fixture-repo', type=Path, required=True, help='existing clean private fixture clone')
    parser.add_argument('--forge-repo', required=True, help='private fixture owner/name')
    parser.add_argument('--base-ref', required=True, help='existing exact remote parent branch; never trunk')
    parser.add_argument('--parent-pr', type=int, required=True, help='existing ready open parent PR whose head is base-ref')
    parser.add_argument('--output', type=Path, required=True, help='private external artifact parent')
    parser.add_argument('--caller-pane', required=True, help='independently verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=5400, help='overall deadline; no automatic retries')
    args = parser.parse_args()
    for key in ('repo', 'fixture_repo', 'output'):
        setattr(args, key, getattr(args, key).expanduser().resolve())
    if args.repo != ROOT:
        parser.error('--repo must identify this driver source checkout')
    if any(args.output == root or root in args.output.parents for root in (ROOT, args.fixture_repo)):
        parser.error('--output must be outside source and fixture checkouts')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.forge_repo):
        parser.error('--forge-repo must be owner/name')
    if args.parent_pr <= 0 or args.base_ref in ('main', 'master') or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', args.base_ref) or '..' in args.base_ref:
        parser.error('provide a positive existing parent PR and non-trunk base ref')
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
