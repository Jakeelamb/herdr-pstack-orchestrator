#!/usr/bin/env python3
"""Real Pi/Herdr Bug fix and Opening a PR E2E against a private fixture.

Creates a retained child branch/worktree and a ready PR on an existing private
baseline branch. Never merges, retries, answers trust prompts, or changes models.
Raw sessions, forge identities and application outputs remain in private artifacts.
Only evidence.json is a candidate for publication after human review.

Use --prepare-fixture DIRECTORY for local-only portable baseline files, without
controller, Herdr, Git or forge calls. Follow the generated README to create your
own private repository and ready bootstrap PR 1 manually, keep that PR unmerged,
then run this driver against your exact baseline branch and configured Pi worker.
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
import shlex
import shutil
import subprocess
import sys
import time
import traceback

import playbook_loop as core

horch = core.horch
ROOT = Path(__file__).resolve().parents[1]
Failure = core.Failure
BASE_STORAGE = 'c32037b76d52e28908e2a46b40e77bf46be109fdb7fb25afd702070e7d74bfc2'
READS = (
    'poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
    'pstack-herdr/references/herdr-tools.md', 'herdr-orchestrator/SKILL.md',
    'poteto-mode/playbooks/bug-fix.md', 'control-cli/SKILL.md',
    'how/SKILL.md', 'how/references/explainer-prompt.md', 'why/SKILL.md',
    'why/references/epistemics.md', 'why/references/investigator-prompt.md',
    'why/references/synthesizer-prompt.md', 'why/references/sources/code-archaeology.md',
    'poteto-mode/playbooks/opening-a-pr.md', 'deslop/SKILL.md',
    'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md',
    'principle-sequence-verifiable-units/SKILL.md',
)

# The probe executes the application's real CLI and always reports app failures
# as data. A native successful tool result can therefore witness a failed app.
PROBE = r'''#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--mode', choices=['missing-field', 'e2e'], required=True)
a = p.parse_args()
r = a.repo.resolve()
d = a.output.resolve()
d.mkdir(parents=True, exist_ok=False, mode=0o700)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def invoke(argv):
    x = subprocess.run(argv, cwd=r, capture_output=True, text=True, timeout=90)
    return {'argv': list(map(str, argv)), 'exit_code': x.returncode,
            'stdout': x.stdout, 'stderr': x.stderr}
sources = {name: digest(r / name) for name in ['cli.py', 'storage.py', 'money.py', 'e2e_import.py']}
if a.mode == 'e2e':
    result = invoke([sys.executable, '-B', str(r / 'e2e_import.py'), '--output', str(d / 'suite')])
    receipt = d / 'suite/evidence.json'
    result['suite'] = json.loads(receipt.read_text()) if receipt.exists() else None
else:
    store = d / 'ledger.json'
    seed = d / 'seed.json'
    seed.write_text(json.dumps([{'id': 'persisted', 'quantity': 2, 'unit_price_cents': 49, 'discount_bp': 0}]))
    cli = [sys.executable, '-B', str(r / 'cli.py')]
    seeded = invoke([*cli, 'import', str(store), str(seed)])
    before = digest(store)
    first, second = d / 'first.json', d / 'second.json'
    first.write_text(json.dumps([{'id': 'first', 'quantity': 1, 'unit_price_cents': 101, 'discount_bp': 5000}]))
    second.write_text(json.dumps([{'id': 'middle', 'quantity': 2, 'unit_price_cents': 333, 'discount_bp': 3333},
                                  {'id': 'last', 'quantity': 1, 'unit_price_cents': 200}]))
    result = invoke([*cli, 'import', str(store), str(first), str(second)])
    result.update(seed=seeded, store_before=before, store_after=digest(store),
                  pending_exists=store.with_suffix('.pending').exists(),
                  export=invoke([*cli, 'export', str(store)]))
result.update(mode=a.mode, source_sha256=sources)
(d / 'observation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
'''


FIXTURE_ORACLE = r'''#!/usr/bin/env python3
"""Exercise the real multi-file import CLI and retain its replayable evidence."""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row(identity, quantity, price, discount=0):
    return {"id": identity, "quantity": quantity,
            "unit_price_cents": price, "discount_bp": discount}


def charged(value):
    amount = (Decimal(value["quantity"]) * Decimal(value["unit_price_cents"])
              * (Decimal(1) - Decimal(value["discount_bp"]) / Decimal(10000)))
    return dict(value, total_cents=int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    directory = args.output.expanduser().resolve()
    if directory == ROOT or ROOT in directory.parents:
        parser.error("--output must be outside the fixture checkout")
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    inputs = directory / "inputs"
    inputs.mkdir()
    store = directory / "ledger.json"
    sources = {name: digest(ROOT / name) for name in ("money.py", "storage.py", "cli.py")}
    checks, flows = [], []
    failure = None

    def observe(name, ok):
        checks.append({"name": name, "ok": bool(ok)})

    def invoke(label, command, groups=()):
        paths = []
        for number, values in enumerate(groups):
            path = inputs / f"{label}-{number}.json"
            path.write_text(json.dumps(values, sort_keys=True) + "\n")
            paths.append(path)
        argv = [sys.executable, "-B", str(ROOT / "cli.py"), command, str(store),
                *map(str, paths)]
        result = subprocess.run(argv, text=True, capture_output=True, timeout=30, cwd=ROOT)
        (directory / f"{label}.stdout").write_text(result.stdout)
        (directory / f"{label}.stderr").write_text(result.stderr)
        value = json.loads(result.stdout)
        flows.append({"name": label, "command": command, "input_files": len(paths),
                      "exit_code": result.returncode, "output": value})
        return result.returncode, value

    try:
        old = row("old-01", 2, 49)
        code, value = invoke("seed", "import", [[old]])
        observe("existing store seeded through the real CLI", code == 0 and value == {
            "count": 1, "total_cents": 98})
        first = [row("txn-z", 1, 101, 5000), row("txn-a", 2, 333, 3333)]
        second = [row("txn-m", 3, 137, 250), row("txn-0", 0, 999),
                  row("txn-free", 7, 101, 10000)]
        expected = sorted(map(charged, [old, *first, *second]), key=lambda item: item["id"])
        expected_total = sum(item["total_cents"] for item in expected)
        code, value = invoke("two-files", "import", [first, second])
        observe("two input files preserve independent integer money results",
                code == 0 and value == {"count": len(expected), "total_cents": expected_total})
        baseline = store.read_bytes()
        rejected = [
            ("persisted-duplicate", [[row("candidate", 1, 200), old]], "duplicate transaction"),
            ("within-file-duplicate", [[row("new-dup", 1, 200), row("new-dup", 2, 300)]],
             "duplicate transaction"),
            ("across-file-duplicate", [[row("cross-dup", 1, 200)], [row("cross-dup", 2, 300)]],
             "duplicate transaction"),
            ("late-invalid-discount", [[row("valid-first", 1, 200)],
                                       [row("invalid-last", 1, 200, 10001)]], "invalid discount"),
        ]
        for label, groups, error in rejected:
            code, value = invoke(label, "import", groups)
            observe(label + " rejects without changing persisted bytes",
                    code == 2 and isinstance(value, dict) and error in value.get("error", "")
                    and store.read_bytes() == baseline and not store.with_suffix(".pending").exists())
        code, value = invoke("export", "export")
        observe("export matches the complete sorted independent ledger",
                code == 0 and value == expected and store.read_bytes() == baseline)
    except Exception as error:
        failure = type(error).__name__
    after = {name: digest(ROOT / name) for name in sources}
    observe("fixture source unchanged", sources == after)
    passed = failure is None and len(flows) == 7 and all(item["ok"] for item in checks)
    receipt = {"schema": "invoice/import-e2e/v1", "verdict": "pass" if passed else "fail",
               "checks": checks, "flows": flows, "source_sha256_before": sources,
               "source_sha256_after": after, "failure_category": failure}
    (directory / "evidence.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"verdict": receipt["verdict"], "flows": len(flows),
                      "evidence": str(directory / "evidence.json")}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''

FIXTURE_SUPPORT = {
    'README.md': r'''# Invoice CLI playbook fixture

This synthetic Python standard-library application supports private, unmerged
playbook E2E pull requests. It contains no production data or credentials.
Raw sessions, worker configuration and generated evidence belong outside Git.

The importer charges each line in integer cents with half-up discount rounding.
It rejects duplicate transaction IDs across stored state and all input files,
then commits the complete batch with one atomic replacement. Export sorts by ID.
The baseline intentionally retains the observed missing-discount validation gap;
its seven-flow E2E oracle does not cover that gap yet.

Run the real CLI oracle with a fresh external output directory:

```sh
python3 -B e2e_import.py --output /tmp/invoice-proof-UNIQUE
```

The artifact records seven CLI flows, independent decimal expected results,
source hashes and persisted-byte checks. Keep the output for review and replay.

## Manual private bootstrap

Fixture preparation does not invoke Git, Herdr, models or a forge. To use the
live driver, create your own private repository and its ready baseline PR 1.
Start in this prepared directory; replace OWNER/NAME with your private repository.
The default branch contains only this README. Do not merge the baseline PR.

```sh
git init -b main
git add README.md
git commit -m "docs: initialize fixture repository"
gh repo create OWNER/NAME --private --source . --remote origin --push
git switch -c feat/fixture-baseline
git add AGENTS.md .gitignore .github money.py storage.py cli.py e2e_import.py
git commit -m "feat(invoice): add import and export fixture"
git push -u origin feat/fixture-baseline
gh pr create --repo OWNER/NAME --base main --head feat/fixture-baseline \
  --title "feat(invoice): add import and export fixture" \
  --body "Add a synthetic multi-file invoice CLI and its seven-flow E2E oracle."
gh pr view 1 --repo OWNER/NAME
```

The create command opens a ready PR by default. Leave PR 1 open and unmerged.
The live driver checks repository privacy, the exact remote baseline tip,
canonical source hashes and a clean local baseline checkout. It creates a child
branch and a separate ready PR targeting feat/fixture-baseline, and retains both.
Bootstrap PR 1 is setup only; it is not playbook execution evidence.

Run the orchestrator driver from its trusted checkout with your configured Pi
controller and verified caller pane. Use this prepared checkout as --fixture-repo,
OWNER/NAME as --forge-repo, feat/fixture-baseline as --base-ref, and an external
private directory as --output. Authenticate and establish trust yourself before
running. The driver never answers trust dialogs or changes models or Git config.
''',
    'AGENTS.md': r'''# Fixture work rules

Keep all work in the assigned feature branch or worktree and within the
assignment's files. Use configured workers through the supplied Herdr adapter.
Never alter worker configuration, model choices, authentication or trust.

Use the real CLI for behavior verification. E2E drivers must retain a receipt
and rerunnable artifact. Do not add unit tests or inferred safety changes.
Write code, comments, docs and commits in English. Keep source changes separate
from generated outputs. Never commit raw sessions, private paths, credentials
or worker configuration.

Do not merge, enable auto-merge, change the default branch or push directly to
main. Open a ready PR only when the assigned playbook or controller asks for it.
A passing check never authorizes a merge.
''',
    '.gitignore': r'''__pycache__/
*.py[cod]
artifacts/
.audit/
''',
    '.github/workflows/invoice.yml': r'''name: Invoice CLI behavior

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  import:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.11', '3.14']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Exercise the real multi-file CLI
        run: python3 e2e_import.py --output "$RUNNER_TEMP/invoice-proof"
''',
}


def prepare_fixture(directory):
    """Write a portable synthetic baseline without Git, configuration or network."""
    directory = directory.expanduser().resolve()
    files = dict(core.cases.LEDGER_FILES, **{'e2e_import.py': FIXTURE_ORACLE})
    files.update(FIXTURE_SUPPORT)
    if hashlib.sha256(files['storage.py'].encode()).hexdigest() != BASE_STORAGE:
        raise Failure('canonical_fixture_storage_changed')
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    hashes = {}
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        hashes[name] = core.sha(path)
    print(json.dumps({'prepared_fixture': str(directory), 'sha256': hashes}, indent=2))
    return 0


def identity():
    paths = [*ROOT.joinpath('skills').rglob('*'),
             *ROOT.joinpath('e2e').glob('*.py')]
    return {str(p.relative_to(ROOT)): core.sha(p) for p in paths
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def literal(command):
    if not isinstance(command, str) or any(c in command for c in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def observation_ok(value, fixed):
    if value.get('mode') != 'missing-field':
        return False
    same = (value.get('store_before') == value.get('store_after')
            and value.get('pending_exists') is False
            and value.get('seed', {}).get('exit_code') == 0
            and value.get('export', {}).get('exit_code') == 0)
    if not fixed:
        return same and value.get('exit_code') == 1 and not value.get('stdout') and 'KeyError' in value.get('stderr', '') and 'discount_bp' in value.get('stderr', '')
    try:
        result = json.loads(value['stdout'])
    except (ValueError, KeyError):
        return False
    return same and value.get('exit_code') == 2 and isinstance(result, dict) and bool(result.get('error')) and not value.get('stderr')


def suite_ok(value, fixed):
    suite = value.get('suite') or {}
    if not fixed:
        return value.get('exit_code') != 0 and suite.get('verdict') == 'fail'
    flows = suite.get('flows', [])
    return (value.get('exit_code') == 0 and suite.get('verdict') == 'pass'
            and len(flows) == 8 and all(c.get('ok') is True for c in suite.get('checks', []))
            and any('missing' in str(flow.get('name', '')).lower() and flow.get('exit_code') == 2 for flow in flows))


def outside_function(text):
    tree = ast.parse(text)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_batch']
    if len(functions) != 1:
        raise Failure('fixture_function_missing')
    functions[0].body = [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def retained_oracle(before, after):
    """Allow exactly the missing-field flow and seven-to-eight flow count edit."""
    original, changed = ast.parse(before), ast.parse(after)
    removed, counts = 0, 0
    for node in ast.walk(changed):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'rejected' for t in node.targets):
            if not isinstance(node.value, ast.List):
                return False
            additions = [item for item in node.value.elts if isinstance(item, ast.Tuple)
                         and item.elts and isinstance(item.elts[0], ast.Constant)
                         and 'missing' in str(item.elts[0].value)]
            if len(additions) != 1:
                return False
            addition = additions[0]
            for expression in ast.walk(addition):
                if isinstance(expression, ast.Call) and not (
                    isinstance(expression.func, ast.Name) and expression.func.id == 'row'
                    and all(isinstance(arg, ast.Constant) for arg in expression.args)
                    and not expression.keywords):
                    return False
                if isinstance(expression, (ast.Attribute, ast.Subscript, ast.NamedExpr, ast.Lambda,
                                           ast.ListComp, ast.DictComp, ast.GeneratorExp)):
                    return False
            node.value.elts.remove(addition)
            removed += 1
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name) and node.left.func.id == 'len'
                and len(node.left.args) == 1 and isinstance(node.left.args[0], ast.Name)
                and node.left.args[0].id == 'flows' and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value == 8):
            node.comparators[0].value = 7
            counts += 1
    return removed == counts == 1 and ast.dump(original, include_attributes=False) == ast.dump(changed, include_attributes=False)


class Run(core.Run):
    """Reuse the maintained lifecycle, never its scenario registry or evaluator."""

    def __init__(self, args):
        args.scenario = 'forge-bug-fix'
        super().__init__(args)
        self.branch = 'e2e/bug-fix-' + format(time.time_ns(), 'x')
        old_directory = self.directory
        self.directory.rename(self.directory.with_name(self.directory.name.replace('playbook-', 'forge-', 1)))
        self.directory = self.directory.with_name(self.directory.name.replace('playbook-', 'forge-', 1))
        if self.env['GIT_CONFIG_GLOBAL'] == str(old_directory / 'git-global.config'):
            self.env['GIT_CONFIG_GLOBAL'] = str(self.directory / 'git-global.config')
        self.env.update(XDG_CONFIG_HOME=str(self.directory / 'config'), XDG_STATE_HOME=str(self.directory / 'state'))
        self.task_root = self.directory / 'state/herdr-orchestrator/tasks'
        self.bundle = self.directory / 'bundle'
        self.artifacts = self.directory / 'artifacts'
        self.worktree = args.repo / 'handoff' / self.directory.name / 'worktree'
        self.probe = self.directory / 'cli-probe.py'
        self.stage_proof = {}
        self.base = None
        self.config_path = None
        self.original_fixture = None
        self.snapshot = {}
        self.pr = None

    def git(self, *args, repo=None, cleanup=False):
        return self.call(['git', '-C', repo or self.worktree, *args], cleanup=cleanup).strip()

    def forge(self, *args):
        # The independent oracle uses gh read-only. The controller resolves its
        # own single forge, including Origin preference, from the original text.
        return json.loads(self.call(['gh', *args]))

    def preflight(self):
        self.check('positive_deadline', self.args.max_seconds > 0)
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.repo)).resolve() == self.args.repo)
        self.revision = self.git('rev-parse', 'HEAD', repo=self.args.repo)
        self.source_status = self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.repo)
        self.hashes = identity()
        self.config_path = horch.config_path()
        self.config_hash = core.sha(self.config_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane)
        self.spec = self.config['workers'].get(self.args.controller, {})
        self.check('controller_is_pi', self.spec.get('harness') == 'pi')
        self.role_workers = {}
        for role in ('bug-fix', 'how explainer', 'why investigators', 'why synthesizer'):
            selected = self.config.get('roles', {}).get(role)
            names = selected if isinstance(selected, list) else [selected]
            self.check('role_' + role.replace(' ', '_'), bool(names) and all(
                name in self.config['workers'] and self.config['workers'][name].get('harness') == 'pi' for name in names))
            self.role_workers[role] = names
        self.check('single_code_and_simple_how_worker', len(self.role_workers['bug-fix']) == len(self.role_workers['how explainer']) == 1)
        self.check('fixture_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.fixture_repo)).resolve() == self.args.fixture_repo)
        self.original_fixture = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo),
                                 self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo))
        self.check('fixture_clean', not self.original_fixture[1])
        origin = self.git('remote', 'get-url', 'origin', repo=self.args.fixture_repo)
        match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', origin)
        self.check('fixture_origin', bool(match) and match[1].lower() == self.args.forge_repo.lower())
        remote = self.forge('repo', 'view', self.args.forge_repo, '--json', 'nameWithOwner,isPrivate')
        self.check('forge_private_identity', remote.get('isPrivate') is True and remote.get('nameWithOwner', '').lower() == self.args.forge_repo.lower())
        base_rows = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.args.base_ref, repo=self.args.fixture_repo).splitlines()
        self.check('remote_base_unique', len(base_rows) == 1)
        self.base = base_rows[0].split()[0]
        self.check('canonical_fixture_source', all(core.sha(self.args.fixture_repo / name)
                   == hashlib.sha256(content.encode()).hexdigest()
                   for name, content in dict(core.cases.LEDGER_FILES, **{'e2e_import.py': FIXTURE_ORACLE}).items()))
        self.check('exact_clean_baseline', self.original_fixture[0] == self.base
                   and self.git('rev-parse', self.args.base_ref, repo=self.args.fixture_repo) == self.base
                   and core.sha(self.args.fixture_repo / 'storage.py') == BASE_STORAGE)
        bootstrap = self.forge('pr', 'view', '1', '--repo', self.args.forge_repo, '--json', 'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('baseline_pr_retained_open', bootstrap.get('state') == 'OPEN' and bootstrap.get('headRefOid') == self.base
                   and bootstrap.get('headRefName') == self.args.base_ref and bootstrap.get('baseRefName') == 'main')
        self.bootstrap = bootstrap
        self.remote_heads = self.git('ls-remote', '--heads', 'origin', repo=self.args.fixture_repo).splitlines()
        self.prs_before = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json', 'number,state,headRefName,baseRefName,isDraft')

    def probe_run(self, repo, label, mode):
        output = self.directory / label
        value = json.loads(self.call([sys.executable, '-B', self.probe, '--repo', repo, '--output', output, '--mode', mode]))
        return value

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.probe.write_text(PROBE)
        self.probe_hash = core.sha(self.probe)
        self.probe.chmod(0o444)
        self.check('baseline_reproduces_real_failure', observation_ok(self.probe_run(self.args.fixture_repo, 'independent-before', 'missing-field'), False))
        baseline_suite = self.probe_run(self.args.fixture_repo, 'independent-baseline-suite', 'e2e')
        self.check('existing_seven_flows_pass', baseline_suite.get('exit_code') == 0 and len((baseline_suite.get('suite') or {}).get('flows', [])) == 7)
        self.git('worktree', 'add', '-b', self.branch, self.worktree, self.base, repo=self.args.fixture_repo)
        self.readers = []
        for number in range(len(self.role_workers['why investigators']) + 2):
            path = self.worktree.parent / f'reader-{number}'
            self.git('worktree', 'add', '--detach', path, self.base, repo=self.args.fixture_repo)
            self.readers.append(path)
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'forge-e2e', '--no-focus',
                         '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                         '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'],
                         '--env', 'MISE_CONFIG_DIR=' + self.env['MISE_CONFIG_DIR'],
                         '--env', 'MISE_STATE_DIR=' + self.env['MISE_STATE_DIR'],
                         '--env', 'GIT_CONFIG_GLOBAL=' + self.env['GIT_CONFIG_GLOBAL'],
                         '--env', 'GH_CONFIG_DIR=' + self.env['GH_CONFIG_DIR'])
        self.pane = tab['root_pane']['pane_id']
        brief = self.directory / 'controller-brief.md'
        brief.write_text(self.prompt())
        (self.directory / 'native-sessions').mkdir()
        flags = horch.launch_args(self.spec, self.directory) + ['--session-dir', str(self.directory / 'native-sessions')]
        self.controller_argv = flags
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

    def prompt(self):
        return f'''Read {self.bundle / 'skills/poteto-mode/SKILL.md'} in full first. You are the
native lead controller for the original Bug fix playbook and its Opening a PR
stage. Read the required mapping and original playbook. Write the exact six-step
checklist to {self.artifacts / 'checklist.md'} before other work. Follow all six
steps. Evaluation tool protocol: call only the native read, bash, write, edit,
grep, find and ls tools directly. Do not use codemode or any tool wrapper;
nested tool results cannot be bound by this evaluator's native call/result audit.
This is an evidence constraint; preserve the configured harness, tool flags and
worker configuration. Put the same tool protocol in every worker brief.
Read every applied document in a separate full native read (no limit or offset)
or a literal cat of one file. Required documents: {json.dumps(list(READS))}
relative to {self.bundle / 'skills'}. Read deslop, no-comments, technical-writing,
unslop and principle-sequence-verifiable-units before the FIRST commit too.

Work in {self.worktree}, own branch {self.branch}, exact baseline {self.base}.
This is an explicitly authorized stacked child of the existing unmerged PR 1,
whose base branch is {self.args.base_ref}. Do not change PR 1 or main. You may push
ONLY {self.branch} to origin and create ONE ready PR with head {self.branch},
base {self.args.base_ref}, repository {self.args.forge_repo}. No other forge
writes, merges, auto-merge, babysit, trust answers, configuration changes, model
substitution, failure retries or native subagents. Preserve all worker flags.
Read-only forge discovery and PR readback are authorized. Resolve ONE forge
according to Opening a PR, recording actual Origin discovery/resolution or the
gh fallback in {self.artifacts / 'forge.json'} (object with forge and reason) before any PR operation. Read back
actual PR status after creation; request headRefName, baseRefName, headRefOid,
isDraft in JSON so the native result contains both branch names and full head SHA. Use full original PR writing/review guidance. Use standalone literal commands
for git commit, push, and forge create/view so native witnesses bind their outputs.
Use literal command -v origin for executable discovery (a missing-command
result is evidence, not an invitation to retry). For Origin creation put
--status open last. Do not chain commands. Use native read/grep/find/ls for
inspection; bash commands must be literal Git, resolved forge, command -v origin,
pwd, bundled horch or external probe invocations. Do not run interpreter inline
programs or other shell utilities in the controller. Git add names each owned
file explicitly (no add-all). Use Git diff without an --output argument.

Observed user bug: a missing discount_bp in the last row of the second input
file crashes import with KeyError, exit 1 and empty stdout. Expected: structured
JSON validation error, exit 2, unchanged persisted bytes. Existing state and
other valid rows must survive rollback. No injected source changes are needed.
The existing real CLI oracle e2e_import.py has seven flows and lacks this case.
Only source changes authorized: first extend e2e_import.py with an eighth flow
for late missing discount_bp by appending one tuple to rejected and changing
len(flows) == 7 to len(flows) == 8; keep all other existing oracle AST unchanged.
Use a missing-field row dict literal and row() calls with literal arguments,
without helper functions or executable expressions in the new tuple. Retain the
existing independent decimal oracle,
half-cent rows, multi-file, duplicate and rollback/export checks; then fix ONLY
storage.py apply_batch. Do not change money.py, cli.py or any other tracked file.

Observe the failing baseline probe result yourself BEFORE dispatching any how
or why investigation worker. Reproduce through control-cli with this immutable
external probe:
{self.probe}. Its --repo PATH --output NEW_EXTERNAL_DIRECTORY --mode missing-field
invokes the real CLI, emits actual exit/stdout/stderr and store hashes as JSON,
and returns zero even for a failed app. --mode e2e runs the real e2e_import.py and
emits actual suite output/receipt, also returning zero. Use standalone literal
python3 invocations, not shell wrappers. Do not modify or copy the probe or write
evidence.json. Use {self.directory / 'native-before'}, {self.directory / 'native-failing-suite'},
{self.directory / 'native-after'}, {self.directory / 'native-passing-suite'} as output
directories in that order. The driver independently replays both commit states.

Use simple how: one configured how explainer, no explorers, for the narrow
apply_batch field-validation question. Why: build an inline source/blame/history
anchor including PR 1, discover actual available evidence categories and record
all seven in {self.artifacts / 'coverage.json'} as a seven-item JSON list, each object with category,
available (boolean), evidence, reason.
Always delegate source-control investigation to configured why investigators;
include other actually available categories; report absent categories honestly.
Delegate synthesis to configured why synthesizer after reading all delivered
investigator reports. Use the original prompt references. Preserve confidence
language. After reading how and why reports and reproducing, write
{self.artifacts / 'diagnosis.json'} BEFORE any code-worker launch: hypotheses
(at least two objects with mechanism, status (eliminated or survives; exactly
one survives), runtime_evidence referencing actual observed output),
surviving_mechanism and scope_reason (single-function fix; architect
unnecessary). A short deterministic hunt needs no Cursor loop.

Delegate all coding through {self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'};
pass --caller-pane {self.pane} on run. Literal standalone horch wait must report
state done before each result/report is read. Read each result.json and every
listed Markdown report fully. Each brief's first nonblank line must be exactly Role: followed by one space
and its own configured role (bug-fix, how explainer, why investigators or why
synthesizer). Put this header before pasted findings, reports or configuration.
Each brief names its configured worker, selection reason, scope, success criteria,
and absolute references to
{self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'} and
{self.bundle / 'skills/poteto-mode/SKILL.md'}, and says: Do not delegate, use
native subagents, or run a whole playbook. Complete this assignment yourself.
Each worker writes a Markdown report and lists it in result.json files.
Configured roles: {json.dumps(self.role_workers)}. Reader tasks use distinct
existing detached worktrees {json.dumps(list(map(str, self.readers)))}; no reader
source writes. If additional discovered categories need more readers, create
distinct detached worktrees under {self.worktree.parent} at {self.base}.
Exactly two fresh configured bug-fix workers serialize in {self.worktree}:
first changes only e2e_import.py with the missing-field case; wait/read/review,
run failing e2e probe yourself, then commit that failing repro BEFORE dispatching
the second worker. Second changes only storage.py/apply_batch. Retain the test
file exactly from the failing-test commit. Controller reviews/verifies/commits,
and never writes source. Keep exactly two ordered commits over the baseline,
first only e2e_import.py, second only storage.py. Follow deslop/no-comments and
technical-writing/unslop before committing/reviewing/opening the ready PR.
Review the actual diff. Run same-surface probe and full eight-flow suite yourself.
Write {self.artifacts / 'reply.md'} after actual PR readback and verified artifacts,
including what broke, mechanism, fix, verbatim failing and passing repro output,
and PR URL. No raw transcripts or private artifacts in Git. On failure preserve
all artifacts and report blocked; do not work around the failed stage.
'''

    def native_events(self, path, include_errors=False):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        pending, events = {}, []
        for index, row in enumerate(rows):
            message = row.get('message', {})
            if message.get('role') == 'assistant':
                for block in message.get('content', []):
                    if block.get('type') == 'toolCall':
                        pending[block['id']] = (block['name'], block['arguments'], index, row.get('id'))
            if message.get('role') == 'toolResult':
                pair = pending.pop(message.get('toolCallId'), None)
                if pair and (message.get('isError') is False or include_errors):
                    events.append({'name': pair[0], 'args': pair[1], 'call_row': pair[2],
                                   'result_row': index, 'call_id': pair[3], 'result_id': row.get('id'),
                                   'output': core.text_content(message), 'successful': message.get('isError') is False})
        return events

    def event_probes(self, events, mode, fixed):
        matches = []
        for event in events:
            words = literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if (len(words) != 8 or Path(words[0]).name not in ('python3', 'python')
                    or Path(words[1]).resolve() != self.probe or words[2] != '--repo'
                    or Path(words[3]).resolve() != self.worktree or words[4] != '--output'
                    or words[6:] != ['--mode', mode]):
                continue
            target = Path(words[5]).resolve()
            if self.directory not in target.parents:
                continue
            try:
                value = json.loads(event['output'])
                on_disk = core.read_json(target / 'observation.json')
            except (OSError, ValueError):
                continue
            expected = self.snapshot['final' if fixed else ('test' if mode == 'e2e' else 'base')]
            if value != on_disk or value.get('source_sha256') != expected:
                continue
            if (observation_ok(value, fixed) if mode == 'missing-field' else suite_ok(value, fixed)):
                matches.append(event)
        return matches

    def controller_command_allowed(self, command):
        """Constrain lead mutations to Git staging/commits and owned PR delivery."""
        argv = literal(command)
        if not argv:
            return False
        binary = Path(argv[0]).name
        if binary in ('python', 'python3'):
            if len(argv) < 3:
                return False
            script = (self.worktree / argv[1]).resolve()
            if script == self.probe:
                return True
            return (script == self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'
                    and argv[2] in ('run', 'wait', 'list', 'close', 'stats', 'detect'))
        if binary == 'git':
            rest = argv[1:]
            if rest[:1] == ['-C'] and len(rest) > 2:
                if Path(rest[1]).resolve() != self.worktree:
                    return False
                rest = rest[2:]
            if not rest:
                return False
            operation = rest[0]
            if operation in ('status', 'diff', 'show', 'log', 'blame', 'rev-parse',
                             'rev-list', 'ls-files', 'ls-remote', 'diff-tree'):
                return not any(word.startswith('--output') for word in rest)
            if operation == 'branch':
                return rest[1:] == ['--show-current']
            if operation == 'remote':
                return rest[1:] == ['get-url', 'origin']
            if operation == 'worktree':
                return (rest[1:2] == ['add'] and '--detach' in rest
                        and any(Path(word).is_absolute() and Path(word).parent == self.worktree.parent
                                for word in rest[2:]) and self.base in rest)
            if operation == 'add':
                files = [word for word in rest[1:] if word != '--']
                return bool(files) and all(word in ('storage.py', 'e2e_import.py') for word in files)
            return operation in ('commit', 'push')
        if binary in ('gh', 'origin'):
            if argv[1:3] in (['pr', 'view'], ['pr', 'list'], ['repo', 'view'],
                             ['issue', 'view'], ['issue', 'list'], ['auth', 'status']):
                return True
            return argv[1:3] == ['pr', 'create']
        if binary == 'cat':
            return len(argv) == 2 and not argv[1].startswith('-')
        return argv in (['command', '-v', 'origin'], ['which', 'origin'], ['pwd'])

    def stage(self, name, events, condition=True):
        self.check('native_' + name, condition and bool(events))
        self.stage_proof[name] = [{'call_row': e['call_row'], 'result_row': e['result_row'],
                                   'call_id_sha256': hashlib.sha256(str(e['call_id']).encode()).hexdigest(),
                                   'result_id_sha256': hashlib.sha256(str(e['result_id']).encode()).hexdigest(),
                                   'output_sha256': hashlib.sha256(e['output'].encode()).hexdigest()}
                                  for e in events]

    def verify(self):
        rows = self.scan()
        self.check('tasks_delivered_closed', bool(rows) and all(s.get('state') == 'done' and s.get('closed') is True for _, s in rows))
        self.check('probe_immutable', core.sha(self.probe) == self.probe_hash)
        self.check('feature_clean', not self.git('status', '--porcelain=v1', '--untracked-files=all'))
        self.check('feature_branch', self.git('branch', '--show-current') == self.branch)
        commits = self.git('rev-list', '--reverse', self.base + '..HEAD').splitlines()
        self.check('two_ordered_commits', len(commits) == 2 and self.git('rev-parse', commits[0] + '^') == self.base
                   and self.git('rev-parse', commits[1] + '^') == commits[0])
        self.commits = commits
        self.check('test_only_first_commit', self.git('diff-tree', '--no-commit-id', '--name-only', '-r', commits[0]).splitlines() == ['e2e_import.py'])
        self.check('storage_only_second_commit', self.git('diff-tree', '--no-commit-id', '--name-only', '-r', commits[1]).splitlines() == ['storage.py'])
        self.check('single_function_scope', outside_function(self.git('show', self.base + ':storage.py')) == outside_function((self.worktree / 'storage.py').read_text()))
        self.check('small_fix', len(self.git('diff', '--unified=0', commits[0], commits[1], '--', 'storage.py').splitlines()) <= 45)
        self.check('test_frozen_after_failure', self.git('rev-parse', commits[0] + ':e2e_import.py') == self.git('rev-parse', commits[1] + ':e2e_import.py'))
        self.check('existing_oracle_retained', retained_oracle(
            self.git('show', self.base + ':e2e_import.py'), (self.worktree / 'e2e_import.py').read_text()))
        for label, revision in (('base', self.base), ('test', commits[0]), ('final', commits[1])):
            directory = self.directory / ('snapshot-' + label)
            directory.mkdir()
            for name in ('cli.py', 'storage.py', 'money.py', 'e2e_import.py'):
                data = subprocess.run(['git', '-C', str(self.worktree), 'show', revision + ':' + name],
                                      capture_output=True, timeout=20, check=True).stdout
                (directory / name).write_bytes(data)
            self.snapshot[label] = {name: core.sha(directory / name) for name in ('cli.py', 'storage.py', 'money.py', 'e2e_import.py')}
        self.check('baseline_snapshot_reproduces', observation_ok(self.probe_run(self.directory / 'snapshot-base', 'replay-baseline', 'missing-field'), False))
        self.check('committed_repro_fails', suite_ok(self.probe_run(self.directory / 'snapshot-test', 'replay-failing-suite', 'e2e'), False))
        self.check('final_original_repro_passes', observation_ok(self.probe_run(self.directory / 'snapshot-final', 'replay-fixed', 'missing-field'), True))
        self.check('final_eight_flows_pass', suite_ok(self.probe_run(self.directory / 'snapshot-final', 'replay-passing-suite', 'e2e'), True))
        self.check('runtime_source_matches_commits', all(core.sha(self.worktree / name) == digest for name, digest in self.snapshot['final'].items()))
        tasks = [task for task, _ in rows]
        self.task_facts = []
        for task in tasks:
            worker = self.config['workers'].get(task.get('worker'), {})
            self.check('task_configuration_binding', task.get('model') == worker.get('model') and task.get('harness') == worker.get('harness')
                       and task.get('argv') == horch.launch_args(worker, Path(task['task_dir']))
                       and Path(task.get('result_path', '')).resolve() == Path(task['task_dir']) / 'result.json')
            result = core.read_json(Path(task['result_path']))
            self.check('task_nonce_and_result_binding', horch.validate_result(result, task) == 'valid' and result.get('status') == 'completed')
            brief = Path(task['brief_path']).read_text()
            role_header = re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)', brief)
            own_role = role_header[1] if role_header else None
            self.check('bounded_worker_role_header', own_role in self.role_workers
                       and task['worker'] in self.role_workers[own_role])
            self.check('bounded_worker_brief', all(word in brief for word in (task['worker'], 'Do not delegate',
                       str(self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'),
                       str(self.bundle / 'skills/poteto-mode/SKILL.md'))) and bool(re.search(r'reason|because', brief, re.I)))
            self.task_facts.append({'task_id_sha256': hashlib.sha256(task['task_id'].encode()).hexdigest(),
                                    'model': task.get('model'), 'effort': worker.get('effort'), 'harness': task.get('harness'),
                                    'task_sha256': core.sha(Path(task['task_dir']) / 'task.json'),
                                    'result_sha256': core.sha(Path(task['result_path'])), 'nonce_validated': True})
        sessions = list((self.directory / 'native-sessions').glob('*.jsonl'))
        self.check('one_controller_native_session', len(sessions) == 1)
        path = sessions[0]
        self.native = core.audit_pi(path, self.session, self.worktree, self.wall_started, self.spec,
                                    [self.bundle / 'skills' / p for p in READS], [], tasks, self.bundle)
        # Core read checks contain only bundle-relative resource names.
        self.check('native_model_effort_reads_delivery', all(check['ok'] for check in self.native['checks']))
        events = self.native_events(path)
        all_events = self.native_events(path, include_errors=True)
        source_roots = {self.worktree, self.args.fixture_repo,
                        *(Path(task['cwd']).resolve() for task in tasks)}
        source_paths = {root / name for root in source_roots
                        for name in ('storage.py', 'e2e_import.py', 'cli.py', 'money.py')}
        self.check('controller_does_not_write_source', all(
            isinstance(event['args'].get('path'), str)
            and (self.worktree / event['args']['path']).resolve() not in source_paths
            for event in all_events if event['name'] in ('write', 'edit')))
        self.check('lead_mutations_within_authorization', all(
            self.controller_command_allowed(e['args'].get('command', ''))
            for e in all_events if e['name'] == 'bash'))
        launches, deliveries = core.workflow_launches(events, tasks, self.worktree, self.bundle)
        self.check('all_native_launches_bound', set(launches) == {t['task_id'] for t in tasks})
        report_reads = {task['task_id']: core.workflow_report_reads(events, task, self.worktree,
                        deliveries.get(task['task_id'])) for task in tasks}
        self.check('all_delivered_reports_read', all(report_reads.values()))
        full_result_reads = [core.workflow_reads(events, self.worktree, Path(t['result_path']),
                             after=deliveries[t['task_id']]['result_row']) for t in tasks]
        self.check('all_delivered_results_read', all(full_result_reads))
        before = self.event_probes(events, 'missing-field', False)
        after = self.event_probes(events, 'missing-field', True)
        failing = self.event_probes(events, 'e2e', False)
        passing = self.event_probes(events, 'e2e', True)
        checklist = core.workflow_writes(events, self.worktree, self.artifacts / 'checklist.md')
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / 'skills/poteto-mode/playbooks/bug-fix.md').read_text(), re.M)
        checklist = [e for e in checklist if re.findall(r'^\d+\. (.+)$', e['args']['content'], re.M) == steps]
        first_launch = min(e['call_row'] for e in launches.values())
        initial_reads = []
        for resource in ('poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
                         'pstack-herdr/references/herdr-tools.md', 'poteto-mode/playbooks/bug-fix.md'):
            reads = core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource,
                                        before=checklist[0]['call_row'] if checklist else -1)
            self.check('initial_read_' + resource.replace('/', '_'), bool(reads))
            initial_reads.extend(reads)
        self.stage('bug_fix_1', initial_reads + before + checklist, bool(before and checklist)
                   and checklist[0]['result_row'] < min(before[0]['call_row'], first_launch)
                   and before[0]['result_row'] < first_launch)
        writers = [t for t in tasks if Path(t['cwd']).resolve() == self.worktree]
        writers.sort(key=lambda t: launches[t['task_id']]['call_row'])
        self.check('two_configured_serial_writers', len(writers) == 2 and all(
            t['worker'] == self.role_workers['bug-fix'][0]
            and re.match(r'\A\s*Role: bug-fix(?:\r?\n|\Z)', Path(t['brief_path']).read_text())
            for t in writers)
                   and deliveries[writers[0]['task_id']]['result_row'] < launches[writers[1]['task_id']]['call_row'])
        readers = [t for t in tasks if t not in writers]
        self.check('distinct_detached_readers', len({t['cwd'] for t in readers}) == len(readers) and all(
            Path(t['cwd']).resolve().parent == self.worktree.parent and not self.git('status', '--porcelain=v1', '--untracked-files=all', repo=t['cwd'])
            and self.git('rev-parse', 'HEAD', repo=t['cwd']) == self.base for t in readers))
        reader_roles = {}
        for role in ('how explainer', 'why investigators', 'why synthesizer'):
            matched = [t for t in readers if re.match(
                r'\A\s*Role: ' + re.escape(role) + r'(?:\r?\n|\Z)',
                Path(t['brief_path']).read_text()) and t['worker'] in self.role_workers[role]]
            self.check('native_role_' + role.replace(' ', '_'), bool(matched) and set(t['worker'] for t in matched) == set(self.role_workers[role]))
            reader_roles[role] = matched
        self.check('simple_how_route', len(reader_roles['how explainer']) == 1)
        for role, resource in (('how explainer', 'how/SKILL.md'), ('why investigators', 'why/SKILL.md')):
            self.check('skill_before_' + role.replace(' ', '_'), bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource,
                before=min(launches[t['task_id']]['call_row'] for t in reader_roles[role]))))
        synthesis_start = min(launches[t['task_id']]['call_row'] for t in reader_roles['why synthesizer'])
        self.check('why_synthesis_after_reports', all(max(e['result_row'] for e, _ in report_reads[t['task_id']]) < synthesis_start
                   for t in reader_roles['why investigators']))
        diagnosis = core.workflow_writes(events, self.worktree, self.artifacts / 'diagnosis.json', before=launches[writers[0]['task_id']]['call_row'], final=True)
        coverage = core.workflow_writes(events, self.worktree, self.artifacts / 'coverage.json', before=synthesis_start, final=True)
        data = core.read_json(self.artifacts / 'diagnosis.json')
        hypotheses = data.get('hypotheses', [])
        self.check('competing_runtime_hypotheses', len(hypotheses) >= 2 and all(isinstance(h, dict) and h.get('mechanism') and h.get('runtime_evidence') for h in hypotheses)
                   and sum(h.get('status') == 'survives' for h in hypotheses) == 1
                   and all(h.get('status') in ('survives', 'eliminated') for h in hypotheses)
                   and bool(data.get('surviving_mechanism')) and bool(data.get('scope_reason')))
        categories = core.read_json(self.artifacts / 'coverage.json')
        self.check('why_seven_evidence_categories', isinstance(categories, list) and len(categories) == 7
                   and len({c.get('category') for c in categories}) == 7 and all(type(c.get('available')) is bool
                   and c.get('reason') and (not c['available'] or c.get('evidence')) for c in categories))
        history = []
        anchor_pr = []
        for event in events:
            argv = literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if argv and argv[0] == 'git' and any(word in argv for word in ('blame', 'log')) and 'storage.py' in argv and event['output'].strip():
                history.append(event)
            if (len(argv) > 3 and argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'view']
                    and argv[3] == '1' and event['output'].strip()):
                anchor_pr.append(event)
        investigator_start = min(launches[t['task_id']]['call_row'] for t in reader_roles['why investigators'])
        self.check('why_runtime_anchor_before_investigators',
                   bool(anchor_pr) and {kind for kind in ('blame', 'log') if any(
                       kind in literal(e['args']['command']) and e['result_row'] < investigator_start for e in history)} == {'blame', 'log'}
                   and anchor_pr[0]['result_row'] < investigator_start)
        self.stage('bug_fix_2', diagnosis + coverage + history,
                   bool(diagnosis and coverage and history) and bool(before)
                   and before[0]['result_row'] < diagnosis[0]['call_row']
                   and all(max(e['result_row'] for e, _ in report_reads[t['task_id']]) < diagnosis[0]['call_row'] for t in readers))
        self.stage('bug_fix_3', [launches[t['task_id']] for t in writers], bool(diagnosis))
        self.stage('bug_fix_4', after + passing, bool(after and passing) and deliveries[writers[1]['task_id']]['result_row'] < min(after[0]['call_row'], passing[0]['call_row']))
        commit_events = []
        push_events = []
        create_events = []
        view_events = []
        for event in events:
            argv = literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if not argv:
                continue
            if argv[0] == 'git' and 'commit' in argv:
                commit_events.append(event)
            if argv[0] == 'git' and 'push' in argv:
                push_events.append(event)
            if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'create']:
                create_events.append(event)
            if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'view']:
                view_events.append(event)
        self.check('writer_reports_before_verification', bool(failing and passing) and all(
            max(e['result_row'] for e, _ in report_reads[t['task_id']]) < boundary
            for t, boundary in ((writers[0], failing[0]['call_row']), (writers[1], passing[0]['call_row']))))
        self.stage('bug_fix_5', failing + commit_events, bool(failing) and len(commit_events) == 2
                   and deliveries[writers[0]['task_id']]['result_row'] < failing[0]['call_row']
                   and failing[0]['result_row'] < commit_events[0]['call_row']
                   and commits[0][:7] in commit_events[0]['output']
                   and commit_events[0]['result_row'] < launches[writers[1]['task_id']]['call_row']
                   and bool(passing) and passing[0]['result_row'] < commit_events[1]['call_row']
                   and commits[1][:7] in commit_events[1]['output'])
        guidance = []
        for resource in ('deslop/SKILL.md', 'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md', 'principle-sequence-verifiable-units/SKILL.md'):
            reads = core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource, before=commit_events[0]['call_row'])
            self.check('pr_guidance_before_commit_' + resource.split('/')[0], bool(reads))
            guidance.extend(reads)
        forge_notes = core.workflow_writes(events, self.worktree, self.artifacts / 'forge.json', final=True)
        forge = core.read_json(self.artifacts / 'forge.json')
        self.check('resolved_one_forge', forge.get('forge') in ('gh', 'origin') and forge.get('reason'))
        selected = forge['forge']
        discovery = [e for e in self.native_events(path, include_errors=True)
                     if e['name'] == 'bash' and e['result_row'] < min(
                         [item['call_row'] for item in create_events + view_events])
                     and literal(e['args'].get('command', '')) in (['command', '-v', 'origin'], ['which', 'origin'])]
        self.check('actual_forge_discovery', bool(discovery))
        if selected == 'origin':
            self.check('origin_discovery_resolves', discovery[0]['successful'] and bool(discovery[0]['output'].strip()))
        elif discovery[0]['successful'] and discovery[0]['output'].strip():
            failed_origin = [e for e in self.native_events(path, include_errors=True)
                             if e['name'] == 'bash' and literal(e['args'].get('command', ''))[:1] == ['origin']
                             and not e['successful'] and e['result_row'] < min(item['call_row'] for item in create_events + view_events)]
            self.check('gh_fallback_after_origin_resolution_failure', bool(failed_origin))
        self.check('one_ready_creation', len(create_events) == 1 and literal(create_events[0]['args']['command'])[0] == selected
                   and '--draft' not in literal(create_events[0]['args']['command'])
                   and (selected != 'origin' or ['--status', 'open'] == literal(create_events[0]['args']['command'])[-2:]))
        self.check('single_forge_for_pr_operations', all(literal(e['args']['command'])[0] == selected for e in create_events + view_events))
        self.check('one_owned_branch_push', len(push_events) == 1 and self.branch in literal(push_events[0]['args']['command'])
                   and 'origin' in literal(push_events[0]['args']['command'])
                   and all(not word.startswith('--force') and word not in ('--all', '--mirror', '-f', '--tags', '--delete')
                           for word in literal(push_events[0]['args']['command'])))
        self.check('native_pr_explicit_base', '--base' in literal(create_events[0]['args']['command'])
                   and literal(create_events[0]['args']['command'])[literal(create_events[0]['args']['command']).index('--base') + 1] == self.args.base_ref)
        readback = [event for event in view_events if event['call_row'] > create_events[0]['result_row']]
        self.check('native_readback_identity', any(
            self.branch in event['output'] and self.args.base_ref in event['output']
            and commits[-1] in event['output'] for event in readback))
        reply = core.workflow_writes(events, self.worktree, self.artifacts / 'reply.md', final=True)
        self.stage('opening_pr', guidance + forge_notes + push_events + create_events + readback + reply,
                   bool(forge_notes and readback and reply) and forge_notes[0]['result_row'] < create_events[0]['call_row']
                   and commit_events[-1]['result_row'] < push_events[0]['call_row']
                   and push_events[0]['result_row'] < create_events[0]['call_row']
                   and readback[-1]['result_row'] < reply[0]['call_row'])
        self.stage('bug_fix_6', create_events + readback + reply, 'opening_pr' in self.stage_proof)
        self.verify_remote(commits[-1])
        self.check('reply_links_verified_pr', self.pr['url'] in (self.artifacts / 'reply.md').read_text())
        for label in ('native-before', 'native-after'):
            observed = core.read_json(self.directory / label / 'observation.json')
            self.check('reply_verbatim_' + label, json.dumps(observed, sort_keys=True) in (self.artifacts / 'reply.md').read_text())

    def verify_remote(self, head):
        remote = self.git('ls-remote', '--heads', 'origin').splitlines()
        expected = sorted([*self.remote_heads, head + '\trefs/heads/' + self.branch])
        self.check('only_owned_remote_branch_added', sorted(remote) == expected)
        prs = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json', 'number,state,headRefName,baseRefName,isDraft')
        created = [p for p in prs if p['number'] not in {p['number'] for p in self.prs_before}]
        self.check('only_one_owned_pr_added', len(created) == 1 and all(p in prs for p in self.prs_before))
        self.pr = self.forge('pr', 'view', str(created[0]['number']), '--repo', self.args.forge_repo, '--json',
                             'number,url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,autoMergeRequest')
        (self.directory / 'pr-readback.json').write_text(json.dumps(self.pr, indent=2) + '\n')
        self.check('real_ready_stacked_pr', self.pr.get('state') == 'OPEN' and self.pr.get('isDraft') is False
                   and self.pr.get('headRefName') == self.branch and self.pr.get('headRefOid') == head
                   and self.pr.get('baseRefName') == self.args.base_ref and self.pr.get('baseRefOid') == self.base
                   and self.pr.get('autoMergeRequest') is None)
        baseline = self.forge('pr', 'view', '1', '--repo', self.args.forge_repo, '--json', 'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('baseline_pr_unchanged_unmerged', baseline == self.bootstrap)

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
        except Exception:
            pass
        self.checks.extend([{'name': 'source_head_config_bundle_probe_integrity', 'ok': integrity},
                            {'name': 'original_fixture_checkout_untouched', 'ok': fixture_integrity},
                            {'name': 'owned_panes_absent', 'ok': cleanup_ok}])
        passed = bool(self.checks) and not self.categories and all(c.get('ok') is True for c in self.checks)
        inventory = {name: 'not_run' for name in core.INVENTORY}
        verdict = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        inventory.update({'bug-fix': verdict, 'opening-a-pr': verdict})
        if not self.native:
            sessions = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(sessions) == 1:
                self.native = {'sha256': core.sha(sessions[0]), 'audit_completed': False}
        receipt = {
            'schema': 'horch/forge-playbook-e2e/v1', 'verdict': 'pass' if passed else 'fail',
            'workflow_verdict': verdict, 'full_inventory_verdict': 'not_run', 'inventory': inventory,
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
                'Only the simple how route and available why evidence categories used by this bug are covered.',
                'Other 21 playbooks and the complete inventory are not run.',
                'Only this two-commit fixture graph and literal native tool grammar are accepted.',
                'Branch, detached reader worktrees, private artifacts and ready PR are retained for inspection.',
                'No live external system is replayed from a controller self-report; native and independent checks are required.',
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
    parser.add_argument('--base-ref', help='existing unmerged fixture baseline branch')
    parser.add_argument('--output', type=Path, help='private artifact parent outside both checkouts')
    parser.add_argument('--caller-pane', help='independently verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=2400, help='overall run deadline; never retries')
    args = parser.parse_args()
    if args.prepare_fixture is not None:
        try:
            return prepare_fixture(args.prepare_fixture)
        except (OSError, Failure) as exc:
            parser.error(str(exc))
    required = ('controller', 'fixture_repo', 'forge_repo', 'base_ref', 'output', 'caller_pane')
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
