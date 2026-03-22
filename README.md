# Master Control

Master Control (MC) is a conversational Linux agent for host inspection and controlled operations.
It combines natural-language planning with typed tools, explicit approval gates, and an audit trail so the assistant can help without turning into unrestricted shell automation.

![Master Control overview](docs/diagrams/readme-overview.svg)

## Why it exists

- conversational interface for Linux operator workflows
- typed tools before generic shell access
- explicit confirmation for risky or privileged actions
- local-first provider routing: `ollama -> openai -> heuristic`
- persistent session context, observations, and recommendation history

## Current status

- late alpha
- CLI-first and single-host by design
- validated on the maintainer workstation and on a dedicated Debian 13 VPS lab
- not positioned as a production-ready Linux administration platform

This README intentionally stays short.
Operational detail, release records, validation evidence, and planning documents live under [docs/README.md](docs/README.md).

## Quick start

From a repository checkout:

```bash
./install.sh --provider heuristic
~/.local/bin/mc doctor
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
~/.local/bin/mc chat --once "o host esta lento"
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
- local heuristic fallback plus OpenAI and Ollama providers

## Validation posture

- automated baseline: `ruff`, `mypy`, `unittest`, `pytest`, `compileall`, and `mc doctor`
- repo-side bootstrap validation harness in CI
- real-host validation evidence captured beyond the maintainer workstation

See [docs/status.md](docs/status.md), [docs/alpha-validation-report.md](docs/alpha-validation-report.md), and [docs/vps-validation-report.md](docs/vps-validation-report.md) for the current evidence-backed state.

## Documentation

- [Documentation map](docs/README.md)
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
src/master_control/    Application code
tests/                 Automated tests
```
