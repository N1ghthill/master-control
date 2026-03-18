# ADR 0002: CLI first and host-level deployment

Status: Accepted
Date: 2026-03-17

## Context

The product vision includes multiple interfaces, but the core technical challenge is safe host execution. The quickest path to useful feedback is a local CLI on the host itself.

## Decision

Start with:

- a CLI-first interface
- a host-level Python process
- optional future `systemd` service support

Defer:

- web UI
- chat integrations
- privileged container deployment

## Consequences

Positive:

- lower complexity
- easier access to host state
- fewer moving parts during security hardening

Negative:

- less friendly for remote and multi-user scenarios at first
- later interface work will still need to be built
