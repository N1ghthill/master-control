# Project Status

Snapshot date: 2026-03-30

## Purpose

This document is the authoritative snapshot of project maturity, implemented scope, and validation evidence at a point in time.

It is not the GitHub landing page.
It is not the long-horizon roadmap.

## Current Position

- Stage: late alpha, pre-1.0
- Release posture: public pre-release `v0.1.0a2` is published
- Product posture: runtime-first and MCP-first
- Interface posture: MCP is the main external integration interface; CLI is the local administration interface; chat/providers are optional
- Install posture: source checkout plus `install.sh`
- Scope posture: single-host and local-first
- Packaging posture: no `.deb` package and no service-mode requirement yet
- Repository posture: public Apache-2.0 repository with security/support/conduct docs, branch protection, Dependabot, and working `pre-commit` hooks

## Current Product Statement

Master Control is a local-first runtime for controlled Linux host operations, with typed capabilities, approval boundaries, and auditability.

The core value today is the bounded runtime:

- typed tools
- policy and confirmation gates
- audit trail
- config safety
- repeatable validation

MCP is the main integration path for that runtime.
CLI remains the local administration surface.
Chat and planner providers remain optional layers on top of the same runtime.

## Implemented Today

### Runtime foundation

- modular Python monolith with `src/` layout
- SQLite bootstrap and local state directory
- architecture, security, roadmap, and ADR documentation
- published repository governance docs: `LICENSE`, `SECURITY.md`, `SUPPORT.md`, and `CODE_OF_CONDUCT.md`
- audit trail for plans, executions, provider errors, and recommendation status changes
- operator bootstrap scripts for install and removal
- repeatable bootstrap validation harness with per-step logs and cleanup checks
- GitHub CI bootstrap smoke for the non-editable operator path
- GitHub CI matrix on Python 3.11 and 3.13, with lint, typecheck, Bandit, tests, wheel smoke, doctor, and bootstrap validation
- working `pre-commit` baseline for whitespace, formatting, lint, typecheck, and Bandit
- host-validation bundle generation and community intake path

### Runtime capabilities

- typed inspection and controlled-action tools
- policy evaluation before every tool execution
- versioned operator policy loading with safe defaults, fail-closed errors, and doctor diagnostics
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

### Interfaces

- experimental MCP stdio bridge with approval-mediated write flow on top of the runtime
- standard JSON-RPC-compatible MCP stdio handshake for real MCP clients
- MCP approval tools exposed through the standard `tools/list` / `tools/call` surface
- CLI commands for doctor, tools, audit, sessions, observations, recommendations, direct tool execution, and chat
- CLI-integrated `validate-host-profile` command backed by reusable host-validation code
- optional `systemd` timer installation for bounded recommendation reconciliation

### Optional planner layer

- provider abstraction
- heuristic planner for offline development
- OpenAI Responses API adapter for structured planning
- Ollama chat adapter for local structured planning
- local-first auto provider resolution: `ollama -> openai -> heuristic`
- structured execution plans instead of free-form tool calls
- provider health reporting in `mc doctor`

## What Is True Right Now

- MC is already useful as a bounded runtime for Linux inspection and controlled actions
- MCP is the main external interface direction, and the current experimental slice already supports approval-mediated write operations
- the official MCP Inspector CLI now validates that a real client can complete the approval-mediated mutation flow
- CLI is still the most complete operator surface today
- chat/provider paths are optional and should not define the product center
- a first operator-configurable policy slice is landed through versioned TOML, but broader validation and operator evidence are still ahead
- approval concurrency is now hardened against duplicate active requests and duplicate in-flight execution for the same action envelope
- the public repository baseline is now materially stronger: Apache-2.0 license, governance docs, branch protection, `pre-commit`, Bandit, and Dependabot are in place
- tool-schema governance and broader runtime ownership cleanup are still ahead of the current baseline
- `github/codeql-action` is temporarily excluded from Dependabot automation due an updater-side failure tracked in issue #20; CodeQL action bumps are currently manual maintainer work

## Active Focus

The current execution focus is defined by `docs/runtime-mcp-maturation-plan.md`.

The next maturity steps are:

1. tool-schema compatibility rules and release policy in issue #17
2. narrower runtime ownership seams, especially around `core.runtime`, `session_store`, and `providers/heuristic` in issue #18
3. lower-friction install and distribution paths in issue #21
4. simpler product narrative around primary operator workflows in issue #19
5. broader client and host validation evidence in issue #2

## Intentionally Out Of Scope Right Now

- unrestricted shell access
- web UI
- voice interface
- Slack or Discord integrations
- multi-user auth and remote deployment
- SaaS-style remote control infrastructure

## Validation Baseline

At this snapshot, the project is validated by:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `python3 -m bandit -q --severity-level medium --confidence-level medium -c pyproject.toml -r src scripts`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m pytest -q`
- explicit runtime/MCP integration coverage in `tests/test_runtime_policy_integration.py` and `tests/test_mcp_stdio_integration.py`
- `python3 -m compileall src`
- `python3 -m pre_commit run --all-files`
- real-client MCP validation through `python3 scripts/validate_mcp_client.py`
- manual CLI smoke checks for chat, recommendations, recommendation-triggered actions, and `reconcile-timer render|install|remove`
- manual CLI smoke checks for managed config write with validation and backup
- manual CLI smoke checks for `process_to_unit` and `failed_services`
- repeatable host-profile validation through `mc validate-host-profile`
- repeatable operator bootstrap validation through `python3 scripts/validate_operator_bootstrap.py`
- GitHub CI bootstrap smoke for the non-editable operator path
- clean-environment operator bootstrap validation via `./install.sh`, `mc doctor`, `mc validate-host-profile`, and `./uninstall.sh --purge-state`
- packaging sanity check via `python3 -m pip wheel . --no-deps -w /tmp/mc-dist`
- dedicated Debian VPS operator-path validation on 2026-03-20
- GitHub `main` protection requiring `Analyze (python)`, `test (python-3.11)`, and `test (python-3.13)` after the 2026-03-30 repo-maturity publication pass

## Current Canonical Docs

- `docs/status.md`: reality snapshot
- `docs/roadmap.md`: concise roadmap
- `docs/runtime-mcp-maturation-plan.md`: canonical execution plan
- `docs/architecture.md`: system structure and boundaries
- `docs/security-model.md`: safety and approval model
- `docs/policy.md`: operator policy guide
- `docs/operator-workflows.md`: bounded operator journeys
- `docs/runtime-integration-testing.md`: runtime and MCP validation guide
- `docs/mcp-client-validation.md`: real MCP client validation guide
- `docs/host-profile-validation.md`: validation harness guide

## Evidence Records

- `docs/alpha-validation-report.md`
- `docs/vps-validation-report.md`
- `docs/beta-readiness-gate.md`

## Historical Records

The following documents remain useful for traceability, but they are not the current product brief or roadmap:

- `docs/history/alpha-release-notes.md`
- `docs/history/release-candidate-0.1.0a2.md`
- `docs/history/beta-resume-plan.md`
- `docs/history/mvp-plan.md`
- `docs/history/mvp-evolution-plan.md`
- `docs/history/mvp-closeout-backlog.md`
- `docs/history/post-mvp-evolution-plan.md`
