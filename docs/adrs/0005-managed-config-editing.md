# ADR 0005: Managed config editing uses bounded targets with validation and backup

Status: Accepted
Date: 2026-03-17

## Context

The MVP needs at least one real configuration editing workflow, but unrestricted file writes would break the project's security model.

The system needs a path for editing configs that is:

- bounded to known targets
- validated before apply
- auditable
- reversible

## Decision

Expose config editing through typed tools only:

- `read_config_file`
- `write_config_file`
- `restore_config_backup`

These tools are constrained to managed targets:

- `<MC_STATE_DIR>/managed-configs/*.ini`
- `<MC_STATE_DIR>/managed-configs/*.cfg`
- `<MC_STATE_DIR>/managed-configs/*.json`
- `/etc/systemd/system/*.service`
- `/etc/systemd/system/*.timer`

Writes must:

- create a managed backup when replacing an existing file
- validate the candidate content before apply
- use atomic replace semantics where feasible
- keep the same policy and audit path as any other tool

## Consequences

Positive:

- the project gains a real config workflow without opening generic file write access
- rollback becomes concrete through managed backups
- testing stays deterministic through the managed state directory targets

Negative:

- the default target set is intentionally narrow
- adding new config domains requires explicit policy and validator design
