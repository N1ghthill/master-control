# Beta Resume Plan

> Historical document
>
> This file is kept for traceability of earlier beta-prep execution work.
> It is not the current product brief or roadmap.
> Use `docs/status.md`, `docs/roadmap.md`, and `docs/runtime-mcp-maturation-plan.md` for current guidance.

Snapshot date: 2026-03-20

## Purpose

This document is the short-horizon execution record for resuming Master Control work in a beta-oriented, professional way after the late-alpha closeout.

It is the canonical local execution record for the current beta-prep track.
Use it to answer, quickly and without reconstructing context from chat history:

- what is already done locally
- what still matters for the release gate
- what should be worked next, in order
- how the work should be grouped professionally

## Consolidated Local State

As of 2026-03-20, the working tree already supports a more operator-friendly bootstrap path:

- `install.sh -> mc doctor -> uninstall.sh --purge-state` passed in a temporary isolated prefix
- `mc validate-host-profile --output-dir <tmp>` produced `overall_ok: true` on the current host
- `python3 scripts/validate_operator_bootstrap.py --output-dir <tmp>` now reruns the full operator lifecycle in isolation and writes a JSON report with per-step logs plus cleanup checks
- GitHub CI now also runs a lightweight bootstrap smoke around `python3 scripts/validate_operator_bootstrap.py --output-dir <tmp>` with `provider=heuristic`
- community validation intake now includes a redacted bundle helper plus a dedicated GitHub issue template for host-validation reports
- CLI coverage for the new `validate-host-profile` command is present
- the reusable host-validation logic now lives in `src/master_control/host_validation.py`
- the local engineering baseline is green with `171` tests
- the heuristic planner now covers broader informal operator phrasing for:
  - slow-host diagnosis
  - failed-service and service-status checks
  - contextual and cause-oriented log follow-ups
  - rollback and short service-action follow-ups
  - informal disk/process requests
  - contextual config reads and process -> service lookups
  - focused summaries from fresh logs and config observations
  - comparative follow-ups for performance, logs, and service status
  - safe config-diff style follow-ups for tracked managed files only
- focused log compression now covers recurring restart or crash loops, dependency failures, environment failures, timeout patterns, permission failures, connection failures, and recovery signals
- broader comparative phrasing like `deu uma melhorada?`, `ta menos pior?`, `continua a mesma coisa?`, and `continua igual nesse arquivo?` now maps back to the existing typed compare flows
- recent observation history now preserves enough comparable reads to support typed comparative follow-ups across repeated inspections
- larger managed config comparisons now summarize changes by section and collapse overflow instead of echoing long raw diffs

This means the project is no longer only a developer-facing alpha scaffold.
It now has a real operator-facing install, validate, remove, and follow-up workflow baseline.

## Completed Local Packages

The current local beta-prep work is best understood as fourteen completed packages:

1. operator bootstrap path
   `install.sh`, `mc doctor`, and `uninstall.sh --purge-state` now exist as a documented non-dev path
2. reusable host validation
   `mc validate-host-profile` is backed by reusable code and direct tests
3. language-flexibility wave 1
   slow-host, failed-service, service-status, rollback, and contextual log follow-ups
4. language-flexibility wave 2
   short service-action follow-ups, informal disk/process requests, contextual config reads, and process -> service lookups
5. language-flexibility wave 3
   service-failure cause requests plus focused summaries from fresh logs and config observations
6. comparative follow-ups
   phrases like `isso piorou?`, `o que mudou desde a última leitura?`, and `está melhor agora?` now work for slow-host, service-status, and log workflows using recent observations plus typed refresh fallback
7. config-diff style follow-ups
   safer summaries like `o que mudou nesse arquivo?` now work for tracked managed files only, including `read -> write -> read` session flows
8. service-log compression
   focused and comparative log follow-ups now compress recurring restart loops, timeout patterns, permission failures, connection failures, and recovery signals into shorter operator-facing summaries
9. bootstrap evidence hardening
   `python3 scripts/validate_operator_bootstrap.py --output-dir <tmp>` now provides a repeatable repo-side operator bootstrap validation path with per-step logs, inner host-validation evidence, and cleanup checks
10. comparative phrase collection
   phrases like `deu uma melhorada?`, `ta menos pior?`, `continua a mesma coisa?`, and `continua igual nesse arquivo?` now reuse the same typed compare flows for performance, service, log, and config follow-ups
11. config-diff refinement
   larger tracked managed config comparisons now group changes by section, summarize added or removed sections, and cap overflow for larger files
12. service-log pattern refinement
   focused and comparative log follow-ups now also compress recurring crash-loop, dependency-failure, and environment-failure signals into shorter operator-facing summaries
13. bootstrap-to-CI decision
   GitHub CI now includes a lightweight non-editable bootstrap smoke through `scripts/validate_operator_bootstrap.py`, without treating that rerun as a substitute for multi-host validation
14. community validation intake
   external testers now have a lower-friction path to submit host-validation evidence through a redacted bundle helper, dedicated guide, and issue template

## External Release Gate

The previously missing second-host evidence is now captured through a dedicated Debian 13 VPS validation run.

Current release-facing work is now:

- synchronize the canonical release docs with the new VPS evidence
- decide whether the project should move from late-alpha/private-preview wording into stronger release language right now

## Operating Rule While The Gate Is Deferred

If an additional host is not available right now, work should still continue under one rule:

- keep advancing local beta-prep work
- do not claim beta release readiness yet
- treat multi-host validation as an external release dependency, not as a blocker for all engineering progress

This means bootstrap hardening and language-flexibility work can continue normally even when the release gate is temporarily deferred.

## Current Priority Order

### B1. Keep Operator Lifecycle Stable

Status:

- locally hardened through a repeatable bootstrap-validation harness, with a lightweight GitHub CI smoke now aligned to the same operator lifecycle path

Near-term tasks:

- keep `install.sh`, `uninstall.sh`, and `validate-host-profile` documented as the preferred operator path
- keep direct tests around host validation in place
- keep the GitHub CI bootstrap smoke lightweight, heuristic-backed, and limited to the non-editable install path
- keep treating multi-host validation as a separate release-evidence track

### B2. Keep Expanding Language Flexibility Around Existing Typed Flows

Status:

- active local hardening track, with comparative, config-diff, config-diff refinement, service-log compression, service-log pattern refinement, and broader comparative phrase collection packages closed locally by 2026-03-20

Near-term tasks:

- collect real operator phrasings for:
  - slow-host
  - failed-service
  - service-failure logs
  - focused summaries
  - config inspection
  - config-diff summaries
  - rollback
- broaden phrase coverage carefully only where it still maps back to the same typed compare or inspection flows
- expand heuristic intent coverage only around existing typed workflows
- keep provider instructions and regression coverage aligned with the same boundaries

### B3. Close The Beta Release Gate

Status:

- external evidence captured; release-doc sync still pending

Near-term tasks:

- summarize the dedicated VPS report in `docs/alpha-validation-report.md`
- update `docs/beta-readiness-gate.md`, `docs/status.md`, `docs/roadmap.md`, and `docs/history/release-candidate-0.1.0a2.md`
- decide whether to tag now or keep the build in private-preview language a little longer
- keep the community submission path simple enough that external testers can still contribute broader host diversity reports

## Professional Grouping Rule

Use the following grouping rule for the next changes:

1. keep operator lifecycle and release-evidence changes grouped together
2. keep language-flexibility changes grouped by workflow family, not by random phrase additions
3. land every natural-language expansion with regression tests in the same change
4. keep external-gate updates separate from local hardening so release blockers remain explicit

## Recommended Next Package Queue

With bootstrap evidence hardening, comparative phrase collection, comparative follow-ups, config-diff, config-diff refinement, service-log compression, service-log pattern refinement, bootstrap-to-CI decision, and community validation intake now closed locally, the cleanest next packages are:

1. external beta-gate evidence
   synchronize the gate docs and cut decision now that the dedicated VPS report exists
2. optional evidence-led refinement
   only take on further typed language or summarization work if new real operator evidence shows a concrete gap

## Commit Slice Recommendation

If the next beta-prep work is going to be committed in parts, the clean remaining slices are:

1. external beta-gate package
   VPS evidence, gate docs, validation report, release-candidate closure
2. optional evidence-led hardening package
   any future typed refinement motivated by concrete operator phrasing or host-validation findings

## Canonical Validation Commands

Use this local command set after each package:

```bash
python3 -m ruff check .
python3 -m mypy src
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall src
```

For operator-lifecycle reruns, the preferred path is:

```bash
./install.sh
~/.local/bin/mc doctor
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
./uninstall.sh --purge-state
```

## Boundaries

- keep execution typed, local, auditable, and approval-gated
- do not add generic shell execution to simulate better language understanding
- delay daemon/API/UI expansion until operator trust and multi-host validation improve
