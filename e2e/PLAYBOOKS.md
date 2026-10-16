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
Mise config and state roots when isolating horch's XDG directories. Git retains
its original global configuration files and precedence through a private include
wrapper, including relative include origins; user Git settings stay unchanged.

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
Each canonical `report.md` must be read and propagated in full. Complete briefs
must use native `write`; shell/Python task-artifact composition is outside the
auditor's grammar. A later attempt correctly stopped on an erroneous synthesis,
so successful unchanged presentation still has no positive receipt.

## Continuity and writable workflows

The maintained drivers below add distinct workflow surfaces. Their existence,
syntax checks and independent code review do not establish a live workflow pass.
Read the measured results and each fresh receipt before reporting coverage.

| Driver | Scope and prerequisites |
|---|---|
| `pause_pickup.py` | Two fresh Pi sessions, one local WIP commit, scoped prior trail and persisted importer verification; no remote writes |
| `forge_loop.py` | Bug fix and Opening a PR against an existing private invoice fixture and ready baseline PR |
| `design_loop.py` | Feature or Refactoring, actual How/Architect/Arena stages, independent behavior/equivalence and a ready private child PR |
| `perf_loop.py` | Fresh profiles, separate unprofiled alternating CLI timings, one-function fix and a ready private child PR |
| `authoring_loop.py` | Actual skill-authoring guidance, existing validator, two independently traced usage cases and a ready private child PR |
| `runtime_loop.py` | Owned live Node Inspector process, CPU capture, benign instrumentation and source-attributed diagnosis; no fix or PR |

For continuity:

```bash
python3 e2e/pause_pickup.py --controller <configured-pi-worker> \
  --repo "$PWD" --caller-pane <verified-pane> \
  --output /tmp/horch-continuity-proof --max-seconds 2400
```

The current continuity fixture establishes its originating Feature workstream
in session A. Session B recovers that context from the actual prior trail, uses
neutral verdict choices and names the numbered original resume step. Earlier
Feature grounding/design and later PR/review are outside this fixture's coverage.
This refined reporting contract awaits a fresh live run.

Prepare portable fixture files without Git, credentials, Herdr or model calls:

```bash
python3 e2e/forge_loop.py --prepare-fixture /tmp/invoice-baseline
python3 -B /tmp/invoice-baseline/e2e_import.py --output /tmp/invoice-baseline-proof
python3 e2e/perf_loop.py --prepare-fixture /tmp/reconciliation-baseline
python3 -B /tmp/reconciliation-baseline/e2e_reconcile.py --output /tmp/reconciliation-baseline-proof
```

Follow the generated README to create your own private fixture repository and
ready baseline PR. Keep it unmerged. Use each live driver's `--help` for explicit
clone, forge repository, base branch and parent PR arguments. These drivers
retain real child PRs and never merge or enable auto-merge. Initial portable
baselines passed their seven invoice flows and six reconciliation flows; those
bootstrap checks are not native playbook executions.

Skill authoring needs existing creator guidance and its validator's PyYAML
dependency; it never installs that dependency. Explicit forward use does not
prove automatic discovery. Runtime forensics needs Node with Inspector and
built-in WebSocket support. Its live V8 frames and shutdown remain unverified.
Bug fix, Feature, Refactoring, Perf issue, Authoring and live-runtime model
workflows remain unrun.

## Interpret evidence

The printed `evidence.json` is authoritative. Its private parent directory also
retains configuration, commands, panes, transcripts, profiles and outputs. Only
the sanitized receipt is a candidate for publication.

- `behavior_verdict` covers independent fixture checks.
- `stage_coverage` covers declared stages and their native evidence.
- `workflow_verdict` additionally requires full workflow eligibility and ordered
  native evidence. Measured core-workflow passes cover fixed-direction Prototype
  and bounded paired-capture Trace forensics. The continuity receipt separately
  records a completed Pause phase; its Pickup phase remains failed. Investigation
  remains failed.
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

The [later Investigation attempt](evidence/playbook-investigation-concat.json)
also remains failed. Both delivered explorer reports reached the synthesis brief
in full, but inline Python composition was outside the native evidence grammar.
Independent review also found a real synthesis error: stored stale totals do not
necessarily survive export and reimport unchanged. The controller correctly
withheld the explanation instead of rewriting it. This is evidence of stopping
on an unresolved result, not a successful presentation. The
[separate reanalysis](evidence/playbook-investigation-concat-reanalysis.json)
records ten of eleven artifact checks passing and preserves the failed native
audit and failed presentation gate.

The [two-session continuity attempt](evidence/playbook-continuity-route.json)
records **Pause safely pass / Session pickup fail**. Pause completed its original
four stages: one delivered money-only implementation, actual half-up observation,
an explicit stop, one matching WIP commit, a clean tree and an off-context note.
Session A closed before the distinct session B began. Independent review confirms
the recorded identities, hashes, native order and preserved checkpoint bytes.

Pickup's fixture was ambiguous: neither A's original goal nor its note established
a Feature workstream. B reasonably selected read-only Investigation, inspected
the inherited state and executed all six pending CLI cases without repeating
the money probe. The evaluator instead demanded Feature. Its original failure
remains unchanged; the refined fixture above does not retroactively promote it.

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
| [Continuity Git setup](evidence/playbook-pause-git.json) | Isolated XDG hid existing Git identity before any model started |
| [Continuity audit call](evidence/playbook-pause-audit.json) | Inherited state shadowed an audit method after the implementation checkpoint |
| [Continuity empty output](evidence/playbook-pause-empty-output.json) | Pi rendered clean Git stdout as `(no output)`, which the checker rejected |
| [Continuity routing](evidence/playbook-continuity-route.json) | Pause passed; Pickup selected a defensible Investigation route that the fixture had not allowed |
| [Investigation composition](evidence/playbook-investigation-concat.json) | Unsupported inline file composition; separately, an erroneous synthesis correctly remained unresolved |

Each attempt retained its failure verdict and confirmed owned cleanup. The first
prototype run did not execute a model task. The contract run produced real
observations; those do not replace a passing independent replay.

## Complete inventory

Three bounded scenarios have complete core-workflow evidence. The remaining 20
playbooks are unresolved, as are untested branches of the passing scenarios.

| Playbook | Scenario or remaining requirement |
|---|---|
| Investigation | [FAIL](evidence/playbook-investigation-concat.json): native grammar gap and unresolved synthesis; correct stop does not satisfy successful presentation |
| Bug fix | Reviewed `forge_loop.py`; live failing input, delegated fix and real PR still unrun |
| Feature | Reviewed `design_loop.py`; live design/implementation Arena, behavior gate and real PR still unrun |
| Refactoring | Reviewed `design_loop.py`; live frozen baseline, equivalence and real PR still unrun |
| Prototype | [PASS: fixed-direction behavioral core workflow](evidence/playbook-prototype.json); open visual design search unverified |
| Perf issue | Reviewed `perf_loop.py`; portable baseline passes, live measurements/fix/PR unrun |
| Hillclimb | Sensitive harness, metric and stop predicate, kept/reverted attempts |
| Runtime forensics | Reviewed `runtime_loop.py`; live Node signal/instrumentation/diagnosis unrun |
| Trace forensics | [PASS: bounded paired-capture core workflow](evidence/playbook-trace.json); large-capture delegation unverified |
| Visual parity | Untouched screenshots, real migration, zero pixel diff, real PR |
| Authoring a skill | Reviewed `authoring_loop.py`; live authored skill, structural usage cases and real PR unrun; automatic discovery separate |
| Eval | Scoped Pi transcripts are accessible in principle; current global skill catalog violates strict blinding under unchanged settings |
| Multi-phase plan | Validator exists; executable cloud lanes and configured swarm role are unavailable |
| Opening a PR | Real forge branch and ready PR with ordered verified commits |
| Babysit | Read-only check can use real private PRs; drive/background wake mechanism unavailable |
| Shipping | Cloud verifier unavailable; no authorization to merge test PRs |
| Autonomous run | Required wake mechanism unavailable |
| Orchestrate | Cloud execution and durable wake mechanism unavailable |
| Autopilot-full | Cloud owners/verifiers and wake mechanism unavailable; no merge authorization |
| Autopilot-stack | Cloud owners and wake mechanism unavailable; no STACK-READY evidence |
| Pause safely | [PASS: bounded local four-stage stop](evidence/playbook-continuity-route.json); its later Pickup phase failed |
| Session pickup | [FAIL: ambiguous originating workstream](evidence/playbook-continuity-route.json); refined fixture awaits fresh run |
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
