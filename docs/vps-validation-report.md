# VPS Validation Report

Snapshot date: 2026-03-20

## Purpose

This document records the first controlled VPS validation pass for Master Control as a private proving ground.

It is not a production-readiness claim.
It is real-host evidence intended to reduce release guesswork.

## Target Host

- Host role: dedicated validation lab
- Access model: maintainer-controlled VPS
- Distribution: Debian GNU/Linux 13 (trixie)
- Kernel: `6.12.73+deb13-amd64`
- Python: `3.13.5`
- Init system: `systemd`

## Operator Path Results

Validated successfully after host preparation:

- `./install.sh --provider heuristic`
- `~/.local/bin/mc doctor`
- `~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation`
- `./uninstall.sh --purge-state`

Observed result:

- the operator bootstrap path completed successfully on the VPS
- `mc doctor` reported `ok: true`
- `mc validate-host-profile` reported `overall_ok: true`
- uninstall removed MC-owned state under the default root-local installation path

## Host Preparation Caveat

Initial bootstrap failed before validation because the VPS had Python `3.13.5` installed but did not yet provide `ensurepip` support for `python3 -m venv`.

Required fix on this Debian 13 host:

```bash
apt-get update
apt-get install -y python3.13-venv
```

Operational interpretation:

- the project requirement on this host was not "install Python"
- it was "install the matching `python3.13-venv` package"
- this is now a documented bootstrap caveat for Debian or Ubuntu style hosts

## Host-Profile Validation Result

Primary report:

- `overall_ok: true`
- provider: `heuristic`
- raw report retained in maintainer-controlled private validation storage

Workflow results:

- slow-host diagnosis: passed
  - executed tools: `memory_usage`, `top_processes`, `process_to_unit`
- failed-service triage: passed
  - `failed_services` returned `unit_count=1`
  - recommendation keys included `failed_service_detected`, `service_state`, and `service_logs_follow_up`
- managed config path: passed
  - managed write succeeded
  - backup path was created
  - restore returned the file to the original content

## Bootstrap Harness Result

Validated successfully:

- `python3 scripts/validate_operator_bootstrap.py --output-dir ./artifacts/bootstrap-validation --provider heuristic`

Observed result:

- `overall_ok: true`
- cleanup checks: `ok: true`
- `install`, `doctor`, `validate_host_profile`, and `uninstall` all exited with code `0`

## Maintainer Baseline On The VPS

Validated successfully in a dedicated remote virtual environment:

- `python -m ruff check .`
- `python -m mypy src`
- `PYTHONPATH=src python -m unittest discover -s tests`
- `PYTHONPATH=src python -m pytest -q`

Observed result:

- `ruff`: passed
- `mypy`: passed
- `unittest`: `171` tests passed
- `pytest`: `171` tests passed

Note:

- later SSH reachability was transient on this VPS during additional reruns
- because of that transient host issue, this report does not claim a complete second rerun of every maintainer command on the VPS in the same session
- the operator-path `doctor` proof and the bootstrap harness proof were both still captured successfully

## Artifact Handling

Generated on the VPS:

- raw host-validation report
- raw bootstrap-validation report
- redacted host-validation bundle with `SUMMARY.md`

Copied back locally for review:

- raw host-validation artifacts
- raw bootstrap-validation artifacts
- redacted validation bundle materials

Public documentation note:

- private host access coordinates and internal staging paths are intentionally omitted from this report

## Assessment

What this VPS run proves:

- Master Control now has real validation evidence on more than one host profile
- the operator bootstrap path is not limited to the maintainer workstation
- the bounded workflows still behave credibly on a second Linux host

What this VPS run does not prove:

- production hardening is complete
- every optional workflow has identical behavior on every future distro
- release positioning should change without updating the canonical gate documents
