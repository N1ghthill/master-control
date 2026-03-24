# Release Checklist

## Purpose

This is the maintainer checklist for pre-1.0 Master Control releases.

Use `docs/status.md` for the current reality.
Use `docs/roadmap.md` and `docs/runtime-mcp-maturation-plan.md` for the current direction.
Use `docs/beta-readiness-gate.md` only when deciding whether beta language is justified.

## Release Preconditions

Before cutting a release or public preview build:

1. confirm the current direction is still described correctly in `README.md`, `docs/README.md`, `docs/status.md`, `docs/roadmap.md`, and `docs/runtime-mcp-maturation-plan.md`
2. confirm architectural or safety changes are reflected in `docs/architecture.md` and `docs/security-model.md`
3. confirm operator-visible workflows are still described correctly in `docs/operator-workflows.md`
4. confirm `CHANGELOG.md` reflects the user-visible scope

## Automated Baseline

Run:

```bash
python3 -m ruff check .
python3 -m mypy src
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall src
PYTHONPATH=src python3 -m master_control --json doctor
python3 -m pip wheel . --no-deps -w /tmp/mc-dist
```

Required result:

- all commands pass

## Operator Bootstrap Validation

Preferred operator-path validation:

```bash
./install.sh --provider heuristic
~/.local/bin/mc doctor
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
./uninstall.sh --purge-state
```

Also rerun the repo-side harness:

```bash
python3 scripts/validate_operator_bootstrap.py --output-dir ./artifacts/bootstrap-validation
```

Required result:

- install, doctor, host validation, and uninstall complete cleanly
- bootstrap harness reports success

## Real-Host Validation

For each host profile used as release evidence:

```bash
mc validate-host-profile --output-dir ./artifacts/host-validation
```

Required result:

- generated report records `overall_ok: true`
- host caveats are written down explicitly
- evidence is kept separate by host profile

## Interface Validation

Validate the interfaces that are part of the release scope.

### CLI

- `mc doctor`
- `mc tools`
- one read-only tool execution
- one approval-gated mutation flow on a safe target

### MCP

- `mc mcp-serve` starts cleanly
- documented MCP behavior matches the currently supported scope
- if the release includes only read-only MCP, confirm mutating tools are still blocked there
- if the release includes write-capable MCP in the future, confirm approval-mediated mutation flow from a real MCP client

### Optional planner layer

- if provider behavior changed, validate heuristic, OpenAI, and/or Ollama paths that are included in the release scope
- confirm provider health reporting in `mc doctor`
- do not treat provider validation as a substitute for runtime validation

## Workflow Validation

At minimum, validate the currently supported bounded workflows:

1. slow-host diagnosis
2. failed-service triage
3. managed-config read, write, validation, and rollback

Use:

- `docs/operator-workflows.md`
- `docs/host-profile-validation.md`
- `docs/alpha-validation-report.md`
- `docs/vps-validation-report.md`

## Documentation Check

Before release:

1. remove or down-rank stale release language
2. confirm historical documents are not presented as current planning docs
3. confirm version references are correct
4. confirm operator-facing commands in docs still match the implementation

## Release Notes Minimum

Release notes should mention:

- supported interfaces
- current MCP scope
- supported providers in the optional planner layer
- approval-gated mutation model
- managed config boundaries
- currently available service actions
- current out-of-scope boundaries
