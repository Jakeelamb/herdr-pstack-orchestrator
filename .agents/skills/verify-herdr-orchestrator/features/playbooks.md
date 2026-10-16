# Original playbook scenarios

Read the [complete inventory and evidence contract](../../../../e2e/PLAYBOOKS.md)
before making any coverage claim. This is a maintained E2E driver for a distinct
feature, not an ad-hoc helper or a replacement for the invoice controller loop.

Select an existing configured Pi controller and confirm the actual caller pane.
Use the shared Doctor. Stop other isolated dispatchers in that workspace.

```bash
python3 e2e/playbook_loop.py --controller <configured-pi-worker> \
  --scenario prototype --repo "$repo" --caller-pane <verified-pane> \
  --output "$proof" --max-seconds 1200
```

Available initial scenarios are `investigation`, `prototype`, and
`trace-forensics`. Read the fresh receipt's separate behavior, stage, workflow,
inventory and cleanup outcomes. Missing native evidence fails closed. A partial
stage pass does not complete a playbook. Do not promote a previous failed run
after fixing the evaluator.

Inspect retained worktrees under `handoff/<run>/worktree`, then remove only the
exact owned worktree with Git. Preserve the external receipt and diagnostics.
Never publish configuration, profiles, raw native sessions or pane text.
