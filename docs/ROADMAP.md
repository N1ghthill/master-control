# MasterControl - Roadmap de execucao

## Estado atual (2026-03-06)

- Fase 4 iniciada parcialmente com adapter LLM local no `mc-ai` (Ollama).
- Benchmark local comparando `qwen2.5:7b` e `qwen3.5:4b` concluido para uso conversacional.
- Integracao LLM no loop principal `mastercontrold` continua pendente.

## Fase 0 - Fundacao (1 semana)

- Definir schemas de `Intent`, `ActionPlan`, `PolicyDecision`, `ActionResult`.
- Criar esqueleto do repositorio e padrao de logs.
- Definir baseline de seguranca e niveis de risco.
- Definir criterios do `Path Selector` (fast/deep) e fallback seguro.
- Definir allowlist inicial de acoes privilegiadas + politica polkit/pkexec.

Saida:
- Repo estruturado + contratos estaveis.

## Fase 1 - Core observador (2 semanas)

- `mastercontrold` com `mc-cli`.
- `mc-contextd` com snapshots de sistema.
- `mc-memory` (SQLite) com trilha de eventos.
- Sem mutacoes no SO (read-only).

Saida:
- Agente explica "o que esta acontecendo agora" com contexto confiavel.

## Fase 2 - Runtime e policy (2 semanas)

- `mc-runtime` deterministico.
- `mc-policyd` com regras por risco.
- Fluxo `plan -> policy -> execute -> verify -> audit`.
- Bootstrap de elevacao funcional (`pkexec` + executor root allowlist).

Saida:
- Execucao controlada para baixo risco.

## Fase 3 - Modulos essenciais (2 a 3 semanas)

- `mod-dns` (unbound-cli).
- `mod-services`.
- `mod-packages`.
- `mod-network`.
- `mod-security` baseline.

Saida:
- Operacao real de administracao local com guardrails.

## Fase 4 - Inteligencia local (2 semanas)

- Integrar LLM local via adapter.
- Intent parsing + planner com schema estrito.
- Path Selector autonomo (fast vs deep) com explicacao de roteamento.

Saida:
- Conversa natural com execucao segura.

## Fase 5 - Confianca e experiencia (2 semanas)

- Trust levels (`T0..T3`) e step-up.
- Lotes de aprovacao com expiracao curta.
- Playbooks de incidente e auto-sugestao.
- Migracao de bootstrap para broker root permanente via systemd.

Saida:
- Sistema usavel no dia a dia com baixa friccao.

## Indicadores de sucesso

- p95 fast path < 500 ms para tarefas simples.
- p95 deep plan < 3 s para diagnosticos iniciais.
- menos de 5% de reclassificacao `fast -> deep` por erro de contexto.
- 100% das mutacoes com auditoria completa.
- 100% das acoes root executadas por allowlist (0 shell root livre).
- rollback disponivel para modulos criticos.
- zero execucao sem policy decision registrada.

## Regras de rollout

- Sempre com feature flags.
- Primeiro em modo observador.
- Mutacao apenas apos testes de modulo + cenarios de falha.
