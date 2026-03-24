# Community Host Validation

Snapshot date: 2026-03-20

## Purpose

This guide is for people who want to help validate Master Control on a real Linux host.

The project is still in a late-alpha or preview state.
That is intentional.
The goal of this flow is to make external validation easy before the beta gate is closed.

## What This Is And Is Not

This flow is for:

- real Linux host validation
- comparable workflow evidence
- low-friction community feedback

This flow is not:

- a claim that the beta gate is already closed
- a requirement that you share unredacted local paths or hostnames
- a request to fabricate a second host with a throwaway VM just to simulate evidence

If your environment is a VM, container, live USB, external SSD install, or another non-default setup, that is still useful.
Just say so clearly in the issue.

## Fast Path

From a repository checkout:

```bash
./install.sh --provider heuristic
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
python3 scripts/prepare_host_validation_bundle.py --latest-under ./artifacts/host-validation
```

Prerequisite note:

- MC currently requires Python 3.13+
- on Debian or Ubuntu hosts, if `install.sh` reports that `ensurepip` is unavailable, install `python3.13-venv` first

Maintainer note:

- use `--run-baseline` only when you explicitly want to rerun `ruff`, `mypy`, tests, and the local CLI baseline on that same host

The bundle helper writes:

- a redacted `report.redacted.json`
- a short `SUMMARY.md`
- a `.zip` archive you can attach to a GitHub issue

## Recommended Submission Path

1. run the validation command on your Linux host
2. run the bundle helper on the generated report
3. open the `Host validation report` issue template on GitHub
4. attach the generated `.zip` bundle or `report.redacted.json`
5. paste the generated `SUMMARY.md` into the issue body
6. mention any caveats such as:
   - no failed services were present on the host
   - the host is a VM, live USB, or external SSD install
   - provider availability differed from the default heuristic path
   - service scope or timer behavior differed on that distro

## Bundle Helper

If you already know the exact report path:

```bash
python3 scripts/prepare_host_validation_bundle.py \
  --report ./artifacts/host-validation/<timestamp>-<hostname>/report.json
```

If you want the helper to find the latest run automatically:

```bash
python3 scripts/prepare_host_validation_bundle.py \
  --latest-under ./artifacts/host-validation \
  --output-dir ./artifacts/validation-bundles
```

## What Gets Redacted

The generated redacted report is designed to hide the most common local identifiers, including:

- hostname
- repository path
- temporary run directories
- state and SQLite paths
- managed config and backup paths
- other remaining absolute filesystem paths

The generated summary still keeps the useful validation facts, such as:

- whether `overall_ok` was true or false
- distro, kernel, and Python version
- provider used
- workflow results and executed tools
- caveats recorded by the harness

Review the generated files before sharing them publicly.
The helper is meant to reduce friction, not to promise perfect anonymization.

## Why This Matters

The current release gate still needs evidence from more than one real host profile.

Community validation reports help answer questions like:

- does the operator bootstrap path hold outside the maintainer machine?
- do the typed workflows behave the same on other distributions?
- are there packaging, provider, or service-scope surprises we should document before beta?

See also:

- `docs/host-profile-validation.md`
- `docs/beta-readiness-gate.md`
- `docs/roadmap.md`
