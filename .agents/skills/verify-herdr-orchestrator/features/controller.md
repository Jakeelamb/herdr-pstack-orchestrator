# AI controller loop

## Sub-features

A real Codex controller reads the current orchestration skill and coordinates the six-task invoice scenario. The driver audits delivery-before-read ordering, wait handles, delegation, results, and cleanup independently.

## How to get to it (user POV)

Select `controller` from workers.toml with **harness = codex**, explicit model, effort, and permission arguments. A Pi worker using an OpenAI model is not a Codex controller. Select writer and two reviewers as in [worker review](workers.md). The driver needs two free worker slots in the caller's workspace plus its separate controller pane and access to the controller's local Codex transcript. Stop other dispatchers in that workspace; isolated task stores cannot reserve the shared workspace limit atomically.

## Driving it with existing scripts

```bash
python3 e2e/controller_loop.py --controller "$controller" \
  --writer "$writer" --reviewer "$reviewer_a" --reviewer "$reviewer_b" \
  --repo "$repo" --output "$proof"
```

Read the printed receipt and require the fresh run's scenario, transcript audit, and cleanup to pass together. Retain local diagnostics; inspect and remove the printed worktree without removing evidence. The [audit contract](../../../../e2e/README.md) defines supported transcript forms and limitations.

## Gotchas

If there is no configured Codex worker, report the prerequisite gap; do not relabel a Pi worker or edit configuration to force the run. Missing/ambiguous transcript evidence fails the audit even if the fixture is correct. Post-run reanalysis is not a fresh integrated pass. This driver does not test an original pstack playbook or a Pi controller.

## Caller context preflight

For a worker placed in the wrong workspace because of stale shell context, use the focused CLI driver:

```bash
python3 e2e/caller_context.py --controller-pane <verified-controller-pane> --output "$proof"
```

Run the driver from the controller pane's own process tree; `horch` now rejects a pane ID it cannot prove. The driver reads live Herdr state and exercises `run` and `check`. Caller cases stop at an empty isolated configuration; configuration cases stop at a missing brief or unknown worker. Unavailable or blank caller identities must fail without falling back to focus; stale workspace/tab variables with a valid pane must resolve to live context and reach the configuration check. Configuration cases cover workers with and without descriptions, a non-string description, and multiple roles naming one worker. Read the printed receipt and require every check to pass. Keep the retained artifact directory; there are no owned panes to close. This checks preflight only, not a real pane move, model launch, or controller routing decisions.

## Caller identity

For a worker placed in another live pane's workspace, including a controller whose tools run in a shared agent daemon, use:

```bash
python3 e2e/caller_identity.py --controller-pane <verified-controller-pane> --output "$proof"
```

Run it from the controller pane itself. It creates and closes one scratch tab and one scratch workspace in Herdr. Require `verdict: pass` and `cleanup_ok: true` in the printed artifact. The detached cases simulate a daemon with `setsid`; they do not drive a real Codex app-server. The session-mismatch case needs a controller pane that reports a session for its harness and fails with a precondition check otherwise.
