# Code Map

Mapa atualizado dos arquivos de codigo do MasterControl, organizado por dominio.

## 1) Core Intelligence

### Responsabilidade

- Orquestracao principal.
- Humanizacao de resposta.
- Selecao autonoma de caminho (`fast/deep`).

### Arquivos

- `mastercontrol/core/mastercontrold.py`
- `mastercontrol/core/humanized_kernel.py`
- `mastercontrol/core/path_selector.py`
- `mastercontrol/core/__init__.py`
- `mastercontrol/modules/mod_dns.py`
- `mastercontrol/modules/mod_network.py`
- `mastercontrol/modules/mod_services.py`
- `mastercontrol/modules/mod_packages.py`
- `mastercontrol/modules/registry.py`
- `mastercontrol/modules/base.py`
- `mastercontrol/modules/__init__.py`

### Entrypoint de uso

- `scripts/mastercontrol`
- `scripts/mc-humanized`
- `scripts/mc-ai`

### Interface conversacional

- `mastercontrol/interface/mc_ai.py`
- `mastercontrol/interface/__init__.py`

## 2) Security / Privileges

### Responsabilidade

- Execucao privilegiada por allowlist.
- Integracao bootstrap com `pkexec/polkit`.
- Auditoria de acoes root.
- Validacao de allowlist confiavel para execucao root.

### Arquivos

- `mastercontrol/runtime/root_exec.py`
- `mastercontrol/runtime/__init__.py`
- `config/privilege/actions.json`
- `config/polkit/io.mastercontrol.rootexec.policy`
- `scripts/install-privilege-bootstrap.sh`
- `scripts/mc-root-action`

### Docs relacionadas

- `docs/PRIVILEGE_MODEL.md`
- `docs/PRIVILEGE_BOOTSTRAP.md`

## 3) Adaptive Intelligence

### Responsabilidade

- Perfil comportamental do operador.
- Analise de tom/urgencia leve.
- "Dream" offline para insights operacionais.

### Arquivos

- `mastercontrol/context/mc_operator_profiler.py`
- `mastercontrol/context/__init__.py`
- `mastercontrol/tone/mc_tone_analyzer.py`
- `mastercontrol/tone/intent_classifier.py`
- `mastercontrol/tone/__init__.py`
- `mastercontrol/dream/mc_dream.py`
- `mastercontrol/dream/__init__.py`
- `scripts/mc-operator-profiler`
- `scripts/mc-tone-analyzer`
- `scripts/mc-intent-classifier`
- `scripts/mc-dream`
- `scripts/install-dream-timer.sh`

### Dados locais

- Banco SQLite: `~/.local/share/mastercontrol/mastercontrol.db`
  - `command_events`
  - `operator_patterns`
  - `dream_insights`
  - `learned_rules`

## 4) Soul / Identity Config

### Responsabilidade

- Identidade operacional e diretrizes de comunicacao.

### Arquivos

- `config/soul/core_profile.yaml`
- `docs/SOUL_CORE.md`
- `docs/HUMANIZATION_RUNTIME.md`
- `docs/AI_INTERFACE.md`

## 5) Documentacao de referencia

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
- `tests/test_intent_classifier.py`
