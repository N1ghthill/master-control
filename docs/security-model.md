# Security Model

## Security posture

Master Control is a high-risk runtime by definition because it sits close to the operating system.
The design must assume:

- interface input can be malformed or malicious
- model output can be wrong
- the host may contain sensitive data
- mistakes in execution can damage availability or integrity

## Security principles

- least privilege by default
- explicit approval for state-changing operations
- strong input validation at the tool boundary
- no hidden escalation path
- every action leaves an audit record

## Current implementation status

Already implemented:

- typed tool registry
- policy evaluation before every tool execution
- explicit confirmation requirement for mutating and privileged tools
- local audit trail for plan generation, tool execution, provider errors, and recommendation status changes
- bounded subprocess execution with `shell=False`, timeouts, and output truncation
- recommendation actions that still execute through the same policy path as direct tool calls
- managed config edit workflow with bounded targets, validation, backup, and restore

Important interpretation:

- the security boundary belongs to the runtime
- chat, planners, and providers are interface layers and must not bypass that boundary

Not implemented yet:

- per-user authentication and authorization
- path-scoped write allowlists
- maintenance windows
- remote execution identity model

## Risk classes

### `read_only`

Characteristics:

- does not change system state
- does not require elevation
- safe to run automatically within configured limits

Examples:

- read basic host metadata
- inspect resource usage
- read logs from approved sources

### `mutating_safe`

Characteristics:

- changes system state
- expected to be reversible or low blast radius
- should require user confirmation

Examples:

- restart a non-critical service
- write an application config with backup
- rotate a cache directory

### `privileged`

Characteristics:

- requires elevated privileges or has significant blast radius
- always requires explicit confirmation and strict validation

Examples:

- package installation
- edits under `/etc`
- service enable/disable
- user and permission changes

## Approval rules

- `read_only`: may execute automatically
- `mutating_safe`: requires user confirmation
- `privileged`: requires user confirmation and preflight validation

Important distinction:

- accepting a recommendation does not execute it
- executing a recommendation action still requires the same confirmation and policy path as a direct tool invocation

Future policy work may add:

- per-user roles
- path allowlists
- command allowlists
- maintenance windows

## Command execution constraints

If command execution is introduced, the executor must enforce:

- `shell=False`
- explicit argument lists
- timeout limits
- output truncation
- controlled environment variables
- optional cwd restrictions

The executor must never expose raw arbitrary shell execution as the default path.

## File operation rules

- read access should prefer allowlisted roots or explicit tool ownership
- writes must support backup, validation, and atomic replace when feasible
- sensitive paths must require elevated approval policy

Current managed write targets are intentionally narrow:

- `<MC_STATE_DIR>/managed-configs/*.ini`
- `<MC_STATE_DIR>/managed-configs/*.cfg`
- `<MC_STATE_DIR>/managed-configs/*.json`
- `/etc/systemd/system/*.service`
- `/etc/systemd/system/*.timer`

Backups are stored under `<MC_STATE_DIR>/config-backups/`.

## Audit events

At minimum, the system must record:

- session identifier
- user action
- selected tool
- policy decision
- execution outcome
- timestamp

Audit data should be easy to export and review locally.

## Near-term hardening priorities

- validate the current service and config targets on real hosts
- add more explicit approval state handling if host validation shows operator friction
- expand end-to-end tests around host-specific validators as needed
