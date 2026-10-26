---
name: herdr-orchestrator
description: "Delegate tasks to worker agents (Pi, Codex, Claude Code) that run in their own herdr panes, then wait for and read their file results. Use when the user asks to delegate, dispatch, or parallelize work through herdr or horch, to run several models on one task, or to set up herdr workers. Requires HERDR_ENV=1 for orchestration. Also use to review how configured workers perform or whether they are efficient."
---

# herdr-orchestrator

You are the controller. Focus on planning, task assignment, guidance, and quality control. Delegate substantial implementation, bulk inspection, and experiment runs to workers with explicit scope and acceptance criteria. Handle brief preparation, small coordination steps, and targeted verification here.

Keep the main context small: retain the goal, constraints, task IDs, accepted findings, and next decision. Ask workers for concise conclusions, blockers, and evidence paths. Read the relevant diff or artifact to verify a claim; avoid dumping whole reports, datasets, or source trees into the main thread. For structured evidence, inspect keys/counts first and extract the fields needed for the decision instead of pretty-printing the entire JSON. Each task gets a fresh worker process through `horch`.

## Required rules

- **Deliver repository changes as a PR by default.** Work on a feature branch, integrate verified worker commits there, then push and open or update the PR. Merge into `main` (or the default/shared target branch), push changes directly there, or enable auto-merge only when the user explicitly asks to merge that work. Task completion, passing checks, and autonomous playbooks do not grant merge authorization. Include this limit in worker briefs.
- Delegate only through `horch`; never use your harness's native subagents while acting as this controller. Workers may use their own subagents.
- Never answer worker dialogs, send keys/text to worker panes, or send `/model`. A new task uses a fresh process with its configured model.
- **Wait for task `state: "done"` before consuming any result.** An early report or `result.json` does not finish a running task. Closing an unfinished worker cancels it and cannot pass a review gate.
- **`done` means delivered.** Read result `status`: `completed` claims success, `failed` reports failure, `blocked` needs the user's answer. Verify the work independently; neither `done` nor `completed` means a review passed.
- When a task has a problem, inspect and report it. Do not restart, resend, or switch workers without the user's decision. Close only panes started by `horch`, using `horch close`.

## Run horch

Use the absolute path inside this installed skill:

```bash
python3 <skill-dir>/scripts/horch.py <command> ...
```

Requires Python 3.11+ on Linux/macOS and a controller inside Herdr (`HERDR_ENV=1`). Pi workers also require `herdr integration install pi` so startup dialogs cannot receive task prompts. `stats` reads stored history outside Herdr too. Commands print JSON; operational errors use `{"error": "<code>", "message": "<text>"}` and exit 1. CLI help and argument errors use argparse output.

| Command | Purpose |
|---|---|
| `run <worker> --brief <file> [--cwd <dir>] [--caller-pane <id>]` | Start a fresh worker and submit its brief; returns after startup and prompt acknowledgement, before task completion. |
| `wait [<task-id> ...] [--max-seconds <n>] [--recheck]` | Wait for a state change. No IDs selects all unsettled tasks. See waiting below. |
| `list` | List task, worker, pane, and state. |
| `stats [--workspace <id>] [--days <n>]` | Review configured workers from stored facts, without Herdr calls or writes. |
| `close <task-id>` | Close that task's recorded pane. |
| `detect` | List installed harnesses, versions, Pi providers, and Pi integration status. |
| `check [<worker> ...] [--cwd <dir>] [--max-seconds <n>] [--caller-pane <id>]` | Verify configured workers with real tasks; default wait cap 300 seconds. |

Workers open in `horch` tabs in your workspace, at most four panes per tab, without taking focus or using your tab. `max_active_workers` applies independently to each workspace; controllers sharing a workspace and task store share that workspace's slots. An unclosed task occupies a slot in the workspace that launched it.

`HERDR_PANE_ID` is a claim, not proof of which pane hosts this conversation. Shell snapshots and shared agent daemons can carry another live pane's ID. `run` and `check` therefore require the named pane's shell to be an ancestor of the `horch` process, then place workers in Herdr's live workspace and tab for that pane. A moved pane's launch-time ID still resolves.

On `caller_context_invalid`, follow [caller context recovery](references/setup.md#caller-context). If the message says `horch` is outside every pane's process tree (for example, Codex tools run by a shared `codex app-server`), confirm the controller pane as described there and pass `--caller-pane <id>` to every `run` and `check`. Do not choose a workspace from UI focus or create replacement panes to work around the error.

## Delegate and verify

1. Choose a configured worker based on the assignment and its optional `description`. With `pstack-herdr` active, follow its role-first routing rules. One worker/model can serve multiple roles in fresh processes. Create a separate git worktree for a writer and pass it as `--cwd`. A read-only worker may share a checkout; explicitly forbid file and external-state changes in its brief.
2. Write a complete brief: goal and acceptance criteria, absolute paths to read, file ownership and constraints, verification commands, output files, and whether to commit. For execution tasks, name the required capabilities and a cheap preflight in the intended execution context before bulk inspection. Configured permission flags do not prove access to host services. Keep host-bound checks with an already-authorized executor under its existing caps and locks. Workers have none of your conversation. Reports go beside `result.json`; `horch` appends its worker rules and exact result schema automatically.
3. Run `horch run <worker> --brief <file> --cwd <dir>`. Record `task_id` and `pane_id`; any state other than `running` needs problem handling. For parallel tasks, submit all allowed by `max_active_workers` before waiting.
4. Wait until every required task is `done`, using the method below. Read `result_path`, inspect its `status`, and read the listed reports and deliverables (paths are relative to the result directory). Verify linked bulk evidence with structured checks rather than dumping generated artifacts into context. Relay a blocked result's `question` to the user. A follow-up is a new task with a complete brief and the prior report.
5. Verify the diff, behavior, and reviewer verdicts before reporting. If `closed` is false, read `message` and retry cleanup with `horch close`; its worker slot remains occupied until closure is confirmed.

## Wait without repeated short calls

`horch wait <task-id> ...` has no default time cap and returns when any waited task changes state. It polls Herdr internally; those polls do not invoke a model. Wait again for the remaining running tasks after handling each change.

- With background commands or yielded shell sessions, run `horch wait` **without `--max-seconds`** and resume that same process/session until it returns. A shell tool's yield timeout returns control to you; it does not require a timeout on `horch`. Post user updates while the wait stays alive. Claude Code supports background commands; Codex runtimes with yielded exec sessions can resume the returned session handle.
- If the runtime only supports blocking shell calls (including Pi without a background facility), use `horch wait <task-id> ... --max-seconds 300` and a shell-tool timeout above 300 seconds. Use a shorter cap only when tool limits, a required update cadence, or a user request requires it.
- A wait cap stops that observation call, not the worker. Repeat while tasks are `running`; report `long_running` once and keep waiting. Never cancel a worker merely to end a wait.

Do not turn repeated `--max-seconds 1` calls into a status loop. While workers run, prepare independent briefs or assess already delivered evidence. For an occasional stored-state lookup, use `horch list`; use the existing wait process to observe delivery.

For a routine progress check, use `herdr agent get <agent-name>` and, if needed, `herdr agent read <agent-name> --source visible`. Reserve native harness transcripts for explicit debugging, not a second status loop. Lifecycle activity does not establish that the work is correct; verify the delivered artifacts.

## Problems

1. Read the pane before closing it: `herdr pane read <pane_id> --source visible`. This is passive; recent-history reads can scroll an idle full-screen agent.
2. Tell the user the task, state, and what the pane shows. Never answer a dialog yourself.
3. Follow the user's decision to close or retry. Start retries as fresh tasks. If the original task recovered after inspection, use explicit `--recheck` as described in [lifecycle and recovery](references/lifecycle.md).

## Read when needed

- **First use or configuration changes:** follow [setup and configuration](references/setup.md), including permission choices, startup dialogs, and `horch check`. Ask one setup question at a time. The user owns `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml` (default `~/.config/herdr-orchestrator/workers.toml`). A missing config is reported as `config_invalid`.
- **State/result interpretation, cleanup, or recovery:** read [lifecycle and recovery](references/lifecycle.md).
- **Worker efficiency, failures, or reminder timing:** read [worker statistics](references/stats.md) before proposing configuration changes.
- **Worker definitions:** [workers.example.toml](references/workers.example.toml). State lives in `$XDG_STATE_HOME/herdr-orchestrator/tasks/` (default `~/.local/state/herdr-orchestrator/tasks/`) and remains until the user deletes it.
