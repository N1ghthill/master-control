# Call For Testers

Snapshot date: 2026-03-20

## Purpose

This document contains ready-to-post copy for inviting real Linux users to validate Master Control on their own hosts.

Use it when you want to ask for:

- host-validation reports
- packaging feedback
- workflow feedback from real Linux environments

Do not use it to imply that the beta gate is already closed.

## Short README Copy

```text
Master Control is looking for Linux testers.

If you want to help validate the operator workflow on a real host, run:

./install.sh --provider heuristic
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
python3 scripts/prepare_host_validation_bundle.py --latest-under ./artifacts/host-validation

Then attach the generated bundle to a GitHub `Host validation report` issue.
See docs/community-host-validation.md for the full flow.
```

## GitHub Issue Or Discussion

```text
Master Control is currently in a late-alpha or preview state, and I am looking for real Linux host validation reports before claiming a wider beta.

What I need:

- real Linux host runs
- honest environment notes such as bare metal, VM, live USB, or external SSD
- the generated host-validation bundle or redacted report

Fast path:

./install.sh --provider heuristic
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
python3 scripts/prepare_host_validation_bundle.py --latest-under ./artifacts/host-validation

Then open the `Host validation report` issue template and attach the generated bundle.

Important: this is a request for validation evidence, not a claim that the multi-host beta gate is already closed.
```

## Release Post

```text
Master Control `0.1.0a2` is available as a preview build for real Linux host testing.

The project already has:

- a bounded local-first runtime for host operations
- typed diagnostics and approval-gated mutations
- a repeatable host-validation harness
- a redacted bundle flow for submitting validation reports

What it still benefits from is broader multi-host validation evidence.

If you want to help with that, please run the host-validation flow on your Linux machine and submit the generated bundle through GitHub:

./install.sh --provider heuristic
~/.local/bin/mc validate-host-profile --output-dir ./artifacts/host-validation
python3 scripts/prepare_host_validation_bundle.py --latest-under ./artifacts/host-validation

Full guide: docs/community-host-validation.md
```

## Short Social Post

```text
I am looking for Linux testers for Master Control.

It is a local-first runtime for controlled Linux host operations, with typed diagnostics, approval-gated actions, and a built-in validation flow.

If you can run a quick validation on your own Linux host and send the generated redacted report, that would help broaden the real-host evidence base beyond the first validated profiles.

Guide: docs/community-host-validation.md
Repo: https://github.com/N1ghthill/master-control
```

## Notes

- prefer `preview`, `late-alpha`, or `validation build` wording over `beta-ready`
- ask testers to describe their environment honestly
- keep the ask narrow: run commands, attach bundle, note caveats
- avoid implying that VM evidence is equivalent to an independent host if that is not the bar you want to claim
