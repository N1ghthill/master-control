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

## Exit criteria

The MVP should only be called complete when all of these are true:

1. the agent can inspect host state through typed tools and explain the result conversationally
2. sessions can be resumed with enough context to make follow-up requests useful
3. risky follow-up actions are represented explicitly and never execute implicitly
4. at least two operational mutation paths exist with policy gates and validation
5. the operator can trace what happened through local audit events
6. the main flows are covered by automated tests and documented commands

## Current delta to close

### Workstream 1: Approval UX

Status:

- implemented in the current codebase

Deliver:

- clearer pending-confirmation responses
- explicit command path for confirming a previously accepted action
- better messaging in chat and CLI help for recommendation lifecycle

Accept when:

- an operator can move from recommendation to execution without guessing the next command
- no state-changing action runs without a visible confirmation step

### Workstream 2: Service operations

Status:

- implemented for `restart_service` and `reload_service`

Deliver:

- `reload_service`
- improved verification after restart or reload
- better service-oriented summaries in chat responses

Accept when:

- service actions return both preflight and post-action state
- failures are actionable and auditable

### Workstream 3: Safe config edits

Status:

- implemented for managed targets

Deliver:

- file read/write ownership model for a bounded set of paths
- backup before write
- validation hook before apply
- atomic replace where feasible

Accept when:

- a config change can be proposed, validated, and rolled back
- the workflow leaves enough audit information to reconstruct the change

### Workstream 4: Hardening and release prep

Status:

- near complete

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

1. alpha packaging baseline and release notes polish
2. optional approval UX polish if release review exposes friction

## Recommended commit slices

If the repository is initialized under git, keep commits small and single-purpose:

1. `docs: align roadmap and project status`
2. `feat(tools): add reload_service`
3. `feat(app): improve approval flow for recommendation actions`
4. `feat(config): add safe config write pipeline`
5. `test(e2e): cover inspect to action workflows`
6. `docs: prepare alpha release notes`
