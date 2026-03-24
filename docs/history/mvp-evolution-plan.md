# MVP Evolution Plan

> Historical document
>
> This file is kept as the MVP closeout sequencing record.
> It is not the current product brief or roadmap.
> Use `docs/status.md`, `docs/roadmap.md`, and `docs/runtime-mcp-maturation-plan.md` for current guidance.

Snapshot date: 2026-03-18

## Purpose

This document now serves as the completion record for the delivery plan that closed the narrow local CLI MVP.

It remains the canonical reference for how the repository's closeout documents relate to each other:

- `docs/history/mvp-plan.md`: stable MVP contract and exit criteria
- `docs/history/mvp-evolution-plan.md`: milestone sequencing and completion record
- `docs/history/mvp-closeout-backlog.md`: closed execution backlog record
- `docs/status.md`: current implementation snapshot
- `docs/roadmap.md`: phase-level roadmap beyond the closed MVP

If those documents disagree about MVP sequencing or closeout state, this file should be treated as the source of truth.

## Executive summary

Master Control closed the narrow local CLI MVP on 2026-03-18 with these properties in place:

- typed tools as the execution boundary
- local policy gates and explicit confirmation for risky actions
- auditable execution and recommendation lifecycle
- persistent session context with structured state for the highest-risk paths
- provider abstraction across heuristic, OpenAI, and Ollama
- enough operator utility to make the main CLI workflows materially useful

The core blockers that existed earlier in the alpha cycle are closed for this MVP:

- unsafe process -> service inference
- missing `scope=user|system` preservation across service flows
- high-risk dependence on summary parsing
- insufficient operator evidence and approval guidance
- missing release baseline synchronization

The narrow local alpha baseline is therefore ready for tagging, while broader production hardening and service mode remain post-MVP work.

## Flow assessment at closeout

### 1. Request -> planning

Closed result:

- the planner contract is explicit across heuristic, OpenAI, and Ollama
- the heuristic path can now chain memory -> processes -> process correlation -> service status for slow-host diagnosis when correlation evidence exists
- the planner still stays inside typed tool boundaries and explicit decision states

Residual non-MVP limits:

- heuristic intent matching is intentionally simple
- broader Linux diagnostic breadth is still future work

### 2. Execution -> policy -> audit

Closed result:

- typed tools remain the only execution surface in the agent core
- mutating actions still require explicit confirmation
- service scope and target identity survive recommendation and execution flows
- config mutation remains bounded by allowlists, validation, backup, and atomic replace

Residual non-MVP limits:

- no daemon/API layer
- no generic shell execution surface
- no production-grade privilege/elevation abstraction

### 3. Execution results -> memory -> recommendations

Closed result:

- session-scoped observations and TTL freshness are active
- `SessionContext` is used for the highest-risk planner and recommendation decisions
- `process_to_unit` and `failed_services` add practical operator evidence without weakening the trust boundary
- recommendation views now expose evidence summaries, target identity, and next-step commands

Residual non-MVP limits:

- summary text still exists as a carry-forward/debug artifact
- future utility work can still broaden disk, logs, and network diagnostics

### 4. Recommendation -> acceptance -> execution

Closed result:

- recommendation actions still go through the same policy and audit path as direct tool calls
- acceptance remains distinct from execution
- the CLI and chat surfaces now render clearer evidence and exact next-step commands

Residual non-MVP limits:

- recommendation breadth is intentionally narrow and safety-first
- the system still targets one local operator on one host

### 5. Engineering posture

Closed result:

- deterministic tests, lint, typecheck, and compile validation are in place
- closeout docs were synchronized in the same change stream as behavior
- clean-environment install validation succeeded via `python3 -m virtualenv`, `pip install -e .`, and `mc doctor`

Residual non-MVP limits:

- `cli.py` and `session_store.py` remain future cleanup candidates
- broader packaging/distribution work is still outside this closeout

## Guiding rules that governed closeout

1. Evidence before inference.
   No mutating action is suggested from guessed entity relationships alone.

2. Structured state before text summaries.
   The summary is no longer the primary safety boundary for the highest-risk paths.

3. Scope is part of identity.
   `system` and `user` service targets survive the full request -> recommendation -> execution flow.

4. No new privileged capability before the trust boundary is stable.
   Utility work during closeout stayed read-only.

5. One execution boundary for every provider.
   Provider quality can change planning, but not policy or audit semantics.

## Milestones

### Milestone 1: Correctness and context hardening

Status:

- Completed on 2026-03-18 for the current service recommendation boundary

Result:

- no service restart or status recommendation is derived solely from a hot process name
- `scope=user|system` is preserved through observation, summary, insight, recommendation, and execution
- regression coverage exists for process/service correlation, stale refresh flows, and scope retention

### Milestone 2: Structured session state and orchestration refactor

Status:

- Completed on 2026-03-18

Result:

- core high-risk planner and recommendation decisions now consume `SessionContext`
- `app.py` was reduced from 1711 lines to 1255 lines by extracting turn planning, turn rendering, and recommendation view helpers
- summary parsing is no longer the primary source for the highest-risk recommendation decisions

### Milestone 3: Operator utility and approval UX

Status:

- Completed on 2026-03-18

Result:

- added `process_to_unit` for typed process -> `systemd` correlation
- added `failed_services` for typed failed-unit listing by scope
- slow-host diagnosis can now reuse correlation evidence and continue to `service_status` when appropriate
- recommendation and approval output now render evidence summaries, freshness, and next-step commands

### Milestone 4: Alpha hardening and release baseline

Status:

- Completed on 2026-03-18

Result:

- canonical docs were synchronized to the closed MVP state
- automated baseline, real-host CLI smokes, and clean-environment install validation were rerun successfully
- the narrow local alpha baseline is ready for tagging on the validated host profile

## Sequencing record

The closeout sequencing that was executed successfully was:

1. Milestone 1
2. Milestone 2
3. Milestone 3
4. Milestone 4

That sequence is now complete.

## Measurement snapshot

Closeout finished with these signals:

- correctness:
  - no unsupported service mutation recommendation from process-name inference alone
  - scope preserved across service flows
- engineering quality:
  - `ruff`, `mypy`, unit baseline, and `compileall` green
  - 92 automated tests passing at closeout
- operator usability:
  - documented commands exist for slow-host, unhealthy-service, recommendation-action, and config rollback flows
  - recommendation-to-action flow is explicit and auditable
- release baseline:
  - clean-environment install validated via `python3 -m virtualenv`
  - `mc doctor` succeeds from the isolated install

## Completed implementation slices

The closeout slices completed under this plan were:

1. `feat(tools): add process-to-unit correlation`
2. `feat(tools): add failed-service listing`
3. `feat(cli): improve recommendation evidence and approval rendering`
4. `test(chat): cover the main operator journeys after utility expansion`
5. `docs: refresh alpha validation and release baseline references`

## Post-closeout direction

Future work is now outside this MVP plan and belongs to the broader roadmap:

1. service mode and external interfaces
2. broader post-alpha hardening
3. incremental operator utility beyond the narrow local alpha baseline
