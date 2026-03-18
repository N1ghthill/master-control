# Alpha Release Notes

Version target: `0.1.0a1` local CLI alpha baseline

Snapshot date: 2026-03-18

## What this alpha includes

- CLI-first conversational Linux agent
- structured provider contract with `heuristic`, `ollama`, `openai`, and `auto`
- local session memory and audit trail in SQLite
- typed inspection tools for host, disk, memory, processes, process correlation, failed-service listing, service status, journal, and managed config reads
- approval-gated mutation tools for service restart, service reload, config write, and config restore
- recommendation lifecycle with explicit acceptance before action execution
- a hardened service recommendation boundary that requires explicit service evidence and preserves `scope=user|system`
- structured session context for high-risk follow-ups and recommendation generation
- operator-facing recommendation evidence and next-step commands in both chat and CLI

## Local LLM baseline

- default local Ollama model: `qwen2.5:7b`
- current validated host setup: `MC_OLLAMA_BASE_URL=http://127.0.0.1:11435/api`

## Service operations

Supported typed operations:

- `service_status`
- `reload_service`
- `restart_service`

Supported scopes:

- default system scope
- optional `scope=user` for `systemd --user`

Alpha validation status:

- `scope=user` is validated on a real host
- system scope is also validated on a real host through a temporary root-scoped validation unit
- system-scoped mutation still depends on the target host having a usable elevation path

## Managed config operations

Supported:

- `read_config_file`
- `write_config_file`
- `restore_config_backup`

Default managed targets:

- `<MC_STATE_DIR>/managed-configs/*.ini`
- `<MC_STATE_DIR>/managed-configs/*.cfg`
- `<MC_STATE_DIR>/managed-configs/*.json`
- `/etc/systemd/system/*.service`
- `/etc/systemd/system/*.timer`

## Known limitations

- no web UI
- no voice interface
- no multi-user auth
- no daemon/API layer
- no generic shell execution surface in the agent core
- no full production hardening yet
- the alpha scope remains intentionally single-host and CLI-first

## Recommended operator baseline

```bash
export MC_PROVIDER=auto
export MC_OLLAMA_BASE_URL=http://127.0.0.1:11435/api
mc doctor
mc chat --once "mostre o uso de memoria"
mc tool process_to_unit --arg name=python3
mc tool failed_services --arg scope=system --arg limit=5
mc tool service_status --arg name=ollama-local.service --arg scope=user
```

## Validation reference

See `docs/alpha-validation-report.md` for the real-host validation snapshot behind this alpha baseline.
