# Adaptive Intelligence Spec

## Scope

This document specifies three components to push MasterControl from static context to adaptive operational intelligence:

- `mc-operator-profiler`
- `mc-tone-analyzer`
- `mc-dream`

All data is local-only (SQLite). No telemetry leaves the machine.

## 1) mc-operator-profiler

### Goal

Capture operator behavior patterns beyond Unix identity and make them usable by `PathSelector` and `SoulKernel`.

### Inputs

- Operator command intent text.
- Chosen path (`fast`, `deep`, `fast_with_confirm`).
- Risk level.
- Success/failure.
- Optional command error marker.
- Optional forced-path marker.

### SQLite tables

`command_events`

- `id INTEGER PRIMARY KEY`
- `ts_utc TEXT NOT NULL`
- `operator_id TEXT NOT NULL`
- `intent_text TEXT NOT NULL`
- `intent_cluster TEXT NOT NULL`
- `risk_level TEXT NOT NULL`
- `selected_path TEXT NOT NULL`
- `success INTEGER NOT NULL`
- `latency_ms INTEGER NOT NULL`
- `command_error TEXT NOT NULL DEFAULT ''`
- `forced_path INTEGER NOT NULL DEFAULT 0`
- `incident INTEGER NOT NULL DEFAULT 0`

`operator_patterns`

- `operator_id TEXT PRIMARY KEY`
- `active_hours TEXT NOT NULL`
- `common_intents TEXT NOT NULL` (JSON array)
- `error_prone_commands TEXT NOT NULL` (JSON array)
- `path_preference TEXT NOT NULL`
- `tone_sensitivity REAL NOT NULL`
- `updated_at TEXT NOT NULL`

### Outputs

Profile snapshot:

- active time window
- common intents
- error-prone intents
- path preference (`fast_default`, `deep_when_uncertain`, `balanced`)
- tone sensitivity score

## 2) mc-tone-analyzer

### Goal

Infer urgency and operator tone quickly without invoking heavy LLM.

### Modes

- `heuristic` (default, no external dependency)
- `transformer` (optional, local model if configured)

### Output schema

- `tone`: `urgent | exploratory | routine | incident`
- `confidence`: `0.0..1.0`
- `intent_cluster`: e.g. `dns.flush`, `service.restart`, `package.manage`
- `frustration_score`: `0.0..1.0`

### Integration

`mastercontrold` uses this output before path selection:

- urgent + medium risk can remain quick but with `fast_with_confirm`.
- incident tone can promote to `deep`.

## 3) mc-dream

### Goal

Offline reflection job (nightly) that compresses recurrent usage patterns into actionable suggestions.

### Trigger

Recommended via `systemd timer` at low activity hours.

### SQLite table

`dream_insights`

- `id INTEGER PRIMARY KEY`
- `ts_utc TEXT NOT NULL`
- `operator_id TEXT NOT NULL`
- `insight_type TEXT NOT NULL`
- `payload_json TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'new'`

### Insight types

- `pattern_repetition`
- `risk_correction`
- `error_hotspot`

### Guarantee

Insights are suggestions only. Never execute actions automatically.

## Integration contract with core

`mastercontrold` flow:

1. parse intent
2. tone analyze
3. load operator profile
4. path select with profile + tone hints
5. plan + execute
6. reflection
7. record event in profiler

## Performance target

- tone analysis (heuristic): < 5 ms
- profile read: < 10 ms
- path selection: < 2 ms
- total overhead for adaptive layer: < 25 ms (p95 local)

