# Post-MVP Evolution Plan

Snapshot date: 2026-03-18

## Purpose

This document starts the next planning track after the narrow local CLI MVP closeout.

It does not replace the closed MVP records:

- `docs/mvp-plan.md`: stable contract for the narrow local CLI MVP
- `docs/mvp-evolution-plan.md`: closed sequencing record for the MVP closeout
- `docs/mvp-closeout-backlog.md`: closed backlog record for the MVP closeout

Instead, this file defines the next professional engineering track for turning Master Control from a validated late-alpha baseline into a more functional, operator-useful product.

The goal of this track is not "more features at any cost". The goal is:

1. stabilize trust in the current operator journeys
2. improve the quality and usefulness of diagnosis
3. make validation and release posture reproducible
4. prepare the codebase and docs for a broader beta-oriented phase

## Executive Summary

Master Control has already proven the core thesis:

- typed tools can be the execution boundary
- policy and confirmation can stay explicit
- local auditability and session memory can improve operator workflows
- a modular Python monolith is a workable shape for the product

The current system is therefore a real MVP, not a mock.

However, the next barrier is no longer "can this architecture exist?".
The next barrier is "can an operator trust it enough to use it repeatedly for meaningful host workflows?".

The current baseline is strong in architecture and intent, but still uneven in three practical areas:

1. diagnostic trust
2. engineering rigor consistency
3. product usefulness in repeated day-to-day workflows

The next track should therefore prioritize trust and repeatable operator value before major interface expansion.

## Current Assessment

### Product assessment

Current strengths:

- narrow scope is clear and disciplined
- recommendation and approval flows are explicit
- CLI-first operator journeys already exist and are understandable
- session memory and freshness make the product more than a stateless tool wrapper

Current weaknesses:

- some "useful" flows can still produce low-quality or misleading evidence
- the recommendation loop is still narrow and can repeat low-value next steps
- the project is more "capable alpha" than "reliable daily tool"

### Engineering assessment

Current strengths:

- architecture is modular enough for continued iteration
- test coverage is good for the current project size
- security posture is coherent for a local alpha
- documentation quality is materially above average for this stage

Current weaknesses:

- hotspot orchestration files remain large
- the engineering baseline is green again for the checked environment, but that reproducibility still needs to hold across future changes
- real-host diagnosis is cleaner after Milestone P1, but still not yet rich enough for all workstation scenarios
- workflow depth and codebase ownership still need the next milestone

### Operational assessment

Current strengths:

- audit trail exists
- policy gate exists
- session and recommendation state exist
- real-host validation has already been done for critical bounded workflows

Current weaknesses:

- some runtime outputs still overfit to collection artifacts instead of operator intent
- release confidence depends too much on one validated host profile
- the quality bar is documented well, but not yet enforced consistently enough

## Primary Problem Statement

Master Control is already structured like a serious product, but it is not yet consistent enough to be trusted as a serious operator tool.

The next phase should close that gap by improving:

- evidence quality
- behavioral predictability
- release reproducibility
- operator workflow depth

## Guiding Principles

1. Trust before breadth.
   New capabilities should not outrun confidence in existing ones.

2. Evidence before action.
   Every recommendation or diagnosis step should be grounded in current, typed, host-local evidence.

3. Reproducibility before optimism.
   Validation must reflect what the repository actually passes now, not what it passed on a previous day or host.

4. Operator value before interface expansion.
   Better workflows on the CLI are more valuable right now than adding a daemon or UI too early.

5. Smaller seams over another central hotspot.
   New work should continue extracting domain and rendering logic away from central orchestration files.

6. Documentation is part of the release artifact.
   Plans, validation reports, and release claims must be updated in the same stream as behavior changes.

## Non-Goals For This Track

This track does not primarily target:

- web UI delivery
- public HTTP API delivery
- remote multi-user deployment
- broad privilege escalation frameworks
- generic shell execution inside the agent core
- premature microservice decomposition

Those can remain future roadmap items unless they become necessary to unlock the operator workflows described here.

## Baseline Gaps To Close First

### Gap A: Diagnostic trust still needs deeper refinement on real hosts

Observed issue:

- the current slow-host flow is cleaner after Milestone P1, but general workstation process lists can still surface technically valid yet low-context hot processes that are not always the most operator-useful lead

Why it matters:

- operator trust still depends on the diagnostic output feeling relevant, not only mechanically correct

Required outcome:

- the hottest-process path should continue improving ranking quality, correlation quality, and next-step usefulness for real workstation scenarios

### Gap B: Baseline reproducibility must stay enforced

Observed issue:

- Milestone P1 closed the immediate mismatch between docs and the checked baseline, but that discipline can regress if release-facing docs and validation reruns stop moving in the same stream as behavior changes

Why it matters:

- once validation claims drift again, release documents stop being reliable engineering artifacts

Required outcome:

- quality gates, docs, and CI expectations must continue matching the current repository state exactly

### Gap C: MVP workflows are useful, but still too narrow for repeated operator use

Observed issue:

- the system has a strong architecture, but only a small number of journeys feel complete enough for daily use

Why it matters:

- operator adoption depends less on architecture and more on whether the same few incidents are handled clearly, repeatedly, and safely

Required outcome:

- deepen a small number of common workflows until they feel dependable and complete

### Gap D: Engineering hotspots still slow safe iteration

Observed issue:

- orchestration and rendering logic still have concentration in large modules

Why it matters:

- this raises regression risk and makes future feature work harder to validate and review

Required outcome:

- continue reducing central hotspots by extracting domain-specific logic and clearer seams

## Success Criteria For The Next Phase

The next phase should be considered successful only when all of these become true:

1. the main operator flows produce materially better evidence on real hosts
2. no documented baseline check is known to be stale or misleading
3. the repository passes a clearly defined and reproducible engineering baseline
4. the recommendation system handles stale, failed, and no-match states more gracefully
5. the product supports a small but credible set of repeated daily CLI workflows
6. roadmap, status, validation, and release docs stay aligned through the same change streams

## Phase Structure

### Phase 1: Stabilization and trust repair

Purpose:

- remove real-host behavior that damages confidence in the main diagnostic flows

Scope:

- filter collection/self-noise from process diagnostics
- introduce explicit no-match/noise-aware process correlation handling
- fix the current type-check baseline
- reconcile validation docs with actual repository state
- tighten smoke coverage around the slow-host and recommendation flows

Deliverables:

- corrected top-process selection behavior
- recommendation logic that does not loop on already failed correlation attempts
- green static typing on the intended environment
- synchronized status, validation, and release docs
- regression tests for the corrected trust-boundary behavior

Exit criteria:

- `o host esta lento` no longer promotes collector artifacts as the top actionable process on the validated host profile
- no recommendation repeats `process_to_unit` for the same no-match state without new evidence
- documented engineering baseline is green and current

### Phase 2: Workflow depth and operator usefulness

Purpose:

- turn the current alpha into a tool that solves a few repeated CLI workflows well

Candidate workflows:

- slow host diagnosis
- unhealthy service diagnosis and action gating
- failed services triage
- managed config inspection, edit, rollback, and post-change verification
- log follow-up after service evidence is known

Scope:

- improve result rendering and next safe step quality
- reduce dead-end flows
- add missing typed read-only diagnostics only where they deepen an existing workflow
- improve recommendation evidence quality and confidence signaling

Deliverables:

- workflow definitions with expected operator journey and evidence chain
- targeted tool additions only if needed for those workflows
- better recommendation transitions and follow-up behavior
- end-to-end regression coverage for the chosen workflows

Exit criteria:

- at least three operator workflows feel complete enough for repeated daily use
- each chosen workflow has deterministic tests and documented real-host smokes

### Phase 3: Release engineering and beta readiness baseline

Purpose:

- make the project easier to trust, validate, and hand off

Scope:

- lock down the engineering baseline
- define release criteria for a beta-oriented local CLI milestone
- reduce drift in docs and quality claims
- improve packaging and environment reproducibility where needed

Deliverables:

- explicit beta baseline checklist
- updated validation report template or structure
- release note expectations for behavior-affecting changes
- documented versioning and supported environment assumptions

Exit criteria:

- maintainers can rerun the full baseline without ambiguity
- release claims are backed by current artifacts
- the repository has a clear beta bar for the local CLI product

## Workstreams

### Workstream A: Diagnostic integrity

Priority:

- Critical

Goals:

- reduce noisy or misleading diagnostic conclusions

Initial backlog:

1. filter process collectors and obvious self-observation noise
2. distinguish "no unit correlation exists" from "correlation not yet attempted"
3. stop repeating no-value process-correlation recommendations
4. expand regression tests around noisy real-host process lists

### Workstream B: Quality baseline enforcement

Priority:

- Critical

Goals:

- restore trust in engineering signals

Initial backlog:

1. fix `mypy` failures
2. document the actual current test count and baseline commands
3. confirm CI and local commands use the same expected baseline
4. decide whether dev tooling needs tighter pinning or compatibility documentation

### Workstream C: Workflow productization

Priority:

- High

Goals:

- improve operator usefulness without widening the trust boundary carelessly

Initial backlog:

1. define the top three CLI workflows explicitly
2. map current dead ends and low-confidence steps in each workflow
3. improve recommendation evidence and next-step transitions
4. add only the smallest missing typed diagnostics needed for those workflows

### Workstream D: Codebase maintainability

Priority:

- High

Goals:

- keep the system easy to evolve without centralizing more logic in the app layer

Initial backlog:

1. identify the next extraction seams in `app.py`
2. identify the next extraction seams in rendering and store logic
3. document module ownership and responsibility boundaries
4. keep new workflow logic out of the central orchestration layer by default

### Workstream E: Documentation and release discipline

Priority:

- High

Goals:

- ensure that repo docs are operational artifacts rather than marketing text

Initial backlog:

1. define which document is canonical for roadmap, validation, and release state
2. require behavior-affecting changes to update validation-facing docs
3. keep status, roadmap, and release checklist synchronized
4. add a short planning cadence and review record for post-MVP work

## Recommended Execution Order

The recommended order for the next track is:

1. Phase 1 / Workstreams A and B together
2. Phase 2 / Workstream C with ongoing D
3. Phase 3 / Workstream E plus final release engineering cleanup

Reason:

- diagnostic trust and engineering trust are the current bottlenecks
- adding more workflow breadth before fixing those would amplify noise instead of value

## Engineering Process

### Planning cadence

Use a short iteration cycle:

- one active milestone at a time
- one small prioritized backlog per milestone
- end-of-milestone validation rerun
- doc sync in the same change stream as code

### Change classes

Use these categories when planning work:

1. behavior fix
2. trust-boundary hardening
3. workflow improvement
4. refactor with no behavior change
5. release/documentation sync

Every change should state which category it belongs to.

### Required artifacts per milestone

For each active milestone, maintain:

- purpose
- scope
- non-goals
- deliverables
- exit criteria
- validation commands
- real-host smoke scenarios
- known risks

### Definition of done

A milestone is done only when:

- behavior changes are implemented
- regression tests exist where the behavior is safety- or trust-relevant
- local validation commands are rerun
- affected docs are synchronized
- residual risks are stated explicitly

## Documentation Process

Use the repository docs as operational artifacts with these roles:

- `docs/status.md`: current implemented state only
- `docs/roadmap.md`: phase-level direction and sequencing only
- `docs/post-mvp-evolution-plan.md`: active planning record for the current post-MVP track
- `docs/operator-workflows.md`: bounded operator journeys, smoke commands, and workflow safety notes
- `docs/alpha-validation-report.md` or future validation docs: validation evidence only
- `docs/release-checklist.md`: release gate only

Avoid placing active planning state in multiple files at once.

## Metrics To Watch

### Trust metrics

- number of known noisy diagnostic false leads in core workflows
- number of recommendation loops or repeated no-value actions
- number of documented flows that still depend on inference-heavy behavior

### Engineering metrics

- green baseline checks
- drift between documented and actual validation results
- hotspot file size and churn concentration

### Product metrics

- number of repeated workflows judged complete enough for daily use
- number of workflows with deterministic tests plus real-host smokes
- operator-facing dead ends per chosen workflow

## Current Milestone Record

### Milestone P1: Trust and baseline stabilization

Status:

- Completed on 2026-03-18

Why first:

- it improves product trust immediately
- it removes the main contradiction between the current codebase and the current release posture

Scope:

- fix slow-host process noise
- fix repeated no-match recommendation behavior
- fix static typing failures
- sync validation-facing docs

Exit criteria:

- current baseline checks are green on the intended environment
- slow-host diagnosis is materially cleaner on the validated host profile
- docs no longer claim stale validation facts

Completed implementation slices:

1. fix process selection noise in `top_processes` and dependent diagnostics
2. model no-match process correlation in session/recommendation logic
3. fix `tool_result_views.py` typing errors and rerun `mypy`
4. refresh validation and status docs after rerunning the baseline

Observed result:

- collector noise from the transient `ps` helper is filtered out of hot-process selection
- process-correlation attempts with no match now persist as explicit session state and do not trigger repeated recommendation loops
- non-service `systemd` correlations such as `.scope` are no longer escalated into `service_status`
- the checked local baseline is green again for `ruff`, `mypy`, `unittest discover`, `compileall`, and `mc doctor`
- validation-facing docs were synchronized with the current 107-test baseline

Exit criteria result:

- met

### Milestone P2: Workflow depth and operator usefulness

Status:

- Completed on 2026-03-18

Purpose:

- turn the stabilized late-alpha baseline into a CLI tool that solves a few repeated workflows well enough for daily use

Priority workflows:

1. slow-host diagnosis
2. unhealthy-service diagnosis and action gating
3. managed-config inspection, change, validation, and rollback

Workflow goals:

1. slow-host diagnosis:
   produce clearer ranking, better evidence, and more useful follow-up transitions after process correlation
2. unhealthy-service diagnosis and action gating:
   unify service status, logs, failed-service evidence, and explicit approval flow into one cleaner operator journey
3. managed-config workflow:
   make the read -> edit -> validate -> backup -> rollback path easier to reason about and verify after changes

Completed implementation slices:

1. reduce slow-host rendering noise by collapsing repeated process commands in the operator-facing output
2. let hot-process evidence move directly into `service_status` when typed process -> service-unit correlation already exists
3. turn `failed_services` observations into explicit service-detail follow-up recommendations instead of a dead-end list
4. preserve config target, validation, and backup metadata in session summary/context so rollback remains available after the initial write
5. support natural-language config rollback requests such as `desfaça a última mudança`
6. add deterministic regression coverage and a dedicated operator workflow guide in `docs/operator-workflows.md`

Observed result:

- slow-host diagnosis now presents a cleaner process lead and can step from typed correlation into service detail more naturally
- failed-service triage now produces an actionable `service_status` next step instead of stopping at the unit list
- the managed-config path now keeps rollback context visible and usable in a later follow-up turn
- the checked local baseline is green with 115 automated tests
- the three selected workflows now have one shared smoke-and-guidance document

Phase-level exit criteria:

- each selected workflow has a documented operator journey
- each selected workflow has deterministic automated coverage
- each selected workflow has a repeatable real-host smoke path
- recommendation transitions feel explicit and useful instead of merely technically correct

Exit criteria result:

- met for the selected workflow set

## Immediate Next Step

The next execution step after Milestone P2 is:

1. rerun the documented workflow smokes on more than one host profile
2. keep expanding the selected workflows only when the new evidence path is still typed and auditable
3. continue reducing orchestration hotspots while preserving the now-green baseline and aligned docs

That is the shortest path from "functional local CLI tool" to "credible beta-oriented operator tool".
