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

The controller does not grade its own result:

| Scenario | Independent observations |
|---|---|
| Investigation | Exact structured facts and source citations across command, transaction storage, and integer money modules |
| Prototype | Two rounding implementations and a labeled CLI rerun on fractional-cent, ordinary, empty and zero-value inputs |
| Trace forensics | Real paired profiles, exact SQLite row preservation, source attribution and equal reconciliation results |

Prototype observations must come from direct CLI invocations with oracle-checked
JSON outputs. Profile conversion must precede a query through the frozen
analysis CLI; query outputs are checked against the retained database. Command
text mentioning a tool is only a hint.

## Interpret evidence

The printed `evidence.json` is authoritative. Its private parent directory also
retains configuration, commands, panes, transcripts, profiles and outputs. Only
the sanitized receipt is a candidate for publication.

- `behavior_verdict` covers independent fixture checks.
- `stage_coverage` covers declared stages and their native evidence.
- `workflow_verdict` additionally requires full workflow eligibility and ordered
  native evidence. Only the fixed-direction Prototype scenario is currently
  eligible; Investigation and Trace forensics still need complete-stage audits.
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

Each attempt retained its failure verdict and confirmed owned cleanup. The first
prototype run did not execute a model task. The contract run produced real
observations; those do not replace a passing independent replay.

## Complete inventory

One fixed-direction Prototype scenario has complete core-workflow evidence.
The remaining 22 playbooks are unresolved, as are other Prototype branches.

| Playbook | Scenario or remaining requirement |
|---|---|
| Investigation | Live scenario implemented; complete stage audit pending |
| Bug fix | Failing input, runtime cause, delegated fix, real PR |
| Feature | Design exploration, delegated implementation, behavior gate, real PR |
| Refactoring | Frozen baseline, equivalent final artifact, real PR |
| Prototype | [PASS: fixed-direction behavioral core workflow](evidence/playbook-prototype.json); open visual design search unverified |
| Perf issue | Frozen workload, paired repeat measurements, correctness, real PR |
| Hillclimb | Sensitive harness, metric and stop predicate, kept/reverted attempts |
| Runtime forensics | Live signal, instrumentation, source-attributed mechanism |
| Trace forensics | Live scenario implemented; complete stage audit pending |
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
