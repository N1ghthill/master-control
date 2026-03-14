# MasterControl - Arquitetura de referencia

## 1) Componentes principais

1. `mastercontrold` (core daemon)
- Orquestra intents, planning, policy e execucao.
- Exponibiliza API local por Unix socket.

2. `mc-cli` (interface operacional)
- Entrada principal para o operador.
- Suporta comandos diretos e natural language.

3. `mc-contextd` (state collectors)
- Coletores assincronos para compor consciencia situacional.
- Atualiza store com snapshots incrementais.
- Faz sweep incremental de `journald` para invalidar contexto afetado por eventos reais do host.

4. `mc-policyd`
- Motor de regras por risco, modulo e alvo.
- Decide allow/deny/step-up.

5. `mc-runtime`
- Executor deterministico.
- Chama modulos com contratos fixos.
- Garante timeout, retries e rollback.

6. `mc-memory`
- Armazena estado de contexto, historico de acoes e preferencias.
- Backend inicial: SQLite local.

7. `mc-llm-adapter`
- Abstracao para modelos locais open-source.
- Fornece parsing de intent, planejamento e justificativa.

8. `mc-path-selector`
- Classifica complexidade/risco/incerteza.
- Decide `FAST`, `DEEP` ou `FAST_WITH_CONFIRM`.
- Promove automaticamente para `DEEP` quando houver sinal de baixa confianca.

9. `mc-privilege-broker`
- Plane de elevacao para operacoes root.
- Executa somente `action_id` allowlisted.
- Faz validacao de argumentos + auditoria obrigatoria.

## 2) Separacao de planos

- `Control Plane`: LLM + planner + policy decision.
- `Execution Plane`: runtime + modules + verificacao.
- `Privilege Plane`: broker root com policy e allowlist de comandos.

Regra: LLM nao executa comando de sistema diretamente.
Regra: runtime nao executa shell root arbitrario; apenas `action_id` permitida.

## 3) Pipeline de comando

1. Receber comando do usuario.
2. Resolver identidade/contexto rapido no store.
3. Converter para intent estruturada.
4. `Path Selector` decide fast/deep path.
5. Planejar acoes candidatas.
6. Avaliar politica e risco.
7. Executar via modulo.
8. Se precisar root: chamar `Privilege Broker` com `action_id` validada.
9. Verificar resultado e registrar auditoria.
10. Se falha por falta de contexto: replanejar em deep path.
11. Responder ao operador.

## 4) Consciencia situacional sem custo linear

Para evitar latencia alta por comando:

- Coletores rodam em background e atualizam estado continuamente.
- Core consulta snapshots versionados (O(1) para leitura basica).
- Deep context e carregado apenas quando necessario.
- Eventos do sistema sao ingeridos de forma incremental, com cursor persistido e `min_interval`, em vez de polling caro por mensagem.

Coletores iniciais:

- Sessao/usuario (`who`, `loginctl`, TTY).
- SO/hardware (`os-release`, kernel, memoria, disco).
- Rede/DNS (`ip`, `nmcli`, unbound health).
- Servicos (`systemctl`).
- Seguranca basica (falhas auth recentes, portas expostas).
- Sweep de eventos recentes do `journald` para manter invalidacao de snapshots coerente com mudancas reais.

## 5) Contrato de modulo

Cada modulo implementa interface padrao:

```text
capabilities() -> list[Capability]
health() -> HealthReport
plan(intent, context) -> ActionPlan
apply(action, policy) -> ActionResult
verify(expected) -> VerificationResult
rollback(checkpoint) -> RollbackResult
```

## 6) Modulos v0.1

- `mod-dns`: backend `unbound-cli`.
- `mod-services`: backend `systemctl`.
- `mod-packages`: backend `apt`, `dpkg`.
- `mod-network`: backend `ip`, `nmcli`, `ss`.
- `mod-security`: checks basicos e baseline.

## 7) Politica e risco

Decisao da politica:

- `allow`: executa direto.
- `confirm`: pede confirmacao contextual.
- `step_up`: exige elevacao de confianca.
- `deny`: bloqueia e explica.

Para acoes privilegiadas, policy deve retornar tambem:

- `privilege_mode`: `none | broker | pkexec_bootstrap`
- `approval_scope`: `single_action | time_window`

Estado atual:

- `pkexec_bootstrap` continua como fallback operacional do host.
- `broker` ja existe em forma inicial via socket Unix local e reusa o executor allowlisted.

## 8) Persistencia e auditoria

Tabelas iniciais (SQLite):

- `events`: eventos do sistema e alertas.
- `actions`: plano, execucao, resultado.
- `approvals`: aprovacoes, nivel de confianca, expiracao.
- `preferences`: escolhas do operador.
- `incidents`: problema, causa, fix aplicado.

Estado atual implementado:

- `context_snapshots`
- `command_events`
- `operator_patterns`
- `dream_insights`
- `learned_rules`
- `event_monitor_state`
- `event_source_state`
- `system_events`
- `security_alerts`

Eventos incrementais atuais:

- `journald` com cursor persistido para servicos, pacotes, rede e auth.
- `udevadm info --export-db` para topologia de dispositivos.
- `dbus/login1` via `busctl` para mudancas de sessoes locais.

Alerting local atual:

- `mc-security-watch` consolida `system_events` em alertas priorizados.
- alertas persistem em `security_alerts`.
- o fluxo conversacional pode consultar o mesmo estado por `security.vigilance.status`.
- o fluxo local tambem pode montar `security.incident.plan` a partir desses alertas.
- contenção automatizada continua limitada: hoje o `mod_security` so permite remediação correlacionada em tres dominios estreitos:
  - servicos afetados diretamente,
  - `ssh.service` para incidentes de autenticacao,
  - servicos da stack de rede para incidentes de conectividade,
  sempre reaproveitando acoes allowlisted ja existentes e ainda dependente de approval/policy.

## 9) Observabilidade

- Logs estruturados (`jsonl`) por componente.
- Correlacao por `trace_id`.
- Metricas minimas:
  - latencia por etapa,
  - taxa de sucesso,
  - acerto do path selector (quando fast precisou escalar para deep),
  - bloqueios por politica,
  - rollback rate.

## 10) Stack sugerida (v0.1)

- Linguagem core: Python 3.13.
- IPC: Unix socket (JSON-RPC simples).
- Storage: SQLite.
- Modulos: Python wrappers para CLIs do sistema.
- LLM local: adapter pluggable (Ollama/llama.cpp/vLLM local).
- Elevacao bootstrap: polkit + pkexec com policy dedicada.
- Broker inicial: socket Unix local em `mastercontrol/privilege/broker.py`.

## 11) Estrutura de repositorio sugerida

```text
master-control/
  docs/
  mastercontrol/
    core/
    runtime/
    privilege/
    policy/
    context/
    memory/
    llm/
    modules/
      dns/
      services/
      packages/
      network/
      security/
  tests/
  scripts/
```
