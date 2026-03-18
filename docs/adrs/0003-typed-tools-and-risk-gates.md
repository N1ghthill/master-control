# ADR 0003: Typed tools and risk-based approval gates

Status: Accepted
Date: 2026-03-17

## Context

Conversational agents are unreliable if they map user intent directly to arbitrary shell execution. The system needs a narrow, inspectable execution surface.

## Decision

Define actions as typed tools with:

- a stable name
- a description
- a risk level
- validated arguments

Route every tool call through a policy engine before execution.

## Consequences

Positive:

- clearer security model
- easier auditing
- better testability

Negative:

- slower feature expansion than exposing raw shell commands
- some advanced workflows will need additional tool modeling
