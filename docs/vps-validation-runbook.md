# VPS Validation Runbook

Snapshot date: 2026-03-20

## Purpose

This runbook defines a controlled validation flow for using a dedicated VPS as a private proving ground for Master Control.

The goal is not to claim beta readiness early.
The goal is to gather real-host evidence, document caveats, and convert successful checks into repeatable operator proof.

## Current Target Host

- Host role: dedicated validation lab
- Access mode: maintainer-controlled VPS
- Current observed profile:
  - distribution: Debian GNU/Linux 13 (trixie)
  - kernel: `6.12.73+deb13-amd64`
  - Python: `3.13.5`
  - init: `systemd`

## Operating Rules

1. treat the VPS as a validation lab, not as a production deployment
2. keep the main operator path separate from the maintainer development baseline
3. capture every command that materially contributes to release evidence
4. record caveats explicitly when the VPS differs from the maintainer workstation
5. do not upgrade release language based on intuition alone; only promote status from recorded evidence
6. keep private host coordinates, internal paths, and lab-only access details out of public repository docs

## Evidence Buckets

The VPS validation should produce evidence in four buckets:

1. host inventory
2. operator bootstrap lifecycle
3. bounded workflow validation
4. maintainer-only baseline reruns

## Recommended Execution Order

### Phase 0: Host Inventory

Capture:

- distro and kernel
- Python version
- `systemd` availability
- package manager
- memory and disk baseline

This establishes whether the host is actually comparable and whether any compatibility caveat must be documented.

### Phase 1: Operator Bootstrap

Primary goal:

- prove the non-dev operator path on the VPS

Preferred commands:

```bash
./install.sh --provider heuristic
~/.local/bin/mc doctor
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
./uninstall.sh --purge-state
```

Success criteria:

- install completes without hand edits
- `mc doctor` reports `ok: true`
- `mc validate-host-profile` reports `overall_ok: true`
- uninstall removes MC-owned artifacts cleanly

Important rule:

- do not use `--run-baseline` for the first operator-path proof
- that flag is maintainer-oriented because it depends on development tools on the host

### Phase 2: Workflow Proof

Primary goal:

- verify that the bounded workflows still behave credibly on the VPS

Minimum workflows:

1. slow-host diagnosis
2. failed-service triage
3. managed-config read, write, restore

Preferred evidence sources:

- `mc validate-host-profile --output-dir <dir>`
- selected manual follow-up commands from `docs/operator-workflows.md`
- short notes describing host-specific caveats

### Phase 3: Maintainer Baseline

Primary goal:

- confirm whether the VPS can also reproduce the engineering baseline

Preferred commands:

```bash
python3 -m ruff check .
python3 -m mypy src
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall src
PYTHONPATH=src python3 -m master_control --json doctor
python3 -m pip wheel . --no-deps -w /tmp/mc-dist
```

Important rule:

- baseline failure does not automatically invalidate operator-path evidence
- operator-path validation and maintainer baseline should be reported separately

### Phase 4: Artifact Packaging

If the host-profile report is green:

```bash
python3 scripts/prepare_host_validation_bundle.py --latest-under ./artifacts/host-validation
```

Keep:

- raw report
- redacted report
- summary markdown
- short maintainer notes about caveats and surprises

## Expected Outputs

After a successful VPS pass, the repository should be able to update:

- `docs/alpha-validation-report.md`
- `docs/beta-readiness-gate.md`
- `docs/release-candidate-0.1.0a2.md`
- `docs/status.md`

## Release Interpretation

Green VPS evidence means:

- Master Control behaves credibly on more than one real host profile
- the operator bootstrap path is not workstation-only
- the project earns stronger release confidence

Green VPS evidence does not mean:

- production hardening is complete
- beta language is automatically justified without updating gate documents
- every service or timer workflow is universally validated on every distro
