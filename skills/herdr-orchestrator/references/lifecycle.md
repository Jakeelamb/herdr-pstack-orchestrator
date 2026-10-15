# Task lifecycle and recovery

## Herdr API boundary

The integration follows Herdr 0.9.3's [agent automation](https://github.com/herdrdev/herdr/blob/v0.9.3/docs/next/website/src/content/docs/agent-automation.mdx) and [socket API guidance](https://github.com/herdrdev/herdr/blob/v0.9.3/docs/next/website/src/content/docs/socket-api.mdx): use CLI wrappers for ordinary orchestration, response IDs for layout, `agent start` for readiness, and `agent prompt --wait` for acknowledgement. `--no-focus` and separate worker tabs implement this project's layout policy.

Herdr supplies agent lifecycle state; `horch` adds task identity, file delivery, review gates, and cleanup. Its single two-second `agent list` poll covers all waited tasks and the notification timer without invoking a model. Herdr's event-driven `agent wait` targets one agent; replacing this loop with subscriptions would also require reconnect and lost-event reconciliation. The current loop is an orchestration choice, not a missing Herdr wait capability.

Use `visible` reads for passive inspection. Recent-history reads can send mouse-scroll input to an idle full-screen agent before restoring its viewport. Routine status checks should use Herdr's agent metadata, not parse a harness's private session files. The Pi readiness guard below also reads Herdr metadata.

## Delivery, outcome, and review verdict

`horch wait` reports the transport state; `result.json` reports the worker's outcome. The controller verifies that outcome separately.

| Task state | Result status | Meaning and next action |
|---|---|---|
| `running` / `long_running` | Any file on disk | Keep waiting. The worker may still change it. |
| `done` | `completed` | Delivery finished; verify the work and any review verdict. |
| `done` | `failed` | Delivery finished; the worker reports failure. Read its report and tell the user. |
| `done` | `blocked` | Delivery finished; relay `question`, then start a fresh task with the answer. |

The existing `done` value is kept for compatibility with v0.1.0 clients and stored task records. It means a finished turn with a valid result, not a successful implementation or a passing review. `horch check` reports `ok: true` only for `done`, a valid result with `status: "completed"`, and confirmed pane closure.

Each `horch wait` line has `task_id`, `state`, `summary`, `result_path`, `files`, `question`, `closed`, and `message`. Until the task is `done` with a valid result, `summary` and `question` are null and `files` is empty. `result_path` always names the expected location; it does not signal completion. Result file paths in `files` are relative to the directory of `result_path`.

A valid result has exactly six keys: matching `task_id` and `nonce`, `status` (`completed`, `failed`, or `blocked`), a string `summary`, a list of string `files`, and `question` (nonempty string when blocked, otherwise null).

Herdr must also report that the turn ended: an idle/done agent with `completion_seq` newer than the pre-prompt baseline, or the observed working-to-idle fallback when no completion sequence is available. An idle agent alone does not establish completion.

Before submitting a Pi task, `horch` additionally waits for the installed Herdr Pi integration to report an idle/done session within the startup budget. Herdr 0.9.3's `interactive_ready` alone can describe Pi 1.1.0's trust dialog. Without the session signal, startup returns `start_failed`, retains the pane, and sends no task prompt. Install the integration and let the user resolve any dialog before starting a fresh task.

## States


| State | Meaning | What to do |
|---|---|---|
| `running` | The worker is working. | Wait again. |
| `long_running` | The task passed `notify_after_minutes`. Reported once. | Tell the user, then wait again. |
| `done` | The turn ended with a valid `result.json`. | Read the result and check `closed` / `message`. |
| `start_failed` | The harness did not start, usually a dialog. | See "Problems". |
| `not_started` | Herdr did not observe acknowledgement within the prompt wait. The task may still be running. | See "Problems". |
| `blocked` | The worker waits at a dialog or permission prompt. | See "Problems". |
| `exited` | The worker process is gone. | See "Problems". |
| `result_missing` | The turn ended without a valid `result.json`, often after a provider API error. | See "Problems". |
| `result_invalid` | `result.json` does not parse or its `task_id` or `nonce` is wrong. | See "Problems". |

## Problem recovery

Follow the [controller's problem procedure](../SKILL.md#problems) before cleanup. Ordinary waits return stored problem states without polling them again.

If inspection shows a previously unacknowledged task started, or the user cleared a dialog, use `horch wait <task-id> --recheck`. Apply the same background or bounded waiting method as a normal wait. Recheck requires explicit task IDs, never resends a prompt, and never restarts a process. Closed and completed tasks are not reopened. An exited process's result stays on disk for inspection; without turn-completion evidence it is not promoted to `done`.

When `done` has `closed: false`, read `message` and retry `horch close <task-id>`. The worker slot remains occupied until closure is confirmed. Closing an unfinished worker cancels it and cannot satisfy a completion or review gate.

A pane-placement error can leave an empty pane when Herdr's response was lost. No worker has started at that point. Inspect Herdr before removing it; never close an unrelated pane. `list` reports `task_invalid` records without hiding healthy history. Each unclosed invalid record reserves one slot in every caller workspace because its owner and pane are unknown; a full `run` returns `worker_limit`, naming the invalid IDs and `horch list`. `check` keeps polling its started tasks and starts pending workers as slots free; workers it cannot start are `not_checked`, with invalid IDs and `horch list` in their message when invalid records held capacity. No-ID `wait` skips them; targeted `wait` still returns `task_invalid`. `close` also returns `task_invalid`: check `herdr pane list` for a leftover `horch` pane, then remove the task directory by hand. Nothing is deleted automatically.

## Task store and concurrency

Processes sharing a task store serialize startup to enforce `max_active_workers` independently for each workspace; workers execute concurrently after launch. Controllers in the same workspace share its slots when they use the same state directory. The shared startup lock prevents two controllers from claiming the last slot together; it does not turn workspace quotas into a total limit. Short per-task transactions prevent a concurrent wait from overwriting confirmed closure. JSON updates replace files atomically.

New task records retain the live caller's `workspace_id` at launch. An unclosed task keeps occupying that workspace's slot, including after a manual pane move or a failed startup. Older records without `workspace_id` count when their recorded pane is present in that workspace's live pane list. A missing legacy pane cannot reserve a slot in another workspace; pane-list failures leave admission unresolved instead of assuming capacity is free. No configuration migration is required.

Scope each task store to one Herdr server. Pane IDs and agent names are server-local, and task records do not retain their originating socket. If using multiple named sessions or machines, give each a separate `XDG_STATE_HOME` and operate its tasks only through that server. Cross-server cleanup with a shared store is unsupported and can target an unrelated pane with the same ID.

A Pi worker waiting for its session signal can use the full 90-second startup budget while holding the startup lock. Install the integration and resolve startup dialogs before checking several workers; `check` stops launching new checks when its overall budget expires.

`horch close` resolves the recorded pane directly, even from another workspace. Only explicit pane/tab/workspace-not-found responses establish that it is already gone; other Herdr errors leave cleanup unresolved.

`check` batches at its caller workspace's `max_active_workers` and deduplicates repeated worker names. Each row has `worker`, `task_id`, `state`, `ok`, `pane_id`, `seconds`, and `message`. Workers that cannot start before the wait cap or have no free slot are `not_checked`, with null task, pane, and duration. Invalid reservations do not abort a batch: started tasks are still polled and pending workers launch as slots free. If invalid records held capacity, never-started workers' messages name those IDs and recommend `horch list`. Unfinished/problem tasks retain their panes; inspect `message` before acting.
