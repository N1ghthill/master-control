# Diagrams

This directory contains the canonical Mermaid diagrams for the current MC flow.

## Diagrams

- `master-control-flow.mmd` / `master-control-flow.svg`
  - End-to-end request flow across CLI, planning, policy, execution, recommendations, and SQLite state
- `chat-planning-flow.mmd` / `chat-planning-flow.svg`
  - Chat turn lifecycle from message intake to iterative planning, tool execution, and final response
- `recommendation-approval-flow.mmd` / `recommendation-approval-flow.svg`
  - Recommendation lifecycle from session insight derivation to acceptance, confirmation, and action execution
- `state-audit-flow.mmd` / `state-audit-flow.svg`
  - How sessions, summaries, observations, recommendations, messages, and audit events are written and consumed

## Preview

### End-to-end flow

![Master Control flow](master-control-flow.svg)

### Chat and planning flow

![Chat planning flow](chat-planning-flow.svg)

### Recommendation and approval flow

![Recommendation approval flow](recommendation-approval-flow.svg)

### State and audit flow

![State and audit flow](state-audit-flow.svg)
