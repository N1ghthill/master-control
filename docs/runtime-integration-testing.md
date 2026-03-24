# Runtime Integration Testing

Snapshot date: 2026-03-23

## Purpose

This document records the current runtime-contract validation layers beyond pure unit coverage.

The goal is to validate the real runtime boundaries:

- policy loading
- approval lifecycle
- managed config mutation
- MCP stdio contract behavior

## Current Layers

1. Unit and module-level regression coverage across `tests/`
2. Runtime policy integration coverage in `tests/test_runtime_policy_integration.py`
3. MCP stdio subprocess contract coverage in `tests/test_mcp_stdio_integration.py`
4. Operator bootstrap validation via `python3 scripts/validate_operator_bootstrap.py`
5. Host-profile validation via `mc validate-host-profile`
6. Real MCP client validation via `python3 scripts/validate_mcp_client.py`

## Local Commands

Run the fast engineering baseline:

```bash
python3 -m ruff check .
python3 -m mypy src
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall src
```

Run the main pytest suite without the runtime/MCP integration slice:

```bash
PYTHONPATH=src python3 -m pytest -q tests \
  --ignore tests/test_runtime_policy_integration.py \
  --ignore tests/test_mcp_stdio_integration.py
```

Run the runtime/MCP integration slice explicitly:

```bash
PYTHONPATH=src python3 -m pytest -q \
  tests/test_runtime_policy_integration.py \
  tests/test_mcp_stdio_integration.py
```

Run the install/bootstrap path:

```bash
python3 scripts/validate_operator_bootstrap.py \
  --output-dir /tmp/mc-bootstrap-validation \
  --provider heuristic \
  --python python3
```

Run the real-client MCP contract check:

```bash
python3 scripts/validate_mcp_client.py \
  --output-dir /tmp/mc-client-validation
```

## What These Tests Prove Today

- operator policy can disable tools, require confirmation, constrain service targets, and redefine managed config targets
- invalid policy fails closed and is surfaced through `mc doctor`
- `mc mcp-serve` works as a real stdio subprocess for both the legacy approval API and the standard JSON-RPC MCP handshake
- approval-mediated config mutation works through the real MCP server process, not just through in-process unit helpers
- the official MCP Inspector CLI can complete `tools/list`, read-only execution, pending approval, `approval_get`, and `approval_approve`

## Known Gaps

- no container-backed integration harness yet for repeatable `systemd` service scenarios
- no desktop-specific GUI transcript is checked in yet
- real-host smoke validation remains necessary for host-specific paths that containers do not model well
