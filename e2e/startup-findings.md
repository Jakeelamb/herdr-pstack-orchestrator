# Worker startup safety

The relocated review driver failed before its first implementation because a Pi project-trust dialog received the task submission. This was reproduced with Herdr 0.9.3, Pi 1.1.0, and the Herdr Pi integration v9. It was not a provider latency failure.

## Reproduction and cause

An earlier local package-install check left an empty `.agents/skills` directory in the shared temporary parent. Its files had been removed, but the directory remained. Pi treats the existence of that directory in any ancestor as project resources requiring a trust decision, even when it is empty. Every fresh fixture directory therefore required trust; an existing directory could already have a saved decision.

The observations were:

1. Herdr returned `agent_started`, `interactive_ready: true`, and `idle` while Pi had no reported session.
2. A fresh diagnostic that withheld the prompt showed Pi's **Trust project folder?** dialog. `herdr agent explain` reported `default_known_agent_idle_fallback`, no matched rule, and `visible_blocker: false`.
3. In the failing runs, the task submission's Enter selected the dialog's default **Trust** option. Pi subsequently showed an empty editor, with no task message or result. The fresh fixture paths appeared as trusted in Pi's store. Herdr returned `agent_prompt_stalled`; horch recorded `not_started`.
4. Removing the empty directory restored normal submission with the original, unchanged horch code in another fresh fixture. The worker delivered a valid result and the corrected line CLI returned `936`.

This explains the earlier pattern: three fresh worktrees failed, while a later manual dispatch in one of those same worktrees succeeded. The reproduction exposed an upstream detection gap and a horch assumption: a reported idle/ready state did not guarantee that task input would reach the agent's conversation.

The upstream code supports these observations:

- [Pi 1.1.0 trust-resource detection and parent-directory decisions](https://github.com/earendil-works/pi/blob/abe508e1b89912adde45528136c3221eb69acdd7/packages/coding-agent/src/core/trust-manager.ts) and [trust-dialog selection](https://github.com/earendil-works/pi/blob/abe508e1b89912adde45528136c3221eb69acdd7/packages/coding-agent/src/core/project-trust.ts).
- [Herdr 0.9.3 managed startup readiness](https://github.com/herdrdev/herdr/blob/7b116c05bfda646af39d2524c54e70c751f57ee8/src/terminal/state.rs) accepts the known agent's idle state after its startup settling interval.
- [Pi's interactive initialization](https://github.com/earendil-works/pi/blob/abe508e1b89912adde45528136c3221eb69acdd7/packages/coding-agent/src/modes/interactive/interactive-mode.ts) installs the input handler before initializing session extensions. Herdr's Pi integration reports the session from `session_start`, after the earlier trust decision.

## Fix and verification

For Pi workers, horch now requires the installed Herdr integration to report a Pi session in idle/done state before capturing the baseline and submitting the task. It shares the existing startup budget. If no session arrives, horch returns `start_failed`, leaves the pane open, and sends no task prompt. The controller can report the dialog or a missing integration. This intentionally makes `herdr integration install pi` a requirement for Pi workers; it does not change the other harnesses or authorize trust automatically.

The public [pi_startup.py](pi_startup.py) reproduces the difficult case with an empty project `.agents/skills` directory in an untrusted location. It verifies that the dialog remains, no prompt baseline or result exists, and Pi's trust decisions remain unchanged. It then starts a fresh worker with an explicit, run-local `--no-approve` setting, verifies real model work and result delivery, and confirms pane cleanup. `--no-approve` declines project resources; the test never accepts a trust dialog.

```bash
python3 e2e/pi_startup.py --worker glm --output /tmp/horch-pi-startup-evidence
```

Choose an authenticated Pi worker without a trust override and an output parent that Pi has not already trusted. The intentional blocked startup takes the normal 90-second budget. Evidence is sanitized; local diagnostic state and pane text remain in the printed run directory. No trust settings, detector manifests, or installed integration files are edited by this test.

## Codex numbered startup picker

Codex can also show **Folder access** while Herdr reports `agent_started`, `interactive_ready: true`, and `idle`. The retained task records from the reported incident show that prompt submission reached acknowledgement and ended `not_started`. The controller observed the trust dialog. A trust entry appeared during the incident, but those records do not prove what changed it.

Herdr's [managed readiness implementation](https://github.com/herdrdev/herdr/blob/v0.9.3/src/terminal/state.rs) accepts an idle agent. Its [prompt command](https://github.com/herdrdev/herdr/blob/v0.9.3/docs/next/website/src/content/docs/agent-automation.mdx) writes text and Enter before acknowledgement. Another acknowledgement wait cannot prevent input from reaching a misclassified dialog. A Codex session hook alone is also insufficient. The [shared daemon limitation](../skills/herdr-orchestrator/references/setup.md#caller-context) can attribute hooks to another pane.

Codex 0.164.0's [folder-access renderer](https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/tui/src/onboarding/trust_directory.rs) uses the shared numbered picker. Its [rendered snapshot](https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/tui/src/onboarding/snapshots/codex_tui__onboarding__trust_directory__tests__renders_snapshot_for_git_repo.snap) shows the selected row beginning with `› 1.`. `horch` now passively reads the full visible screen before recording its prompt baseline. Any selected numbered row with that structure stops startup. It also rejects incomplete numeric rows such as `› 1` and a number alone or with picker punctuation on the line immediately after `›`. Synthetic controls reproduce those parser counterexamples; their reachability in real terminal rendering is not established. The check does not match English dialog labels or infer that the directory is untrusted.

The check also requires a visible composer line beginning with `›` and whitespace, or an empty composer after that marker. Without one, it observes for at most six seconds after `agent start` returns, also bounded by the remaining 90-second startup budget. Snapshot timeouts and polling sleeps use that observation deadline. A read error, an expired window, or a numbered picker returns `start_failed`, retains the pane, and sends no task prompt. A trusted editor proceeds immediately without a polling sleep, human checkpoint, or trust-setting change. Pi retains its integration guard, and Claude startup is unchanged.

The six-second cap gives an editor three polling opportunities at the existing two-second interval when snapshots return immediately. It limits the additional time an unknown screen holds the shared startup lock after Herdr has reported startup. Agent startup and prompt acknowledgement have separate budgets; this is not a six-second limit on the entire launch. Six seconds is a conservative design choice, not a measured guarantee about rendering speed. An editor that renders later can now fail startup even when the larger budget has time left. A narrow live pane previously showed folder-access text with the selected row entirely offscreen. It received no prompt but consumed the full startup budget. A retained-screen fixture checks the shorter wait with a simulated clock; fresh live verification remains separate.

This is a conservative mitigation for the current rendering, not an authoritative editor-readiness signal. Any digit immediately after the marker's whitespace or on the following line blocks startup. This also rejects editor text beginning with a digit. Other numbered menus can stop startup, including quoted picker output in the visible transcript. An unsupported composer layout can exhaust the observation window. Empty composers remain supported without requiring an English placeholder or extra layout markers. A picker clipped all the way to a bare `›` or `› ` is indistinguishable from that supported empty editor and can pass. The numeric-prefix fix does not resolve that ambiguity. An unnumbered dialog using the same chevron could also evade this check. The read and prompt commands are separate, so a dialog appearing after the snapshot is not covered. A complete solution requires a pane-bound editor-readiness signal or an atomic conditional submission from the runtime.

The regression runs the real task-start implementation against controlled Herdr subprocess responses. Its dialog fixture preserves the upstream picker structure while reporting idle and interactive readiness. It asserts zero prompt or key delivery, no baseline, and an open pane. Trusted controls assert exactly one prompt. It also checks translated labels, the second selected option, a picker over an editor, delayed editor display, missing snapshots, transport errors, and the existing acknowledgement behavior.

```bash
uv run --no-project python -m unittest discover -s tests -v
```

This is fixture-based submission-boundary verification. It does not launch Herdr, Codex workers, or model calls, and does not establish a fresh live dialog-preservation result.

The original [relocation failure](evidence/relocation-e2e.json) remains in the repository as historical evidence. Fresh receipts identify the fixed source separately. The guard is verified for the versions above; it is not a claim that every harness dialog is detected or that later upstream versions behave identically.
