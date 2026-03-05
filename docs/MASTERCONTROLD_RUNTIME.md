# MasterControlD Runtime

## Purpose

`mastercontrold` is the first executable core loop where every operator response is routed through the Soul Kernel.

## What it does now

- Receives natural-language intent.
- Runs lightweight tone analysis (`mc-tone-analyzer`).
- Loads operator profile preferences (`mc-operator-profiler`).
- Selects `fast`, `deep`, or `fast_with_confirm` autonomously (when `--path auto`).
- Builds an operational plan.
- Produces a humanized operator response with identity awareness.
- Runs mandatory post-action reflection checks.
- Records event back into operator profiler memory.

## CLI

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol --help
```

Example:

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --operator-name Irving \
  --intent "Please stabilize DNS and confirm unbound health" \
  --risk-level medium
```

JSON output:

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --intent "Investigate service incident and propose safe fix" \
  --risk-level high \
  --incident \
  --json
```

## Humanization guarantees in runtime

- Every response includes: intent, plan, risk, outcome, next step/rollback.
- `name`, `creator`, and `role` are always present through soul profile.
- Reflection checks are always generated and exposed.
- Safety boundaries remain non-negotiable.

## Next integration step

Connect `mastercontrold` plan execution to real modules (`mod-dns`, `mod-services`) via runtime + privilege broker.

Also schedule nightly `mc-dream` execution for pattern compression and suggestions.
