# Release Candidate 0.1.0a2

Snapshot date: 2026-03-20

## Purpose

This document records the release-candidate state for `0.1.0a2`.

It is not the final release announcement.
It is the cut-preparation artifact that should make the current release state explicit.

## Target State

- package version aligned to `0.1.0a2`
- release notes updated for the current scope
- release checklist and beta gate synchronized with the repository state
- local baseline and GitHub CI green
- second real host validation evidence captured before tagging

## Current Candidate Status

- candidate prepared: yes
- package version aligned: yes
- local baseline green: yes
- GitHub PR baseline green: yes
- repeatable host-profile validation harness available: yes
- second real host-profile report captured: yes
- local beta-prep work may continue while release docs are synchronized: yes
- ready to tag `0.1.0a2` today: not until the release docs and final positioning decision are synchronized

## Included Candidate Scope

This candidate includes:

- workflow-depth improvements for slow-host, failed-service, managed-config, service-failure log flows, and focused follow-up summaries
- comparative follow-ups for slow-host, service-status, and log flows using recent observations plus typed refresh fallback
- broader comparative phrase coverage for performance, service, log, and config follow-ups
- safe config-diff follow-ups for tracked managed files only
- refined config-diff summaries for larger managed files, including section-aware grouping and overflow capping
- refined service-log summaries for recurring restart or crash loops, dependency failures, environment failures, timeout patterns, permission failures, connection failures, and recovery signals
- repeatable operator bootstrap validation harness with per-step logs, inner host-validation evidence, and cleanup checks
- lightweight GitHub CI bootstrap smoke around the same non-editable operator install path
- redacted host-validation bundle preparation plus a dedicated community issue template for submitted reports
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
- local rerun currently green with `171` tests
- wheel packaging sanity check passed with:
  - `python3 -m pip wheel . --no-deps -w /tmp/mc-dist`
  - `/tmp/mc-dist/master_control-0.1.0a2-py3-none-any.whl`
- host-profile validation harness executed successfully on the current host with:
  - `mc validate-host-profile --output-dir /tmp/mc-host-validation`
  - `mc validate-host-profile --output-dir /tmp/mc-host-validation --run-baseline`
- operator bootstrap smoke passed with:
  - `./install.sh`
  - `~/.local/bin/mc doctor`
  - `~/.local/bin/mc validate-host-profile --output-dir /tmp/mc-host-validation`
  - `./uninstall.sh --purge-state`
- repeatable bootstrap validation harness executed successfully on the current host with:
  - `python3 scripts/validate_operator_bootstrap.py --output-dir /tmp/mc-bootstrap-validation`
- local equivalent of the GitHub CI bootstrap smoke executed successfully with:
  - `python3 scripts/validate_operator_bootstrap.py --output-dir /tmp/mc-bootstrap-ci-decision`
- dedicated Debian 13 VPS validation now also exists with:
  - `./install.sh --provider heuristic`
  - `~/.local/bin/mc doctor`
  - `~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation`
  - `./uninstall.sh --purge-state`
  - `python3 scripts/validate_operator_bootstrap.py --output-dir ./artifacts/bootstrap-validation --provider heuristic`
- dedicated VPS report reference:
  - `docs/vps-validation-report.md`

## Remaining Release Work

The missing second-host evidence is now closed.
The remaining release work before tagging is:

1. summarize the dedicated VPS validation in the canonical release-facing docs
2. rerun the local baseline one final time
3. confirm release wording stays aligned with the actual risk posture

Related GitHub issues:

- `#2` Validate operator workflows on additional host profiles
- `#7` Close the beta readiness gate and decide the `0.1.0a2` cut

## Cut Procedure With The Second Report In Hand

1. attach or summarize the VPS report in `docs/alpha-validation-report.md`
2. update `docs/beta-readiness-gate.md`, `docs/status.md`, and `docs/roadmap.md` to reflect that multi-host evidence now exists
3. rerun the local baseline one final time
4. confirm `CHANGELOG.md`, `docs/alpha-release-notes.md`, and the release wording are still aligned with the actual scope
5. decide whether to tag `0.1.0a2` immediately or keep the build in private-preview language a little longer
