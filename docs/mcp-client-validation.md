# MCP Client Validation

Snapshot date: 2026-03-23

## Purpose

This document records the current real-client validation path for `mc mcp-serve`.

The goal is not to rely only on in-process stdio tests.
The goal is to prove that a standard MCP client can complete the approval-mediated mutation flow against the real server process.

## Validated Client

Current validated client:

- official MCP Inspector CLI via `@modelcontextprotocol/inspector --cli`

Current validated host:

- maintainer workstation with Node `22.22.1`

Note:

- the dedicated Debian 13 VPS lab currently provides Node `20.19.2`, which is below the Inspector package's declared Node floor
- the VPS remains useful for operator bootstrap and host-validation evidence, but the current Inspector CLI transcript is maintained from the workstation

## What Is Validated

The current Inspector-backed flow validates:

1. standard JSON-RPC `initialize` over stdio
2. `tools/list` against the real `mc mcp-serve` process
3. read-only `tools/call` for `system_info`
4. approval-mediated `tools/call` for `write_config_file`
5. approval resolution through MCP-exposed tools:
   - `approval_get`
   - `approval_approve`

This means a real MCP client can:

- inspect the host
- trigger a bounded mutating action
- receive a structured pending-approval payload
- resolve that approval through the MCP tool surface
- observe the executed result and persisted approval record

## Repeatable Command

Run:

```bash
python3 scripts/validate_mcp_client.py --output-dir ./artifacts/mcp-client-validation
```

Optional JSON report:

```bash
python3 scripts/validate_mcp_client.py --json
```

## Generated Artifacts

Each run writes:

- `report.json`
- per-step stdout/stderr logs
- isolated MC state under the run directory

Each successful run is written beneath:

- `artifacts/mcp-client-validation/`

## Current Interpretation

What this validation proves:

- `mc mcp-serve` now closes the standard JSON-RPC MCP handshake required by the official Inspector client
- the server exposes host tools and approval tools in a format accepted by a standard MCP client
- the approval-mediated mutation path works through a real external client, not only through direct line tests

What this validation does not prove:

- every desktop MCP client UX is identical
- GUI-oriented client affordances are already documented well enough for operators
- the broader tool schema governance work is complete

## Remaining Gap

The remaining MCP evidence gap is narrower now:

- a desktop-specific transcript such as Claude Desktop is still useful follow-up evidence
- but the project is no longer blocked on "no real MCP client validation at all"
