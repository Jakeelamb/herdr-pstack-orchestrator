Replace angle-bracket placeholders with your configured worker and absolute fixture/oracle paths before dispatch. This is a reusable task template, not a worker transcript.

Implement a non-mutating invoice import preview in this repository: <fixture-worktree>.

Requirement: add `import --dry-run STORE BATCH...`, with --dry-run immediately
after import. Validate every batch and calculate the same count/totals and errors
as normal import. Across multiple input files, preserve Decimal-equivalent
rounding, duplicate rejection and late invalid-input behavior. Dry run must
never create/change ledger bytes or create/change/remove its .pending file;
a preexisting pending sentinel must remain exact. Keep ALL existing normal
import/export behavior, including the baseline post-replacement missing-total
error. Read the actual source to decide the smallest coherent design.

Role: feature, refactoring. Worker: <implementation-worker>, selected from the current role map.
You own ONLY cli.py and storage.py under <fixture-worktree>. money.py, e2e_import.py,
all other tracked files and existing tests remain unchanged. Do not commit,
push, open a PR, modify configuration/auth/permissions, or touch other worktrees.
Do not delegate or launch other agents. Complete this implementation yourself.
Use ordinary available tools; no special greeting or prescribed tool-call shape.

Run the existing immutable application oracle after implementation:
python3 <oracle.py> --repo <fixture-worktree> --output OWN_TASK_DIRECTORY/behavior --mode feature
Replace OWN_TASK_DIRECTORY with the directory containing your assigned result.json.
It executes real CLI flows and retains the original suite. Read its observations;
a passing oracle alone does not excuse changes to normal behavior. Root will
independently compare all 11 normal records with the frozen before observations.
Do not change the oracle, contract or input expectations. Run checks only as
needed for this change. Retain any failure, do not rerun to improve timings.

Write report.md in your actual task directory: resulting behavior, design,
modified files, commands/results, evidence paths and any remaining concern.
Deliver the normal nonce-bound result.json only when the assignment is complete.
