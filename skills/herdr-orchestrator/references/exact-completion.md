# Experimental exact Codex completion

This developer experiment is **default off and not native-runtime qualified**.
It has an end-to-end caller, notification wrapper, bounded stdio observer and
persisted delivery/cancellation decision. Controlled fixtures verify its control
logic. They do not establish that an installed Codex producer reports `completed`
only after post-notification compaction has finished. Complete that native
qualification before using the mode for actual work. App-server is documented
as experimental; the installed binary's upstream provenance is not established.

Ordinary Codex, Pi and Claude tasks keep their existing contract, including the
null-completion-sequence fallback. Existing tasks are never upgraded.

## Selecting the experiment

Only new `run` or `check` tasks can select `--completion codex-exact-v1`. They
also require `HORCH_EXACT_STORE` to name a new, absolute, private directory
(mode 0700), separate from the ordinary task store. Keep that same environment
selection for `wait`, `list`, `stats` and `close`. The CLI rejects an existing,
nonempty unmarked store and rejects legacy launches into the selected exact
store. It never changes user configuration or the installed harness.

For an already qualified disposable worker configuration, the command shape is:

```bash
HORCH_EXACT_STORE=/absolute/private/disposable-store \
  uv run --no-project python skills/herdr-orchestrator/scripts/horch.py \
  run <qualified-codex-worker> --brief /absolute/brief.md \
  --completion codex-exact-v1
```

An isolated store has **independent per-workspace quotas**. Its workers and the
ordinary store's workers are not counted together. Do not use separate stores
to obtain extra capacity on the same server; the operator must reserve capacity
across them. The store marker cannot fence old binaries or hostile writers.
Every command accessing this store must use the upgraded implementation. Do
not redirect old clients into it with `XDG_STATE_HOME`. Use one unchanged Herdr
server scope for the lifetime of its tasks.

The configured Codex args must already contain exactly one explicit root-level
`-c notify=[...]` or `--config notify=[...]` override. The adapter parses TOML,
replaces that value **in its original slot**, and leaves every other argv token
unchanged. It never resolves inherited settings or inserts an empty notifier.
Production launches require a nonempty notifier command. Empty notifications
are used only inside disposable test fixtures, never suggested as a setup fix.
Inherited-only, absent, duplicate, dotted/quoted, malformed or ambiguous notify
settings decline the experiment before pane creation or prompt submission.

The supported argv grammar is deliberately narrow: separate-value model,
sandbox, approval, add-dir and a single profile flag; `model_reasoning_effort`
config overrides; `--no-alt-screen` and `--no-daemon`. Unknown switches/config
keys, positional prompts, subcommands, joined flag syntax and script wrappers
are rejected. The PATH-selected `codex` must resolve to an ELF executable. The
observer pins its bytes and the HOME/CODEX_HOME/XDG context selectors; this
identifies a local binary/context, not a trusted upstream build or a proven
Herdr launch-path equivalence. Native qualification must establish those too.

## Completion, cancellation and recovery

A fresh 128-bit attempt nonce appears in the sole initial input. The native
notification must contain the exact full input list, type, thread ID and turn
ID. Foreign events create no binding. Identical callbacks are idempotent;
differing matching identities permanently withhold delivery for that attempt.
The hook retains only the matching identity and digests, never the native
transcript. It forwards the original raw callback to the original notifier
without a shell, including foreign/malformed events and receipt failures.
Successful exec preserves the notifier's cwd, environment, lifetime and exit
status. No notifier side effect is retried.

This assumes a cooperative exclusive root worker, one input, no pointer
forwarding, no autonomous later turns, and no pane reuse. A worker or same-UID
process can forge files or forward the identical input; this is **not hostile
worker isolation or root-process authentication**. A conflict discovered after
committed delivery cannot revoke the snapshot; it records an association
assumption diagnostic instead.

After a matching callback, ordinary `wait` queries only that bound thread's
`thread/turns/list` over private app-server stdio, with `itemsView: notLoaded`.
It selects the exact turn, never the newest one. Only `completed` without an
error authorizes the next step. Interrupted, failed, malformed, missing and
unavailable history remain unverified and retryable. In particular a standalone
reader can project an active turn as interrupted. No global session scan,
resume, new turn, hook installation or observer daemon exists.

The query runs outside locks. A short locked transaction then rechecks the
full immutable task identity, callback, nonce and current cancellation, reads
one regular non-symlink result of at most 256 KiB, and commits proof plus the
validated exact result bytes and digest together. Failure to replace state
permits neither delivery nor cleanup. `wait`, `check` and `stats` use that
committed snapshot. Exact-mode wait lines also return `result` (all six captured
fields) and `delivery_id`; both remain null before delivery. `result_path`
continues to identify the worker's original file, which can subsequently change.
Use the returned `result` for the delivered status and content.

Explicit close first commits cancellation intent, then performs the pane RPC.
The same lifecycle exclusion orders startup, delivery, close and automatic
cleanup. Whichever decision commits first wins: a cancelled attempt cannot
deliver; an already delivered attempt retains its snapshot. Busy lifecycle
ownership returns an unverified diagnostic and requires retrying the command.
Failed close leaves cancellation intent and the capacity reservation intact.
There is no automatic close of an unverified worker. Automatic cleanup is
allowed only after committed delivery, and is retried independently.

Dispatch intent is persisted before the sole prompt call. Launcher/observer
death, acknowledgement timeout, missing callback and wait expiry never resend
that prompt. New ordinary waits can recover a late callback or committed
snapshot. Death before an uncertain submission or permanent loss of the native
callback can remain unverified forever. Read the diagnostic; do not invent
completion from idle state, sequence counters or an early result file.

## Bounds and remaining acceptance

Each candidate uses an owned reader group, at most three pages of 50 turns,
a 1 MiB frame cap, 4 MiB total output, 64 frames, and a two-second query deadline.
A poll batch admits at most ten seconds of native observation, clipped to the
wait deadline; remaining candidates are deferred. Zero-budget observation
starts no reader or cleanup RPC. Native failures remain task diagnostics and
do not consume the unrelated Herdr-list failure budget. Unchanged diagnostics
and duplicate receipts cause no state replacement.

A Linux parent-death supervisor kills the owned reader process group when its
observer dies, including same-group initialization descendants. Normal teardown
kills the group and waits at most one additional second for the direct child.
Escaped/detached descendants and actual installed initialization behavior still
require native qualification. Herdr/filesystem calls have their existing
separate bounds; these are not hard real-time wall-clock guarantees. App-server
initialization may write normal Codex local state even though the history RPC
is read-only. The adapter neither reads credentials nor fabricates CODEX_HOME.
Atomic replacements cover process crashes, **not power-loss durability**; no
file/directory fsync guarantee is made.

Before any real rollout, qualify the exact executable/version and unchanged
reader/Herdr context with native foreign callbacks, notifier preservation,
early result plus delayed compaction/interruption, cancellation, and observer
SIGKILL controls. A premature positive `completed` projection is a blocking
producer defect. Do not make this mode the default or retrofit it onto running
work based on the controlled fixture suite.

Official protocol references: [notification contract](https://learn.chatgpt.com/docs/config-file/config-advanced#notifications),
[app-server and turn history](https://learn.chatgpt.com/docs/app-server).
