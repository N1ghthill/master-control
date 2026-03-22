# Master Control

Master Control (MC) is a local-first runtime for controlled Linux host operations.
It exposes typed capabilities behind policy, approval, and audit boundaries so operators and external clients can inspect and act on a Linux host without falling back to unrestricted shell automation.

![Master Control overview](docs/diagrams/readme-overview.svg)

## What it is

- safe capability layer for bounded Linux inspection and controlled actions
- CLI-first today, with room for multiple interfaces on top of the same runtime
- designed so deterministic clients and AI clients can reuse the same execution, policy, and audit path

## Why it exists

- typed tools before generic shell access
- explicit confirmation for risky or privileged actions
- local audit trail, state, and validation evidence
- reusable runtime instead of interface-specific host logic

## Current status

- late alpha
- single-host and local-first by design
- current public install path is source checkout plus `install.sh`
- validated on the maintainer workstation and on a dedicated Debian 13 VPS lab
- the chat/provider path still exists, but it is no longer the product center
- an experimental read-only MCP stdio bridge now exists on top of the same runtime
- not positioned as a production-ready Linux administration platform, security auditor, or package manager

This README intentionally stays short.
Operational detail, release records, validation evidence, and planning documents live under [docs/README.md](docs/README.md).

## Quick start

From a repository checkout:

```bash
./install.sh --provider heuristic
~/.local/bin/mc doctor
~/.local/bin/mc tools
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
```

The current chat interface is still available:

```bash
~/.local/bin/mc chat --once "o host esta lento"
```

An experimental read-only MCP bridge is also available:

```bash
~/.local/bin/mc mcp-serve
```

To remove the user-local install:

```bash
./uninstall.sh --purge-state
```

Debian or Ubuntu note:

- if `install.sh` reports that `ensurepip` is unavailable, install `python3.13-venv` first

## What MC currently covers

- host, disk, memory, process, service, and journal inspection
- process-to-`systemd` correlation and failed-service triage
- managed config read, write, backup, and restore inside a constrained policy boundary
- recommendation workflow with explicit approval before risky execution
- repeatable host-profile validation through `mc validate-host-profile`
- optional heuristic, OpenAI, and Ollama-backed planning path on top of the same runtime

## Validation posture

- automated baseline: `ruff`, `mypy`, `unittest`, `pytest`, `compileall`, and `mc doctor`
- repo-side bootstrap validation harness in CI
- real-host validation evidence captured beyond the maintainer workstation

See [docs/status.md](docs/status.md), [docs/alpha-validation-report.md](docs/alpha-validation-report.md), and [docs/vps-validation-report.md](docs/vps-validation-report.md) for the current evidence-backed state.

## Documentation

- [Documentation map](docs/README.md)
- [Core + interfaces refactor plan](docs/core-interfaces-refactor-plan.md)
- [Current status](docs/status.md)
- [Operator workflows](docs/operator-workflows.md)
- [Provider setup](docs/providers.md)
- [Host-profile validation guide](docs/host-profile-validation.md)
- [Community host validation guide](docs/community-host-validation.md)
- [Architecture](docs/architecture.md)
- [Security model](docs/security-model.md)
- [Contributing](CONTRIBUTING.md)

## Repository layout

```text
docs/                  Documentation, validation records, and planning docs
src/master_control/core/        Runtime, policy, persistence, and validation
src/master_control/interfaces/  CLI, chat, and MCP entry points
src/master_control/shared/      Neutral contracts shared across boundaries
tests/                 Automated tests
```
