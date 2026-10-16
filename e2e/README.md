# End-to-end verification

For agent-driven verification, use the project-local [verify-herdr-orchestrator skill](../.agents/skills/verify-herdr-orchestrator/SKILL.md). Its feature map selects existing drivers and records prerequisites, evidence locations, and cleanup without adding another test harness.

These files are repository tooling, outside the installed skills.

## Original playbooks and worker replacement

The [23-playbook inventory](PLAYBOOKS.md) separates native stage evidence,
independent behavior checks, complete workflow eligibility and unavailable
capabilities. `playbook_loop.py` drives a fresh Pi controller through the original
skills; its initial scenarios are Investigation, Prototype and Trace forensics.
Partial stage evidence must not be described as a completed playbook.
The [fixed-direction Prototype receipt](evidence/playbook-prototype.json) and
[paired-capture Trace receipt](evidence/playbook-trace.json) record ordered
six-stage core workflow passes. The other 21 playbooks remain unresolved. The
Investigation failure includes an actual explanation-preservation violation;
its separately passing artifact checks do not promote the workflow.

For live replacement and removal of worker definitions, use the existing
`check_workers.py --hot-swap-only` mode. It keeps two real reconciliation tasks
running across alias changes, checks new-dispatch selection and removal refusal,
then verifies outputs and configuration integrity. See the maintained
[worker procedure](../.agents/skills/verify-herdr-orchestrator/features/workers.md#live-worker-replacement).

## Caller context preflight

After a real Codex shell snapshot supplied another workspace's old IDs, a worker was created in the wrong workspace. The [observation and before/after receipt](evidence/caller-context.json) records that failure and the focused fix. Reproduce the preflight check with a verified live controller pane:

```bash
python3 e2e/caller_context.py --controller-pane <verified-pane-id> --output /tmp/horch-context
```

The driver uses real Herdr reads and invokes both `run` and `check`. Unavailable or missing/blank caller pane IDs must fail; a verified pane with stale workspace/tab variables must resolve through Herdr and reach configuration loading. Caller cases use an empty isolated configuration; configuration cases use a missing brief or an unknown worker as a second stopping condition. No workers launch, including before the fix. It retains `evidence.json` and command output outside the checkout. The [native-context receipt](evidence/native-caller-context.json) records the context correction; the [worker-description receipt](evidence/worker-description.json) covers the current driver, legacy configurations, optional description validation, and single-worker role metadata. This checks preflight only: it does not move a pane, exercise a moved-pane alias or worker startup, or test controller role selection. Pane ownership is covered by the caller identity driver below. The earlier caller-context receipt documents the original stricter check, not the current contract.

The original caller-context receipt also records a 30-minute, read-only observation of the previous release: nine tracked tasks delivered and closed, but the controller repeatedly used short wait caps and performed bulk implementation itself before user guidance. The new routing instructions have not received a model-driven workflow run. These receipts do not establish broader pstack playbook coverage.

## Caller identity

A Codex 0.162 controller's tools ran in a shared `codex app-server` daemon (parent PID 1) that had inherited another workspace's pane ID. That pane was still live as a plain shell, so the preflight above accepted it and workers opened in the wrong workspace. The [before/after receipt](evidence/caller-identity.json) records the fix:

```bash
python3 e2e/caller_identity.py --controller-pane <verified-pane-id> --output /tmp/horch-identity
```

Run it from the controller pane's own process tree. It creates a scratch tab and a scratch workspace, runs `run` and `check` against real process trees, and closes both. The cases are: a stale ID naming a live shell pane; `--caller-pane` contradicting the process tree; a detached process (via `setsid`, parent PID 1, like the daemon) with a stale or a correct `HERDR_PANE_ID`; `--caller-pane` naming a plain-shell pane or a pane with another session ID; plus three that must still pass: a correct in-tree controller, a confirmed `--caller-pane` from a detached process, and a pane moved to another workspace that uses its launch-time alias. Accepted cases stop at an empty isolated configuration, so no worker starts. Pass `--horch <file>` to run the same cases against another revision. The receipt was produced by a Claude Code controller on Linux; the real Codex daemon and macOS `ps` were not exercised.

## Worker setup checks

```bash
python3 e2e/check_workers.py --worker <worker-a> --worker <worker-b> \
  --cwd . --output /tmp/horch-check-proof
```

Choose at least two distinct authenticated workers from your existing configuration; names do not imply harnesses. The driver repeats the first selection automatically and copies only selected definitions, unchanged, to a private isolated configuration. A one-slot limit forces batching even with two workers. It verifies serial reservation lifetimes independently: each later task.json publication must have a strictly later filesystem timestamp than the preceding closed state.json, before driver cleanup. Equal/coarse timestamps fail closed. It checks deduplicated output against the actual repeated selection, exact task/result identities, closure before teardown, zero-slot lifecycle fields without allocations, an acknowledged worker whose pane is deliberately closed, and an already exhausted budget. It resolves the live caller through `herdr pane current --current`, then creates and removes its own workspace. Use a trusted checkout, installed integration for Pi workers, and no other dispatchers in the owned workspace; never answer worker dialogs to make it pass.

The printed `evidence.json` contains source hashes, separate Herdr CLI/server versions, selected harness/model metadata, bounded lifecycle observations and 44 behavioral assertions on a complete successful run (20 existing checks plus 24 stats checks). Scenario completion separately gates the verdict. It contains no pane transcripts, raw command streams or free-form message/error diagnostics; known cwd/output/config/home/repository/run paths are replaced in every field, including `rerun`. Keep the sibling isolated config, task state and `diagnostics/` private. Command stdout/stderr and failure details stay there outside the checkout; the receipt records only a placeholder diagnostic location. Missing or invalid worker configuration also produces a failed receipt. Model speed can prevent the exit probe from observing an acknowledged running worker: that is a failed probe, not a pass. CI runs only `--help`; the controller must run and inspect live evidence.

After the existing scenario, the driver configures an unused worker without running it and plants an invalid record plus a legacy-timed result for an unconfigured worker in a different workspace. Whole-store and workspace-filtered `stats` must match its known counts, task states, result statuses, exclusions, configuration flags, workspace ownership, first settlement timestamps and independently observed duration bounds; arguments must be absent and config/task files unchanged. Synthetic records remain closed and retained in private state. The stats phase then launches one real worker with a delayed-result brief and closes it while still running; whole-store and workspace stats must count only the new cancellation, not another running task or problem. It also asserts fixed delivered-duration thresholds (strict boundaries, nondefault current and deduplication), recovered-style first-done endpoints, multi-sample median/p90, day filtering, dangling roles, configuration facts including provider, separate in-flight counts, and stored reminder firings per worker and in total across scopes.

The [setup-check receipt](evidence/check-workers.json) records a fresh 44/44 pass in 49.602 seconds with real `gpt` and `glm` Pi workers, Herdr CLI 0.9.5 and server 0.9.5, including the `horch stats` phase and a worker closed while running. Its source hashes match commit `af4f81e`. On the real task store, the first `stats` version counted 28 tasks closed before delivery as running problems; they are now reported separately.

## Workspace worker limits

```bash
python3 e2e/workspace_limits.py --worker <configured-worker> --output /tmp/horch-workspace-proof
```

The driver creates two owned workspaces and a shared isolated task store, with two slots in each workspace. It fills workspace A, verifies `run` and `check` refuse additional work without allocating a task or pane, then converts only its own A records to the legacy format without `workspace_id`. Workspace B must still start two workers. All four tasks must deliver correct nonce-bound results and close; a fresh setup check must then succeed in A. Failure diagnostics stay local, the receipt records source hashes, and cleanup removes only the driver's worker panes and workspaces. Select an authenticated configured worker and a trusted checkout; do not change permission or trust settings for this run.

A final phase plants an unclosed malformed record in the same isolated store. A admits one real worker, then `run` must return `worker_limit` and `check` must report `not_checked`, both naming that record without allocating anything. B also fills its remaining slot and must refuse another `run` naming the invalid record. Supply `--second-worker <distinct-configured-worker>` to exercise a two-selection `check` with one free slot beside corruption: the first worker must deliver and close, the second must deliver and close or be `not_checked`, and no real task may remain unclosed. Without this option that batching sub-case is explicitly recorded as skipped. No-ID `wait` must deliver the real nonce-bound result; targeted wait and close must report `task_invalid`, with close giving manual recovery guidance. The driver removes only its planted directory, starts and delivers a fresh worker, and retains a new receipt in its unique external run directory, never overwriting the historical receipt.

The [invalid-record receipt](evidence/invalid-task-records.json) records a fresh 101/101 pass in 342.015 seconds with real `glm-flash` and `glm` Pi tasks. It records Herdr CLI 0.9.5 and server 0.9.5 separately, and its source hashes match commit `2e5f8cf`. The two-worker `check` beside an invalid record started, delivered, and closed both workers. Before the fix, the same malformed record made `run`, no-ID `wait`, and `close` all fail with `task_invalid`.

Quota ownership is the workspace that launched a new task. Manually moving a new worker does not transfer its slot; older records are recognized by their recorded pane's current workspace membership. Other task stores are not included in the admission count, so controllers that share a workspace limit must share the state directory.

The [workspace quota receipt](evidence/workspace-limits.json) records a fresh 49/49 pass in 66.744 seconds with five real Pi tasks. The same revised driver first reproduced the old global limit: B's first worker received `worker_limit` after A held two legacy reservations. It also preserves the earlier fixture's unrelated second-worker startup failure. Cleanup passed for all three attempts; no failed run is relabeled as passing. Concurrent same-workspace admission and manual pane moves were not exercised.

## Worker and controller loops

Run the public loop driver from a clone inside Herdr:

```bash
python3 e2e/review_loop.py \
  --writer gpt --reviewer glm --reviewer haiku \
  --repo . --output /tmp/horch-evidence
```

Choose configured workers and two reviewers with distinct model definitions. The driver makes real model calls, needs two free slots, and uses a detached worktree. It plants two independent invoice defects, checks a scoped implementation, requires two failing initial reviews, then checks a fresh fix and two passing final reviews. It also covers fractional/full discounts, zero quantities, and single-line invoices.

The run retains its worktree and writes `evidence.json` with assertions, source hashes, revisions, and observed CLI output. It cleans up only panes it started. Reports stay in the local task store; no transcripts go into evidence. Remove the retained worktree with `git worktree remove <printed-path>` after inspection.

For a controller-level test, configure a Codex worker with explicit model, effort, and permission arguments, then run:

```bash
python3 e2e/controller_loop.py \
  --controller gpt --writer glm --reviewer ds --reviewer glm \
  --repo . --output /tmp/horch-controller-evidence
```

This starts a real Codex controller that reads the current skill and handles the six-task scenario itself. The task prompt does not prescribe wait duration, background commands, or the skill's delegation rules. The driver verifies task records, nonce-bound results, reviewer verdicts, both committed CLI versions, file scope, and cleanup independently of the controller's optional report. It then audits the actual Codex tool transcript for wait launches, resumed process handles, delivery-before-read ordering, and native delegation or pane-input calls.

The controller run copies the existing worker configuration and isolates task state. The configured concurrency limit remains in force, and existing Herdr workers in the caller's workspace count against preflight capacity. Keep other dispatchers in that workspace stopped during the run: separate task stores cannot reserve a shared workspace limit atomically. The transcript audit recognizes literal shell-tool calls (including fixed-string addition), sequential `text(await ...)` results, ordered `Promise.allSettled(...).forEach(text)` results, and the measured `const cmds=[...]; text(await Promise.all(cmds.map(cmd=>tools.exec_command({cmd,max_output_tokens:N}))));` form with immutable JSON strings and a literal positive cap. The latter must return a complete, uniquely identified array of tool envelopes in input order. It follows partial outputs across a yielded exec cell and subsequent waits, distinguishes literal brief-writing heredocs from reads, and checks delivery against independently observed state-file write times. An `invalid_task_id` rejection is counted separately and supplies no delivery evidence. Dynamic artifact reads cannot establish delivery evidence. Redundant final verification is allowed only after all six tasks already have explicit gated reads and their independently observed delivery times precede that call. Earlier unresolved reads, shell loops around waits, combined wait/read commands, and ambiguous required evidence fail the audit. It is not a proof of arbitrary shell semantics. Missing transcripts fail the run. Full transcripts stay in the harness's local store; private diagnostics stay beside the retained worktree, outside the repo.

Pi workers require the Herdr Pi integration. A git worktree can still need a separate Pi trust decision when its directory inherits project resources. The [startup investigation](startup-findings.md) explains the reproduced failure and provides a real dialog-preservation test.

To verify Pi preflight against real Herdr, including a mixed batch that must allocate no workers when Pi integration is absent:

```bash
python3 e2e/pi_preflight.py --pi ds --pi glm --other gpt \
  --cwd . --output /tmp/horch-pi-preflight
```

The driver uses Herdr's supported `PI_CODING_AGENT_DIR` override with an empty directory. It does not uninstall the user's integration. It checks immediate rejection of `run` and a mixed `check`, then completes a non-Pi task under the same missing-integration environment and two Pi tasks with the normal installation. It validates nonce-bound results, cleanup, and unchanged sources/configuration/integration. Use an existing trusted checkout, two free slots, and stop other dispatchers. Only its sanitized receipt should be published; diagnostic outputs stay local.

## Evidence and source attribution

- [caller-identity.json](evidence/caller-identity.json): the unfixed horch passed 4/18 caller identity checks; it accepted a stale ID naming a live shell pane and any ID from a detached process. The fixed horch passed 18/18, including a moved pane's alias, and the driver closed its scratch tab and workspace.
- [controller-e2e.json](evidence/controller-e2e.json): a fresh invocation of the final driver passed 47/47 in 736.836 seconds. The six-task scenario, original transcript audit, source/configuration integrity, and actual pane cleanup passed together. Six yielded waits resumed through 23 handle calls, with no short caps. This supersedes the earlier verification gap without changing the historical failed receipts.
- [check-workers.json](evidence/check-workers.json): a fresh 44/44 worker-setup pass with real Pi workers, including the `horch stats` phase and a worker closed while running.
- [workspace-limits.json](evidence/workspace-limits.json): a fresh 49/49 workspace-quota pass, five real Pi tasks across two workspaces sharing one task store.
- [invalid-task-records.json](evidence/invalid-task-records.json): a fresh 101/101 pass over planted invalid records with real Pi tasks, including a two-worker `check` beside the malformed record.
- [pi-preflight.json](evidence/pi-preflight.json): 15/15 real integration-preflight and worker-delivery checks, with missing integration rejected in about 0.05 seconds before allocation.
- [pi-controller.json](evidence/pi-controller.json): the original historical Pi-controller 10/10 receipt, with original artifact hashes and explicit source attribution. It predates the updated wait guidance and is not a v0.1.1 test.
- [verification.json](evidence/verification.json): development runs, including the historical Codex and Claude Code controller records, tested versions, source hashes, and limits.
- [review-e2e.json](evidence/review-e2e.json): the release-era public six-task driver pass and its observed outputs.
- [upstream-sync-0.15.25.json](evidence/upstream-sync-0.15.25.json): the current 56-entry 0.15.25 bundle installed from a local source copy, all 197 files preserved, and native Pi/Codex discovery.
- [skill-discovery.json](evidence/skill-discovery.json): native Pi/Codex catalog checks and the recorded original `how` invocation, a Pi controller with three explorer tasks and one explainer task.
- [relocation-e2e.json](evidence/relocation-e2e.json): the historical failing attempt after moving the driver. It failed at initial worker acknowledgement (`not_started` / Herdr `agent_prompt_stalled`), before implementation. Three attempts stopped there. The [subsequent investigation](startup-findings.md) identified the trust-dialog cause; this receipt remains unchanged.
- [startup-diagnosis.json](evidence/startup-diagnosis.json): sanitized failure, withheld-prompt dialog observation, and successful unchanged-code control after removing the leftover empty directory.
- [pi-startup.json](evidence/pi-startup.json): the fixed guard passed 11/11 checks with a real trust dialog, unchanged trust decisions, fresh explicitly declined-resource work, and confirmed cleanup.
- [startup-fixed-review.json](evidence/startup-fixed-review.json): a fresh six-task review loop on the fixed horch passed 27/27 in 431 seconds.
- [controller-audit-initial.json](evidence/controller-audit-initial.json): the first new Codex-controller run completed all six tasks and passed outcome/cleanup checks, but its initial transcript auditor mistook a literal brief-writing heredoc for reading results. That failing receipt is preserved. Corrections distinguish writes from reads and map real tool outputs to their process handles.
- [controller-audit-second.json](evidence/controller-audit-second.json): the second real run also passed all 46 scenario/source/cleanup assertions. Its original invocation failed because the auditor rejected fixed-string addition. The completed trace also exposed a rejected mistyped wait request and partial tool outputs across a yielded cell; the auditor now accounts for both.
- [controller-array-reanalysis.json](evidence/controller-array-reanalysis.json): the corrected auditor passes the three unchanged real traces. Older wait/handle counts are unchanged; the new trace has six unbounded yielded waits and 36 handle resumes. This is reanalysis, not a new integrated pass.
- [controller-audit-array.json](evidence/controller-audit-array.json): all six tasks and 46 scenario/source/cleanup assertions passed, but the auditor rejected a literal command array mapped through `Promise.all` during initial context reads. This original invocation remains a failure.
- [controller-provider-error.json](evidence/controller-provider-error.json): the next attempt completed implementation but a first-round DeepSeek reviewer received CommandCode HTTP 400 before delivering its result. The controller inspected the problem and asked whether to retry, leading to `controller_blocked`. The partial report did not pass the review gate; source integrity and cleanup passed.
- [controller-stalled.json](evidence/controller-stalled.json): a fresh invocation of the final driver stopped after 1,214 seconds. The first GLM worker stayed working without visible progress; the controller asked whether to retry, producing `controller_blocked`. Source integrity and cleanup passed, but the six-task scenario and transcript audit did not complete. The worker stall root cause is undetermined.
- [controller-reanalysis.json](evidence/controller-reanalysis.json): the corrected auditor passes both unchanged real transcripts. Each controller launched six unbounded waits, resumed the same yielded processes, and used no short wait caps. The second controller corrected one rejected task-ID typo. This is post-run reanalysis; neither original driver invocation is relabeled as passing, and this reanalysis is not a fresh integrated pass. The separate current-driver attempt is recorded above.
- [lifecycle.json](evidence/lifecycle.json), [recovery.json](evidence/recovery.json), and [completion.json](evidence/completion.json): sanitized historical real-worker probes, with original artifact hashes and tested source attribution. Their local drivers are not distributed; these records are supporting evidence, not additional portable test commands.

Historical evidence keeps its original source attribution. Moving the driver changes its hash; it does not retroactively change which code an earlier run exercised. The CLI itself is unchanged by the relocation.

`review_loop.py` controls `horch` directly; `controller_loop.py` tests an AI controller following `herdr-orchestrator`. Neither exercises the pstack rubric. Earlier controller/pstack development runs remain attributed to their original sources. GitHub Actions checks Python compatibility, configuration parsing, and installation into Claude Code, Codex, and Pi. Earlier package CI runs recorded Python 3.11/3.14, installed-file comparisons, and regeneration from the then-pinned upstream source. Authenticated model E2Es run locally.

## Reproduce original skill discovery

[upstream-frontmatter.json](evidence/upstream-frontmatter.json) records upstream frontmatter preservation, regeneration, installation, and native Pi/Codex catalogs. Its Phase A measured Pi model visibility and explicit expansion for `unslop` and `typescript-best-practices`, aborting before provider work, plus enabled Codex catalog entries. Codex explicit invocation, implicit selection, `paths:` activation, Claude Code runtime behavior, and model workflows were not measured; Codex/Claude invocation semantics are documented only. The local Pi probe script and extension are not distributed; those observations are supporting evidence, not an additional portable test command. The distributed `skill_catalogs.py` reproduces installation/catalog checks only.

[upstream-sync-0.15.25.json](evidence/upstream-sync-0.15.25.json) records the current 56-entry pstack 0.15.25 bundle installed from a local source copy, all 197 files preserved for Codex, Pi, and Claude Code after that copy was deleted, and native Pi/Codex discovery. Claude Code installation was checked; native discovery was not measured.

[upstream-sync-0.15.24.json](evidence/upstream-sync-0.15.24.json) records the 56-entry pstack 0.15.24 bundle installed from a local source copy, all 197 files preserved after that copy was deleted, and native Pi/Codex discovery. Regeneration from the pinned source, the upstream freshness check, and cleanup passed. The new `in-your-own-words` and `sharpen` entries were discovered; updated workflows and upstream scripts were source-reviewed but not exercised at runtime.

[upstream-sync-0.15.21.json](evidence/upstream-sync-0.15.21.json) records the 54-entry pstack 0.15.21 bundle installed from a local source copy, all 193 files preserved after that copy was deleted, and native Pi/Codex discovery. Regeneration from the pinned source, the upstream freshness check, and cleanup passed. The updated agent mappings, playbooks, and upstream script behavior were source-reviewed but not exercised at runtime.

[upstream-sync-0.15.18.json](evidence/upstream-sync-0.15.18.json) records the preceding 54-entry pstack 0.15.18 bundle installed from a local source copy, all 192 files preserved after that copy was deleted, and native Pi/Codex discovery. It also records regeneration from the pinned source, the successful upstream freshness check, and cleanup. No model workflow or visual recap was run for this sync; `ketchup` execution remains runtime unverified.

[upstream-sync-0.15.17.json](evidence/upstream-sync-0.15.17.json) records the preceding 54-entry pstack 0.15.17 sync and retains its original source attribution, hashes, checks, and runtime limits.

[bundled-install.json](evidence/bundled-install.json) records the historical 53-entry pstack 0.15.15 bundle installed from a commit-pinned GitHub URL, all 190 files preserved, native Pi/Codex discovery, and a separate local installation checked after its temporary source was deleted. It retains its exact source/driver hashes and cleanup.

[skill-discovery.json](evidence/skill-discovery.json) records the real 56-entry Pi/Codex catalog checks, preserved original content/resources/licenses, a fresh original `how` invocation with four delivered and closed workers (a Pi controller; three explorer tasks and one explainer task), and real current/older-pin upstream comparisons. The receipt discloses the evaluation controller's corrected tab placement, the user's mid-run role change, and the limited scope of the source walkthrough. The trace review was manual; full transcripts remain private. These results do not validate other original workflows.

The current bundle is installed in one command. For an isolated installation, use a new directory and omit `-g`:

```bash
consumer=$(mktemp -d)
cd "$consumer"
npx --yes skills@1.7.1 add \
  https://github.com/conscientiousness/herdr-pstack-orchestrator/tree/main/skills \
  -s '*' -a codex -a claude-code -a pi -y
```

From the repository clone, run the real catalog check (requires installed Pi and Codex, but makes no model calls):

```bash
python3 e2e/skill_catalogs.py "$consumer"
```

It compares installed names and every file against this repository's bundle, checks Claude Code's installed entries, then queries Pi's native RPC command catalog and Codex's `skills/list` for enabled, described skills. It retains `evidence.json` plus raw catalogs outside the repository. Use the same repository revision as the installed bundle; CI's `--installation-only` mode skips the native catalog calls. Pi reads the installed files through an isolated user skill directory; Codex discovers them in the disposable project. Unrelated user/system skills are excluded from the comparison. No authentication or trust settings are changed. This measures actual discovery on Pi and Codex. Claude Code's runtime discovery is not claimed. The [verification procedure](../.agents/skills/verify-herdr-orchestrator/features/discovery.md) also checks installation after deleting a temporary source copy and records cleanup.

For a live routing check, install into the controller's normal skill locations, start a fresh controller in its own Herdr tab, and ask it to use `how` to explain the worker lifecycle across configuration, startup, delivery, and cleanup. Supply the repository, read-only scope, and a local output path, but no skill file path or dispatch sequence. The real invocation should discover `how`, load its adapter, use the configured explorer/explainer roles, wait for delivered results, and clean up its own workers. Inspect actual task records and the controller's local tool trace before accepting the explanation. Keep transcripts and machine-specific paths private. This checks one original skill workflow, not every `poteto-mode` playbook.

The daily monitor can also run locally without models:

```bash
python3 scripts/check_upstream.py --output /tmp/pstack-upstream-result.json
```

It returns 0 for unchanged relevant trees, 1 for changes requiring review, and 2 when the check could not complete. Use `--manifest <file>` to compare a deliberately selected historical upstream revision without changing the repository's pin. The JSON and stdout identify the exact two revisions and changed paths.

## Historical pstack source

The controller/pstack review-loop runs recorded on 2026-10-09 used **pstack-claude 0.9.73**, the port by Michael Denyer, at commit `8d3aa5719ab836e89482c894bbedd710224f4424` ([source](https://github.com/michael-denyer/pstack-claude/tree/v0.9.73/plugins/pstack)). Their role-sheet and runtime mappings belonged to that integration. The original receipts, versions, and hashes remain unchanged.

The current adapter bundles selected skills from Lauren Tan's original `cursor/plugins`. Those historical passes do not verify the new source or entry instructions. The [current source pin and update procedure](../skills/pstack-herdr/references/compatibility.md) distinguish source inspection from actual runtime evidence. Neither public loop driver exercises the original pstack rubric.

## Why the lifecycle mechanisms remain

An evidence audit should distinguish a naturally observed failure, a deliberate fault/race exercise, and static reasoning. A passing exercise shows the current behavior; it is not proof of a prior production incident or an exhaustive concurrency test.

| Mechanism | Evidence | Scope of the conclusion |
|---|---|---|
| Startup `flock` | `lifecycle.json`: `simultaneous starts honor one slot` | Two simultaneous real launches with one slot produced one accepted task and one `worker_limit`. Deliberate concurrency exercise. The lock covers startup, not worker execution. |
| Per-task `flock` and monotonic closure | `recovery.json`: `explicit close succeeds during wait`, `background poll preserves confirmed closure`, `background wait exposes closure` | A real worker was explicitly closed while another process waited. Deliberate race exercise; confirmed closure survived polling. |
| Explicit `--recheck` | `recovery.json`: `normal wait preserves problem state`, `explicit recheck recovers original task` | A finished worker's result was deliberately damaged, observed as invalid, then restored. Recheck recovered the same task without another prompt. |
| `task_invalid` | `recovery.json`: `corrupt record does not hide healthy history`, `targeted corrupt record gives task_invalid` | A malformed task record was injected into a store with real task history. Healthy entries remained visible and targeting the damaged record produced a clear error. |
| Explicit missing-pane error codes | `lifecycle.json`: cross-workspace cleanup and `already closed is idempotent` | Confirms direct lookup and already-gone cleanup. The three individual pane/tab/workspace-not-found responses were not each isolated by this probe. Keep the narrow allowlist so other Herdr errors do not falsely confirm closure. |
| Withhold results until turn completion | `verification.json`: Pi controller's `prior_failure`; `completion.json`: early fields, final delivery, cancellation | A real controller previously consumed early reports and closed unfinished reviewers. A later focused probe deliberately injected provisional results and verified withholding. A fresh controller loop passed after the fix. |

These findings support retaining the mechanisms rather than deleting them by line count. They do not establish that every defensive branch was triggered. Deliberate approval denial, turns longer than 30 minutes, macOS runtime, and original-pstack workflows beyond the recorded `how` run remain unverified.
