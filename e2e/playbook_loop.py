#!/usr/bin/env python3
"""Live Pi playbook evaluation, with private artifacts and conservative receipts.

Runs a real controller in an owned Herdr tab. It never retries, edits worker
configuration, grants trust, or performs forge writes. Retains its worktree.
Only evidence.json is intended for review for eventual sanitized publication.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/herdr-orchestrator/scripts'))
import horch  # noqa: E402
import playbook_cases as cases  # noqa: E402

INVENTORY = ('investigation', 'bug-fix', 'perf-issue', 'hillclimb',
             'runtime-forensics', 'trace-forensics', 'feature', 'refactoring',
             'prototype', 'visual-parity', 'authoring-a-skill', 'eval', 'babysit',
             'shipping', 'autonomous-run', 'orchestrate', 'autopilot-full',
             'autopilot-stack', 'session-pickup', 'pause-safely',
             'multi-phase-plan', 'worktree-cleanup', 'opening-a-pr')


class Failure(Exception):
    """A public, fixed failure category; never arbitrary subprocess output."""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source_hashes():
    paths = [*ROOT.joinpath('skills').rglob('*'), Path(__file__).resolve(),
             Path(cases.__file__).resolve(), ROOT / 'e2e/controller_loop.py',
             ROOT / 'e2e/review_loop.py']
    return {str(p.relative_to(ROOT)): sha(p) for p in paths
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def text_content(message):
    return '\n'.join(c.get('text', '') for c in message.get('content', [])
                     if isinstance(c, dict) and c.get('type') == 'text')


def read_target(name, args, cwd):
    """Recognize literal read/cat/sed only; mentioning a path is insufficient."""
    if name == 'read' and isinstance(args.get('path'), str):
        return (cwd / args['path']).resolve()
    if name != 'bash' or not isinstance(args.get('command'), str):
        return None
    command = args['command']
    # Fail closed for substitutions, pipelines, redirects and compound commands.
    if any(t in command for t in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if len(words) == 2 and words[0] == 'cat' and not words[1].startswith('-'):
        return (cwd / words[1]).resolve()
    if (len(words) == 4 and words[:2] == ['sed', '-n']
            and re.fullmatch(r'\d+,\d+p', words[2]) and not words[3].startswith('-')):
        return (cwd / words[3]).resolve()
    return None


def invocation_result(command, output, cwd, requirement):
    """Match one actual Python CLI invocation and independently check its result."""
    lines = command.strip().splitlines()
    if not lines:
        return False
    first, stdin = lines[0], None
    heredoc = re.search(r"\s*<<\s*(['\"])([A-Za-z_]\w*)\1\s*$", first)
    if heredoc:
        if len(lines) < 3 or lines[-1].strip() != heredoc[2]:
            return False
        first, stdin = first[:heredoc.start()], '\n'.join(lines[1:-1])
    elif len(lines) != 1:
        return False
    if any(token in first for token in (';', '|', '&', '>', '<', '`', '$', '\\')):
        return False
    try:
        argv = shlex.split(first)
        if (len(argv) < 2 or Path(argv[0]).name not in {'python', 'python3'}
                or (cwd / argv[1]).resolve() != Path(requirement['script']).resolve()):
            return False
        prefix = requirement.get('arguments', [])
        if argv[2:2 + len(prefix)] != prefix:
            return False
        actual = json.loads(output.strip())
        oracle = requirement['oracle']
        if oracle == 'json_equals':
            return len(argv) == 2 + len(prefix) and actual == requirement['expected_output']
        if oracle == 'rounding':
            if len(argv) != 2 + len(prefix) or stdin is None:
                return False
            data = json.loads(stdin)
            numerators = [r['quantity'] * r['unit_price_cents'] * (10000 - r['discount_bp'])
                          for r in data['lines']]
            if not numerators or not any(n % 10000 for n in numerators):
                return False
            variant = requirement['variant']
            total = (sum((n + 5000) // 10000 for n in numerators) if variant == 'per_line'
                     else (sum(numerators) + 5000) // 10000)
            return actual == {'variant': variant, 'total_cents': total}
        if oracle == 'sqlite_query':
            if len(argv) != 3 + len(prefix):
                return False
            sql = argv[-1]
            if not sql.lstrip().lower().startswith('select '):
                return False
            with sqlite3.connect(f"file:{requirement['database']}?mode=ro", uri=True) as database:
                deadline = time.monotonic() + 3
                database.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                accessed = set()
                def authorize(action, table, column, *_):
                    if action == sqlite3.SQLITE_READ and table == 'profile_samples':
                        accessed.add(column)
                    return sqlite3.SQLITE_OK
                database.set_authorizer(authorize)
                cursor = database.execute(sql)
                expected = {'columns': [item[0] for item in cursor.description],
                            'rows': [list(row) for row in cursor.fetchmany(100)]}
            return (bool(expected['rows']) and actual == expected
                    and 'function' in accessed and bool(accessed & {'self_seconds', 'cumulative_seconds'}))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        return False
    return False


def audit_pi(path, session, cwd, started, spec, required_reads, required_commands, tasks, bundle,
             required_invocations=(), required_order=()):
    """Trust native successful calls/results, never a controller's self-report."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows or rows[0].get('type') != 'session' or rows[0].get('version') != 3:
        raise Failure('native_transcript_unsupported')
    header = rows[0]
    if (Path(header.get('cwd', '')).resolve() != cwd or not started <= stamp(header['timestamp']) <= time.time()
            or not header.get('id')):
        raise Failure('native_session_binding_failed')
    value = session.get('value')
    if session.get('agent') != 'pi' or not value:
        raise Failure('native_session_identity_missing')
    if session.get('kind') == 'path':
        if Path(value).expanduser().resolve() != path.resolve():
            raise Failure('native_session_identity_mismatch')
    elif value != header['id']:
        raise Failure('native_session_identity_mismatch')
    pending, successful, read_paths = {}, [], set()
    delivered, artifact_reads = set(), set()
    known_tasks = {task['task_id']: task for task in tasks}
    horch_script = (bundle / 'skills/herdr-orchestrator/scripts/horch.py').resolve()
    last = None
    ids = set()
    models = set()
    thinking = set()
    for row in rows[1:]:
        identity = row.get('id')
        if identity in ids or not identity or row.get('parentId') != last:
            raise Failure('native_transcript_branch_or_identity_ambiguous')
        ids.add(identity)
        last = identity
        if row.get('type') == 'model_change':
            models.add((row.get('provider'), row.get('modelId')))
        if row.get('type') == 'thinking_level_change':
            thinking.add(row.get('thinkingLevel'))
        message = row.get('message', {})
        if message.get('role') == 'assistant':
            if message.get('model'):
                models.add((message.get('provider'), message['model']))
            for block in message.get('content', []):
                if block.get('type') != 'toolCall':
                    continue
                name = block.get('name', '')
                if name not in {'read', 'bash', 'write', 'edit', 'grep', 'find', 'ls'}:
                    raise Failure('native_delegation_or_unsupported_tool')
                args = block.get('arguments')
                if not isinstance(args, dict) or block.get('id') in pending:
                    raise Failure('native_tool_arguments_invalid')
                command = args.get('command', '')
                if name == 'bash' and re.search(r'(?:^|[;&|\n]\s*)(?:codex|claude|pi)\b|\bherdr\s+agent\s+start\b', command):
                    raise Failure('native_delegation_forbidden')
                pending[block['id']] = (name, args)
        elif message.get('role') == 'toolResult':
            pair = pending.pop(message.get('toolCallId'), None)
            if pair is None or message.get('toolName') != pair[0]:
                raise Failure('native_tool_result_unbound')
            if message.get('isError') is not False:
                continue
            name, args = pair
            output = text_content(message)
            successful.append((name, args, output))
            target = read_target(name, args, cwd)
            # Other literal artifact-access forms must not disappear from an
            # ordering audit merely because their shell grammar is unsupported.
            argument_text = json.dumps(args, ensure_ascii=False)
            if name in {'bash', 'grep', 'find', 'ls'} and target is None:
                if name == 'bash':
                    from controller_loop import without_literal_file_writes
                    argument_text = without_literal_file_writes(args.get('command', ''))
                mentions_task = any(task['task_dir'] in argument_text or task['task_id'] in argument_text
                                    for task in tasks)
                is_horch_operation = False
                if name == 'bash' and not any(t in argument_text for t in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
                    try:
                        argv = shlex.split(argument_text)
                        is_horch_operation = (len(argv) >= 3 and Path(argv[0]).name in {'python', 'python3'}
                                              and (cwd / argv[1]).resolve() == horch_script
                                              and argv[2] in {'run', 'wait', 'list', 'close', 'stats'})
                    except ValueError:
                        pass
                if mentions_task and not is_horch_operation:
                    raise Failure('native_artifact_access_unsupported')
            if name == 'bash':
                command = args.get('command', '')
                words = []
                if not any(token in command for token in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
                    try:
                        words = shlex.split(command)
                    except ValueError:
                        pass
                # Delivery must come from the actual literal horch wait command,
                # not echo, prose or reading a fabricated status file.
                if (len(words) >= 3 and Path(words[0]).name in ('python', 'python3')
                        and (cwd / words[1]).resolve() == horch_script and words[2] == 'wait'):
                    for line in output.splitlines():
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        task = known_tasks.get(event.get('task_id'))
                        if task and event.get('state') == 'done':
                            if (event.get('result_path') != task['result_path']
                                    or stamp(row['timestamp']) < Path(task['result_path']).stat().st_mtime):
                                raise Failure('native_delivery_binding_failed')
                            delivered.add(task['task_id'])
            if target:
                for task in tasks:
                    directory = Path(task['task_dir']).resolve()
                    if (directory in target.parents and target.is_file()
                            and target.name not in {'brief.md', 'task.json', 'state.json'}):
                        if task['task_id'] not in delivered:
                            raise Failure('artifact_read_before_proven_delivery')
                        content = target.read_text().strip()
                        if content and content in output:
                            artifact_reads.add(task['task_id'])
            if target in required_reads:
                # Native read offsets/truncation and partial sed ranges count only
                # if the actual result contains the complete required document.
                content = target.read_text().strip()
                if content and content in output:
                    read_paths.add(target)
    if pending:
        raise Failure('native_tool_result_missing')
    if not models or any(model != spec['model'] or (spec.get('provider') and provider != spec['provider'])
                         for provider, model in models):
        raise Failure('native_model_changed_or_unproven')
    if spec.get('effort') and thinking != {spec['effort']}:
        raise Failure('native_effort_changed_or_unproven')
    checks = [{'name': 'read ' + str(p.relative_to(bundle)), 'ok': p in read_paths}
              for p in required_reads]
    checks.extend([{'name': 'tasks observed delivered through horch wait',
                    'ok': delivered == set(known_tasks)},
                   {'name': 'task artifacts read after delivery',
                    'ok': artifact_reads == set(known_tasks)}])
    for requirement in required_commands:
        pattern = re.compile(requirement['pattern'])
        checks.append({'name': 'command text hint: ' + requirement['name'], 'ok': any(
            name == 'bash' and pattern.search(args.get('command', '')) and bool(output.strip())
            for name, args, output in successful)})
    positions = {}
    for requirement in required_invocations:
        for index, (name, args, output) in enumerate(successful):
            if name == 'bash' and invocation_result(args.get('command', ''), output, cwd, requirement):
                positions.setdefault(requirement['name'], index)
        checks.append({'name': requirement['name'], 'ok': requirement['name'] in positions})
    if required_order:
        checks.append({'name': 'native required invocation order', 'ok': all(
            left in positions and right in positions and positions[left] < positions[right]
            for left, right in zip(required_order, required_order[1:]))})
    return {'checks': checks, 'tool_calls': len(successful),
            'session_id_sha256': hashlib.sha256(header['id'].encode()).hexdigest(),
            'sha256': sha(path), 'format': 'pi-session-v3',
            'harness': 'pi', 'model': spec['model'], 'effort': spec.get('effort')}


class Run:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.wall_started = time.time()
        self.deadline = self.started + max(1, args.max_seconds)
        self.directory = args.output / ('playbook-' + str(time.time_ns()))
        self.directory.mkdir(parents=True, mode=0o700)
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.directory / 'config'),
                        XDG_STATE_HOME=str(self.directory / 'state'))
        # Isolate horch without changing the shell's existing Mise trust roots.
        for variable, xdg, default in (
                ('MISE_CONFIG_DIR', 'XDG_CONFIG_HOME', Path.home() / '.config'),
                ('MISE_STATE_DIR', 'XDG_STATE_HOME', Path.home() / '.local/state')):
            self.env.setdefault(variable, str(Path(os.environ.get(xdg, default)) / 'mise'))
        self.task_root = self.directory / 'state/herdr-orchestrator/tasks'
        self.worktree = args.repo / 'handoff' / self.directory.name / 'worktree'
        self.bundle = self.directory / 'bundle'
        self.artifacts = self.directory / 'artifacts'
        self.pane = None
        self.agent = 'playbook-e2e-' + format(time.time_ns(), 'x')
        self.session = {}
        self.tasks = {}
        self.checks, self.stage_checks, self.categories = [], [], []
        self.hashes = {}
        self.config_hash = None
        self.spec = {}
        self.config = {}
        self.native = {}
        self.behavior = {}
        self.prepared = {}
        self.revision = None
        self.case = cases.CASES.get(args.scenario, {})
        self.command_number = 0
        self.tracked_baseline = None
        self.untracked_baseline = set()
        self.inventory_names = sorted(p.stem for p in (ROOT / 'skills/poteto-mode/playbooks').glob('*.md'))
        self.phase = 'preflight'

    def call(self, argv, *, cleanup=False):
        timeout = 30 if cleanup else min(150, self.deadline - time.monotonic())
        if timeout <= 0:
            raise Failure('overall_timeout')
        self.command_number += 1
        try:
            proc = subprocess.run([str(a) for a in argv], env=self.env, text=True,
                                  capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Failure('subprocess_timeout') from None
        # Commands, stdout, stderr and failures stay private.
        (self.directory / f'command-{self.command_number}.json').write_text(json.dumps(
            {'argv': [str(a) for a in argv], 'returncode': proc.returncode,
             'stdout': proc.stdout, 'stderr': proc.stderr}, indent=2))
        if proc.returncode:
            raise Failure('subprocess_failed')
        return proc.stdout

    def herdr(self, *args, cleanup=False):
        return json.loads(self.call(['herdr', *args], cleanup=cleanup))['result']

    def check(self, name, ok):
        self.checks.append({'name': name, 'ok': bool(ok)})
        if not ok:
            raise Failure('assertion_failed')

    def preflight(self):
        self.check('inventory_matches_23_declared_playbooks',
                   len(self.inventory_names) == 23 and set(self.inventory_names) == set(INVENTORY))
        if self.args.max_seconds <= 0 or not self.case:
            raise Failure('scenario_or_duration_invalid')
        repo = Path(self.call(['git', '-C', self.args.repo, 'rev-parse', '--show-toplevel']).strip()).resolve()
        self.check('repository_root', repo == self.args.repo)
        self.revision = self.call(['git', '-C', repo, 'rev-parse', 'HEAD']).strip()
        self.hashes = source_hashes()
        self.config_path = horch.config_path()
        self.config_hash = sha(self.config_path)
        # horch's CLI error details may contain configuration or caller paths.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane)
        self.spec = self.config['workers'].get(self.args.controller, {})
        if self.spec.get('harness') != 'pi':
            raise Failure('controller_harness_unsupported')
        roles = self.case.get('expected_roles', [])
        for role in roles:
            selection = self.config.get('roles', {}).get(role)
            names = selection if isinstance(selection, list) else [selection]
            if not names or any(name not in self.config['workers'] for name in names):
                raise Failure('configured_role_missing')

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.call(['git', '-C', self.args.repo, 'worktree', 'add', '--detach', self.worktree, 'HEAD'])
        self.prepared = cases.prepare(self.args.scenario, self.worktree, self.artifacts, self.bundle)
        (self.directory / 'prepared.json').write_text(json.dumps(self.prepared, indent=2) + '\n')
        self.tracked_baseline = self.call(['git', '-C', self.worktree, 'diff', '--binary', 'HEAD'])
        self.untracked_baseline = set(self.call(['git', '-C', self.worktree, 'ls-files',
                                                '--others', '--exclude-standard']).splitlines())
        for role in self.prepared.get('expected_roles', []):
            value = self.config.get('roles', {}).get(role)
            names = value if isinstance(value, list) else [value]
            if not names or any(name not in self.config['workers'] for name in names):
                raise Failure('configured_role_missing')
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'],
                         '--cwd', self.worktree, '--label', 'playbook-e2e', '--no-focus',
                         '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                         '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'],
                         '--env', 'MISE_CONFIG_DIR=' + self.env['MISE_CONFIG_DIR'],
                         '--env', 'MISE_STATE_DIR=' + self.env['MISE_STATE_DIR'])
        self.pane = tab['root_pane']['pane_id']
        prompt = f'''This is a real playbook evaluation. Read {self.bundle / 'skills/poteto-mode/SKILL.md'}
in full first, then select and execute the applicable original playbook and its
Herdr mapping. Follow the playbook's required stages and use configured roles.
The source bundle is {self.bundle}; work only in {self.worktree}.
For each required source document use a separate native read call without an
offset/limit, or a literal cat of that single file, so its full contents appear
in the native tool result. If truncated, report the unsupported evidence stage.
Use {self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'} for delegation,
with --caller-pane {self.pane} when dispatching; never native subagents.
For delivery use a standalone native bash call of python3 followed by the exact
absolute horch.py path, wait, and task IDs. Read each delivered task's report or
result with a separate native read call, after wait has reported state done.
Write your final answer to {self.artifacts / 'reply.md'}.
Put all checklists and control notes under {self.artifacts}; the worktree is read-only.
Do not create or edit evidence.json or an evaluator/checker. No external forge
writes, merges, configuration edits, trust changes, or model substitutions are
authorized. Report any blocked required stage explicitly.
\n{self.prepared['prompt']}\n'''
        brief = self.directory / 'controller-brief.md'
        brief.write_text(prompt)
        session_dir = self.directory / 'native-sessions'
        session_dir.mkdir()
        flags = horch.launch_args(self.spec, self.directory)
        flags += ['--session-dir', str(session_dir)]
        started = self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', self.pane,
                             '--timeout', '90000', '--', *flags)
        self.check('controller_started', started.get('type') == 'agent_started')
        ready_deadline = min(self.deadline, time.monotonic() + 90)
        while time.monotonic() < ready_deadline:
            entry = self.herdr('agent', 'get', self.agent)['agent']
            session = entry.get('agent_session') or {}
            if (session.get('agent') == 'pi' and session.get('source') == 'herdr:pi'
                    and session.get('value') and entry.get('agent_status') in ('idle', 'done')):
                self.session = session
                break
            if entry.get('agent_status') == 'blocked':
                raise Failure('controller_start_blocked')
            time.sleep(min(1, max(0, ready_deadline - time.monotonic())))
        else:
            raise Failure('controller_session_not_ready')
        prompted = self.herdr('agent', 'prompt', self.agent,
                              f'Read {brief} in full and execute it.', '--wait',
                              '--until', 'working', '--timeout', '30000')
        self.check('controller_prompted', prompted.get('type') == 'agent_prompted')

    def scan(self):
        rows = []
        for path in sorted(self.task_root.glob('t-*/task.json')):
            task = read_json(path)
            if (not horch.TASK_ID_RE.fullmatch(path.parent.name)
                    or task.get('task_id') != path.parent.name
                    or Path(task.get('task_dir', '')).resolve() != path.parent.resolve()
                    or task.get('agent') != 'horch-' + path.parent.name[2:]):
                raise Failure('task_identity_invalid')
            # Only these independently discovered isolated tasks are cleanup-owned.
            self.tasks[task['task_id']] = task
            state = read_json(path.parent / 'state.json')
            rows.append((task, state))
        return rows

    def monitor(self):
        idle_since = None
        while time.monotonic() < self.deadline:
            rows = self.scan()
            if any(s.get('state') in horch.SETTLED_STATES - {'done'} for _, s in rows):
                raise Failure('worker_failed_or_blocked')
            entry = self.herdr('agent', 'get', self.agent)['agent']
            self.session = entry.get('agent_session') or self.session
            status = entry.get('agent_status')
            if status == 'blocked':
                raise Failure('controller_blocked')
            if status in ('idle', 'done'):
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since >= 8:
                    return
            else:
                idle_since = None
            time.sleep(min(1, max(0, self.deadline - time.monotonic())))
        raise Failure('overall_timeout')

    def verify(self):
        rows = self.scan()
        if self.prepared.get('read_only'):
            self.check('tracked_worktree_unchanged', self.call(
                ['git', '-C', self.worktree, 'diff', '--binary', 'HEAD']) == self.tracked_baseline)
            untracked = set(self.call(['git', '-C', self.worktree, 'ls-files',
                                      '--others', '--exclude-standard']).splitlines())
            unexpected = {p for p in untracked - self.untracked_baseline
                          if not (p.startswith('.audit/') or p in {'todo.md', '.todo.md'}
                                  or '__pycache__' in Path(p).parts)}
            self.check('only_controller_notes_added_to_worktree', not unexpected)
        self.check('reply_exists', (self.artifacts / 'reply.md').is_file())
        self.check('tasks_delivered_and_closed', all(
            state.get('state') == 'done' and state.get('closed') is True for _, state in rows))
        for task, _ in rows:
            worker = self.config['workers'].get(task.get('worker'), {})
            self.check('task_configuration_and_scope',
                       task.get('cwd') == str(self.worktree)
                       and task.get('model') == worker.get('model')
                       and task.get('harness') == worker.get('harness')
                       and task.get('argv') == horch.launch_args(worker, Path(task['task_dir']))
                       and Path(task.get('result_path', '')).resolve() == Path(task['task_dir']) / 'result.json')
            result = read_json(Path(task['result_path']))
            self.check('task_result_identity', horch.validate_result(result, task) == 'valid'
                       and result.get('status') == 'completed')
        for role in self.prepared.get('expected_roles', []):
            value = self.config['roles'].get(role)
            names = value if isinstance(value, list) else [value]
            used = []
            for task, _ in rows:
                brief = Path(task['brief_path']).read_text()
                # Role and worker must occur in the actual submitted brief,
                # together with an explicit selection reason, not just the reply.
                if role in brief and task.get('worker') in brief and re.search(r'\b(?:reason|because)\b', brief, re.I):
                    used.append(task['worker'])
            self.check('configured_role_' + role, all(used.count(name) >= names.count(name) for name in names))
        candidates = []
        for path in (self.directory / 'native-sessions').glob('*.jsonl'):
            with path.open() as stream:
                header = json.loads(stream.readline())
            if header.get('type') == 'session' and Path(header.get('cwd', '')).resolve() == self.worktree:
                candidates.append(path)
        self.check('native_transcript_unique', len(candidates) == 1)
        required = [(self.bundle / p).resolve() for p in self.prepared['required_reads']]
        self.native = {'sha256': sha(candidates[0]), 'format': 'pi-session-v3',
                       'session_identity_sha256': hashlib.sha256(str(self.session.get('value', '')).encode()).hexdigest()}
        self.native.update(audit_pi(candidates[0], self.session, self.worktree, self.wall_started,
                               self.spec, required, self.prepared.get('required_commands', []),
                               [task for task, _ in rows], self.bundle,
                               self.prepared.get('required_invocations', []),
                               self.prepared.get('required_order', [])))
        self.stage_checks = self.native['checks']
        self.behavior = cases.verify(self.args.scenario, self.worktree, self.artifacts,
                                     self.prepared.get('context', {}))
        self.checks.extend(self.behavior.get('checks', []))
        observed = {c['name']: c.get('ok') is True for c in
                    self.stage_checks + self.behavior.get('checks', [])}
        declared = self.case.get('required_stages', [])
        self.stage_checks.extend({'name': 'stage_' + name, 'ok': observed.get(name, False)}
                                 for name in declared)
        self.check('declared_stages_present', bool(declared))
        self.check('native_required_stages', all(c['ok'] for c in self.stage_checks))

    def finish(self):
        cleanup_ok = True
        if not self.native:
            try:
                paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
                if len(paths) == 1:
                    self.native = {'sha256': sha(paths[0]), 'audit_completed': False,
                                   'session_identity_sha256': hashlib.sha256(str(
                                       self.session.get('value', '')).encode()).hexdigest()}
            except Exception:
                self.categories.append('native_snapshot_failed')
        # Inspect every owned pane before closure. Stop controller first, preventing
        # new tasks, then scan once more for tasks created during the last poll.
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
        task_facts = []
        for task in self.tasks.values():
            try:
                state = read_json(Path(task['task_dir']) / 'state.json')
                task_facts.append({'task_id': task['task_id'], 'worker': task['worker'],
                                   'harness': task.get('harness'), 'model': task.get('model'),
                                   'effort': self.config.get('workers', {}).get(task.get('worker'), {}).get('effort'),
                                   'state': state.get('state') if state.get('state') in horch.SETTLED_STATES | {'running', 'long_running'} else 'invalid',
                                   'closed_before_cleanup': state.get('closed') is True})
                if not state.get('closed'):
                    entry = self.herdr('agent', 'get', task['agent'], cleanup=True)['agent']
                    if entry.get('pane_id') != task.get('pane_id'):
                        raise Failure('cleanup_ownership_unproven')
                    screen = self.call(['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '80'], cleanup=True)
                    (self.directory / (task['task_id'] + '-pane.json')).write_text(screen)
                    self.call([sys.executable, self.bundle / 'skills/herdr-orchestrator/scripts/horch.py',
                               'close', task['task_id']], cleanup=True)
            except Exception:
                cleanup_ok = False
        for pane in ([self.pane] if self.pane else []) + [t['pane_id'] for t in self.tasks.values()]:
            try:
                proc = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env,
                                      text=True, capture_output=True, timeout=15)
                reply = json.loads(proc.stdout or proc.stderr)
                error = reply.get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if proc.returncode == 0 or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        integrity = False
        after_hashes = {}
        try:
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            after_hashes = source_hashes()
            integrity = (bool(self.hashes) and after_hashes == self.hashes
                         and sha(self.config_path) == self.config_hash
                         and (not copied.exists() or sha(copied) == self.config_hash)
                         and self.call(['git', '-C', self.args.repo, 'rev-parse', 'HEAD'], cleanup=True).strip() == self.revision)
            if self.bundle.exists() and (self.bundle / 'skills').exists():
                integrity = integrity and all(sha(self.bundle / p) == digest for p, digest in self.hashes.items() if p.startswith('skills/'))
        except Exception:
            pass
        self.checks += [{'name': 'source_and_config_integrity', 'ok': integrity},
                        {'name': 'owned_panes_absent', 'ok': cleanup_ok}]
        passed = not self.categories and all(c.get('ok') is True for c in self.checks)
        behavior_ok = bool(self.behavior.get('checks')) and all(c.get('ok') is True for c in self.behavior['checks'])
        stage_ok = bool(self.stage_checks) and all(c.get('ok') is True for c in self.stage_checks)
        prerequisite_block = self.phase in ('preflight', 'setup') or any(
            c in ('controller_blocked', 'controller_session_not_ready', 'controller_start_blocked') for c in self.categories)
        workflow = 'pass' if passed and self.case.get('workflow_complete', False) else (
            'blocked' if passed or prerequisite_block else 'fail')
        playbook = self.case.get('playbook', self.args.scenario)
        inventory = {name: 'not_run' for name in sorted(set(self.inventory_names) | set(INVENTORY))}
        if playbook in inventory:
            inventory[playbook] = workflow
        receipt = {'schema': 'horch/playbook-e2e/v1', 'scenario': self.args.scenario,
                   'verdict': 'pass' if passed else 'fail',
                   'stage_coverage': {'verdict': 'pass' if stage_ok else 'fail', 'checks': self.stage_checks,
                                      'declared_stages': self.case.get('required_stages', [])},
                   'behavior_verdict': 'pass' if behavior_ok else 'fail',
                   'workflow_verdict': workflow, 'full_inventory_verdict': 'not_run',
                   'inventory': inventory, 'inventory_discovered': self.inventory_names, 'source_revision': self.revision,
                   'source_sha256_before': self.hashes, 'source_sha256_after': after_hashes, 'config_sha256_before': self.config_hash,
                   'config_sha256_after': None, 'controller': {k: self.spec.get(k) for k in ('harness', 'model', 'effort', 'provider')},
                   'native_transcript': self.native, 'tasks': task_facts, 'checks': self.checks,
                   'observations': self.behavior.get('observations', {}),
                   'failure_categories': self.categories, 'last_phase': self.phase,
                   'claims': self.prepared.get('claims', []) if passed else [],
                   'limitations': self.behavior.get('limitations', []) + [
                       'Inter-task dependency graphs are not inferred; native audit proves delivery before individual artifact reads only.'],
                   'seconds': round(time.monotonic() - self.started, 3)}
        try:
            receipt['config_sha256_after'] = sha(self.config_path)
        except Exception:
            pass
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, help='existing configured Pi worker used as evaluation controller')
    parser.add_argument('--scenario', required=True, help='scenario key in playbook_cases.CASES')
    parser.add_argument('--repo', type=Path, default=Path('.'), help='existing trusted repository root')
    parser.add_argument('--output', type=Path, required=True, help='private artifact parent outside repository')
    parser.add_argument('--caller-pane', required=True, help='explicit actual caller pane; independently verified')
    parser.add_argument('--max-seconds', type=int, default=1800, help='overall run deadline')
    args = parser.parse_args()
    args.repo = args.repo.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.output == args.repo or args.repo in args.output.parents:
        parser.error('--output must be outside repository')
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
