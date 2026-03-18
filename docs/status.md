# Project Status

Snapshot date: 2026-03-18

## Maturity

- Stage: late alpha
- Progress against the narrow MVP: complete for the local alpha baseline
- Primary gap: future work is now post-MVP: broader production hardening, service mode, and external interfaces
- Provider integration note: the Ollama path is now validated against a real local server and installed model, not only tests and fake transports
- Local model baseline: `qwen2.5:7b` is the current default profile for the alpha track
- MVP closeout record: `docs/mvp-evolution-plan.md`
- MVP closeout backlog record: `docs/mvp-closeout-backlog.md`
- Active post-MVP planning record: `docs/post-mvp-evolution-plan.md`
- Active operator workflow guide: `docs/operator-workflows.md`
- Active beta gate: `docs/beta-readiness-gate.md`
- Milestone note: service recommendation trust hardening completed on 2026-03-18
- Milestone note: structured session state and orchestration refactor completed on 2026-03-18
- Milestone note: operator utility and approval UX completed on 2026-03-18
- Milestone note: alpha hardening and release baseline completed on 2026-03-18
- Milestone note: post-MVP trust and baseline stabilization completed on 2026-03-18
- Milestone note: post-MVP workflow depth and operator usefulness completed on 2026-03-18
- Narrow local CLI MVP closeout: completed on 2026-03-18

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
- explicit planning decisions (`needs_tools`, `complete`, `blocked`) across the provider contract and audit trail
- typed decision kinds and final `turn_decision` classification for confirmation waits, missing tools, refreshes, and evidence-backed completion
- deterministic final-message guidance driven by `turn_decision`
- structured session context passed to providers for high-risk follow-ups and recommendations
- turn-planning, turn-rendering, and recommendation-view seams extracted from the central app layer
- heuristic slow-host diagnosis now ignores non-service `systemd` correlations when deciding whether a `service_status` step is valid
- rendered hot-process output now collapses repeated commands so slow-host diagnosis is less noisy in operator-facing output

### Linux inspection tools

- `system_info`
- `disk_usage`
- `memory_usage`
- `top_processes`
- `process_to_unit`
- `service_status`
- `failed_services`
- `read_journal`
- `read_config_file`
- `top_processes` now filters collector noise from the current MC process tree and transient `ps` helper invocations

### Memory and recommendations

- persistent chat sessions
- local conversation history
- provider continuation state for supported backends
- compact deterministic session summaries
- structured session context derived from tracked entities, observations, and freshness
- session-scoped observations with TTL-based freshness state
- deterministic session insights
- persistent recommendation queue with lifecycle states
- recommendations that degrade to refresh actions when the underlying signal is stale
- recommendation listings now expose signal freshness and confidence to the operator
- recommendation ordering now prioritizes fresh signals over stale ones
- explicit recommendation reconciliation is available through CLI and chat command paths
- optional `systemd` timer installation is available for periodic `mc reconcile --all`
- high-risk recommendation decisions no longer depend primarily on summary parsing
- recommendation views expose evidence summaries, confidence, and next-step commands directly to the operator
- process-correlation no-match state is now preserved in session context so hot-process recommendations do not repeat failed correlation attempts
- failed-service observations can now drive a direct `service_status` follow-up recommendation
- unhealthy-service recommendations now request `read_journal` when matching log evidence is missing or stale
- recent managed config backups now stay visible in session context so rollback can be planned from natural-language follow-ups
- recent managed config writes and restores now surface a `read_config_file` verification follow-up

### Safe mutations started

- privileged `restart_service` tool
- `reload_service` as a lower-risk service action
- optional `scope=user` support for service tools
- `write_config_file` with backup, validation, and atomic replace
- `restore_config_backup` for rollback from managed backups
- natural-language rollback follow-ups can now map back to the tracked managed backup for the current session
- policy decision returned for every tool call
- explicit confirmation gate for privileged execution
- explicit approval hints with next CLI and chat commands
- recommendation actions that still pass through the same policy and audit path

## MVP closeout result

The current MVP target is not "full Linux admin agent". It is a smaller milestone:

- single-host CLI agent
- structured planning
- useful inspection tools
- persistent memory
- auditable recommendation workflow
- a minimal but real mutation path with approval

That narrow MVP closeout is now complete for the local alpha baseline.

Work that remains beyond this MVP closeout:

1. broader post-alpha diagnostics beyond the current typed-tool set
2. daemon/API and external interface work
3. production hardening beyond the current single-host alpha scope

Alpha release material now available:

- `docs/alpha-validation-report.md`
- `docs/alpha-release-notes.md`
- `docs/mvp-evolution-plan.md`
- `docs/operator-workflows.md`
- `docs/beta-readiness-gate.md`

## What is intentionally out of scope right now

- web UI
- voice interface
- Slack or Discord integrations
- vector memory
- multi-user auth and remote deployment
- daemon mode and public API

## Validation baseline

At this snapshot, the project is validated by:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m pytest -q`
- `python3 -m compileall src`
- manual CLI smoke checks for chat, recommendations, and recommendation-triggered actions
- manual CLI smoke checks for `reconcile-timer render|install|remove`
- manual CLI smoke checks for managed config write with validation and backup
- manual CLI smoke checks for `process_to_unit` and `failed_services`
- automated coverage for observation freshness and stale-context refresh behavior
- real-host validation of `service_status`, `reload_service`, and `restart_service` on `systemd --user`
- real-host validation of `service_status`, `reload_service`, and `restart_service` on system-scoped units
- real-host validation of `reconcile-timer install|remove` on `systemd --user`
- real-host validation of managed config read/write/restore on a file under `<MC_STATE_DIR>/managed-configs/`
- clean-environment install validation via `python3 -m virtualenv`, `pip install -e .`, and `mc doctor`
- repository hygiene baseline with `ruff`, `mypy`, `pre-commit`, CI lint/typecheck, and GitHub issue/PR templates
- current local rerun after post-MVP workflow depth work: `python3 -m unittest discover -s tests` and `python3 -m pytest -q` passed with 120 tests alongside green `ruff`, `mypy`, `compileall`, and `mc doctor`
