# Roadmap

Snapshot date: 2026-03-17

## Current stage

- late alpha
- foundation, read-only inspection, session memory, provider integration, recommendation tracking, and first mutation workflows are in place
- MVP closeout now depends mostly on release hardening and packaging hygiene
- the current local alpha profile is `qwen2.5:7b`

## Phase 0: Foundation

Status:

- Completed

Deliverables:

- repository structure
- architecture and security documents
- ADRs for major early decisions
- Python package bootstrap
- local SQLite initialization
- policy engine and initial tool registry

## Phase 1: Read-only Linux introspection

Deliverables:

- `disk_usage`
- `memory_usage`
- `top_processes`
- `service_status`
- `read_journal`
- chat loop wired to a provider abstraction

Status:

- Completed for the narrow MVP slice

Current state:

- read-only tools are implemented
- the chat loop is wired to a structured heuristic provider
- an OpenAI Responses API provider is implemented
- multi-turn session context is persisted locally
- provider continuation state is persisted when supported
- audit events are stored for each execution

Exit criteria:

- tool outputs are structured and testable
- all tools have clear risk levels
- audit events are persisted for each execution

Result:

- Exit criteria met

## Phase 2: Safe mutations

Status:

- Complete for the narrow MVP slice, pending release hardening

Deliverables:

- confirmation flow for mutating tools
- config write helpers with backup and validation
- service restart and reload tools
- approval prompts in the CLI

Current state:

- `restart_service` is implemented as the first privileged tool
- `reload_service` is implemented as a lower-risk service action
- service tools can target either system scope or `systemd --user` through `scope=user`
- direct tool execution and recommendation actions both require explicit confirmation
- recommendation actions cannot execute until the recommendation is accepted
- managed config read, write, validation, backup, and restore are implemented for bounded targets

Remaining:

- optional UX polish discovered during host validation

Exit criteria:

- no mutation happens without a visible policy decision
- rollback paths exist for config changes

## Phase 3: Memory and provider integration

Status:

- In progress

Deliverables:

- session history storage
- observation freshness model
- provider adapters for local and remote LLMs
- structured plan generation

Exit criteria:

- provider output is schema-bound
- stale observations can be detected and refreshed

Current state:

- session history storage is implemented
- observation freshness is now active in the operator flow
- provider output is schema-bound
- OpenAI, Ollama, and heuristic providers are wired to the same planning contract
- the app can re-plan within the same turn using execution observations from earlier steps
- session-scoped observations are persisted with TTL metadata and passed to planners as freshness context
- stale recommendations now prefer refresh actions over risky follow-up actions
- `qwen2.5:7b` is the current default local Ollama profile for the alpha track

## Phase 4: Service mode and external interfaces

Status:

- Not started

Deliverables:

- long-running daemon mode
- HTTP or websocket API
- web UI or chat integrations
- richer observability

Exit criteria:

- interface layer is separate from execution core
- all external interfaces reuse the same policy and audit paths

## MVP closeout focus

The next careful steps are:

1. prepare an alpha release baseline
2. decide whether to freeze the narrow MVP or polish approval UX further
