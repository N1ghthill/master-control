# MasterControl - Handoff de Retomada

## Data

- checkpoint atualizado em `2026-03-14`

## Onde o projeto parou

- O projeto consolidou a parte mais forte da `Fase 6`.
- O broker privilegiado root esta funcional no host Debian Testing e validado com:
  - bloqueio sem token,
  - approval token curto,
  - `dry-run` seguro,
  - mutacao real auditada via `systemd`.
- O watcher local de seguranca agora cobre:
  - `system_events`,
  - `security_alerts`,
  - `ack/silence`,
  - `security.incident.plan`,
  - `incident ledger` persistente (`incidents`, `incident_activity`),
  - listagem, detalhe, `resolve` e `dismiss` de incidente por `incident_id`.
- O rollout operacional no host ja foi concluido:
  - `mastercontrol-security-watch.timer` instalado e ativo,
  - `mastercontrol-privilege-broker.socket` instalado e ativo,
  - `mastercontrol-privilege-broker.service` validado via socket activation.
- O watcher no host esta com retencao final aplicada:
  - `system_events=7d`
  - `security_alerts=21d`
  - `incidents=60d`
  - `incident_activity=90d`
  - `security_silences=14d`
- A regressao de auto-observacao do watcher foi corrigida:
  - o monitor ignora logs emitidos pelo proprio MasterControl,
  - `security.auth.anomaly` nao trata mais sessoes `pkexec/sudo` bem-sucedidas como anomalia por si so.
- A resposta a incidente continua com contenção limitada por policy em tres dominios:
  - `service`: remediacao correlacionada por unidade afetada,
  - `security/auth`: `ssh.service` apenas,
  - `network`: servicos da stack de rede como `NetworkManager.service`, `systemd-networkd.service` e `systemd-resolved.service`.

## O que esta pronto

- contratos centrais, contexto em camadas, store persistente e invalidacao por evento;
- `PathSelector` e `PolicyEngine` usando sinais reais do host;
- broker root com socket Unix, approval token e auditoria;
- watcher continuo com ciclo de vida de alertas;
- ledger persistente de incidentes com estado `open | contained | resolved | dismissed`;
- trilha `incident_activity` com decisao do operador e ultima acao;
- playbooks locais de incidente;
- contenção automatizada estreita, sempre reaproveitando acoes allowlisted existentes e ainda dependente de approval/policy;
- interface local/TUI com resumo combinado de alertas + incidentes e diretivas explicitas:
  - `/incidents`
  - `/incident-show <incident_id>`
  - `/incident-resolve <incident_id>`
  - `/incident-dismiss <incident_id>`
- painel navegavel de incidentes na TUI com selecao por `Up/Down` e detalhe do item selecionado;
- schema versionado do watcher em `security_watch_meta` (versao atual `3`);
- pruning local para `system_events`, `security_alerts`, `security_silences`, `incidents` e `incident_activity`;
- testes de recovery para reinicio do watcher e do broker com persistencia em SQLite.
- instalador do watcher com retencao/pruning como configuracao operacional de unit;
- instaladores de watcher e broker com `--output-dir` para validacao nao-destrutiva via `systemd-analyze verify`;
- playbook do operador para `ack/silence/resolve/dismiss/contain` em `docs/INCIDENT_OPERATIONS.md`;
- validacao operacional local feita com:
  - geracao real de units em diretorio temporario,
  - `systemd-analyze verify`,
  - `mc-security-watch --prune-only`,
  - roundtrip de broker com restart entre `approve` e `exec`.
- validacao operacional no host ja feita com:
  - units reais instalados e ativos,
  - `dry-run` real via broker no socket do host,
  - sweeps reais do watcher com pruning ativo,
  - limpeza do incidente artificial causado pela antiga auto-observacao.

## Restricoes importantes

- nao abrir primitivas privilegiadas novas sem regra de policy clara e teste dedicado;
- nao automatizar resposta defensiva ampla sem correlacao explicita com incidente ativo persistido;
- `auth` continua limitado a `ssh.service`;
- `network` continua limitado a restart de servicos da stack de rede;
- qualquer expansao sensivel precisa manter trilha completa `plan -> policy -> approval -> execute -> verify -> audit`.

## Melhor ponto para retomar

O proximo bloco tecnico recomendado deixou de ser instalacao. Agora e endurecimento operacional do host real e reducao de ruido residual.

Objetivo:
- sair de "servicos instalados e funcionando" para "servicos observados, previsiveis e com ruido controlado".

Entregas recomendadas:
- validar reboot/restart do host e confirmar socket activation do broker e retomada do timer do watcher;
- observar alguns ciclos reais com a retencao `7/21/60/90/14` e revisar crescimento do SQLite;
- decidir tratamento operacional para o ruido atual de `network.instability` e `service.failure.cluster`:
  - corrigir origem real,
  - silenciar por janela,
  - ou refinar classificacao se houver falso positivo recorrente;
- so depois escolher entre ampliar UX operacional adicional ou ampliar automacao defensiva.

## Ordem sugerida para a proxima sessao

1. Validar reboot/restart do host com os services ja instalados:
   - `mastercontrol-security-watch.timer`,
   - `mastercontrol-privilege-broker.socket`,
   - `mastercontrol-privilege-broker.service` via socket activation.
2. Medir comportamento real:
   - crescimento do SQLite,
   - ruido residual de alertas,
   - uso efetivo de `ack/silence/resolve/dismiss`.
3. Decidir resposta para `network.instability` e `service.failure.cluster`.
4. Ajustar heuristica/classificacao ou silences operacionais se necessario.
5. So depois avaliar ampliacao da automacao defensiva.

## Arquivos de entrada recomendados

- `mastercontrol/security/watcher.py`
- `mastercontrol/modules/mod_security.py`
- `mastercontrol/core/mastercontrold.py`
- `mastercontrol/interface/mc_ai.py`
- `mastercontrol/interface/mc_tui.py`
- `tests/test_security_watch.py`
- `tests/test_mastercontrold_flow.py`
- `tests/test_mc_ai_interface.py`

## Verificacao minima ao retomar

```bash
python3 -m unittest discover -s tests -v
```

Estado do ultimo checkpoint:
- suite verde com `153` testes.
