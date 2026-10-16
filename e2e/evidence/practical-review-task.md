Replace angle-bracket placeholders with the actual pinned revisions, configured workers and absolute paths before dispatch. This is a reusable task template, not a worker transcript.

Independently review invoice import preview at exact commit <reviewed-commit>.
Repository: <fixture-worktree>. Read-only assignment. Do not change source, tests, commits,
configuration, other worktrees or forge state. Do not delegate or launch agents.

Role: judgment and prose. Worker: <review-worker>, selected from the current role
map, independent of implementation worker <implementation-worker>. This is an ordinary
functionality review, with no named-agent greeting or tool formatting contract.

Requirement: `import --dry-run STORE BATCH...` validates all input batches and
returns the same counts/totals/errors as normal import, using the same rounding
and duplicate rules. It must never create/change ledger bytes or touch a pending
file, including a preexisting sentinel. Existing normal import/export behavior
must be preserved, including the known post-replacement missing-total error.
Only cli.py and storage.py may differ from baseline <baseline-commit>.

Read the full actual source and complete Git diff; bind your review to the
exact commit above. Run the existing real-CLI oracle once:
python3 <oracle.py> --repo <fixture-worktree> --output OWN_TASK_DIRECTORY/behavior --mode feature
Replace OWN_TASK_DIRECTORY with your assigned result.json directory. The oracle
covers successful multi-file rounding, normal exports, persisted/within/across
file duplicates, late errors, absent ledger and existing pending bytes, plus the
post-replacement error. Inspect the implementation and actual observations;
passing tests are evidence, not a replacement for reviewing the change.
If you find a material gap, report it; do not demand unrelated improvements or
original 23-playbook conformance. No source writes or test/oracle changes.

Write report.md explaining the behavior reviewed, actual checks and any findings.
Also write review.json with reviewed_commit (the exact SHA), verdict (pass or
fail), findings (a list; empty if none), and a concise rationale. Put all outputs
and CLI scratch beneath your actual own task directory. Deliver the normal
nonce-bound result only after the review is complete.
