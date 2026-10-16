# Verification feature map

Commands run from the repository root, using `repo` and `proof` from [Launch](../SKILL.md#launch). Select the feature relevant to the change or observed failure.

| Feature | Driver | Preconditions and scope |
|---|---|---|
| [Skill installation and discovery](discovery.md) | `skill_catalogs.py` | Bundled skills, npm, Pi, Codex; no models |
| [Worker review loop](workers.md) | `review_loop.py` | Authenticated workers, two free slots; six real tasks |
| [Worker setup checks](workers.md#worker-setup-checks) | `check_workers.py` | At least two authenticated configured workers, owned workspace, one-slot batching and injected exit |
| [Workspace worker limits](workers.md#workspace-worker-limits) | `workspace_limits.py` | One authenticated worker, two owned workspaces, shared isolated task store |
| [AI controller loop](controller.md) | `controller_loop.py` | Configured Codex controller plus workers; transcript audit |
| [Original playbook scenarios](playbooks.md) | `playbook_loop.py` | Configured Pi controller; native session audit and independent artifacts |
| [Pause and pickup](playbooks.md) | `pause_pickup.py` | Two fresh Pi sessions, normal Git identity and local WIP; no forge writes |
| [Private PR workflows](playbooks.md) | `forge_loop.py`, `design_loop.py`, `perf_loop.py`, `hillclimb_loop.py`, `authoring_loop.py` | Bug fix halted for scope violation; other live workflows unrun; private fixture, ready parent PR and role-specific prerequisites |
| [Live runtime diagnosis](playbooks.md) | `runtime_loop.py` | First live receipt failed checker grammar; separate artifact audit; corrected fresh run pending |
| [PR-chain status](playbooks.md) | `babysit_loop.py` | Reviewed driver; explicit private base chain and existing Bun; one read-only Check only, live unrun |
| [Live worker replacement](workers.md#live-worker-replacement) | `check_workers.py --hot-swap-only` | Two distinct configured execution definitions; owned workspace and in-flight gates |
| [Caller context preflight](controller.md#caller-context-preflight) | `caller_context.py` | Verified live controller pane; read-only Herdr checks, no models |
| [Caller identity](controller.md#caller-identity) | `caller_identity.py` | Run from the controller pane; scratch tab and workspace, no models |
| [Pi integration and startup](pi.md) | `pi_preflight.py`, `pi_startup.py` | Select the reproduced failure; different prerequisites |
| [Upstream update detection](upstream.md) | `check_upstream.py` | Git and network; no models |

This is the map of reproducible drivers, not a claim of complete workflow coverage. The invoice loop drivers do not exercise the original pstack rubric. The playbook driver audits declared original-workflow stages; full workflow eligibility and the 23-playbook inventory remain separate gates. A historical manual `how` run is recorded in [skill-discovery.json](../../../../e2e/evidence/skill-discovery.json). Approval denial, turns longer than 30 minutes, and macOS runtime remain unverified. Historical lifecycle/recovery/completion receipts have no distributed driver.
