# Core + Interfaces Refactor Plan

Snapshot date: 2026-03-22

## Purpose

This document is the canonical working brief for the current Master Control refactor.

Its job is to preserve the full strategic and technical context for a multi-commit migration that may touch code, documentation, packaging posture, repository layout, and product positioning.

During this refactor, if older planning documents still describe the previous AI-first framing, this document takes precedence for refactor decisions until the canonical docs are rewritten.

## Why this refactor exists

Master Control is currently over-indexed on conversational-agent framing relative to the practical value it delivers.

The project already contains substantial engineering work:

- typed tools
- policy and approval gates
- audit trail
- managed config safety
- recommendation tracking
- provider integrations
- session context and observation freshness
- validation harnesses
- install and uninstall paths

But the real delivered value is narrower than the surrounding architecture suggests.

The current mismatch is:

- high internal complexity
- high maintenance cost
- high explanation cost for new users
- relatively narrow real operator utility

The strongest conclusion from the current state is that MC's real value does not come from "being the AI". It comes from being the safe runtime that exposes bounded Linux capabilities with policy, auditability, and predictable execution.

That means the current AI-first framing is no longer the best fit for the product.

## Baseline snapshot before refactor

As of 2026-03-22:

- project stage: late alpha
- public release posture: GitHub pre-release `v0.1.0a2`
- install posture: source checkout plus `install.sh`
- package posture: no `.deb` package yet, and `.deb` is not the current priority
- host scope: single-host, local-first
- validation posture: `ruff`, `mypy`, `unittest`, `pytest`, `compileall`, `mc doctor`, bootstrap validation, and dedicated Debian 13 VPS lab validation all exist
- repository posture: local `main` and `origin/main` are aligned
- privacy posture: public repository cleanup has already been performed; private VPS coordinates and internal-only access details must remain out of public docs and release surfaces

This refactor starts from a clean, published, evidence-backed alpha baseline. It is not a rescue from a broken branch. It is a deliberate repositioning and simplification effort.

## Strategic decisions already made

These decisions are considered locked unless a later explicit decision supersedes them:

- keep one repository
- keep one product identity: `Master Control`
- do not split into separate `core` and `mcp` repositories now
- treat `MCP` as an interface, not as a separate product
- keep infrastructure local-first and single-host-first
- keep the CLI as a first-class operator and administration interface
- move the conversational/LLM path out of the product center
- treat chat, planners, and providers as optional interfaces on top of the runtime
- do not expand scope into package management, full security auditing, multi-host orchestration, or SaaS infrastructure during this refactor
- do not prioritize a `.deb` package until the runtime contract is more stable

## Product position after refactor

The target positioning is:

Master Control is a local-first runtime for controlled Linux host operations, with typed capabilities, approval boundaries, and auditability.

More concrete wording:

- MC is not primarily "the AI"
- MC is the safe capability layer
- CLI, MCP, and chat are interfaces to that capability layer

### What MC should clearly be

- a runtime for bounded Linux inspection and controlled actions
- a policy and audit boundary for host operations
- a reusable capability layer for deterministic clients and AI clients
- a single-host operational tool with strong execution contracts

### What MC should not claim to be

- a general autonomous Linux administrator
- a full security auditing suite
- a package management front-end
- a production multi-host orchestration platform
- a product whose main value is raw conversational UX

## Target architecture

The target architecture is a modular monolith with a clearer center of gravity.

```text
master_control/
  core/
    tools/
    policy/
    executor/
    store/
    config/
    validation/
    audit/
    runtime/
  interfaces/
    cli/
    mcp/
    agent/
  shared/
    schemas/
    rendering/
```

This does not need to land in one move.

The real architectural rule is:

- `core` owns capabilities, policy, persistence, and safe execution
- `interfaces` adapt the core to a user or client entry point
- no interface should become the hidden owner of core business logic

## Current-to-target code mapping

The current codebase already contains many of the right building blocks, but their ownership is not yet explicit enough.

### Core candidates

These areas represent the stable value of the product and should remain central:

- `src/master_control/tools/`
- `src/master_control/policy/`
- `src/master_control/executor/`
- `src/master_control/store/`
- `src/master_control/config_manager.py`
- `src/master_control/bootstrap_validation.py`
- `src/master_control/bootstrap_prereqs.py`
- `src/master_control/host_validation.py`
- `src/master_control/validation_bundle.py`

### Interface candidates

These areas should be treated as interfaces or interface-adjacent logic:

- `src/master_control/cli.py`
- future `src/master_control/interfaces/mcp/`
- `src/master_control/agent/`
- `src/master_control/providers/`

### Composition hotspot

`src/master_control/app.py` is currently the main composition and orchestration hotspot.

It should stop being the implicit product center.
Over time it should be split so that:

- core orchestration becomes runtime-oriented
- CLI concerns move behind a CLI boundary
- agent/chat concerns move behind an agent interface boundary

## Known hotspots and refactor pressure points

The current largest or most complex modules are useful signals for where refactor pressure is highest:

- `src/master_control/providers/heuristic.py` at about 3189 lines
- `src/master_control/app.py` at about 1326 lines
- `src/master_control/cli.py` at about 736 lines
- `src/master_control/agent/session_context.py` at about 708 lines
- `src/master_control/agent/session_insights.py` at about 630 lines
- `src/master_control/agent/tool_result_views.py` at about 594 lines
- `src/master_control/providers/openai_responses.py` at about 557 lines
- `src/master_control/providers/ollama_chat.py` at about 496 lines

These files should be treated as likely decomposition targets, not as the best long-term ownership boundaries.

## Refactor status

Current state of execution:

- the canonical documentation reset has landed in the working tree
- shared planning and observation contracts have moved out of `agent` ownership into `shared/` and `core/`
- `src/master_control/core/runtime.py` now exists as the runtime-oriented composition layer
- `src/master_control/app.py` is now a compatibility facade over runtime plus chat interface
- the CLI now resolves through `src/master_control/interfaces/cli/entrypoint.py`
- host validation now targets `core.runtime` plus the chat interface instead of the legacy app facade
- an initial experimental read-only MCP stdio bridge exists under `src/master_control/interfaces/mcp/`
- the current working tree remains green on `ruff`, `mypy`, `pytest`, `unittest`, and `mc doctor`

## Engineering assessment

This refactor is justified by the current engineering profile of the repository, not only by product narrative.

### Current strengths

- the project already has a real runtime, not just an interface demo
- typed tools, bounded execution, and explicit risk levels are already in place
- config safety is one of the strongest parts of the codebase and already behaves like a reusable runtime concern
- install, uninstall, bootstrap validation, host validation, and CI smoke coverage are stronger than typical alpha-stage projects
- the repository has meaningful automated coverage and a repeatable operator path

### Current liabilities

- the architectural center is wrong: conversational orchestration currently owns too much of the perceived product and too much of the implementation shape
- the runtime is not yet independently legible because some core-adjacent modules still depend on `agent` types and helpers
- `MasterControlApp` has become a composition hotspot and a maintenance choke point
- the heuristic planner contains too much product behavior in one large file
- CLI and host-validation flows still couple through the current app facade more than they should
- policy exists and is directionally correct, but it is still relatively shallow for a long-term runtime product

### Engineering conclusion

The project is not overbuilt in the sense of "no real value exists".
It is over-centered on the wrong layer.

The runtime, install path, validation path, and safe tool model are the durable assets.
The refactor should preserve those assets while reducing how much of the repository depends on the agent layer as the default center of gravity.

## Critical structural findings

These findings are the main reasons the refactor must be more than a directory rename:

- `src/master_control/app.py` was a god-object composition layer; it is now a compatibility facade, but the deeper chat split inside `core/runtime.py` is still incomplete
- `src/master_control/store/session_store.py` no longer depends on `agent` ownership for observation freshness and serialization
- `src/master_control/providers/base.py` now consumes `core` and `shared` contracts instead of `agent` contracts, but providers still need clearer interface ownership
- `src/master_control/host_validation.py` now validates through runtime plus chat interface, so the original app-facade coupling has been removed
- `src/master_control/providers/heuristic.py` is large enough that it should be treated as a subsystem, not as a harmless adapter

## Refactor invariants

The following behavior should remain stable while code moves:

- `install.sh` and `uninstall.sh`
- `mc doctor`
- `mc tools`
- `mc tool ...`
- `mc validate-host-profile`
- current recommendation persistence and audit trail behavior
- current test and CI baseline

If a slice cannot preserve these invariants, that slice is too large.

## Infrastructure position

The infrastructure stance for this refactor is intentionally conservative.

### Keep

- local process model
- SQLite
- local filesystem state
- optional `systemd` integration when it helps on-host operation
- single-host execution model

### Avoid

- microservices
- Kubernetes
- a remote control plane
- mandatory cloud dependencies
- multi-tenant or multi-user remote infrastructure
- external API infrastructure before the core contract is stable

### Working assumption

If MCP later needs a long-running process, that should be an optional local service managed on the host, not a platform pivot.

## Documentation strategy

This refactor will touch many documents, but not all of them in the same way.

### Rewrite first

These are the canonical documents that must align early with the new product center:

- `README.md`
- `docs/README.md`
- `docs/architecture.md`
- `docs/status.md`
- `docs/roadmap.md`
- `docs/security-model.md`
- `docs/providers.md`
- `docs/operator-workflows.md`
- `CONTRIBUTING.md`

### Preserve, then reframe as needed

These documents contain useful evidence or historical execution context and should not be deleted casually:

- `docs/alpha-validation-report.md`
- `docs/vps-validation-report.md`
- `docs/vps-validation-runbook.md`
- `docs/history/release-candidate-0.1.0a2.md`
- `docs/history/alpha-release-notes.md`
- `docs/beta-readiness-gate.md`
- `docs/history/beta-resume-plan.md`
- `docs/history/mvp-plan.md`
- `docs/history/mvp-evolution-plan.md`
- `docs/history/mvp-closeout-backlog.md`
- `docs/history/post-mvp-evolution-plan.md`
- `docs/community-host-validation.md`
- `docs/host-profile-validation.md`

### Documentation rule during this refactor

Do not delete context until its replacement is written and linked.

## Privacy and publication constraints

This repository has already gone through a public-surface cleanup.
That standard must hold during the refactor.

Never publish:

- private VPS IP addresses
- private hostnames
- internal-only paths from the lab environment
- internal SSH commands that expose private lab access
- secrets, tokens, or real credentials

Validation evidence is still valuable, but it must remain sanitized for public surfaces.

## Execution principles

These are the working rules for the refactor itself:

- preserve behavior before expanding behavior
- prefer boundary clarification over feature growth
- keep commit slices small and defensible
- keep the repo installable during the migration
- do not let docs drift silently from the new direction
- keep public claims narrower than validated capability
- do not add a second architectural center while trying to remove the first one

## Proposed execution phases

### Phase 1: Narrative and contract reset

Goal:

- move the product story from AI-first agent to safe runtime plus interfaces

Deliverables:

- rewritten canonical docs
- updated architecture language
- explicit statement that CLI and MCP are first-class interfaces
- explicit statement that chat/providers are optional interfaces

### Phase 2: Package and boundary refactor

Goal:

- make the code layout match the new ownership model without a major behavior change

Deliverables:

- `core` package skeleton
- `interfaces` package skeleton
- moved or wrapped stable runtime modules under core ownership
- thinner composition path in place of the current central `app.py` hotspot

### Phase 3: Agent isolation

Goal:

- make chat, planners, session narrative helpers, and providers depend on the core instead of acting as the product center

Deliverables:

- agent code behind an explicit interface boundary
- providers behind the agent interface boundary
- reduced reverse coupling from runtime code into conversational code

### Phase 4: MCP interface

Goal:

- expose selected runtime capabilities through MCP using the same policy and audit path as the CLI

Deliverables:

- initial MCP interface implementation
- documentation for local activation and scope
- explicit statement of which capabilities are MCP-safe in the first iteration

### Phase 5: Cleanup and retirement

Goal:

- remove obsolete naming, stale docs, and compatibility shims that no longer help

Deliverables:

- retired AI-first wording from canonical docs
- old migration shims removed when safe
- diagrams refreshed
- planning artifacts reduced once the new baseline is stable

## Commit-slice execution plan

The refactor should be executed as small compatibility-preserving slices.

### Slice 1: Documentation reset

Goal:

- align the public and canonical story with the runtime-first direction

Expected files:

- `README.md`
- `docs/README.md`
- `docs/architecture.md`
- `docs/status.md`
- `docs/roadmap.md`
- `docs/security-model.md`
- `docs/core-interfaces-refactor-plan.md`

Validation:

- `git diff --check`

Status:

- already in progress in the current working tree

### Slice 2: Package skeleton and compatibility seams

Goal:

- introduce the target ownership model without behavior change

Expected work:

- add `src/master_control/core/`
- add `src/master_control/interfaces/`
- add minimal `__init__.py` modules and compatibility comments
- do not move large files yet

Validation:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m pytest -q`

### Slice 3: Neutral shared contracts

Goal:

- move shared runtime contracts out of `agent`

Expected work:

- extract planning structures to a neutral runtime-owned location
- extract observation freshness and observation serialization helpers to a runtime-owned location
- update imports in store, providers, app, and agent modules
- leave compatibility re-exports from the old `agent` modules temporarily

Why this comes first:

- this is the smallest code slice that reduces architectural dishonesty without forcing large runtime rewrites

Validation:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m pytest -q`

### Slice 4: Runtime facade extraction

Goal:

- reduce `MasterControlApp` so it stops being the implicit owner of non-chat behavior

Expected work:

- introduce a runtime-oriented service or facade under `core`
- move bootstrap, tool execution, doctor, audit, timer, and tool-listing behavior behind that service
- keep `MasterControlApp` as a compatibility facade that delegates instead of owning everything directly

Validation:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m pytest -q`
- `PYTHONPATH=src python3 -m master_control --json doctor`

### Slice 5: CLI thinning

Goal:

- turn the CLI into a thin interface over the runtime

Expected work:

- update CLI command handlers to target runtime-owned services
- keep chat handling behind an explicit agent entry point
- avoid adding new CLI-only logic during the move

Validation:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m pytest -q`
- `PYTHONPATH=src python3 -m master_control --json doctor`

### Slice 6: Agent isolation

Goal:

- make chat orchestration depend on the runtime instead of the reverse

Expected work:

- move chat orchestration behind an explicit interface-facing service
- shrink `MasterControlApp` into a legacy facade or retire it if replacement coverage is sufficient
- reduce direct runtime dependence on `agent` helpers

Validation:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m pytest -q`
- `PYTHONPATH=src python3 -m unittest discover -s tests`

### Slice 7: Provider relocation and cleanup

Goal:

- make providers clearly belong to the agent interface path

Expected work:

- move provider modules behind the agent interface boundary
- keep compatibility imports until the tree is stable
- reduce the number of runtime-owned modules that import provider types directly

Validation:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m pytest -q`

### Slice 8: MCP introduction

Goal:

- add MCP only after the runtime boundary is clearer

Expected work:

- implement an initial MCP interface on top of the runtime
- expose only a deliberately small, safe capability set in the first iteration
- reuse the same policy and audit path already used by the CLI

Validation:

- existing baseline
- targeted MCP integration tests once the interface exists

## Immediate next code slice

The next correct code slice is now cleanup and consolidation after the initial landing.

That means:

1. keep compatibility re-exports in place only where they still protect public entry points
2. reduce legacy app/runtime duplication without breaking the validated alpha path
3. harden the current experimental read-only MCP bridge before expanding it
4. continue moving agent-specific ownership out of runtime-facing modules

This is the smallest sequence that produces further architectural progress without destabilizing the validated alpha path.

## Immediate working assumptions

These assumptions are good enough to proceed unless refactor evidence contradicts them:

- recommendation persistence may stay near the core if it represents operator work state, but recommendation generation logic should not force the whole runtime to remain agent-centric
- `mc chat` should remain supported during the transition, but it should stop being the primary way the product is explained
- provider auto-selection can remain for compatibility during the transition, but it is no longer a centerpiece of the product story
- the `systemd` reconcile timer remains a secondary operational helper, not the product center

## Risks and controls

### Risk: architecture churn without value

Control:

- each phase must make the product easier to explain or the code easier to own

### Risk: breaking a validated alpha while moving modules

Control:

- preserve behavior first
- rerun baseline checks after meaningful slices

### Risk: documentation cleanup deleting important history

Control:

- preserve validation and release evidence until replacement docs are established

### Risk: private lab details leaking back into the public tree

Control:

- treat all lab-specific coordinates as private by default

### Risk: keeping too much of the old agent-centric story alive

Control:

- rewrite canonical docs before deep code cleanup finishes

### Risk: fake modularization

Control:

- do not count package renames as progress unless imports and ownership boundaries genuinely improve

### Risk: extracting the wrong contracts first

Control:

- move neutral shared types before moving orchestration-heavy modules

### Risk: breaking the operator path while cleaning architecture

Control:

- keep `install.sh`, `mc doctor`, `mc validate-host-profile`, and the bootstrap harness green throughout the refactor

## Definition of done for the refactor

This refactor is not done when files merely move.

It is done when:

- the canonical documentation describes MC as a runtime with interfaces, not primarily as an AI-first conversational agent
- the core runtime can be understood independently of chat and providers
- CLI and MCP both operate through the same runtime, policy, and audit boundaries
- agent and provider code are clearly optional layers on top of the core
- the repository stays single-host-first and local-first
- validation evidence remains intact and sanitized
- the codebase becomes easier to explain, maintain, and extend than it is today

## Exit condition for the current planning stage

This document is sufficient to start the code refactor when:

- the documentation reset slice is committed
- the next branch or commit series starts with Slice 2 and Slice 3
- compatibility-preserving validation is treated as mandatory, not optional
