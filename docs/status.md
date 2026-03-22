# Project Status

Snapshot date: 2026-03-22

## Purpose

This document is the authoritative snapshot of project maturity, implemented scope, and validation evidence at a point in time.

It is not the GitHub landing page.
It is not the long-horizon roadmap.

## Maturity

- Stage: late alpha
- Public release posture: GitHub pre-release `v0.1.0a2` is published
- Product posture: MC is being repositioned from an AI-first conversational agent to a runtime-first capability layer with interfaces
- Interface posture: MCP is the main integration interface; the CLI remains the local administration interface; the chat/provider path remains optional
- Install posture: source checkout plus `install.sh`; no `.deb` package yet
- Scope posture: single-host and local-first
- Refactor posture: the runtime-first documentation reset and the first code-boundary slices have landed without resetting the validated alpha baseline
- Historical planning records remain available in `docs/mvp-evolution-plan.md`, `docs/mvp-closeout-backlog.md`, `docs/post-mvp-evolution-plan.md`, and `docs/beta-resume-plan.md`

## Current product statement

Master Control is a local-first runtime for controlled Linux host operations, with typed capabilities, approval boundaries, and auditability.

The core value today is not generic AI autonomy.
The core value is the bounded runtime:

- typed tools
- policy and confirmation gates
- audit trail
- config safety
- repeatable validation

The MCP interface is the main integration path for that runtime.
The CLI remains the local administration surface.
The conversational and provider-backed path still exists, but it is now understood as an optional interface layered on top of the same runtime.

## What is already implemented

### Runtime foundation

- modular Python monolith with `src/` layout
- SQLite bootstrap and local state directory
- architecture, security, roadmap, and ADR documentation
- audit trail for plans, executions, provider errors, and recommendation status updates
- operator bootstrap scripts for install and removal
- repeatable repo-side bootstrap validation harness with per-step logs and cleanup checks
- GitHub CI bootstrap smoke for the non-editable operator path via `scripts/validate_operator_bootstrap.py`
- redacted host-validation bundle generation plus a dedicated intake path for community-submitted reports

### Runtime capabilities

- typed inspection and controlled-action tools
- policy evaluation before every tool execution
- explicit confirmation gates for mutating and privileged paths
- bounded subprocess execution with `shell=False`, timeouts, and output truncation
- managed config read, write, validation, backup, and restore for bounded targets
- service actions with scope-aware safety boundaries
- persistent audit events, sessions, observations, summaries, and recommendation state

### Implemented tool surface

- `system_info`
- `disk_usage`
- `memory_usage`
- `top_processes`
- `process_to_unit`
- `service_status`
- `failed_services`
- `read_journal`
- `read_config_file`
- `write_config_file`
- `restore_config_backup`
- `reload_service`
- `restart_service`

### Runtime interfaces

- experimental read-only MCP stdio bridge on top of the runtime
- CLI commands for doctor, tools, audit, sessions, observations, recommendations, direct tool execution, and chat
- CLI-integrated `validate-host-profile` command backed by reusable host-validation code
- optional `systemd` timer installation for bounded recommendation reconciliation

### Optional agent interface

- provider abstraction
- heuristic planner for offline development
- OpenAI Responses API adapter for structured planning
- Ollama chat adapter for local structured planning
- local-first auto provider resolution: `ollama -> openai -> heuristic`
- structured execution plans instead of free-form tool calls
- iterative per-turn planning loop that can continue a diagnosis using fresh tool outputs
- provider health reporting in `mc doctor`, including local Ollama endpoint and model availability
- deterministic turn guidance, structured session context, and recommendation rendering helpers

## Product interpretation of the current baseline

The validated alpha baseline should now be interpreted as follows:

- MC is already useful as a bounded runtime for Linux inspection and controlled actions
- MCP is the clearest external integration surface for the current product direction
- the CLI is the local operator and administration surface
- the current chat/provider path is an optional interface, not the explanation of the product
- the current codebase still carries more conversational complexity than the runtime-centered product story requires
- the current refactor is meant to correct that mismatch without throwing away validated behavior

## Current refactor focus

The active refactor is described in `docs/core-interfaces-refactor-plan.md`.

The near-term objective is:

1. finish aligning the remaining supporting docs with the runtime-first contract
2. continue reducing legacy compatibility surface around the old app-centric entry points
3. harden the current experimental MCP bridge without expanding its capability surface prematurely
4. perform broader cleanup only after the replacement structure is stable

## What is intentionally out of scope right now

- general package management
- full host security auditing or compliance scanning
- web UI
- voice interface
- Slack or Discord integrations
- multi-user auth and remote deployment
- SaaS-style remote control infrastructure

## Validation baseline

At this snapshot, the project is validated by:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m pytest -q`
- `python3 -m compileall src`
- manual CLI smoke checks for chat, recommendations, recommendation-triggered actions, and `reconcile-timer render|install|remove`
- manual CLI smoke checks for managed config write with validation and backup
- manual CLI smoke checks for `process_to_unit` and `failed_services`
- automated coverage for observation freshness and stale-context refresh behavior
- real-host validation of `service_status`, `reload_service`, and `restart_service` on `systemd --user`
- real-host validation of `service_status`, `reload_service`, and `restart_service` on system-scoped units
- real-host validation of managed config read/write/restore on a file under `<MC_STATE_DIR>/managed-configs/`
- repeatable host-profile validation harness available through `mc validate-host-profile`
- repeatable operator bootstrap validation harness available through `python3 scripts/validate_operator_bootstrap.py`
- GitHub CI bootstrap smoke for the non-editable operator path
- clean-environment operator bootstrap validation via `./install.sh`, `mc doctor`, `mc validate-host-profile`, and `./uninstall.sh --purge-state`
- packaging sanity check via `python3 -m pip wheel . --no-deps -w /tmp/mc-dist`
- dedicated VPS operator-path validation on 2026-03-20 after installing `python3.13-venv`
- dedicated VPS bootstrap harness rerun on 2026-03-20 with `overall_ok: true`

## Evidence records

Primary evidence and release records remain:

- `docs/alpha-validation-report.md`
- `docs/vps-validation-report.md`
- `docs/alpha-release-notes.md`
- `docs/release-candidate-0.1.0a2.md`
- `docs/operator-workflows.md`
- `docs/beta-readiness-gate.md`
