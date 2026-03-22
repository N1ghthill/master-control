# Documentation Map

This is the canonical index for repository documentation.

Use `README.md` as the short public landing page.
Use this file to find the right working document, validation record, or planning artifact.

## Start Here

- `README.md`: GitHub-facing overview, current posture, and quick-start path
- `docs/status.md`: authoritative snapshot of maturity, implemented scope, and validation baseline
- `docs/release-candidate-0.1.0a2.md`: current release-candidate record and cut state

## Product And Operator Guides

- `docs/providers.md`: provider selection, setup, and behavior
- `docs/operator-workflows.md`: supported operator workflows and follow-up paths
- `docs/host-profile-validation.md`: maintainer/operator host validation harness guide
- `docs/community-host-validation.md`: public submission flow for external host validation
- `docs/release-checklist.md`: release execution checklist

## Validation And Evidence

- `docs/alpha-validation-report.md`: main alpha-track validation summary
- `docs/vps-validation-report.md`: dedicated Debian 13 VPS lab validation evidence
- `docs/vps-validation-runbook.md`: repeatable runbook for the maintainer-controlled VPS lab
- `docs/call-for-testers.md`: maintainer-facing outreach copy for collecting more validation evidence

## Architecture And Security

- `docs/architecture.md`: system structure, scope boundaries, and major flows
- `docs/security-model.md`: safety model, approval boundaries, and execution constraints
- `docs/adrs/`: architectural decision records
- `docs/diagrams/README.md`: diagram index and rendering notes

## Plans And Release Management

- `docs/roadmap.md`: high-level sequence of work and milestone framing
- `docs/beta-readiness-gate.md`: beta gate criteria and current release blockers
- `docs/beta-resume-plan.md`: short-horizon maintainer execution record
- `docs/mvp-plan.md`: original MVP definition
- `docs/mvp-evolution-plan.md`: MVP evolution and closeout record
- `docs/mvp-closeout-backlog.md`: deferred backlog after MVP closeout
- `docs/post-mvp-evolution-plan.md`: longer-horizon post-MVP planning
- `docs/alpha-release-notes.md`: current alpha-facing release notes

## Contribution And Repository Docs

- `CONTRIBUTING.md`: contributor workflow and engineering guardrails
- `CHANGELOG.md`: externally visible change history

## Documentation Rules

- `README.md` stays short and GitHub-facing
- `docs/README.md` is the canonical document map
- `docs/status.md` records the current reality; it is not the marketing page
- validation reports record evidence and should avoid private host coordinates or internal-only access details
- planning documents keep maintainer context; stable operator instructions belong in focused guides
- when you add, rename, or repurpose a document, update this map
