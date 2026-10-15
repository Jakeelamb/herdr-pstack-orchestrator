# Worker statistics

Use `horch stats` when the user asks whether workers are worth keeping, slow,
failing, or efficient, whether reminder timing fits, or before changing
`workers.toml`. It reports facts; the controller interprets them.

```bash
python3 <skill-dir>/scripts/horch.py stats [--workspace <id>] [--days <n>]
```

This reads only workers.toml and the task store: no Herdr calls, environment
requirement, locks, or writes. The default is the whole store because worker
definitions are global. Workspace scope uses the recorded launch workspace;
positive integer days filter created_at from a UTC cutoff (inclusive).
Concurrent controllers can change records during the scan; it is not a snapshot.

## Fields

- `scope` records filters and cutoff; `task_count` totals valid in-scope records.
- `workers` is keyed by names seen in scope or currently configured.
  `configured`, `harness`, `model`, `effort` describe current configuration,
  not necessarily the model used for historical tasks; arguments are omitted.
- `task_count`, `states`, `result_statuses`: stored task states and valid,
  nonce-bound result statuses, only delivered (`done`) results for the latter.
  Early, missing, and invalid results are not counted as delivered outcomes.
- `problem_count` and `problem_rate` count states other than done, including
  running tasks; the rate is a fraction of tasks, not a model failure probability.
- `last_use` is the latest created_at; `workspaces` counts recorded workspace IDs.
  Legacy records contribute to `unknown_workspace_count`, not workspace filters.
- `duration_minutes`: sample_size, median, nearest-rank p90, max, and `sources`
  counts for done tasks with valid results (any result status). Prefer the first
  observed `settled_at` in state.json; legacy records use result.json mtime.
  `duration_excluded_count` counts done records without usable results/timing.
  Negative/future endpoints and malformed timestamps are excluded.
- `configured_unused_workers` lists configured names with zero tasks in scope;
  `roles_with_unconfigured_workers` maps roles to missing assigned names.
- `invalid_task_ids` lists malformed task/state records excluded from numbers.
  Invalid task.json IDs are listed even when their scope cannot be established;
  invalid states are listed within known scope. Disappearing records are skipped.
- `notify_after_minutes` gives timed_task_count and count/share strictly above
  the current threshold and 15, 30, 45, 60, 90 minutes. The denominator is the
  same completed duration sample, not active elapsed times. Empty rates and
  percentiles are null; empty counts are zero.

## Interpretation and configuration

Small samples can mislead; different task scopes are not controlled comparisons.
A blocked result may be a real specification question. Provider faults behind
result_missing are not evidence of poor model behavior. Durations include startup,
notification/polling delays and any wait for observation; mtime fallback can shift
if results are copied or rewritten. First settlement remains first after recheck.
The store cannot show reviewer quality or cost.

Knobs are `notify_after_minutes`, removing or redefining a worker, role assignments,
and `max_active_workers` (per-workspace concurrency, not worker speed). The user owns
workers.toml: propose changes with the numbers and edit only with consent, because
these choices affect their routing, resources, and authorization.
