# Changelog

## Unreleased

### Added

- modular Python scaffold for Master Control
- CLI-first application bootstrap
- SQLite-backed session, summary, recommendation, and audit storage
- structured planning contract with heuristic and OpenAI providers
- read-only inspection tools for host, disk, memory, processes, services, and journal logs
- deterministic session summary and insight generation
- persistent recommendation queue with lifecycle tracking
- first privileged action tool, `restart_service`
- recommendation actions gated by acceptance, policy, and explicit confirmation
- `reload_service` as a second service operation
- managed config tools: `read_config_file`, `write_config_file`, and `restore_config_backup`
- approval hints that return the exact next CLI and chat command
- end-to-end tests for recommendation-driven service actions and config rollback
- Ollama provider for local structured planning
- iterative per-turn planning so the agent can continue a diagnosis with fresh tool results
- provider health checks in `mc doctor`, including Ollama endpoint and model availability
- session-scoped observation persistence with TTL-based freshness

### Changed

- project documentation now reflects the current alpha stage instead of the initial scaffold stage
- roadmap now separates completed foundation work from the remaining MVP closeout work
- the project now reads as a late-alpha MVP candidate rather than an early scaffold
- `MC_PROVIDER=auto` now resolves providers in local-first order: `ollama -> openai -> heuristic`
- the Ollama operational docs now cover explicit `MC_OLLAMA_BASE_URL` overrides and a user-local install path without sudo
- the default Ollama profile for the alpha track is now `qwen2.5:7b`
- service tools now support `scope=user` for `systemd --user` operations and validation
- alpha release docs now include a real-host validation report and release notes baseline
- stale session observations can now trigger refresh-oriented planning instead of relying on old summaries
- recommendations now degrade to refresh actions when the underlying signal is stale
- recommendation listings now expose signal freshness/confidence in the operator surface
- recommendation ordering now prioritizes fresh signals over stale ones

### Notes

- the repository is still pre-release
- the current milestone is a narrow local CLI MVP, not a production-ready Linux operations platform

## 0.1.0a1 - 2026-03-17

Initial public alpha baseline.

### Highlights

- local CLI conversational Linux agent with typed tools and policy-gated mutations
- local-first provider stack with `ollama`, `openai`, `heuristic`, and `auto`
- host-validated service operations for both `system` and `scope=user`
- managed config read, write, backup, validation, and restore flow
- SQLite-backed memory, audit trail, recommendations, and session summaries
