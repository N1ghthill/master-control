# MasterControl - Roadmap

## Estado atual (2026-03-14)

- O projeto esta em prototipo funcional `v0.1`.
- O alvo principal passou a ser explicitamente `Debian Testing`.
- O core ja tem orquestracao inicial, modulos operacionais basicos, bootstrap de privilegios e interface conversacional local.
- A arquitetura desejada ainda esta parcialmente documentada e parcialmente implementada.

## Norte do roadmap

Este roadmap organiza o projeto para cumprir os compromissos definidos em `docs/PROJECT_FOUNDATIONS.md`:

- documentacao forte para contribuidores,
- integracao profunda com Linux,
- permissoes e guardrails do operador,
- consciencia situacional com custo proporcional,
- identidade estavel do MC,
- obediencia com protecao em risco alto,
- autoconsciencia do proprio funcionamento,
- especializacao Linux e Debian,
- defesa do host,
- evolucao modular continua.

## Fase 0 - Base documental e contratos

Objetivo:
- tornar o projeto legivel, contribuivel e governavel antes de ampliar autonomia.

Entregas:
- indice de documentacao e guia de contribuicao;
- consolidacao da visao e dos fundamentos do projeto;
- contratos estaveis para `Intent`, `ContextSnapshot`, `ActionPlan`, `PolicyDecision`, `ActionResult`;
- manifesto de ambiente e dependencias do projeto;
- padrao claro para logs, auditoria e compatibilidade de modulos.

Criterio de saida:
- um novo contribuidor entende arquitetura, risco, fluxo privilegiado e pontos de extensao sem depender de conversa privada.

## Fase 1 - Plataforma Debian e ambiente reproducivel

Objetivo:
- fazer o MC nascer como um sistema Linux real, nao como camada abstrata generica.

Entregas:
- suporte formal a `Debian Testing`;
- manifesto de dependencias Python e de ferramentas do host;
- instalacao local reproduzivel;
- baseline de integracao com `systemd`, `journald`, `apt`, `dpkg`, `ip`, `ss`, `/proc` e `/sys`;
- matriz de suporte do que e garantido no host alvo.

Criterio de saida:
- ambiente local sobe de forma previsivel e documentada em Debian Testing.

## Fase 2 - Context engine e memoria operacional

Objetivo:
- dar ao MC consciencia do ambiente com custo proporcional a tarefa.

Entregas:
- `mc-contextd` com snapshots em camadas;
- estrategia de `hot`, `warm` e `deep context`;
- cache, `TTL`, invalidacao e atualizacao por evento;
- store local para contexto, eventos, historico e incidentes;
- path selector consumindo contexto real em vez de heuristica isolada.

Regras desta fase:
- nao rodar varredura ampla por default;
- nao usar bateria fixa de verificacoes por mensagem;
- subir de camada de contexto apenas quando houver necessidade tecnica.

Criterio de saida:
- interacoes simples usam contexto leve e recente;
- diagnosticos e operacoes elevam observacao apenas quando necessario.

## Fase 3 - Identidade, confianca, policy e aprovacao

Objetivo:
- controlar quem pede, o que pode ser feito e em quais condicoes.

Entregas:
- modelo de identidade do operador e confianca de sessao;
- `mc-policyd` com risco, escopo e step-up;
- tokens de aprovacao com validade curta;
- registro de decisao de policy antes de toda mutacao;
- kill-switch local e limites para operacoes sensiveis.

Criterio de saida:
- toda operacao mutavel tem politica explicita, escopo claro e auditoria.

## Fase 4 - Runtime deterministico e privilege broker

Objetivo:
- executar com previsibilidade e seguranca, inclusive em acoes privilegiadas.

Entregas:
- consolidacao do fluxo `plan -> policy -> execute -> verify -> audit`;
- evolucao do bootstrap atual para broker privilegiado de longa vida;
- verificacao pos-acao e rollback quando fizer sentido;
- contratos deterministas entre core, runtime e modulos.

Criterio de saida:
- zero mutacao sem policy decision;
- zero shell privilegiado arbitrario;
- toda acao root passa por allowlist.

## Fase 5 - Especializacao Linux e modulos operacionais

Objetivo:
- tornar o MC um operador Linux util de verdade.

Entregas:
- maturidade dos modulos `dns`, `services`, `packages` e `network`;
- criacao de `mod-security`;
- contratos e SDK de modulo;
- playbooks tecnicos para instalacao, remocao, reparo, compilacao e configuracao;
- integracao com base de conhecimento Linux e Debian.

Criterio de saida:
- o MC executa e orienta tarefas reais de administracao local com guardrails fortes.

## Fase 6 - Vigilancia, protecao e resposta a incidente

Objetivo:
- proteger operador e host sem perder controle humano.

Entregas:
- observacao de logs relevantes;
- deteccao de falhas de autenticacao, portas expostas e mudancas suspeitas;
- planos de resposta em modo observador primeiro;
- automacao defensiva gradual, condicionada a policy.

Estado atual:
- `system_events`, `security_alerts`, `ack/silence` e watcher continuo ja estao operacionais;
- `security.incident.plan` gera playbooks locais a partir dos alertas ativos;
- `incident ledger` persistente ja existe com `incidents` e `incident_activity`;
- a interface local ja expone resumo de incidentes ativos e comandos explicitos para listar, inspecionar, resolver e descartar incidentes;
- contenção automatizada inicial existe e continua estreita:
  - servicos afetados com correlacao explicita de unidade;
  - `ssh.service` para auth anomaly;
  - servicos da stack de rede para network instability;
  sempre dependente de approval/policy.

Criterio de saida:
- o MC detecta, explica e sugere resposta para eventos de seguranca relevantes;
- automacao defensiva sensivel fica auditada e limitada por risco.

## Fase 7 - Experiencia humanizada e inteligencia local

Objetivo:
- unir naturalidade conversacional com disciplina operacional.

Entregas:
- identidade do `MC` consistente em todas as interfaces;
- explicacoes claras de risco, impacto, rollback e estado atual;
- planner local melhor integrado ao contexto e a policy;
- orientacao embutida sobre como usar o proprio sistema;
- uso de LLM local de forma auxiliar e controlada.

Criterio de saida:
- o operador entende o que o MC sabe, vai fazer, ja fez e por que.

## Fase 8 - Modularidade, atualizacoes e evolucao continua

Objetivo:
- permitir crescimento do sistema sem quebrar previsibilidade.

Entregas:
- versionamento de contratos de modulo;
- mecanismo de carga e atualizacao de modulos;
- feature flags e compatibilidade entre core e extensoes;
- estrategia de update do core e dos modulos;
- testes de regressao por modulo e por capacidade.

Criterio de saida:
- novos modulos entram com baixo atrito e sem violar arquitetura ou seguranca.

## Proximo sprint recomendado

1. Validar reboot/restart do host com watcher e broker ja instalados no Debian Testing.
2. Observar alguns ciclos reais do timer com a retencao operacional `7/21/60/90/14` e medir crescimento do SQLite.
3. Tratar o ruido residual de `network.instability` e `service.failure.cluster` com correcao real, silencio operacional ou refinamento de classificacao.
4. So depois decidir se o proximo incremento deve priorizar UX operacional adicional ou ampliacao da automacao defensiva.
5. Manter docs, instaladores e service units sincronizados com o comportamento real do runtime.

## Indicadores de sucesso

- p95 de interacoes simples abaixo do custo de uma coleta profunda.
- p95 de diagnostico inicial controlado e justificavel.
- menos de 5% de reclassificacao `fast -> deep` por erro de contexto.
- 100% das mutacoes com auditoria completa.
- 100% das acoes root por allowlist.
- zero shell root arbitrario.
- rollback ou estrategia de recuperacao definida para modulos criticos.
- zero execucao mutavel sem `PolicyDecision`.

## Regras de rollout

- primeiro observacao, depois mutacao;
- sempre com feature flags quando aumentar autonomia;
- testes de modulo e cenarios de falha antes de liberar mutacao;
- mudancas em privilegio, contexto ou seguranca exigem docs e testes na mesma entrega.
