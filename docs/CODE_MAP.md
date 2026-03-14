# Code Map

Mapa atualizado dos arquivos de codigo do MasterControl, organizado por dominio.

## 1) Core Intelligence

### Responsabilidade

- Orquestracao principal.
- Humanizacao de resposta.
- Selecao autonoma de caminho (`fast/deep`).

### Arquivos

- `mastercontrol/contracts.py`
- `mastercontrol/core/mastercontrold.py`
- `mastercontrol/core/humanized_kernel.py`
- `mastercontrol/core/path_selector.py`
- `mastercontrol/core/__init__.py`
- `mastercontrol/modules/mod_dns.py`
- `mastercontrol/modules/mod_network.py`
- `mastercontrol/modules/mod_services.py`
- `mastercontrol/modules/mod_packages.py`
- `mastercontrol/modules/mod_security.py`
- `mastercontrol/modules/registry.py`
- `mastercontrol/modules/base.py`
- `mastercontrol/modules/__init__.py`

### Entrypoint de uso

- `scripts/mastercontrol`
- `scripts/mc-humanized`
- `scripts/mc-ai`
- `scripts/mc-ai-chat`

### Interface conversacional

- `mastercontrol/interface/mc_ai.py`
- `mastercontrol/interface/mc_tui.py`
- `mastercontrol/interface/__init__.py`
- `mastercontrol/llm/ollama_adapter.py`
- `mastercontrol/llm/__init__.py`

## 2) Security / Privileges

### Responsabilidade

- Execucao privilegiada por allowlist.
- Integracao bootstrap com `pkexec/polkit`.
- Broker privilegiado inicial por socket Unix local.
- Auditoria de acoes root.
- Validacao de allowlist confiavel para execucao root.

### Arquivos

- `mastercontrol/runtime/root_exec.py`
- `mastercontrol/privilege/broker.py`
- `mastercontrol/privilege/pexec.py`
- `mastercontrol/privilege/__init__.py`
- `mastercontrol/policy/engine.py`
- `mastercontrol/policy/__init__.py`
- `mastercontrol/runtime/__init__.py`
- `config/privilege/actions.json`
- `config/polkit/io.mastercontrol.rootexec.policy`
- `scripts/install-privilege-bootstrap.sh`
- `scripts/install-privilege-broker.sh`
- `scripts/mc-privilege-broker`
- `scripts/mc-root-action`

### Docs relacionadas

- `docs/PRIVILEGE_MODEL.md`
- `docs/PRIVILEGE_BOOTSTRAP.md`
- `docs/PRIVILEGE_BROKER.md`
- `docs/PEXEC_MODEL.md`

## 3) Adaptive Intelligence

### Responsabilidade

- Perfil comportamental do operador.
- Analise de tom/urgencia leve.
- "Dream" offline para insights operacionais.

### Arquivos

- `mastercontrol/context/contextd.py`
- `mastercontrol/context/events.py`
- `mastercontrol/context/mc_operator_profiler.py`
- `mastercontrol/context/__init__.py`
- `mastercontrol/security/watcher.py`
  - watcher continuo, ledger persistente de incidente, playbooks de incidente e validacao de contenção correlacionada para servico, auth e network.
- `mastercontrol/security/__init__.py`
- `mastercontrol/tone/mc_tone_analyzer.py`
- `mastercontrol/tone/intent_classifier.py`
- `mastercontrol/tone/__init__.py`
- `mastercontrol/dream/mc_dream.py`
- `mastercontrol/dream/__init__.py`
- `scripts/mc-operator-profiler`
- `scripts/mc-tone-analyzer`
- `scripts/mc-intent-classifier`
- `scripts/mc-dream`
- `scripts/mc-security-watch`
- `scripts/install-dream-timer.sh`
- `scripts/install-security-watch-timer.sh`

### Dados locais

- Banco SQLite: `~/.local/share/mastercontrol/mastercontrol.db`
  - `command_events`
  - `operator_patterns`
  - `dream_insights`
  - `learned_rules`
  - `context_snapshots`
  - `event_monitor_state`
  - `event_source_state`
  - `system_events`
  - `security_alerts`
  - `incidents`
  - `incident_activity`
  - compartilhado por profiler, contexto persistido, monitor incremental de eventos, alerta local continuo e sinais usados em `path selection`, `policy`, auditoria local e vigilancia de seguranca

## 4) Soul / Identity Config

### Responsabilidade

- Identidade operacional e diretrizes de comunicacao.

### Arquivos

- `config/soul/core_profile.yaml`
- `docs/SOUL_CORE.md`
- `docs/HUMANIZATION_RUNTIME.md`
- `docs/AI_INTERFACE.md`

## 5) Documentacao de referencia

- `docs/INDEX.md`
- `docs/PROJECT_FOUNDATIONS.md`
- `docs/MC_ENGINEERING_FLOW.md`
- `docs/CORE_CONTRACTS.md`
- `docs/CONTEXT_ENGINE.md`
- `docs/PEXEC_MODEL.md`
- `docs/SECURITY_WATCH.md`
- `docs/MASTERCONTROL_V0.1_SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/OPERATIONAL_INTELLIGENCE.md`
- `docs/ADAPTIVE_INTELLIGENCE_SPEC.md`
- `docs/ADAPTIVE_RUNTIME.md`
- `docs/DREAM_TIMER.md`
- `docs/WORKLOG.md`

## 6) Testes automatizados

- `tests/test_root_exec_security.py`
- `tests/test_privilege_broker.py`
- `tests/test_intent_classifier.py`
- `tests/test_mc_ai_interface.py`
- `tests/test_mc_tui.py`
- `tests/test_mastercontrold_context.py`
- `tests/test_mastercontrold_flow.py`
- `tests/test_ollama_adapter.py`
- `tests/test_context_collectors.py`
- `tests/test_contracts.py`
- `tests/test_context_engine.py`
- `tests/test_context_events.py`
- `tests/test_context_store.py`
- `tests/test_path_selector_context.py`
- `tests/test_policy_engine.py`
- `tests/test_pexec.py`
- `tests/test_security_watch.py`
