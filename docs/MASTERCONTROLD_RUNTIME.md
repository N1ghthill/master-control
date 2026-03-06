# MasterControlD Runtime

## Purpose

`mastercontrold` is the first executable core loop where every operator response is routed through the Soul Kernel.

## What it does now

- Receives natural-language intent.
- Runs lightweight tone analysis (`mc-tone-analyzer`).
- Runs local-first intent classification (`mc-intent-classifier`: transformer local optional -> history/heuristic merge with explicit mutation-verb safeguard).
- Loads operator profile preferences (`mc-operator-profiler`).
- Selects `fast`, `deep`, or `fast_with_confirm` autonomously (when `--path auto`) using profile + learned rules.
- Builds an operational plan and maps eligible intents to allowlisted `action_id`.
- Resolves modules through `ModuleRegistry` (cluster-aware priority + deterministic fallback).
- Delegates DNS planning to `mod_dns` (`capabilities/pre_check/apply/verify/rollback`).
- Delegates network diagnostics to `mod_network` (`ping/resolve/route default`, read-only).
- Delegates service operations to `mod_services` (`restart/start/stop` with unit extraction + verify/rollback hints).
- Delegates package operations to `mod_packages` (`update/install/remove` with package extraction + verify/rollback hints).
- Executes real allowlisted actions through `scripts/mc-root-action` when `--execute` is provided.
- Produces a humanized operator response with identity awareness.
- Runs mandatory post-action reflection checks.
- Records event back into operator profiler memory.
- Appends core execution audit events in `~/.local/share/mastercontrol/mastercontrold.log`.

## CLI

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol --help
```

Interface interativa IA:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai
```

Fluxo detalhado e roteiro diario da interface:
- `docs/AI_INTERFACE.md` (secoes "Fluxo ponta a ponta" e "Roteiro diario (5 comandos)")

Padrao atual do `mc-ai`: `qwen2.5:7b` com `--llm-timeout 25` e autodeteccao de runtime local atualizado (`~/.local/ollama-latest/bin/ollama`).

Interface interativa IA (preset conversacional):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai-chat
```

Interface IA sem LLM (fallback manual):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --no-llm
```

Interface IA com modelo explicito:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen2.5:7b --llm-timeout 25
```

Interface IA com foco em resposta mais elaborada (latencia maior):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen3.5:4b --llm-timeout 45
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

Dry-run execution (safe validation):

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --intent "flush negative cache" \
  --risk-level low \
  --execute \
  --dry-run
```

Real execution:

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --intent "flush dns cache" \
  --risk-level low \
  --execute
```

High-risk gated execution (example with service restart):

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --intent "restart unbound service" \
  --risk-level medium \
  --execute \
  --approve \
  --allow-high-risk \
  --dry-run
```

Service stop dry-run (module path):

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --intent "stop docker service" \
  --risk-level medium \
  --execute \
  --dry-run
```

Package install dry-run (module path):

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --intent "apt install htop" \
  --risk-level medium \
  --execute \
  --dry-run
```

Network diagnostic dry-run (module path):

```bash
/home/irving/ruas/repos/master-control/scripts/mastercontrol \
  --intent "ping 1.1.1.1" \
  --risk-level low \
  --execute \
  --dry-run
```

## Humanization guarantees in runtime

- Every response includes: intent, plan, risk, outcome, next step/rollback.
- `name`, `creator`, and `role` are always present through soul profile.
- Reflection checks are always generated and exposed.
- Safety boundaries remain non-negotiable.
- In `mc-ai`, local LLM routing (`intent` vs `chat`) is optional and does not bypass runtime policy.

## Execution guardrails

- `--execute` is required to mutate state. Without it, output is analysis-only.
- `fast_with_confirm` path blocks real mutation unless `--approve` is provided.
- High/critical mapped actions are blocked unless `--allow-high-risk` is provided.
- `--dry-run` validates command mapping and privilege path without mutating state.
- Every execution carries a `request_id` for cross-log correlation.
- Learned rules cannot force unsafe downgrade on incident/high-risk (`fast` is blocked in those contexts).
- If no module resolves the intent, response stays analysis-only and exposes attempted modules in plan.
- Privileged execution only accepts trusted allowlist files under `/etc/mastercontrol` (root-owned, not group/other writable).
- `scripts/mc-root-action` uses `/etc/mastercontrol/actions.json` for privileged execution; custom `--actions-file` is allowed only with `--dry-run`.

## Audit trails

- Core loop log:
  - `~/.local/share/mastercontrol/mastercontrold.log`
- Privileged executor log:
  - `/var/log/mastercontrol/root-exec.log` (root-owned)

Together these logs capture interpretation -> path decision -> action execution -> reflection outcome.

## Automated validation

Run unit tests:

```bash
python3 -m unittest discover -s tests -v
```
