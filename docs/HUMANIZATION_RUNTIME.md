# MasterControl - Humanization Runtime

## Objective

Make humanized behavior enforceable in runtime, not only in documentation.

## Components

- `mastercontrol/core/humanized_kernel.py`
  - Loads soul profile.
  - Validates communication contract fields.
  - Builds structured communication metadata (`style`, `adaptation_notes`, profile/tone signals).
  - Adapts communication mode by risk, tone, frustration and operator profile.
  - Generates post-action reflection checks.
- `scripts/mc-humanized`
  - Convenience entrypoint to execute the kernel.

## Communication contract

Required fields are defined in:

- `config/soul/core_profile.yaml`

At runtime, missing fields are rejected.

## Usage

Compose operator-facing message:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-humanized speak \
  --operator-name Irving \
  --risk-level medium \
  --intent-understood "You asked to recover DNS responsiveness." \
  --action "Flush negative cache." \
  --action "Verify unbound health." \
  --risk-assessment "Low service risk; no package changes." \
  --outcome "Action completed and DNS answers are normal." \
  --next-step "Monitor for 10 minutes; rollback not required."
```

Run reflection after execution:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-humanized reflect \
  --risk-level medium \
  --path-used fast_with_confirm \
  --success \
  --policy-compliant \
  --confidence 0.88
```

## Guarantees

- Humanized response is identity-aware (`name`, `creator`, `role`).
- Response always includes intent, plan, risk, outcome, next step/rollback.
- Runtime can expose why communication was adapted (`tone`, `frustration`, learned preference, low-confidence intent).
- Reflection always checks accuracy, path quality, safety and usefulness.
- Safety boundaries remain non-negotiable.
