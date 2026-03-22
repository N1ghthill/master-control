# Roadmap

Snapshot date: 2026-03-22

## Current stage

- late alpha
- public pre-release `v0.1.0a2` is out
- the alpha baseline is validated on the maintainer host and on a dedicated Debian 13 VPS lab
- the runtime already supports bounded inspection, controlled service/config actions, auditability, and validation workflows
- the main roadmap change is not "add more AI"; it is to make the product center match the value already present in the runtime
- the active track is now the runtime-first refactor described in `docs/core-interfaces-refactor-plan.md`

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

## Phase 1: Bounded runtime capabilities

Status:

- Completed for the current alpha slice

Deliverables:

- typed host inspection tools
- structured and testable tool outputs
- audit persistence
- local state persistence
- safe operator-facing CLI entry points

Result:

- exit criteria met for the current alpha scope

## Phase 2: Controlled mutations and operator trust

Status:

- Completed for the current alpha slice

Deliverables:

- confirmation flow for mutating tools
- config write helpers with backup and validation
- service restart and reload tools
- clearer operator approval prompts

Result:

- the current service and config mutation boundary is implemented and evidence-backed

## Phase 3: Alpha baseline and validation

Status:

- Completed

Deliverables:

- narrow local CLI alpha baseline
- repeatable bootstrap validation
- release-facing docs and evidence
- second real-host validation evidence

Result:

- the current alpha baseline is validated and publicly present as `v0.1.0a2`

## Phase 4: Runtime-first repositioning

Status:

- In progress, with the first code-boundary slices already landed

Goal:

- reposition MC around its runtime value instead of its conversational framing

Deliverables:

- rewritten canonical docs around the runtime-first contract
- explicit `core` versus `interfaces` ownership in the codebase
- reduced architectural centrality of the current agent/provider path
- preserved alpha baseline while boundaries are clarified

Exit criteria:

- the canonical docs describe MC as a runtime with interfaces
- core ownership is clearer in code than it is today
- the repository is easier to explain and maintain than the current chat-centric shape

## Phase 5: MCP interface

Status:

- In progress for the first experimental read-only slice

Deliverables:

- first experimental MCP interface on top of the existing runtime
- same policy and audit path as the CLI
- local-first activation and administration guidance

Exit criteria:

- MCP does not duplicate business logic already owned by the runtime
- MCP remains an interface, not a second product

## Phase 6: Service mode and broader interfaces

Status:

- Not started

Deliverables:

- optional local service mode where justified by MCP or other interfaces
- any further interface additions that still reuse the same runtime boundary
- richer observability

Exit criteria:

- interface layer remains separate from execution core
- all external interfaces reuse the same policy and audit paths

## Next roadmap focus

The immediate roadmap track is:

1. finish the canonical documentation rewrite around the runtime-first contract
2. introduce clearer `core` and `interfaces` ownership in the codebase
3. keep the current operator bootstrap and validation path stable while code moves
4. harden the current experimental MCP bridge before expanding it
5. postpone broader service mode and additional interfaces until the runtime contract is easier to own

Historical milestone sequencing remains recorded in `docs/mvp-evolution-plan.md`, `docs/mvp-closeout-backlog.md`, `docs/post-mvp-evolution-plan.md`, and `docs/beta-resume-plan.md`.
The current authoritative refactor brief is `docs/core-interfaces-refactor-plan.md`.
