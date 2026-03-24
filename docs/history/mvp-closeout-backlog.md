# MVP Closeout Backlog

> Historical document
>
> This file is kept as the MVP closeout completion record.
> It is not the current product brief or roadmap.
> Use `docs/status.md`, `docs/roadmap.md`, and `docs/runtime-mcp-maturation-plan.md` for current guidance.

Snapshot date: 2026-03-18

## Purpose

This file now serves as the completion record for the narrow local CLI MVP closeout backlog.

To avoid backlog sprawl and legacy planning documents:

- keep only one closeout backlog file in the repository
- rewrite this file in place when the closeout state changes
- once closeout is complete, keep the closure record here instead of creating a parallel "final backlog" file

Closeout status:

- No active closeout milestone
- Narrow local CLI MVP closeout completed on 2026-03-18

Completed milestones:

- Milestone 1: correctness and context hardening, completed on 2026-03-18 for the current service recommendation boundary
- Milestone 2: structured session state and orchestration refactor, completed on 2026-03-18
- Milestone 3: operator utility and approval UX, completed on 2026-03-18
- Milestone 4: alpha hardening and release baseline, completed on 2026-03-18

The higher-level completion record remains in `docs/history/mvp-evolution-plan.md`.

## Closed scope

This closeout covered:

- evidence-gated service recommendations and preserved `scope=user|system`
- structured session context for the highest-risk planner and recommendation paths
- read-only operator-value additions:
  - `process_to_unit`
  - `failed_services`
- recommendation and approval rendering with evidence summaries and next-step commands
- regression coverage and smoke-ready operator journeys
- alpha-facing documentation and release baseline synchronization

Out of scope for this closeout:

- new privileged capability beyond the bounded MVP mutation set
- daemon or API work
- remote multi-user deployment
- production hardening beyond the local alpha baseline

## Closeout result

The closeout succeeded when all of these became true, and they are now true:

- the main operator journeys expose richer evidence before suggesting the next safe action
- recommendation and approval output make freshness, target identity, and next-step commands explicit
- the service trust boundary remains intact after the utility expansion
- baseline quality checks are green:
  - `python3 -m ruff check .`
  - `python3 -m mypy src`
  - `python3 -m unittest discover -s tests`
  - `python3 -m compileall src`

## Completed slices

1. BL-1: add process-to-unit correlation
Result:
`process_to_unit` can correlate a process name or pid to a real `systemd` unit when that evidence exists.

2. BL-2: add failed-service listing
Result:
`failed_services` can list failed units by scope as a typed read-only diagnostic.

3. BL-3: improve recommendation evidence and approval rendering
Result:
recommendations and approval prompts now expose evidence summaries, target identity, freshness, and next-step commands.

4. BL-4: cover the main operator journeys with regression and smoke-ready paths
Result:
the slow-host, unhealthy-service, and recommendation-action flows are covered by deterministic regression tests and smoke-ready commands.

5. BL-5: refresh alpha-facing docs after the utility changes
Result:
README, status, roadmap, MVP plan, evolution plan, validation snapshot, and release notes now describe the same closed MVP state.

## Validation snapshot

At closeout, the repository validated successfully with:

- `python3 -m unittest discover -s tests` -> 92 tests
- `python3 -m ruff check src tests`
- `python3 -m mypy src`
- `python3 -m compileall src`
- `PYTHONPATH=src python3 -m master_control --json tool process_to_unit --arg name=python3`
- `PYTHONPATH=src python3 -m master_control --json tool failed_services --arg scope=system --arg limit=5`
- `PYTHONPATH=src python3 -m master_control --json chat --new-session --once "o host esta lento"`
- clean-environment install via `python3 -m virtualenv`, `pip install -e .`, and `mc doctor`

## Next planning track

Future work now belongs to the post-MVP roadmap, not to this closeout backlog:

1. service mode and external interfaces
2. broader production hardening
3. incremental operator utility beyond the narrow alpha baseline
