# Operator Workflows

Snapshot date: 2026-03-22

## Purpose

This document records the bounded operator workflows that currently define the post-MVP useful baseline for Master Control.

Each workflow below is intentionally small, typed, and auditable.
They describe runtime-supported operator paths; the same runtime may be reached through direct CLI commands, the optional chat interface, or the current experimental read-only MCP bridge where appropriate.

## Workflow 1: Slow Host Diagnosis

Goal:

- move from "the host feels slow" to current typed evidence and a safe next diagnostic step

Expected evidence chain:

1. `memory_usage`
2. `top_processes`
3. `process_to_unit` when the hottest process still needs `systemd` correlation
4. `service_status` only when there is explicit service evidence or typed process -> service-unit correlation

Current behavior guarantees:

- transient collector noise such as the `ps` helper is filtered out before process recommendations are derived
- repeated commands in the rendered top-process view are grouped with counts so the operator sees a cleaner lead
- non-service correlations such as `.scope` remain evidence, but do not escalate into `service_status`
- when a hot process already maps to a service unit, the recommendation layer can now move directly to `service_status`
- when a generic interpreter dominates the top list, the slow-host path can prefer a nearby service-relevant process as the next `process_to_unit` lead

Repeatable smoke path:

```bash
MC_PROVIDER=heuristic PYTHONPATH=src python3 -m master_control --json chat --new-session --once "o host esta lento"
```

Useful follow-up checks:

```bash
PYTHONPATH=src python3 -m master_control --json observations
PYTHONPATH=src python3 -m master_control --json recommendations
```

Dead ends and safety boundaries:

- do not infer a service action from a hot process alone
- do not treat generic user/session scopes as restartable services
- refresh stale memory, process, or service signals before trusting them

## Workflow 2: Failed Service Triage

Goal:

- turn a failed-unit listing into a concrete triage path instead of a dead-end list

Expected evidence chain:

1. `failed_services`
2. `service_status` on the first actionable failed unit
3. `read_journal` for evidence before intervention
4. `restart_service` or `reload_service` only through explicit approval

Current behavior guarantees:

- a fresh failed-services observation can now produce a direct `service_status` recommendation
- once a service is confirmed unhealthy, the recommendation layer now pushes the operator toward `read_journal` when matching log evidence is missing or stale
- recommendation rendering keeps the operator on an explicit accept -> confirm -> execute path
- stale failed-service listings degrade to a refresh recommendation instead of a stale action

Repeatable smoke path:

```bash
MC_PROVIDER=heuristic PYTHONPATH=src python3 -m master_control --json chat --new-session --once "quais servicos com falha eu tenho?"
```

If the host has no failed units, validate the typed tool path directly:

```bash
PYTHONPATH=src python3 -m master_control --json tool failed_services --arg scope=system --arg limit=5
```

Useful follow-up checks:

```bash
PYTHONPATH=src python3 -m master_control --json recommendations
PYTHONPATH=src python3 -m master_control --json insights
```

Dead ends and safety boundaries:

- listing failed units is not the same thing as approving a restart
- the operator should inspect status/log evidence before any privileged action
- if the signal is stale, refresh it first

## Workflow 3: Managed Config Change And Rollback

Goal:

- keep the bounded config path readable, validated, recoverable, and easy to roll back

Expected evidence chain:

1. `read_config_file`
2. `write_config_file` with validation and managed backup
3. confirmation-gated rollback via `restore_config_backup`
4. optional post-change verification through a follow-up read or service inspection

Current behavior guarantees:

- config target, validation kind, and last backup path are now preserved in session summary/context
- a recent managed backup creates a rollback recommendation in session insights
- recent `write_config_file` and `restore_config_backup` actions now create an explicit `read_config_file` verification follow-up
- natural-language follow-up such as `desfaça a última mudança` can now map to `restore_config_backup`

Controlled smoke path:

```bash
export MC_PROVIDER=heuristic
export MC_STATE_DIR=/tmp/mc-workflow-smoke
export MC_DB_PATH=/tmp/mc-workflow-smoke/mc.sqlite3
mkdir -p "$MC_STATE_DIR/managed-configs"
printf '[service]\nmode=old\n' > "$MC_STATE_DIR/managed-configs/service.ini"
PYTHONPATH=src python3 -m master_control --json tool read_config_file --arg path="$MC_STATE_DIR/managed-configs/service.ini"
PYTHONPATH=src python3 -m master_control --json tool write_config_file --arg path="$MC_STATE_DIR/managed-configs/service.ini" --arg content=$'[service]\nmode=new\n' --confirm
PYTHONPATH=src python3 -m master_control --json chat --new-session --once "desfaça a última mudança"
```

Useful follow-up checks:

```bash
PYTHONPATH=src python3 -m master_control --json recommendations
PYTHONPATH=src python3 -m master_control --json observations
```

Dead ends and safety boundaries:

- only managed config targets are writable
- rollback still requires explicit confirmation
- validation remains part of both write and restore paths

## Current Exit Assessment

For the selected post-MVP workflows, the repository now has:

- deterministic regression coverage
- repeatable smoke commands in one document
- explicit evidence chains and safety boundaries
- typed next-step recommendations that are closer to operator intent
