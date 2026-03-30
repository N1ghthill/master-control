# Security Policy

## Scope

Master Control is a local-first runtime that can inspect and mutate parts of a Linux host.
Treat security issues in this repository as high-sensitivity reports even when the current release line is pre-1.0.

Out of scope for public issues:

- exploit details for unpatched vulnerabilities
- secrets, tokens, or host-specific private data
- reports that require publishing a proof-of-concept before maintainer review

## Supported Versions

Security fixes are only guaranteed for:

- the latest published pre-release
- the current `main` branch

Older pre-releases may receive no fix or may only receive documentation updates.

## Reporting A Vulnerability

Preferred path:

1. Use GitHub private vulnerability reporting for this repository if it is enabled.
2. If private reporting is unavailable, contact the maintainer privately before opening any public issue.
3. Include reproduction steps, affected version or commit, impact, and any local configuration required to trigger the issue.

Do not open a public issue for a live security vulnerability before there is a maintainer response.

## What To Include

- affected commit, tag, or release
- exact command, workflow, or interface used
- expected behavior
- observed behavior
- impact assessment
- whether the issue depends on local configuration, environment variables, or host privileges

## Response Expectations

Target process for confirmed reports:

1. Acknowledge receipt.
2. Reproduce and assess impact.
3. Prepare a fix or mitigation.
4. Publish the fix and any required operator guidance.

Because the project is still pre-1.0, some fixes may land on `main` before a formal tagged release is cut.
