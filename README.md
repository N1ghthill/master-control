# Master Control

[![CI](https://github.com/N1ghthill/master-control/actions/workflows/ci.yml/badge.svg)](https://github.com/N1ghthill/master-control/actions/workflows/ci.yml)
[![CodeQL](https://github.com/N1ghthill/master-control/actions/workflows/codeql.yml/badge.svg)](https://github.com/N1ghthill/master-control/actions/workflows/codeql.yml)

Master Control (MC) is a local-first runtime for bounded Linux host operations.
It exposes typed host capabilities through a shared runtime with policy, approval, and audit boundaries around every action.

![Master Control overview](docs/diagrams/readme-overview.svg)

MC is not just an MCP server.
MC is the runtime. MCP is its main external integration interface, and the CLI is the main local operator surface.

MC is built around three product constraints:
- typed tools before generic shell access
- explicit confirmation for risky or privileged actions
- local audit trail and repeatable validation

## Current status

- stage: late alpha
- scope: single-host and local-first
- install path: source checkout plus `install.sh`
- Python floor: 3.11+
- validated on the maintainer workstation and a dedicated Debian VPS lab
- main external interface: experimental JSON-RPC-compatible MCP stdio with approval-mediated write flow
- main local interface: CLI
- optional interface: chat/provider path
- not positioned as a production-ready Linux administration platform, security auditor, or package manager

## What it already does

- host, disk, memory, process, service, and journal inspection
- process-to-`systemd` correlation and failed-service triage
- managed config read, write, backup, and restore inside a constrained policy boundary
- operator-configurable policy through a versioned TOML file with safe defaults and fail-closed load errors
- recommendation workflow with explicit approval before risky execution
- repeatable host-profile validation through `mc validate-host-profile`
- optional heuristic, OpenAI, and Ollama-backed planning on top of the same runtime

## Start here

The shortest operator path today is:

```bash
./install.sh --provider heuristic
~/.local/bin/mc doctor
~/.local/bin/mc tools
~/.local/bin/mc tool system_info
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
```

If you want the MCP surface:

```bash
~/.local/bin/mc mcp-serve
```

If you want the optional chat interface:

```bash
~/.local/bin/mc chat --once "o host esta lento"
```

Remove the user-local install:

```bash
./uninstall.sh --purge-state
```

If `install.sh` reports that stdlib `venv` support is unavailable on Debian or Ubuntu, install the matching `pythonX.Y-venv` package for the interpreter you are using.

## Repository policy

- [Contributing](CONTRIBUTING.md)
- [Support policy](SUPPORT.md)
- [Security policy](SECURITY.md)
- [License](LICENSE)

## Documentation

- [Documentation map](docs/README.md)
- [Product maturity assessment](docs/product-maturity-assessment.md)
- [Current status](docs/status.md)
- [Roadmap](docs/roadmap.md)
- [Runtime + MCP maturation plan](docs/runtime-mcp-maturation-plan.md)
- [Architecture](docs/architecture.md)
- [Security model](docs/security-model.md)
- [Policy guide](docs/policy.md)
- [Operator workflows](docs/operator-workflows.md)
- [Runtime integration testing](docs/runtime-integration-testing.md)
- [MCP client validation](docs/mcp-client-validation.md)
- [Provider setup](docs/providers.md)
- [Host-profile validation guide](docs/host-profile-validation.md)
- [Validation evidence](docs/alpha-validation-report.md)
