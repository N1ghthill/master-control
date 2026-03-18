# Project Status

Snapshot date: 2026-03-17

## Maturity

- Stage: late alpha
- Progress against the narrow MVP: roughly 90% to 95%
- Primary gap: the core workflow is validated; the main remaining work is release hardening and alpha packaging hygiene
- Provider integration note: the Ollama path is now validated against a real local server and installed model, not only tests and fake transports
- Local model baseline: `qwen2.5:7b` is the current default profile for the alpha track

## What is already implemented

### Foundation

- modular Python monolith with `src/` layout
- SQLite bootstrap and local state directory
- architecture, security, roadmap, and ADR documentation
- audit trail for plans, executions, provider errors, and recommendation status updates

### Conversational core

- CLI chat loop
- provider abstraction
- heuristic planner for offline development
- OpenAI Responses API adapter for structured planning
- Ollama chat adapter for local structured planning
- local-first auto provider resolution: `ollama -> openai -> heuristic`
- structured execution plans instead of free-form tool calls
- iterative per-turn planning loop that can continue a diagnosis using fresh tool outputs
- provider health reporting in `mc doctor`, including local Ollama endpoint and model availability
- LLM-backed final response synthesis for OpenAI and Ollama after tool execution

### Linux inspection tools

- `system_info`
- `disk_usage`
- `memory_usage`
- `top_processes`
- `service_status`
- `read_journal`
- `read_config_file`

### Memory and recommendations

- persistent chat sessions
- local conversation history
- provider continuation state for supported backends
- compact deterministic session summaries
- session-scoped observations with TTL-based freshness state
- deterministic session insights
- persistent recommendation queue with lifecycle states
- recommendations that degrade to refresh actions when the underlying signal is stale
- recommendation listings now expose signal freshness and confidence to the operator
- recommendation ordering now prioritizes fresh signals over stale ones
- explicit recommendation reconciliation is available through CLI and chat command paths
- optional `systemd` timer installation is available for periodic `mc reconcile --all`

### Safe mutations started

- privileged `restart_service` tool
- `reload_service` as a lower-risk service action
- optional `scope=user` support for service tools
- `write_config_file` with backup, validation, and atomic replace
- `restore_config_backup` for rollback from managed backups
- policy decision returned for every tool call
- explicit confirmation gate for privileged execution
- explicit approval hints with next CLI and chat commands
- recommendation actions that still pass through the same policy and audit path

## What is still missing for the MVP

The current MVP target is not "full Linux admin agent". It is a smaller milestone:

- single-host CLI agent
- structured planning
- useful inspection tools
- persistent memory
- auditable recommendation workflow
- a minimal but real mutation path with approval

Remaining work to close that MVP:

1. tighten release hygiene for a first tagged alpha
2. decide whether to freeze the current narrow MVP as complete or add one more operator-friendly approval improvement before tagging

Alpha release material now available:

- `docs/alpha-validation-report.md`
- `docs/alpha-release-notes.md`

## What is intentionally out of scope right now

- web UI
- voice interface
- Slack or Discord integrations
- vector memory
- multi-user auth and remote deployment
- daemon mode and public API

## Validation baseline

At this snapshot, the project is validated by:

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall src`
- manual CLI smoke checks for chat, recommendations, and recommendation-triggered actions
- manual CLI smoke checks for `reconcile-timer render|install|remove`
- manual CLI smoke checks for managed config write with validation and backup
- automated coverage for observation freshness and stale-context refresh behavior
- real-host validation of `service_status`, `reload_service`, and `restart_service` on `systemd --user`
- real-host validation of `service_status`, `reload_service`, and `restart_service` on system-scoped units
- real-host validation of `reconcile-timer install|remove` on `systemd --user`
- real-host validation of managed config read/write/restore on a file under `<MC_STATE_DIR>/managed-configs/`
