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

Coletores iniciais:

- Sessao/usuario (`who`, `loginctl`, TTY).
- SO/hardware (`os-release`, kernel, memoria, disco).
- Rede/DNS (`ip`, `nmcli`, unbound health).
- Servicos (`systemctl`).
- Seguranca basica (falhas auth recentes, portas expostas).

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

## 8) Persistencia e auditoria

Tabelas iniciais (SQLite):

- `events`: eventos do sistema e alertas.
- `actions`: plano, execucao, resultado.
- `approvals`: aprovacoes, nivel de confianca, expiracao.
- `preferences`: escolhas do operador.
- `incidents`: problema, causa, fix aplicado.

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
