# Runtime + MCP Maturation Plan

Snapshot date: 2026-03-23

## Purpose

This document is the canonical working plan for the next Master Control maturation track.

It translates the current runtime-first architecture into a practical execution order aimed at the next durable product outcome:

Master Control should become a safe, auditable MCP runtime for Linux host inspection and controlled mutation, with optional planning layers on top.

This plan does not replace `docs/status.md`.
It does not replace the historical alpha and MVP records.
It defines the next ordered path so the project does not drift between runtime work, MCP work, and optional agent work.

## Current Baseline

As of this snapshot, MC already has:

- a real runtime with typed tools, policy checks, confirmation gates, audit events, SQLite state, and bounded execution
- operator-facing CLI flows for inspection, recommendation handling, managed config changes, and host validation
- an experimental MCP bridge with approval-mediated write flow over the same runtime
- repeatable local validation through lint, typecheck, tests, compile checks, bootstrap validation, and host-profile validation
- optional heuristic, OpenAI, and Ollama planning paths layered on top of the runtime

The current codebase also still has clear limits:

- the MCP write path now exists through persisted approvals, but real-client validation and broader contract hardening are still pending
- the runtime still carries chat-oriented orchestration inside `core.runtime`
- a first operator-configurable policy slice now exists through versioned TOML, but broader validation and operator guidance are still pending
- the tool contract does not yet have explicit schema-version governance
- concurrency and multi-call behavior are only partially addressed through SQLite WAL and bounded subprocesses, not through a complete runtime concurrency model
- real-host validation exists, but deeper integration coverage for runtime mutation paths and MCP write flows is not yet the main center of the test strategy

## Product Goal

The target product shape is:

1. MCP is the primary external interface
2. the runtime remains the owner of execution, policy, approval, audit, and state
3. mutating host operations remain bounded, typed, and explicitly approved
4. operator policy can be configured without code edits
5. chat and planner providers remain optional interfaces over the same runtime

In plain terms:

- MC should not expose a general shell
- MC should expose a safe operational capability layer
- MCP clients should be able to inspect the host and apply controlled changes through that layer
- every risky step should remain attributable, reviewable, and reversible where possible

## Execution Order

The maturation order for this track is:

1. make the runtime and MCP write path safe, testable, and operator-configurable
2. make the runtime broader and trustworthy enough for daily host administration on a single host
3. reactivate planning and chat as optional accelerators on top of a stable MCP-first core

This order is intentional.
If MC expands tools or agent UX before the MCP write path, policy model, and runtime validation are hardened, complexity will grow faster than trust.

## Strategic Invariants

The following constraints remain fixed through this plan:

- typed tools before generic shell execution
- explicit approval for mutating or privileged actions
- one runtime, reused by CLI, MCP, and chat
- single-host and local-first first
- SQLite remains acceptable until concurrency or scale proves otherwise
- every external interface must reuse the same policy and audit paths
- optional provider work must not weaken runtime guarantees

## Phase 1: Controlled MCP Write Path

Status:

- Not complete

Goal:

- harden the experimental MCP bridge into a controlled read-write MCP interface that still preserves policy, approval, and audit guarantees

Why this phase is first:

- this is the heart of the product value
- until MCP can mutate safely through the runtime, the current architecture is only partially realized

### Workstream 1.1: Runtime-centered integration validation

Required outcomes:

- define a first-class integration test matrix for runtime operations
- cover both read and write paths against a real host or controlled containerized target where appropriate
- keep unit coverage, but stop treating it as enough evidence for runtime trust

Required coverage slices:

- read-only host inspection: `system_info`, `disk_usage`, `memory_usage`, `top_processes`, `process_to_unit`, `service_status`, `failed_services`, `read_journal`
- managed file reads and writes within policy-managed targets
- backup and restore paths for managed config
- approval-gated service reload and restart
- audit trail persistence for allowed, denied, pending-confirmation, and executed actions
- failure-mode validation for invalid arguments, denied paths, missing confirmation, validator failure, and command timeout paths

Execution model:

- keep fast unit tests for pure logic
- add integration suites for runtime contracts
- use a layered validation strategy:
  - local fast integration tests with temporary managed targets
  - container-backed integration tests for repeatable service/config scenarios
  - real-host smoke validation for `systemd` and host-specific paths that containers cannot model cleanly

Artifacts to add:

- runtime integration test guide
- container or fixture harness for integration scenarios
- explicit CI split between unit coverage and runtime integration coverage

### Workstream 1.2: MCP read-write contract with approval

Current progress:

- persisted tool approvals are now part of the runtime state model
- the experimental MCP bridge now exposes controlled write requests plus `approvals/list|get|approve|reject`
- approval lifecycle coverage exists at unit and runtime-contract level

Required outcomes:

- extend the MCP surface from read-only to controlled read-write
- preserve the same runtime `run_tool` policy and confirmation flow
- make approval explicit and machine-tractable for MCP clients

Required MCP behavior:

- read-only tools may execute immediately
- mutating and privileged tools must not execute on the first unsafe request
- MCP responses must return a structured pending-approval payload instead of silently failing or silently executing
- approval must be attributable to a pending action, not just to a repeated raw request

Recommended approval contract:

- add explicit pending approval state in MCP responses
- add a small approval workflow surface such as:
  - `approvals/list`
  - `approvals/get`
  - `approvals/approve`
  - `approvals/reject`
- bind each pending action to an approval id plus a normalized action envelope
- include operator-facing evidence in the approval payload:
  - requested tool
  - normalized arguments
  - risk class
  - policy decision
  - execution summary preview
  - rollback or follow-up hints when available

Implementation rule:

- approval is a runtime concept exposed through MCP
- MCP must not invent its own policy logic

Interoperability target:

- `mc mcp-serve` can be used from a standard MCP client
- a client such as Claude Desktop can inspect the host and complete an approval-mediated mutation flow without unrestricted shell access

### Workstream 1.3: Operator-configurable policy model

Current progress:

- versioned TOML policy loading now exists
- a missing policy file falls back to the default safe policy
- invalid policy fails closed and is surfaced through `mc doctor`

Required outcomes:

- move policy configuration out of code for operator-owned boundaries
- document the policy model clearly enough that an operator can change allowed targets and approval rules without editing Python

Recommended configuration shape:

- versioned TOML policy files under the MC state or config directory
- separate policy domains for:
  - tool enablement
  - risk overrides only where explicitly allowed
  - managed file targets and validators
  - service scopes and allowlisted units where needed
  - package/network/user-management domains when those tools are added later

Minimum requirements:

- a missing policy file should fall back to a safe default
- invalid policy should fail closed
- policy load errors should be visible through `mc doctor`
- policy changes should be auditable
- docs must explain how to add or narrow managed targets safely

Non-goal for the first slice:

- do not introduce a full RBAC or multi-user authorization system yet

### Workstream 1.4: Core/interface cleanup required for MCP-first ownership

Required outcomes:

- reduce chat ownership inside `core.runtime`
- keep MCP and CLI thin over reusable runtime methods
- continue shrinking `MasterControlApp` into compatibility-only or retirement-ready status

Concrete direction:

- move chat-specific planning and rendering seams out of `core.runtime`
- expose reusable runtime services for:
  - tool execution
  - approval lifecycle
  - recommendation reconciliation
  - audit queries
  - policy diagnostics

### Phase 1 exit criteria

Phase 1 is complete when all of the following are true:

- runtime integration coverage exists for the main read and write flows
- MCP supports controlled write operations through the same runtime path as CLI
- mutating MCP calls produce explicit approval flows instead of direct execution
- operator policy for managed targets is configurable without code changes
- `mc mcp-serve` can be exercised from a real MCP client for diagnostic and controlled mutation flows
- the audit trail captures pending approval, approval decision, execution result, and failure paths

## Phase 2: Trusted Daily Host Operations

Status:

- Not complete

Goal:

- make the runtime reliable enough for daily single-host administration with a broader safe tool surface

Why this phase is second:

- tool breadth without trust will create a large unsafe surface
- once Phase 1 exists, new tools can follow a stable contract instead of inventing new behavior

### Workstream 2.1: Broaden tool coverage by operational domain

Priority order for new tools:

1. package management
2. network inspection and bounded network changes
3. user and group inspection before user mutation
4. filesystem and process maintenance tasks that fit the same safety model

Admission rule for every new tool:

- typed arguments and typed output
- explicit risk classification
- policy and approval integration
- audit integration
- real integration coverage
- operator documentation
- rollback or bounded blast radius where applicable

Examples of likely additions:

- package manager read tools before install/remove tools
- network interface and listening-port inspection before config mutation
- user inspection before account or group changes

Non-goal:

- do not add “raw command execution” as a shortcut for breadth

### Workstream 2.2: Concurrency and state integrity

Required outcomes:

- define the runtime concurrency model explicitly before claiming broader MCP service reliability
- prevent concurrent calls from corrupting state or trampling the same managed target

Current baseline:

- SQLite uses WAL and a busy timeout
- subprocesses are bounded
- this is directionally good, but not yet a complete concurrency model

Required runtime guarantees:

- concurrent reads must remain safe
- concurrent writes to the same managed file must serialize
- concurrent service actions on the same unit must serialize
- approval consumption must be atomic
- recommendation reconciliation and audit writes must not corrupt state under concurrent calls

Recommended implementation direction:

- per-target locks for managed files
- per-service locks for service actions
- transaction boundaries around approval state transitions
- explicit idempotency handling for repeated approval or repeated MCP calls
- concurrency tests that intentionally race write and approval paths

Longer-term note:

- if MCP evolves from stdio to a long-running local service, queueing and worker isolation may become necessary
- that should be added only after the current single-process concurrency model is explicit and tested

### Workstream 2.3: Semantic versioning and tool-schema governance

Required outcomes:

- define what constitutes a breaking change for the runtime and MCP tool surface
- version tool schemas intentionally instead of allowing accidental drift

Required governance:

- stable tool names as long-lived contracts
- explicit schema version metadata for each tool contract
- compatibility rules for adding optional fields, deprecating fields, and changing semantics
- documented release policy connecting runtime versions to tool-schema compatibility

Recommended release rules:

- patch: fixes, no schema break
- minor: backward-compatible tool additions or field additions
- major: breaking schema or behavior changes

Required artifacts:

- schema compatibility policy document
- contract tests for the exposed MCP tool descriptors
- release checklist updates to verify tool compatibility

### Workstream 2.4: Production-oriented validation and observability

Required outcomes:

- improve confidence that MC can be trusted for daily single-host work
- expand evidence from “passes on the maintainer host” to a more deliberate operational validation matrix

Required additions:

- broader host-profile validation scenarios
- failure-injection tests for policy denial, validation failure, lock contention, and restart errors
- operator diagnostics for:
  - policy load state
  - pending approvals
  - lock contention or busy-state reporting
  - version and schema compatibility

### Phase 2 exit criteria

Phase 2 is complete when all of the following are true:

- the MCP tool surface covers the main daily host-administration journeys within the project scope
- concurrent calls do not corrupt runtime state or bypass approval guarantees
- tool schemas are versioned and governed by documented compatibility rules
- the runtime has evidence-backed trust for routine single-host operations
- the operator can rely on MC for daily bounded administration without treating it as an experimental shell proxy

## Phase 3: Optional Planning And Secondary Interfaces

Status:

- Partially present, but not the primary focus

Goal:

- restore planning and conversational UX as optional value-add layers over a stable MCP-first runtime

Why this phase is third:

- the runtime must already be trustworthy on its own
- optional planning should accelerate safe workflows, not define the product core

### Workstream 3.1: Re-center providers as optional planners

Required outcomes:

- keep heuristic, OpenAI, and Ollama support behind the same runtime contract
- ensure provider output can never bypass policy, approval, or audit
- refresh provider docs and tests after MCP-first core work lands

Required rules:

- planner output remains structured
- planner proposes, runtime decides
- planner quality may affect convenience, not safety semantics

### Workstream 3.2: Maintain and improve chat as a secondary interface

Required outcomes:

- keep chat usable for operators who want guided flows
- keep chat thin over runtime and planning seams
- avoid reintroducing chat as the architectural center

Required contract:

- chat should call into the same approval and audit lifecycle as MCP
- approval guidance should remain explicit
- chat-specific rendering should stay out of the runtime core

### Phase 3 exit criteria

Phase 3 is complete when all of the following are true:

- heuristic, OpenAI, and Ollama paths work as optional planners over the same runtime
- chat remains useful without reclaiming core ownership
- MCP remains the primary external interface in docs, validation, and architecture

## Cross-Cutting Validation Strategy

Every phase in this plan should be validated through the same layered evidence model:

1. unit tests for pure logic and formatting
2. integration tests for runtime contracts
3. MCP interoperability tests against the running server
4. real-host or controlled-environment workflow validation
5. release-facing evidence updates

The minimum recurring baseline should continue to include:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m pytest -q`
- `python3 -m compileall src`
- `PYTHONPATH=src python3 -m master_control --json doctor`

Additional validation that should become mandatory for this track:

- runtime integration suite
- MCP interoperability suite
- concurrency suite for approval and mutation paths
- policy configuration load and failure tests

## Recommended Immediate Package Queue

The next clean execution slices are:

1. MCP write-path design package
   define approval lifecycle, MCP method shape, and runtime service seams before broad implementation
2. operator-configurable policy package
   externalize managed target and tool policy into a documented versioned policy file
3. runtime integration harness package
   add container or host-backed integration tests for read/write runtime flows
4. MCP read-write implementation package
   implement the approval-mediated MCP mutation flow
5. concurrency hardening package
   add locking, atomic approval state transitions, and contention tests
6. tool-schema governance package
   define semantic versioning and contract-compatibility rules
7. safe tool-breadth package
   add new admin domains only after the previous packages are stable
8. optional planner reactivation package
   re-harden heuristic, OpenAI, Ollama, and chat as secondary layers

## Sequencing Rules

To avoid losing the plot, follow these rules:

1. do not expand tool breadth before approval-mediated MCP writes exist
2. do not claim production trust before concurrency and policy configuration are explicit
3. do not let chat/provider work block MCP-first core work
4. land every new tool with policy, tests, docs, and audit support in the same change family
5. treat schema compatibility as part of the product contract, not as release polish

## Deferred Until Proven Necessary

The following items remain intentionally deferred during this track:

- unrestricted shell access
- multi-user auth and remote control-plane design
- SaaS orchestration
- broad daemon/service-mode expansion before the current MCP and concurrency model is solid
- large UI work

## Success Definition

This maturation track is successful when MC can truthfully be described this way:

Master Control is a production-trustworthy local runtime for bounded Linux host administration on a single host, exposed primarily through MCP, with explicit approval for risky actions, operator-configurable policy, audited execution, stable tool contracts, and optional planner-backed interfaces layered on top.
