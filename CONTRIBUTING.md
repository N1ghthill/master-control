# Contributing

## Scope

This project is still in an early local-first stage. Contributions should preserve the core design rule:

- conversation is the interface
- typed tools are the execution surface
- policy and audit stay in the execution path

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pre-commit install
```

## Baseline checks

Run these before considering a change complete:

```bash
python3 -m ruff check .
python3 -m mypy src
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall src
PYTHONPATH=src python3 -m master_control --json doctor
```

The repository also has a matching GitHub Actions baseline in `.github/workflows/ci.yml`. Keep local checks and CI checks aligned.

If you use `pre-commit`, the repository will run:

- basic whitespace and merge-conflict hooks
- `ruff check --fix`
- `ruff format`
- `mypy src`

## Engineering guardrails

### Architecture

- prefer typed tools over generic command execution
- keep policy checks in front of every tool execution
- do not let providers execute host actions directly
- use structured plans instead of free-form action text
- document architectural changes with an ADR when they change core system contracts

### Security

- keep `shell=False`
- validate tool arguments strictly
- require explicit confirmation for mutating or privileged actions
- do not bypass the audit trail for convenience
- treat recommendation acceptance as intent, not execution
- keep config editing constrained to managed targets unless a deliberate architecture change is approved

### Documentation

- keep `README.md` short and GitHub-facing
- update `docs/README.md` when docs are added, renamed, or repurposed
- update `README.md` when quick-start or public-facing positioning changes
- update `docs/roadmap.md` and `docs/status.md` when project stage changes
- update `docs/security-model.md` when the execution or approval boundary changes
- prefer concise docs that capture contracts and decisions rather than implementation trivia

### Tests

- add or update tests for every new tool
- add chat flow tests when provider routing or summaries change
- add policy tests when risk handling changes
- prefer deterministic tests over environment-dependent host behavior
- when touching config editing, prefer tests under `MC_STATE_DIR/managed-configs` over host paths
- keep lint and typecheck green for `src/`

## Commit conventions

This repository should use small commits with one primary purpose each.

Recommended commit prefixes:

- `feat`: new capability
- `fix`: behavior correction
- `docs`: documentation only
- `test`: tests only
- `refactor`: internal cleanup without behavior change
- `chore`: housekeeping

Recommended examples:

- `docs: align roadmap with current MVP state`
- `feat(tools): add reload_service`
- `feat(app): execute accepted recommendation actions`
- `test(chat): cover service recommendation flow`

## Change checklist

Before closing a change, verify:

- code path follows policy and audit rules
- docs match the user-visible behavior
- tests cover the intended contract
- lint and typecheck stay green
- the change can be described in one focused commit
