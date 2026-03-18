# MVP Plan

## Target MVP definition

Master Control MVP means:

- one local Linux host
- one CLI-first conversational interface
- structured planning through a provider abstraction
- typed inspection tools
- persistent session memory
- persistent recommendation tracking
- at least a minimal set of approval-gated state-changing actions
- auditability for plans, executions, and approvals

This MVP does not require web UI, daemon mode, plugins, or remote multi-user deployment.

## Canonical planning documents

To avoid legacy planning drift, use the documents this way:

- `docs/mvp-plan.md`: stable MVP contract and exit criteria
- `docs/mvp-evolution-plan.md`: milestone sequencing and closeout completion record
- `docs/mvp-closeout-backlog.md`: closed execution backlog record for the MVP closeout
- `docs/status.md`: current implementation snapshot
- `docs/roadmap.md`: phase-level view of the post-closeout roadmap

## Exit criteria

The MVP should only be called complete when all of these are true:

1. the agent can inspect host state through typed tools and explain the result conversationally
2. sessions can be resumed with enough context to make follow-up requests useful
3. risky follow-up actions are represented explicitly and never execute implicitly
4. risky operational recommendations are only suggested when backed by explicit evidence and preserved target scope
5. at least two operational mutation paths exist with policy gates and validation
6. the operator can trace what happened through local audit events
7. the main flows are covered by automated tests and documented commands

## Current delta to close

The narrow local CLI MVP closeout is complete. `docs/mvp-evolution-plan.md` now serves as the completion record for that delivery plan.

### Workstream 1: Correctness and context hardening

Status:

- completed on 2026-03-18 for the current service recommendation boundary

Deliver:

- evidence-gated service recommendations
- preservation of service scope and identity through the full operator flow
- regression coverage for process/service correlation and recommendation safety boundaries

Accept when:

- no service recommendation or action is derived solely from process-name inference
- `scope=user|system` survives summary, recommendation, and execution flows

### Workstream 2: Structured session state and orchestration

Status:

- completed on 2026-03-18

Deliver:

- structured session context for planners and recommendation builders
- summary treated primarily as a rendering artifact
- clearer boundaries between chat orchestration, execution, and recommendation syncing

Accept when:

- high-risk recommendation logic no longer depends primarily on text summary parsing
- hotspot files have narrower responsibilities

### Workstream 3: Operator utility and approval UX

Status:

- completed on 2026-03-18

Deliver:

- higher-value read-only tools for diagnosis
- clearer recommendation evidence and freshness presentation
- lower-friction recommendation -> accept -> confirm -> execute flow

Accept when:

- an operator can move through the main flows without guessing the next safe step
- recommendations clearly show what evidence and freshness level support them

### Workstream 4: Hardening and release prep

Status:

- completed on 2026-03-18

Deliver:

- end-to-end tests for the main operator flows
- documentation pass for commands, architecture, and security boundaries
- initial release notes and release checklist
- an explicit alpha validation report

Accept when:

- the project can be handed to a new developer with local setup and operating instructions
- the alpha release scope is explicit
- the validation report covers both local LLM operation and the main mutation paths

## Recommended implementation order

All four MVP closeout workstreams are complete for the narrow local alpha baseline.

## Recommended commit slices

The closeout slices that satisfied this plan were:

1. `feat(tools): add higher-value read-only diagnostics`
2. `feat(cli): improve recommendation evidence and approval rendering`
3. `test(chat): cover the main operator journeys after utility expansion`
4. `docs: align release and MVP closeout documents`
