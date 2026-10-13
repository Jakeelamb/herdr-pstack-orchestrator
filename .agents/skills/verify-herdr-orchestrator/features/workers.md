# Worker review loop

## Sub-features

Fresh implementation, two independent failing reviews, a fresh fix, and two passing reviews of an invoice CLI. The driver also executes edge-case invoices and checks scope, result delivery, and pane cleanup.

## How to get to it (user POV)

Use configured workers through `horch`. Select `writer`, `reviewer_a`, and `reviewer_b` from workers.toml; reviewers must have distinct model definitions. Require two free slots, authenticated harnesses, a trusted repository, and Pi integration for Pi workers. Use the shared Doctor first.

## Driving it with existing scripts

```bash
python3 e2e/review_loop.py --writer "$writer" \
  --reviewer "$reviewer_a" --reviewer "$reviewer_b" \
  --repo "$repo" --output "$proof"
```

Read the printed `evidence.json`: require a passing verdict, expected initial FAIL/final PASS reviews, observed invoice results, and confirmed pane cleanup. Inspect the retained worktree, then remove that exact worktree with Git while retaining the sibling receipt. See the [driver documentation](../../../../e2e/README.md) for the full scenario.

## Gotchas

This makes real model calls and tests `horch` directly, not an AI controller or pstack rubric. A newly created worktree can need its own Pi trust decision; report a blocked startup without submitting input to the dialog. A historical passing receipt does not prove a new run passed.

## Workspace worker limits

For quota changes, select one authenticated worker from the existing configuration and use a trusted checkout. The driver creates two temporary workspaces with their own caller panes, a shared isolated task store, and a two-slot limit in each workspace:

```bash
python3 e2e/workspace_limits.py --worker "$worker" --output "$proof"
```

It fills the first workspace, checks local `run` and `check` refusals, strips workspace metadata from its own records to exercise legacy installation compatibility, then fills the second workspace. After real result delivery and cleanup, a fresh setup check must succeed. Read the printed receipt and require all capacity, result, source-integrity, and cleanup assertions to pass. Preserve failed receipts and inspect owned problem panes before teardown. Never clear worker dialogs or change configured permission flags to make the check pass. The driver removes only its own workspaces; retained receipts and diagnostics stay outside the checkout.
