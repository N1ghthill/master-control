# Architecture

## Purpose

Master Control is a conversational Linux agent that helps inspect, explain, and eventually change a host system in a controlled way.

The architecture favors strong boundaries:

- Conversation is untrusted input
- Plans are structured data
- Tools are typed execution contracts
- Policy decides whether a tool call may proceed
- Audit records every meaningful decision and action

## MVP goals

- Run on a single Linux host
- Provide a CLI-first conversational interface
- Expose read-only system inspection tools
- Persist local state and audit data in SQLite
- Keep the codebase modular, but inside one deployable process

## MVP non-goals

- Autonomous privileged actions
- Multi-user remote deployment
- Voice interface
- Vector memory
- Container-first deployment
- Multi-service orchestration

## High-level components

```text
[User]
  |
  v
[CLI / Future UI]
  |
  v
[Agent App]
  |- Context assembly
  |- Provider adapter
  |- Planner contract
  |- Tool selection
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
  |- messages
  |- observations
  |- audit_events
```

## Request lifecycle

1. User sends a message through the CLI.
2. The agent builds context from the current session, local observations, and available tools.
3. A provider produces a structured plan. The current scaffold uses a heuristic provider as the first safe implementation of that contract.
4. The app resolves the requested tool by name.
5. The policy engine evaluates the tool risk.
6. If the action is allowed, the tool executes through controlled adapters.
7. The result and policy decision are written to the audit trail.
8. The user receives a natural-language or JSON response.

## Core design rules

### 1. Typed tools before shell

The default path is a typed tool, for example:

- `system_info`
- `disk_usage`
- `memory_usage`
- `service_status`
- `read_journal`
- `read_config_file`
- `write_config_file`
- `restore_config_backup`
- `reload_service`
- `restart_service`

Generic command execution is a last-resort capability, not the foundation.

### 2. Structured plans, not free-form reasoning

The system contract is:

- user intent
- plan steps
- tool calls
- approval requirements
- results

The agent should not depend on hidden reasoning to stay correct.

### 3. Facts must be attributable

Long-lived observations about the host must include:

- source
- timestamp
- optional TTL

This prevents stale or hallucinated system state from becoming trusted memory.

## Deployment model

For the MVP, the recommended runtime is a host-level Python process. A future production path can add a `systemd` unit.

Container deployment is intentionally deferred because deep host integration, file access, and service management are harder to secure and reason about from a privileged container.

## Persistence model

SQLite is enough for the first milestone:

- `sessions`: chat sessions
- `session_summaries`: compact session memory derived from recent turns and tool results
- `session_recommendations`: explicit queue of operational recommendations, statuses, and optional action metadata
- `conversation_messages`: user and agent messages
- `observations`: system facts with source and freshness metadata
- `audit_events`: policy evaluations, tool executions, errors

The database must be local to the host and easy to inspect for debugging.

## Proactive guidance

The app can derive deterministic session insights from the persisted summary. This allows MC to surface operational suggestions, such as disk pressure or unhealthy service state, without asking the user to restate all prior context.

These suggestions are then synchronized into a persistent recommendation queue, so the operator can track whether each item is still open, accepted, dismissed, or resolved.

When an insight maps cleanly to a safe operational action, the recommendation can also carry a typed action envelope such as `restart_service(name=...)`. Execution still does not happen automatically: the recommendation must first be accepted, then the action must pass the same policy and confirmation gates as any direct tool invocation.

## Evolution path

After the read-only CLI is stable, the next safe increments are:

1. Mutating tools with diff, backup, validation, and confirmation
2. Richer LLM provider integration with multi-turn context and provider-specific optimizations
3. Service mode and API layer
4. Multi-interface support

## Current provider path

The repository now supports two planning paths:

- `heuristic`: local rules-based planning for offline development and bootstrap
- `openai`: remote planning through the Responses API, constrained to a single required function that returns a structured plan

This keeps the execution boundary stable regardless of which planner is active.
