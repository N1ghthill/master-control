# ADR 0004: Recommendation actions remain approval-gated tool executions

Status: Accepted
Date: 2026-03-17

## Context

The project now derives deterministic insights from session summaries and persists them as recommendations. Some recommendations naturally map to a typed follow-up action, such as restarting an unhealthy service.

The system needs a way to represent those actions without creating a second execution path outside the normal policy and audit boundary.

## Decision

Persist optional action metadata on session recommendations:

- action kind
- tool name
- validated arguments
- human-facing action title

Recommendation lifecycle and execution are deliberately separate:

- a recommendation may be `open`, `accepted`, `dismissed`, or `resolved`
- moving a recommendation to `accepted` does not execute anything
- if an action is present, execution must still call the same local tool path used elsewhere
- policy checks, confirmation requirements, and audit events remain mandatory

## Consequences

Positive:

- recommendations can guide the operator toward safe next steps
- the system avoids hidden execution paths
- actionability improves without weakening the security model

Negative:

- recommendation handling becomes a more explicit state machine
- the operator workflow is slightly more verbose until approval UX improves
