# Release Candidate 0.1.0a2

Snapshot date: 2026-03-18

## Purpose

This document records the release-candidate state for `0.1.0a2`.

It is not the final release announcement.
It is the cut-preparation artifact that should make the remaining blocker explicit.

## Target State

- package version aligned to `0.1.0a2`
- release notes updated for the current scope
- release checklist and beta gate synchronized with the repository state
- local baseline and GitHub CI green
- only one external blocker left before tagging

## Current Candidate Status

- candidate prepared: yes
- package version aligned: yes
- local baseline green: yes
- GitHub PR baseline green: yes
- repeatable host-profile validation harness available: yes
- second real host-profile report captured: no
- ready to tag `0.1.0a2` today: no

## Included Candidate Scope

This candidate includes:

- workflow-depth improvements for slow-host, failed-service, and managed-config flows
- post-MVP recommendation trust repairs and follow-up quality improvements
- additional orchestration reduction in the app/session path
- repeatable host-profile validation procedure and JSON reporting harness

## Validation Evidence At This Snapshot

- `python3 -m ruff check .`
- `python3 -m mypy src`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m pytest -q`
- `python3 -m compileall src`
- `PYTHONPATH=src python3 -m master_control --json doctor`
- local rerun currently green with `123` tests
- wheel packaging sanity check passed with:
  - `python3 -m pip wheel . --no-deps -w /tmp/mc-dist`
  - `/tmp/mc-dist/master_control-0.1.0a2-py3-none-any.whl`
- host-profile validation harness executed successfully on the current host with:
  - `python3 scripts/validate_host_profile.py --output-dir /tmp/mc-host-validation`
  - `python3 scripts/validate_host_profile.py --output-dir /tmp/mc-host-validation --run-baseline`

## Remaining Blocker

Only one blocker remains before tagging:

1. run `python3 scripts/validate_host_profile.py --output-dir ./artifacts/host-validation --run-baseline` on at least one additional real host profile and capture a second `overall_ok: true` report

Related GitHub issues:

- `#2` Validate operator workflows on additional host profiles
- `#7` Close the beta readiness gate and decide the `0.1.0a2` cut

## Cut Procedure Once The Second Report Exists

1. attach or summarize the second host report in `docs/alpha-validation-report.md`
2. update `docs/beta-readiness-gate.md` current status from single-host blocker to actual host count
3. rerun the local baseline one final time
4. confirm `CHANGELOG.md`, `docs/status.md`, `docs/roadmap.md`, and `docs/alpha-release-notes.md` are still aligned
5. tag and publish `0.1.0a2`
