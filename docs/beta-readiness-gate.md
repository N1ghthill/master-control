# Beta Readiness Gate

Snapshot date: 2026-03-18

## Purpose

This document defines the minimum bar for moving Master Control from the current late-alpha track into a credible beta-oriented phase.

It is not a feature wishlist.
It is a release gate.

## Gate Summary

Beta should not be declared until all of the following are true:

1. the selected operator workflows are validated on more than one host profile
2. the recommendation system remains typed, auditable, and conservative under stale or partial evidence
3. the engineering baseline stays reproducible in local reruns and GitHub CI
4. the mutation boundary remains explicit, confirmation-gated, and easy to inspect
5. the main orchestration hotspots are reduced enough to support safer iteration

## Gate 1: Workflow Validation

The following workflows must be validated end to end:

1. slow-host diagnosis
2. failed-service triage
3. managed-config read, write, validation, and rollback

Minimum exit bar:

- deterministic automated coverage exists for each workflow
- a repeatable smoke path exists for each workflow
- the workflow is rerun on at least 2 distinct host profiles
- any host-specific caveats are documented explicitly

Primary reference:

- `docs/operator-workflows.md`
- `docs/host-profile-validation.md`

## Gate 2: Trust And Recommendation Quality

Minimum exit bar:

- stale observations degrade into refresh or inspection recommendations instead of risky action
- failed-service and hot-process recommendations lead to useful next inspection steps
- non-service correlations do not accidentally escalate into service operations
- repeated no-match states do not loop into the same low-value recommendation

Evidence sources:

- session insight and recommendation tests
- real-host workflow smokes
- validation report updates

## Gate 3: Mutation Safety

Minimum exit bar:

- every privileged action still requires explicit confirmation
- approval guidance remains clear in both CLI and chat paths
- managed config writes and restores remain bounded to policy-managed targets
- rollback remains available after a successful managed write

Evidence sources:

- policy and tool tests
- recommendation-action tests
- managed config workflow smokes

## Gate 4: Engineering Baseline

Minimum exit bar:

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m pytest -q`
- `python3 -m compileall src`
- `PYTHONPATH=src python3 -m master_control --json doctor`
- GitHub CI runs the same effective baseline

Failure rule:

- beta is blocked if release-facing docs claim a greener baseline than the repository actually passes

## Gate 5: Codebase Maintainability

Minimum exit bar:

- the next workflow improvements do not primarily expand central hotspot files
- orchestration logic keeps moving into narrower session, recommendation, rendering, and provider seams
- reviewable changes remain small enough to validate without guesswork

Primary hotspots still to watch:

- `src/master_control/app.py`
- `src/master_control/providers/heuristic.py`
- `src/master_control/agent/session_insights.py`

## Required Release Artifacts Before Beta

Before any beta tag, the repository should have:

- updated `docs/status.md`
- updated `docs/roadmap.md`
- updated validation report
- updated release checklist
- a short release note describing workflow scope and remaining boundaries

## Current Status

Current assessment on 2026-03-18:

- not yet beta-ready

Main remaining blockers:

1. workflow validation is still concentrated on one primary host profile
2. the repository now has a repeatable host-profile validation harness, but it still needs reports from additional real hosts
