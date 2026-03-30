# Roadmap

Snapshot date: 2026-03-30

## Current Direction

- late alpha, pre-1.0
- validated alpha baseline published as `v0.1.0a2`
- runtime-first and MCP-first product direction
- runtime already supports bounded inspection, controlled service/config actions, auditability, and validation workflows
- a first operator-configurable policy slice now exists through versioned TOML
- standard-client MCP validation now exists through the official Inspector CLI
- approval concurrency now deduplicates active envelopes and blocks duplicate in-flight execution
- the public repository baseline now includes Apache-2.0 licensing, governance docs, working `pre-commit`, Bandit, Dependabot, and protected `main` status checks
- current priority is to mature the runtime and MCP path into a trustworthy operational interface

## Phase 1: Controlled MCP Write Path

Status:

- Current focus

Goal:

- make MCP the primary controlled interface for both inspection and bounded mutation

Deliverables:

- runtime integration coverage for the main read and write flows
- MCP read-write contract with explicit approval lifecycle
- documented and validated operator-configurable policy model
- thinner runtime ownership boundaries between core and interfaces

Exit criteria:

- MCP can execute bounded mutations through the same runtime path as CLI
- approval is explicit, auditable, and machine-tractable for MCP clients
- policy is configurable without code changes for managed boundaries
- runtime integration evidence exists for the main mutation paths

## Phase 2: Trusted Daily Host Operations

Status:

- Not complete

Goal:

- make the runtime trustworthy enough for daily single-host operational work

Deliverables:

- broader safe tool surface for daily host administration
- explicit concurrency and state-integrity model
- semantic versioning and tool-schema compatibility rules
- stronger operational validation and diagnostics

Exit criteria:

- the runtime can be trusted for routine single-host operational work
- concurrent calls do not corrupt state or bypass approval
- tool schemas have defined compatibility rules
- new tool domains follow the same typed, policy-gated, auditable contract

## Phase 3: Optional Planning And Secondary Interfaces

Status:

- Later phase

Goal:

- restore planner and conversational UX as optional layers over a stable MCP-first runtime

Deliverables:

- refreshed heuristic, OpenAI, and Ollama support on top of the stabilized runtime
- chat as a secondary interface over the same approval and audit model
- documentation and validation that keep MCP as the primary external interface

Exit criteria:

- planner and chat layers remain optional
- they improve convenience without owning safety semantics
- MCP remains the product center in architecture, docs, and validation

## Near-Term Execution Order

1. define tool-schema compatibility rules and release policy in issue #17
2. continue core/interface cleanup in issue #18
3. reduce install and distribution friction beyond source checkout in issue #21
4. simplify the operator journey around primary workflows in issue #19
5. broaden client and host validation evidence in issue #2
6. keep `github/codeql-action` updates manual until the Dependabot failure tracked in issue #20 is resolved

## Out Of Scope For This Track

- unrestricted shell access
- multi-user auth and remote control-plane work
- SaaS orchestration
- large UI work
- service-mode expansion before the single-process runtime model is solid

## Historical Records

Earlier MVP, alpha, and beta-prep planning documents remain in the repository for traceability.
They are not the current roadmap.
Use `docs/runtime-mcp-maturation-plan.md` for the detailed execution plan behind this roadmap.
