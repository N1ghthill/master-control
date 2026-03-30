# Changelog

## Unreleased

### Added

- product maturity assessment document for evaluating MC as a real public product
- real `.pre-commit-config.yaml` so contributor setup matches the documented local workflow
- Apache-2.0 `LICENSE`
- `SUPPORT.md` for public support scope and compatibility expectations
- `SECURITY.md` for vulnerability reporting and supported-version policy
- `CODE_OF_CONDUCT.md` for public collaboration expectations
- `dependabot` automation for Python and GitHub Actions updates
- structured `SessionContext` for the core high-risk planner and recommendation paths
- extracted session-analysis seam for summary -> context -> insight assembly outside the central app orchestrator
- repeatable host-profile validation harness and guide for collecting multi-host workflow evidence
- `process_to_unit` as a typed read-only process -> `systemd` correlation tool
- `failed_services` as a typed read-only failed-unit listing tool
- extracted turn-planning, turn-rendering, and recommendation-view helpers from the central app layer
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
- `reconcile-timer render|install|remove` commands for optional periodic recommendation maintenance through `systemd`
- final response synthesis for `openai` and `ollama` after tool execution
- explicit planning decisions for provider turns: `needs_tools`, `complete`, `blocked`
- typed planning decision kinds plus final turn classification
- deterministic final-message guidance keyed off turn classification
- repository hardening with `ruff`, `mypy`, `pre-commit`, and GitHub templates
- official MCP Inspector CLI validation harness in `scripts/validate_mcp_client.py`
- MCP approval tools for standard clients: `approval_list`, `approval_get`, `approval_approve`, and `approval_reject`

### Changed

- interface-owned planning, rendering, session-summary, and tool-result helpers now live under `master_control.interfaces.agent.*`, while `master_control.agent.*` remains a compatibility namespace
- CI now runs Bandit and a wheel-build smoke in addition to lint, typecheck, tests, and runtime validation
- Python support floor is now `3.11+` instead of `3.13+`
- README now leads with the operator journey and repository policy instead of only architectural posture
- host validation baseline commands now execute without `shell=True`
- provider endpoints now require `http` or `https` before any network call is attempted
- production tool paths no longer rely on `assert` for runtime argument guarantees
- generated `artifacts/` output is now ignored by git
- the narrow local CLI MVP closeout is now complete for the alpha baseline
- slow-host diagnosis can now chain memory, processes, process correlation, and service status when correlation evidence exists
- hot-process follow-up logic no longer relies on guessed service identity and can use typed correlation evidence instead
- hot-process selection now filters collector noise from transient `ps` helper processes before recommendations are derived
- slow-host lead selection can now prefer a nearby service-relevant process over generic interpreter noise before `process_to_unit`
- process-correlation no-match state now persists through session context so the recommendation layer does not repeat failed correlation attempts
- heuristic service follow-ups no longer treat non-service `systemd` units such as `.scope` as valid `service_status` targets
- operator-facing top-process rendering now collapses repeated commands so slow-host output is less noisy
- operator-facing top-process rendering now groups repeated commands with counts instead of flattening them silently
- failed-service observations can now drive a direct `service_status` follow-up recommendation
- unhealthy-service follow-ups now recommend `read_journal` when matching log evidence is missing or stale
- managed config summary/context now preserves target, validation, and backup metadata for later rollback
- natural-language rollback follow-ups can now plan `restore_config_backup` from tracked session context
- managed config writes and restores now produce an explicit `read_config_file` verification follow-up
- recommendation and approval rendering now expose evidence summaries, freshness, target identity, and next-step commands
- MVP closeout documents were rewritten as completion records instead of leaving an active milestone backlog behind
- alpha validation now includes clean-environment install via `virtualenv`, real-host operator-utility smokes, workflow guidance docs, and 123 automated tests
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
- recommendation state can now be reconciled explicitly without a new chat turn
- recommendation maintenance can now be scheduled through generated `systemd` user or system units
- chat responses on LLM-backed providers now prefer a model-synthesized final answer, with deterministic local fallback on synthesis failure
- planning no longer relies only on empty/non-empty step arrays; decision state is now explicit in provider output and audit
- chat payloads and audit now distinguish planner intent from final turn outcome, including missing safe tools and confirmation waits
- blocked or partial turns now return clearer operator guidance instead of relying only on provider prose
- CI now enforces lint and typecheck in addition to tests and smoke validation
- `mc mcp-serve` now closes the standard JSON-RPC MCP handshake expected by real clients
- MCP stdio now exposes approval resolution through standard `tools/list` and `tools/call`, not only through custom approval methods
- tool approvals now deduplicate active action envelopes and block duplicate in-flight execution for the same pending action
- release-facing docs and gates now reflect the latest VPS rerun and the Inspector-backed MCP validation path

### Notes

- the repository is still pre-release
- the current unreleased target is the `0.1.0a2` release candidate documented in `docs/history/release-candidate-0.1.0a2.md`
- the narrow local CLI MVP is closed for the current alpha baseline
- the project is not yet a production-ready Linux operations platform

## 0.1.0a1 - 2026-03-17

Initial public alpha baseline.

### Highlights

- local CLI conversational Linux agent with typed tools and policy-gated mutations
- local-first provider stack with `ollama`, `openai`, `heuristic`, and `auto`
- host-validated service operations for both `system` and `scope=user`
- managed config read, write, backup, validation, and restore flow
- SQLite-backed memory, audit trail, recommendations, and session summaries
