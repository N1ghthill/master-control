# Host Profile Validation

Snapshot date: 2026-03-18

## Purpose

This guide defines the repeatable procedure for validating the bounded MC operator workflows on additional host profiles.

The goal is not to improvise ad hoc smoke notes.
The goal is to produce one comparable report per host.

## Validation Harness

Preferred path once MC is installed:

```bash
mc validate-host-profile --output-dir ./artifacts/host-validation
```

Repository wrapper path:

```bash
python3 scripts/validate_host_profile.py --output-dir ./artifacts/host-validation
```

Optional full local baseline on the same host:

```bash
python3 scripts/validate_host_profile.py --output-dir ./artifacts/host-validation --run-baseline
```

Default behavior:

- uses `MC_PROVIDER=heuristic` unless overridden with `--provider`
- creates an isolated state directory under the chosen output directory
- runs the three selected operator workflows
- writes a JSON report under `artifacts/host-validation/<timestamp>-<hostname>/report.json`

## Workflows Covered

The harness records evidence for:

1. slow-host diagnosis through chat
2. failed-service triage through chat plus typed `failed_services`
3. managed-config read, write, verification recommendation, and restore on an isolated managed file

## Per-Host Procedure

For each additional host profile:

1. clone the repository and run `./install.sh`
2. run `mc validate-host-profile --output-dir ./artifacts/host-validation`
3. optionally rerun with `--run-baseline` if you want stronger local evidence for the same host
4. prepare a shareable redacted bundle with:
   `python3 scripts/prepare_host_validation_bundle.py --latest-under ./artifacts/host-validation`
5. inspect the generated `report.redacted.json` and `SUMMARY.md`
6. note any host-specific caveats, especially for:
   - no failed services present on the target host
   - provider availability differences
   - service-scope limitations on that host
7. submit the bundle through the `Host validation report` GitHub issue template or copy the resulting summary into the release discussion

## Required Evidence Before Beta

Before closing the multi-host gate:

- at least two distinct host profiles have a generated report
- each report shows `overall_ok: true`
- any caveats are summarized in `docs/alpha-validation-report.md` or the next validation report
- `docs/beta-readiness-gate.md` is updated from "single validated host" to the actual host count

## Current Limitation

This harness makes cross-host validation reproducible, but it does not replace the need for real additional hosts.

GitHub CI may also rerun `python3 scripts/validate_operator_bootstrap.py --output-dir <tmp>` as a repository-side bootstrap smoke.
That improves repeatability of the install path, but it still counts as single-run CI evidence, not as an additional host profile.

If only one host report exists, Gate 1 remains open.

See `docs/community-host-validation.md` for the lower-friction community submission flow.
