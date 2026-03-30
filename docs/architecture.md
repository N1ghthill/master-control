# Architecture

## Purpose

Master Control is a local-first runtime for controlled Linux host operations.
It is designed so multiple interfaces can reuse the same typed capabilities, policy gates, and audit trail.

The architecture favors strong boundaries:

- interface input is untrusted input
- runtime actions flow through typed contracts
- tools are typed execution contracts
- policy decides whether a tool call may proceed
- audit records every meaningful decision and action

During this refactor, older diagrams or planning docs may still show the previous chat-first framing.
The authoritative direction is now runtime-first: the conversational path is an interface, not the center of the product.

## Current goals

- run on a single Linux host
- provide a stable local runtime for bounded host operations
- treat MCP as the main integration interface on top of the runtime
- keep the CLI as the local operator and administration interface
- preserve the existing chat/provider path as an optional interface
- keep an experimental MCP bridge with approval-mediated write flow on top of the same runtime
- persist local state and audit data in SQLite
- keep the codebase modular, but inside one deployable process

## Current non-goals

- autonomous privileged actions
- general package management
- full security auditing or compliance scanning
- multi-user remote deployment
- SaaS or remote control-plane infrastructure
- multi-service orchestration

## High-level components

```text
[Operator / Client]
  |
  v
[MCP | CLI | Chat / Agent]
  |
  v
[Core Runtime]
  |- Tool dispatch
  |- Policy evaluation
  |- Config safety
  |- Validation helpers
  |- Audit persistence
  |- Optional recommendation state
  |
  v
[Policy Engine]
  |
  v
[Tool Registry]
  |
  v
[Executor / OS adapters]
  |
  v
[Linux host]

[SQLite]
  |- sessions
  |- session_summaries
  |- session_recommendations
  |- conversation_messages
  |- observations
  |- audit_events
```

The conversation and provider stack is still part of the repository, but it should be understood as an optional interface path into the runtime, not the foundational layer.

Import-path note:

- `master_control.interfaces.*` is the preferred namespace for interface-owned helpers
- conversational planning, rendering, session-summary, and tool-result helpers now live under `master_control.interfaces.agent.*`
- `master_control.agent.*` remains available as a compatibility namespace during the refactor track

## Flow diagrams

The repository keeps the canonical Mermaid diagrams under `docs/diagrams/`:

- `docs/diagrams/README.md`
- `docs/diagrams/master-control-flow.mmd`
- `docs/diagrams/chat-planning-flow.mmd`
- `docs/diagrams/recommendation-approval-flow.mmd`
- `docs/diagrams/state-audit-flow.mmd`

Primary end-to-end view:

![Master Control flow](diagrams/master-control-flow.svg)

Some diagrams still reflect the earlier chat-first explanation.
Until those assets are refreshed, this document and `docs/core-interfaces-refactor-plan.md` are the authoritative source for architectural direction.

## Request lifecycle

1. An interface receives an operator or client request.
2. The interface normalizes that request into a runtime action, workflow, or planning request.
3. The runtime resolves the requested tool or workflow by typed name and arguments.
4. The policy engine evaluates the requested action.
5. If the action is allowed, the tool executes through controlled adapters.
6. The result and policy decision are written to the audit trail.
7. The interface renders the outcome in its own format, such as CLI text, JSON, or MCP responses.

For the optional chat path, a planner may produce a structured action plan before the runtime step.
That planning layer is still constrained by the same runtime, policy, and audit boundary.

## Core design rules

### 1. Typed tools before shell

The default path is a typed tool, for example:

- `system_info`
- `disk_usage`
- `memory_usage`
- `process_to_unit`
- `failed_services`
- `service_status`
- `read_journal`
- `read_config_file`
- `write_config_file`
- `restore_config_backup`
- `reload_service`
- `restart_service`

Generic command execution is a last-resort capability, not the foundation.

### 2. Core logic must not live inside an interface

- interfaces may request actions in different ways
- the runtime remains the owner of execution, policy, and audit
- a planner or provider must not become the hidden owner of operational correctness

### 3. Structured plans, not free-form reasoning

Where planning is used, the contract is:

- user intent
- plan steps
- tool calls
- approval requirements
- results

The runtime must not depend on hidden reasoning to stay correct.

### 4. Facts must be attributable

Long-lived observations about the host must include:

- source
- timestamp
- optional TTL

This prevents stale or hallucinated system state from becoming trusted memory.

## Deployment model

The recommended runtime is a host-level Python process.
If the experimental MCP bridge or another interface later needs a long-running process, that should be an optional local service, likely managed by `systemd`, not a platform pivot.

Container deployment is intentionally deferred because deep host integration, file access, and service management are harder to secure and reason about from a privileged container.

For lightweight background upkeep on a single host, the repository can also render and install an optional `systemd` timer that runs `mc reconcile --all`. This remains intentionally bounded to recommendation maintenance, not arbitrary autonomous host mutation.

## Persistence model

SQLite is enough for the current product stage:

- `sessions`: chat sessions
- `session_summaries`: compact session memory derived from recent turns and tool results
- `session_recommendations`: explicit queue of operational recommendations, statuses, and optional action metadata
- `conversation_messages`: user and agent messages
- `observations`: system facts with source and freshness metadata
- `audit_events`: policy evaluations, tool executions, errors

The database must be local to the host and easy to inspect for debugging.

Latest observations are session-scoped and TTL-bound. This lets the app distinguish between a fresh fact that can be summarized safely and a stale fact that should be refreshed through a typed tool before the planner relies on it.

At runtime, the app derives structured session context from observations, tracked entities, and recommendation state. The compact summary remains useful for inspection and carry-forward state, but high-risk decisions should prefer structured context instead of reparsing summary text.

## Proactive guidance

The app can derive deterministic session insights from structured session context plus observation freshness. This allows MC to surface operational suggestions, such as disk pressure or unhealthy service state, without asking the user to restate all prior context.

These suggestions are then synchronized into a persistent recommendation queue, so the operator can track whether each item is still open, accepted, dismissed, or resolved.

When an insight maps cleanly to a safe operational action, the recommendation can also carry a typed action envelope such as `restart_service(name=...)`. Execution still does not happen automatically: the recommendation must first be accepted, then the action must pass the same policy and confirmation gates as any direct tool invocation.

For service-oriented actions, MC now requires explicit service evidence from the request, tracked context, or a matching service observation. A hot process alone is not enough to expose `restart_service`, and the tracked `systemd` scope is treated as part of the target identity.

## Interfaces

### CLI

The CLI is the local operator and administration interface.
It should remain fully capable of inspection, validation, and controlled execution without requiring any remote provider.

### Chat / agent path

The chat path remains available for natural-language interaction.
Its planners, providers, summaries, and rendering helpers are interface logic, not the product center.

### MCP

An experimental MCP stdio bridge now exists with approval-mediated write operations.
It is the main integration interface for exposing runtime capabilities to external AI clients without duplicating policy, audit, or execution logic.
Broader capability exposure remains intentionally deferred until the runtime boundary is easier to own.

## Evolution path

The next safe increments are:

1. finish the runtime-first documentation and boundary refactor
2. make core ownership clearer in the codebase without breaking the validated alpha path
3. harden the experimental MCP bridge without overexpanding its surface
4. continue service mode only when it clearly serves the runtime and interface model

## Current provider path

The repository currently supports three planning paths for the optional agent interface:

- `heuristic`: local rules-based planning for offline development and bootstrap
- `openai`: remote planning through the Responses API, constrained to a single required function that returns a structured plan
- `ollama`: local structured planning through `/api/chat` with a strict JSON schema

These planning paths are layered on top of the same execution boundary.
