# ADR 0001: Modular monolith in Python

Status: Accepted
Date: 2026-03-17

## Context

The project needs deep Linux integration, fast iteration, and a clear execution boundary. Splitting the system into multiple services too early would add operational overhead without solving a current problem.

## Decision

Build the first version as a modular Python monolith with a `src/` layout and well-defined internal packages:

- `agent`
- `executor`
- `policy`
- `providers`
- `store`
- `tools`

## Consequences

Positive:

- simpler development and debugging
- easy local deployment
- direct access to Python's Linux ecosystem

Negative:

- fewer isolation boundaries than a distributed design
- future extraction of services will require deliberate interface cleanup

