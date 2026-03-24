# Policy Guide

Snapshot date: 2026-03-23

## Purpose

This guide documents the first operator-configurable policy slice for Master Control.

The policy file lets an operator narrow tool access and managed config targets without editing Python.
It does not introduce RBAC or multi-user authorization.

## Policy File Location

Default path:

- `MC_STATE_DIR/policy.toml`

Override:

- `MC_POLICY_PATH=/path/to/policy.toml`

Runtime behavior:

- missing policy file: fall back to the default safe policy
- invalid policy file: fail closed for tool execution
- policy load state is visible through `mc doctor`

## Supported Domains

Current version:

- `version = 1`

Supported tool rule fields under `[tools.<tool_name>]`:

- `enabled = true|false`
- `require_confirmation = true|false`
- `allowed_scopes = ["system", "user"]`
- `service_patterns = ["nginx.service", "*.service"]`

Supported managed target fields under `[[config_targets]]`:

- `name`
- `description`
- `roots`
- `file_globs`
- `validator`
- `validator_command` only when `validator = "command"`

Current validators:

- `ini_parse`
- `json_parse`
- `command`

## Example

```toml
version = 1

[tools.system_info]
require_confirmation = true

[tools.restart_service]
allowed_scopes = ["system"]
service_patterns = ["nginx.service", "sshd.service"]

[[config_targets]]
name = "managed_ini"
description = "Operator-managed INI files under state."
roots = ["$STATE_DIR/managed-configs"]
file_globs = ["*.ini", "*.cfg"]
validator = "ini_parse"

[[config_targets]]
name = "systemd_unit"
description = "Systemd units under /etc/systemd/system."
roots = ["/etc/systemd/system"]
file_globs = ["*.service", "*.timer"]
validator = "command"
validator_command = ["systemd-analyze", "verify", "{path}"]
```

## Path Rules

- `$STATE_DIR` expands to the resolved MC state directory
- relative `roots` are resolved from the policy file directory
- confirmation rules may add confirmation to safer tools, but they do not weaken built-in confirmation for risky tools

## Operational Notes

- use `mc doctor` after every policy change
- invalid policy blocks execution until fixed
- keep target roots narrow and validators explicit
- broader package, network, and user-management policy domains are later work
