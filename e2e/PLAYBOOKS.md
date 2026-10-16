# Original playbook verification

Skill discovery, a correct application result, and execution of an original
playbook are separate claims. This inventory covers all 23 files in
[`poteto-mode/playbooks`](../skills/poteto-mode/playbooks/). Unavailable stages
stay unresolved. A local scenario does not establish another controller
harness's compatibility.

## Run a live controller

`playbook_loop.py` starts a real evaluation controller directly in its own
Herdr tab. The controller reads the bundled `poteto-mode`, selects a playbook,
and uses configured workers through `horch`. It is not a bounded `horch` worker.
The initial implementation supports Pi controllers; Codex and Claude Code
controller coverage remains separate work.

Run from a trusted checkout inside Herdr. Confirm the actual caller pane using
the [caller identity procedure](../skills/herdr-orchestrator/references/setup.md#caller-context).
Use a private artifact directory outside the checkout:

```bash
python3 e2e/playbook_loop.py --controller <configured-pi-worker> \
  --scenario prototype --repo "$PWD" --caller-pane <verified-pane> \
  --output /tmp/horch-playbook-proof --max-seconds 1200
```

Other initial scenario IDs are `investigation` and `trace-forensics`. These make
authenticated model calls. Stop other isolated dispatchers in that workspace.
The runner copies worker definitions unchanged, preserves existing permission
flags, and does not answer trust dialogs. It preserves the shell's original
Mise config and state roots when isolating horch's XDG directories.

Native sessions must match the fresh controller's cwd, time, session identity,
model and effort. Required documents must appear in successful native tool
results. Submitted tasks must match configured launch arguments and deliver
valid results. Artifact reads must follow delivery. Final claims that a skill
was followed do not establish execution.

The current auditor recognizes direct native `read`, `bash`, `write`, `edit`,
`grep`, `find` and `ls` calls. Pi's `codemode` is a native tool, but its nested
calls are outside this evidence grammar. The evaluation prompt states that
restriction explicitly; it does not change the configured harness or permissions.

The controller does not grade its own result:

| Scenario | Independent observations |
|---|---|
| Investigation | Exact structured facts and source citations across command, transaction storage, and integer money modules |
| Prototype | Two rounding implementations and a labeled CLI rerun on fractional-cent, ordinary, empty and zero-value inputs |
| Trace forensics | Real paired profiles, exact SQLite row preservation, source attribution and equal reconciliation results |

Prototype observations must come from direct CLI invocations with oracle-checked
JSON outputs. Profile conversion must precede analysis through the frozen CLI.
The importer preserves function rows and captured caller edges; query outputs
are checked against the retained database. Source citations resolve to the exact
supplied file, including valid fixture-relative and worktree-relative paths.
Command text mentioning a tool is only a hint.

The Investigation fixture uses a narrower presentation protocol than How's
allowance for light edits: the explainer applies `unslop` before delivery, and
the controller presents that explanation unchanged with one throughput line.
This makes explanation preservation observable without a semantic-similarity
score. A synthesis that needs substantive correction leaves the stage unresolved.
Each canonical `report.md` must be read and propagated in full. The revised
protocol has no positive live receipt yet.

## Interpret evidence

The printed `evidence.json` is authoritative. Its private parent directory also
retains configuration, commands, panes, transcripts, profiles and outputs. Only
the sanitized receipt is a candidate for publication.

- `behavior_verdict` covers independent fixture checks.
- `stage_coverage` covers declared stages and their native evidence.
- `workflow_verdict` additionally requires full workflow eligibility and ordered
  native evidence. Measured core-workflow passes cover fixed-direction Prototype
  and bounded paired-capture Trace forensics. Investigation remains failed.
- `inventory` accounts for every playbook. `not_run` is not a pass.
- `full_inventory_verdict` cannot pass from one scenario.

No inter-task dependency graph is inferred from final task states. Delivery
before an individual artifact read is audited separately. Role names in a
brief alone cannot prove a multi-phase workflow.

Failed attempts stay failed, including startup failures before a model prompt.
Fixing the verifier does not retroactively promote a receipt. Recorded source
hashes identify the tested code; keep historical attribution intact.

### Measured results

The [complete Prototype receipt](evidence/playbook-prototype.json) passes the
fixed-direction core workflow with a real Pi controller and one delivered
implementation task. Its six-stage native record proves the original checklist
preceded delegation, all three scripts were inspected, both labeled alternatives
were observed on the same discriminating input, and the decision and final
handoff followed the observations. Reference gathering was explicitly skipped
because the supplied contract fixed the direction, as the playbook permits.
The decision records concrete tradeoffs, throwaway scope and a Feature handoff.

Independent replay returns 102 versus 101 cents for the separating invoice,
933 cents for the ordinary case, and zero for zero-cost and empty invoices.
Both standalone variants and the shared runner produce these results even when
the decision file is temporarily unavailable. This covers the behavioral fork
with a fixed direction; it does not cover an open visual design search or a
production Feature build. The [earlier stage receipt](evidence/playbook-prototype-stages.json)
retains its original unresolved workflow verdict.

The [fresh Trace forensics receipt](evidence/playbook-trace.json) passes all six
stages in 148.428 seconds. Independent review compared every SQLite row and edge
with the original profiles: nine function rows and five caller edges were
preserved exactly. Four native SQL observations were replayed read-only without
changing database bytes. The controller converted before analysis, queried the
hot path and captured caller, mapped it to source, compared the pair, then wrote
the diagnosis. The captures show 6,000 lookups before and zero after, with equal
reconciliation results of 958008. No workload rerun or source change occurred.
This covers bounded controller-local captures, not large-capture delegation,
runtime instrumentation, or a generalized performance improvement.

The [Investigation attempt](evidence/playbook-investigation-codemode.json)
remains failed. The native audit could not inspect a `codemode` wrapper.
Independent review confirmed both full explorer reports reached synthesis and
all five technical facts were correct, but the controller substantially rewrote
the delivered explanation. That violates How's presentation rule. The
[separate artifact reanalysis](evidence/playbook-investigation-reanalysis.json)
fixes an overly narrow citation check using actual Python symbol scopes; it
preserves the failed workflow verdict. Correct facts do not complete this workflow.

The [fresh live-replacement receipt](evidence/hot-swap.json) verifies two real
Pi tasks using distinct configured models. Both were held working while the
private alias was changed and removed. A dispatch after removal failed without
allocation; existing tasks retained their exact launch snapshots, delivered
correct 720-event reconciliations and independently rerunnable scripts. Native
session evidence confirms both selected models. Real worker configuration,
skill sources and tracked checkout remained unchanged; owned cleanup passed.
This verifies worker definition replacement, not automatic role or skill reload.

### Preserved failed attempts

| Receipt | Observed failure |
|---|---|
| [Prototype startup](evidence/playbook-prototype-startup.json) | Isolated XDG roots changed Mise's existing trust environment; no model prompt submitted |
| [Prototype contract](evidence/playbook-prototype-contract.json) | Controller ran both variants, but the fixture omitted exact JSON field names and the independent checker could not replay them |
| [Replacement launch](evidence/hot-swap-launch.json) | Verifier parsed an empty successful pane-run response as JSON before any worker allocation |
| [Replacement audit](evidence/hot-swap-audit.json) | Swap/removal gates passed, but verifier queried a live agent after delivery had automatically closed it |
| [Investigation tooling](evidence/playbook-investigation-codemode.json) | Native `codemode` was outside the auditor's grammar; separate review also found a substantive How rewrite |
| [Trace source path](evidence/playbook-trace-path.json) | All six native stages executed, but the checker rejected a valid worktree-relative source path |

Each attempt retained its failure verdict and confirmed owned cleanup. The first
prototype run did not execute a model task. The contract run produced real
observations; those do not replace a passing independent replay.

## Complete inventory

Two bounded scenarios have complete core-workflow evidence. The remaining 21
playbooks are unresolved, as are untested branches of the passing scenarios.

| Playbook | Scenario or remaining requirement |
|---|---|
| Investigation | [FAIL](evidence/playbook-investigation-codemode.json): correct facts, unsupported wrapper and substantial synthesis rewrite; revised preservation protocol unrun |
| Bug fix | Failing input, runtime cause, delegated fix, real PR |
| Feature | Design exploration, delegated implementation, behavior gate, real PR |
| Refactoring | Frozen baseline, equivalent final artifact, real PR |
| Prototype | [PASS: fixed-direction behavioral core workflow](evidence/playbook-prototype.json); open visual design search unverified |
| Perf issue | Frozen workload, paired repeat measurements, correctness, real PR |
| Hillclimb | Sensitive harness, metric and stop predicate, kept/reverted attempts |
| Runtime forensics | Live signal, instrumentation, source-attributed mechanism |
| Trace forensics | [PASS: bounded paired-capture core workflow](evidence/playbook-trace.json); large-capture delegation unverified |
| Visual parity | Untouched screenshots, real migration, zero pixel diff, real PR |
| Authoring a skill | Discovered skill, structural cases and links, real PR |
| Eval | Blinded candidates, hidden rubric, native transcript audit, independent synthesis |
| Multi-phase plan | Checked dependency plan, prototype evidence, executable live-lane recipe |
| Opening a PR | Real forge branch and ready PR with ordered verified commits |
| Babysit | Real PR blocker, declared mode and merge-ready outcome |
| Shipping | Verified stack and explicit authorization to merge test PRs |
| Autonomous run | Available wake mechanism, iteration trail, reached stop predicate |
| Orchestrate | Available cloud execution, durable ledger/frontier, rolling dispatch |
| Autopilot-full | Cloud owners, wake mechanism, independent verification, authorized merges |
| Autopilot-stack | Cloud owners, wake mechanism, real base-chained PRs, STACK-READY |
| Pause safely | Actual in-flight task stopped at a durable safe boundary |
| Session pickup | Fresh controller, inherited trail, no duplicate work, verified outcome |
| Worktree cleanup | Owned worktrees, justified removals and active-work protection |

Cloud execution and `/loop` are not supplied by the current adapter. Gate-only
Shipping evidence cannot complete Shipping. Remote scenarios need a dedicated
test destination; this repository's default branch is not a test target.

## Retain artifacts and clean up

The runner closes only owned controller and worker panes. It retains the
worktree under `handoff/<run>/worktree` for inspection. Never commit that folder.
After inspection remove only the exact owned worktree with `git worktree remove`.
Keep external receipts and private diagnostics.

CI checks syntax, CLI entry points and installation. Authenticated scenarios
run locally. A green package CI run does not establish workflow coverage.
