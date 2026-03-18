# Master Control

Master Control (MC) is a conversational Linux agent designed around controlled execution, explicit approvals, and auditability.

The project starts as a modular Python monolith with a CLI-first interface. The main architectural rule is simple: conversation is the user interface, but execution is never delegated blindly to a language model.

## Design principles

- Conversational interface first
- Typed tools before generic shell access
- Least privilege and explicit approval gates
- Auditable actions and structured logs
- Small, composable modules that can evolve without rewriting the core

## MVP scope

The first implementation slice is intentionally narrow:

- Local host only
- CLI-first experience
- Read-only tools first, then approval-gated mutations
- SQLite for local state and audit trail
- Provider abstraction with a structured planning contract
- Risk-based policy engine for future mutating operations

## Repository layout

```text
docs/                  Architecture, security model, ADRs, roadmap
src/master_control/    Application code
tests/                 Automated tests
```

## Bootstrap commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
mc doctor
mc tools
mc tool system_info
mc tool disk_usage --arg path=/
mc tool read_config_file --arg path=<managed-config-path>
mc tool write_config_file --arg path=<managed-config-path> --arg content='[main]\nkey=value\n' --confirm
mc tool service_status --arg name=ollama-local.service --arg scope=user
mc tool restart_service --arg name=ollama-local.service --arg scope=user --confirm
mc tool top_processes --arg limit=5
mc chat --once "mostre o uso de memoria"
mc chat --once "o host esta lento"
mc chat --once "reinicie o servico nginx"
mc sessions --limit 5
mc observations --session-id 1
mc observations --session-id 1 --stale-only
mc insights --session-id 1
mc recommendations --session-id 1
mc recommendations --session-id 1 --status open
mc reconcile --session-id 1
mc reconcile --all
mc reconcile-timer render
mc reconcile-timer install --scope user
mc reconcile-timer remove --scope user
mc recommendation <id> accepted
mc recommendation-run <id>
mc recommendation-run <id> --confirm
mc audit --limit 5
```

## Current status

This repository currently contains:

- Core documentation for the MVP architecture
- Initial ADRs to lock major technical decisions
- A minimal Python scaffold with CLI, policy engine, tool registry, SQLite bootstrap, and audit events
- The first inspection tools: `system_info`, `disk_usage`, `memory_usage`, `top_processes`, `service_status`, and `read_journal`
- A first approval-gated action tool: `restart_service`
- A heuristic provider that turns natural language into explicit tool plans
- An OpenAI provider that uses the Responses API to return structured plans via function calling
- An Ollama provider that uses `/api/chat` with schema-constrained JSON output
- Persistent session memory built from short history plus a compact deterministic session summary
- Session-scoped observations with TTL-based freshness, so stale diagnostic context can be refreshed automatically
- Deterministic proactive suggestions derived from each session summary
- A persistent recommendation queue per session with explicit status tracking and optional executable actions
- Freshness-aware recommendations, so stale signals ask for refresh before they suggest risky actions
- Approval hints that return the exact CLI and chat commands required to confirm risky actions
- Managed config tools with allowlisted targets, backup, validation, atomic writes, and restore from backup
- End-to-end test coverage for the main recommendation and config-edit workflows
- Iterative per-turn planning so the agent can continue a diagnosis with fresh tool results
- Observation freshness injected into all planners, so stale memory/process/service context can trigger a refresh instead of a stale summary
- Optional `scope=user` support for service tools, so the same typed workflow can operate on `systemd --user` units
- Optional `systemd` timer management for periodic `mc reconcile --all`

Current maturity:

- late alpha
- MVP candidate for the narrow local CLI-first milestone
- roughly 90% to 95% of the narrow MVP defined for the local host milestone
- not yet ready to be treated as a production-ready host administration agent

Recent real-host validation:

- `service_status`, `reload_service`, and `restart_service` validated against both `systemd --user` and system scope
- managed config read/write/restore validated on a real file under `<MC_STATE_DIR>/managed-configs/`

## Documents

- `docs/architecture.md`
- `docs/status.md`
- `docs/mvp-plan.md`
- `docs/providers.md`
- `docs/alpha-validation-report.md`
- `docs/alpha-release-notes.md`
- `docs/release-checklist.md`
- `docs/security-model.md`
- `docs/roadmap.md`
- `docs/adrs/0001-modular-monolith-python.md`
- `docs/adrs/0002-cli-first-host-service.md`
- `docs/adrs/0003-typed-tools-and-risk-gates.md`
- `docs/adrs/0004-recommendation-actions-and-approval.md`
- `docs/adrs/0005-managed-config-editing.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`

## Provider setup

Local-first automatic selection:

```bash
export MC_PROVIDER=auto
mc doctor
```

`MC_PROVIDER=auto` now resolves providers in this order:

- `ollama` when the local endpoint is reachable and the configured model is installed
- `openai` when `OPENAI_API_KEY` is configured
- `heuristic` as the offline fallback

OpenAI provider:

```bash
export OPENAI_API_KEY=...
export MC_PROVIDER=openai
mc doctor
mc chat --once "mostre o uso de memoria"
mc sessions --limit 5
```

Automatic selection:

```bash
export MC_PROVIDER=auto
mc doctor
```

Ollama provider:

```bash
ollama serve
ollama pull qwen2.5:7b
export MC_PROVIDER=ollama
export MC_OLLAMA_MODEL=qwen2.5:7b
mc doctor
mc chat --once "o host esta lento"
```

If `mc doctor` reports that Ollama is unavailable, confirm:

- the `ollama` binary is installed on the host
- the local server is listening on `http://localhost:11434`
- the configured model was pulled locally
- if your host uses a non-default Ollama port, set `MC_OLLAMA_BASE_URL=http://127.0.0.1:<port>/api`

Current local alpha profile:

- default Ollama model: `qwen2.5:7b`
- rationale: validated on this host and materially faster than the previous baseline candidate

One user-local bootstrap path when you do not want or cannot install Ollama system-wide:

```bash
curl --fail --show-error --location -o /tmp/ollama-linux-amd64.tar.zst \
  https://ollama.com/download/ollama-linux-amd64.tar.zst
mkdir -p ~/.local/bin ~/.local
zstd -dc /tmp/ollama-linux-amd64.tar.zst | tar -xf - -C ~/.local
ln -sfn ~/.local/ollama-latest/bin/ollama ~/.local/bin/ollama
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=$HOME/.local/share/ollama/models \
  nohup ~/.local/bin/ollama serve >/tmp/ollama-serve.log 2>&1 &
```

## Rules of the road

- No generic `shell=True` execution path in the agent core
- No privileged actions without explicit approval design
- No persistent "facts" about the system without source and timestamp
- No premature split into microservices

## Development baseline

Useful local checks:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall src
mc doctor
```

GitHub Actions baseline:

- `.github/workflows/ci.yml` runs editable install, unit tests, `compileall`, and an offline-safe `mc doctor` smoke on Python 3.13

Observation inspection:

- `mc observations --session-id <id>` shows the latest stored observations and freshness for a session
- `mc observations --session-id <id> --stale-only` filters only stale observations
- observations start appearing from new executions after the freshness model was introduced; older sessions are not backfilled
- `mc recommendations --session-id <id>` now shows confidence/freshness for the signal behind each recommendation
- recommendation listings and chat highlights now prioritize fresh signals before stale ones
- `mc reconcile --session-id <id>` recomputes recommendations from the current summary + freshness state without waiting for a new chat turn
- `mc reconcile-timer render` shows the generated `systemd` service and timer units without touching disk
- `mc reconcile-timer install --scope user` installs a periodic `systemd --user` timer that runs `mc reconcile --all`
- `mc reconcile-timer remove --scope user` disables and removes that timer again

Provider-specific optional knobs:

- `MC_PROVIDER_PROBE_TIMEOUT_S` defaults to `0.75`

Managed config targets are intentionally narrow by default:

- `<MC_STATE_DIR>/managed-configs/*.ini`
- `<MC_STATE_DIR>/managed-configs/*.cfg`
- `<MC_STATE_DIR>/managed-configs/*.json`
- `/etc/systemd/system/*.service`
- `/etc/systemd/system/*.timer`
