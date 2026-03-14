# MasterControl

Orquestrador geral para Debian/Linux: um "cerebro modular" que observa, analisa e executa operacoes no SO com seguranca, auditabilidade e controle humano.

## Contrato central

O `MasterControl` (`MC`) e o agente central do sistema.

A hierarquia correta do projeto e:

1. operador;
2. instrucoes, protocolos e limites definidos pelo operador;
3. `MC` como agente Linux profundamente integrado;
4. modulos como ferramentas e extensoes do `MC`;
5. host Linux real como ambiente operado.

O `MC` existe para servir e ajudar o operador. A camada de I.A existe para dar inteligencia adaptativa e humanizacao ao `MC`, nao para substituir esse contrato.

## Visao

MasterControl deve ser:

- Obediente: segue ordens do operador dentro de politicas claras.
- Inteligente: interpreta contexto, planeja e escolhe a melhor acao.
- Humanizado: comunica com adaptacao real ao operador, ao risco e ao momento.
- Autonomo no raciocinio: decide sozinho quando usar fast path ou deep path.
- Prestativo e util: responde rapido para tarefas simples e aprofunda quando necessario.
- Situacional: sabe `quem`, `onde`, `quando` e `o que esta acontecendo agora`.
- Modular: inteligencia no core; modulos existem como extensoes do `MC`.

## Principios de engenharia

- Sem "LLM com root livre".
- Separacao entre raciocinio (LLM) e execucao (runtime deterministico).
- Politicas explicitas para risco e permissoes.
- Dry-run, verificacao pos-acao e rollback sempre que possivel.
- Telemetria e trilha de auditoria como requisitos de produto.

## Documentacao

- [Indice da documentacao](./docs/INDEX.md)
- [Guia de contribuicao](./CONTRIBUTING.md)
- [Fundamentos do projeto](./docs/PROJECT_FOUNDATIONS.md)
- [Fluxo de engenharia do MC](./docs/MC_ENGINEERING_FLOW.md)
- [Contratos centrais](./docs/CORE_CONTRACTS.md)
- [Context Engine](./docs/CONTEXT_ENGINE.md)
- [Continuous Security Watch](./docs/SECURITY_WATCH.md)
- [Operacao de Incidentes](./docs/INCIDENT_OPERATIONS.md)
- [PExec / Execucao privilegiada](./docs/PEXEC_MODEL.md)
- [Privilege Broker](./docs/PRIVILEGE_BROKER.md)
- [Code Map](./docs/CODE_MAP.md)
- [Especificacao v0.1](./docs/MASTERCONTROL_V0.1_SPEC.md)
- [Arquitetura](./docs/ARCHITECTURE.md)
- [Identidade e Confianca](./docs/IDENTITY_AND_TRUST.md)
- [Soul Core](./docs/SOUL_CORE.md)
- [Humanization Runtime](./docs/HUMANIZATION_RUNTIME.md)
- [Interface IA (chat)](./docs/AI_INTERFACE.md)
- [MasterControlD Runtime](./docs/MASTERCONTROLD_RUNTIME.md)
- [Inteligencia Operacional](./docs/OPERATIONAL_INTELLIGENCE.md)
- [Adaptive Intelligence Spec](./docs/ADAPTIVE_INTELLIGENCE_SPEC.md)
- [Adaptive Runtime Usage](./docs/ADAPTIVE_RUNTIME.md)
- [Nightly Dream Timer](./docs/DREAM_TIMER.md)
- [Privilegios e Elevacao](./docs/PRIVILEGE_MODEL.md)
- [Bootstrap de Privilegios](./docs/PRIVILEGE_BOOTSTRAP.md)
- [Diario de Acoes e Resultados](./docs/WORKLOG.md)
- [Roadmap](./docs/ROADMAP.md)

## Estado atual

Prototipo funcional `v0.1` com:

- loop principal executavel (`mastercontrold`),
- agente central ja estruturado para operar por contexto, policy, memoria e comunicacao adaptativa,
- modulos DNS/service/package/network conectados ao runtime,
- interface conversacional `mc-ai` com assistente local opcional via Ollama,
- atalho de uso conversacional: `scripts/mc-ai-chat` (preset atual para `qwen3:4b-instruct-2507-q4_K_M`),
- bootstrap de privilegios ativo via `pkexec` + allowlist,
- broker privilegiado inicial via socket Unix + approval tokens curtos,
- ledger persistente de incidentes com `open | contained | resolved | dismissed`,
- acoes locais explicitas para `incident list/show/resolve/dismiss`,
- TUI com painel navegavel de incidentes ativos,
- watcher com schema versionado e pruning local de dados historicos,
- alvo operacional principal: `Debian Testing`,
- testes automatizados em `tests/` (`python3 -m unittest discover -s tests -v`).
