# Documentation Map

This is the canonical index for repository documentation.

Use `README.md` as the short public landing page.
Use this file to find the right working document, validation record, or planning artifact.

## Start Here

- `README.md`: GitHub-facing overview, current posture, and quick-start path
- `docs/status.md`: authoritative snapshot of current maturity, scope, and validation baseline
- `docs/roadmap.md`: concise phase-level roadmap for the current direction
- `docs/runtime-mcp-maturation-plan.md`: canonical execution plan for the MCP-first runtime maturation track

## Product And Operator Guides

- `docs/architecture.md`: system structure, scope boundaries, and major flows
- `docs/security-model.md`: safety model, approval boundaries, and execution constraints
- `docs/policy.md`: operator-configurable policy file guide
- `docs/operator-workflows.md`: bounded operator workflows and evidence chains
- `docs/host-profile-validation.md`: maintainer/operator host validation harness guide
- `docs/community-host-validation.md`: public submission flow for external host validation
- `docs/providers.md`: provider setup and behavior for the optional planner layer
- `docs/release-checklist.md`: release execution checklist

## Validation And Evidence

- `docs/alpha-validation-report.md`: main validation summary for the current pre-1.0 baseline
- `docs/runtime-integration-testing.md`: runtime and MCP contract validation guide
- `docs/vps-validation-report.md`: dedicated Debian VPS validation evidence
- `docs/vps-validation-runbook.md`: repeatable runbook for the maintainer-controlled VPS lab
- `docs/call-for-testers.md`: outreach copy for collecting more host-validation evidence

## Supporting Engineering Docs

- `docs/core-interfaces-refactor-plan.md`: supporting engineering brief for the remaining code-ownership cleanup
- `docs/beta-readiness-gate.md`: beta gate criteria and release blockers
- `docs/adrs/`: architectural decision records
- `docs/diagrams/README.md`: diagram index and rendering notes

## Historical Records

- `docs/history/README.md`: index of historical planning and release records
- `docs/history/release-candidate-0.1.0a2.md`: historical cut record for the current public pre-release
- `docs/history/alpha-release-notes.md`: historical alpha release notes
- `docs/history/beta-resume-plan.md`: historical beta-prep execution record
- `docs/history/mvp-plan.md`: original MVP framing kept for traceability
- `docs/history/mvp-evolution-plan.md`: MVP closeout sequencing record
- `docs/history/mvp-closeout-backlog.md`: MVP closeout completion record
- `docs/history/post-mvp-evolution-plan.md`: previous planning record kept for context

## Contribution And Repository Docs

- `CONTRIBUTING.md`: contributor workflow and engineering guardrails
- `CHANGELOG.md`: externally visible change history

## Documentation Rules

- `README.md` stays short and GitHub-facing
- `docs/README.md` is the canonical document map
- `docs/status.md` records the current reality; it is not the marketing page
- `docs/roadmap.md` and `docs/runtime-mcp-maturation-plan.md` are the current planning references
- historical documents stay available for traceability, but they are not authoritative for current direction
- validation reports record evidence and should avoid private host coordinates or internal-only access details
- stable operator instructions belong in focused guides
- when you add, rename, or repurpose a document, update this map
