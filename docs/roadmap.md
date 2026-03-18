# Roadmap

Snapshot date: 2026-03-18

## Current stage

- late alpha
- foundation, read-only inspection, session memory, provider integration, recommendation tracking, and first mutation workflows are in place
- service trust hardening is now in place for the current recommendation boundary
- structured session state and orchestration refactor is now in place for the core decision paths
- operator utility, approval UX, and alpha hardening are now closed for the narrow local CLI MVP
- the local alpha baseline is ready for tagging on the validated host profile
- the selected post-MVP operator workflows now have documented smoke paths and deterministic coverage
- the current local alpha profile is `qwen2.5:7b`
- detailed sequencing and result targets live in `docs/mvp-evolution-plan.md`
- the closed execution record lives in `docs/mvp-closeout-backlog.md`
- the active post-MVP planning record now lives in `docs/post-mvp-evolution-plan.md`
- post-MVP Milestone P1 (trust and baseline stabilization) completed on 2026-03-18
- post-MVP Milestone P2 (workflow depth and operator usefulness) completed on 2026-03-18

## Phase 0: Foundation

Status:

- Completed

Deliverables:

- repository structure
- architecture and security documents
- ADRs for major early decisions
- Python package bootstrap
- local SQLite initialization
- policy engine and initial tool registry

## Phase 1: Read-only Linux introspection

Deliverables:

- `disk_usage`
- `memory_usage`
- `top_processes`
- `service_status`
- `read_journal`
- chat loop wired to a provider abstraction

Status:

- Completed for the narrow MVP slice

Current state:

- read-only tools are implemented
- the chat loop is wired to a structured heuristic provider
- an OpenAI Responses API provider is implemented
- multi-turn session context is persisted locally
- provider continuation state is persisted when supported
- audit events are stored for each execution

Exit criteria:

- tool outputs are structured and testable
- all tools have clear risk levels
- audit events are persisted for each execution

Result:

- Exit criteria met

## Phase 2: Safe mutations

Status:

- Implemented for the current MVP slice; the current service trust boundary is hardened

Deliverables:

- confirmation flow for mutating tools
- config write helpers with backup and validation
- service restart and reload tools
- approval prompts in the CLI

Current state:

- `restart_service` is implemented as the first privileged tool
- `reload_service` is implemented as a lower-risk service action
- service tools can target either system scope or `systemd --user` through `scope=user`
- direct tool execution and recommendation actions both require explicit confirmation
- recommendation actions cannot execute until the recommendation is accepted
- managed config read, write, validation, backup, and restore are implemented for bounded targets

Exit criteria:

- no mutation happens without a visible policy decision
- rollback paths exist for config changes

## Phase 3: MVP closeout

Status:

- Completed on 2026-03-18

Current state:

- the memory, recommendation, and provider foundations are in place
- Workstreams 3A, 3B, 3C, and 3D are closed
- the narrow local CLI MVP now has its intended operator utility, approval UX, and alpha release baseline
- future work now moves to post-MVP phases, not back into closeout rework

### Workstream 3A: Correctness and context hardening

Status:

- Completed on 2026-03-18 for the current service recommendation boundary

Deliverables:

- evidence-gated service recommendations
- end-to-end preservation of service scope
- regression tests for process/service correlation and scope handling

Exit criteria:

- no mutating service recommendation is derived from unsupported inference alone
- service target identity is preserved through recommendation and execution paths

### Workstream 3B: Structured session state and orchestration refactor

Status:

- Completed on 2026-03-18

Deliverables:

- structured session context for planners and recommendations
- reduced dependence on text-parsed summary state
- clearer app-layer boundaries

Exit criteria:

- high-risk recommendation decisions no longer depend primarily on summary parsing
- hotspot files have narrower responsibilities

### Workstream 3C: Operator utility and approval UX

Status:

- Completed on 2026-03-18

Deliverables:

- a small set of high-value read-only tools
- clearer recommendation evidence and confirmation guidance
- lower-friction recommendation lifecycle

Exit criteria:

- the main diagnostic journeys produce evidence-rich next steps
- recommendation -> accept -> confirm -> execute remains explicit and auditable

Result:

- `process_to_unit` and `failed_services` were added to the typed read-only toolset
- slow-host diagnosis can now chain memory -> processes -> process correlation -> service status when correlation evidence exists
- recommendation and approval output now render evidence summaries and next-step commands directly

### Workstream 3D: Alpha hardening and release baseline

Status:

- Completed on 2026-03-18

Deliverables:

- documentation synchronization
- final validation rerun
- clean-environment install and packaging sanity checks

Exit criteria:

- canonical documents describe the same MVP closeout order
- release checklist is green for the intended alpha scope

Result:

- canonical docs were synchronized to the closed MVP state
- automated baseline, real-host smokes, and clean-environment install validation were rerun successfully

## Phase 4: Service mode and external interfaces

Status:

- Not started

Deliverables:

- long-running daemon mode
- HTTP or websocket API
- web UI or chat integrations
- richer observability

Exit criteria:

- interface layer is separate from execution core
- all external interfaces reuse the same policy and audit paths

## Next roadmap focus

The MVP closeout is complete. The next roadmap track is:

1. service mode and external interfaces
2. broader post-alpha hardening
3. incremental operator utility beyond the narrow MVP baseline

The current execution recommendation after Milestone P2 is to rerun the documented operator workflows on more host profiles before broader interface expansion. See `docs/post-mvp-evolution-plan.md` and `docs/operator-workflows.md`.
