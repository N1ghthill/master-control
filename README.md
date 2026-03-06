# MasterControl

Orquestrador geral para Debian/Linux: um "cerebro modular" que observa, analisa e executa operacoes no SO com seguranca, auditabilidade e controle humano.

## Visao

MasterControl deve ser:

- Obediente: segue ordens do operador dentro de politicas claras.
- Inteligente: interpreta contexto, planeja e escolhe a melhor acao.
- Autonomo no raciocinio: decide sozinho quando usar fast path ou deep path.
- Prestativo e util: responde rapido para tarefas simples e aprofunda quando necessario.
- Situacional: sabe `quem`, `onde`, `quando` e `o que esta acontecendo agora`.
- Modular: inteligencia no core; operacoes em modulos especializados.

## Principios de engenharia

- Sem "LLM com root livre".
- Separacao entre raciocinio (LLM) e execucao (runtime deterministico).
- Politicas explicitas para risco e permissoes.
- Dry-run, verificacao pos-acao e rollback sempre que possivel.
- Telemetria e trilha de auditoria como requisitos de produto.

## Documentacao inicial

- [Code Map](./docs/CODE_MAP.md)
- [Especificacao v0.1](./docs/MASTERCONTROL_V0.1_SPEC.md)
- [Arquitetura](./docs/ARCHITECTURE.md)
- [Identidade e Confianca](./docs/IDENTITY_AND_TRUST.md)
- [Soul Core](./docs/SOUL_CORE.md)
- [Humanization Runtime](./docs/HUMANIZATION_RUNTIME.md)
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
- modulos DNS/service/package/network conectados ao runtime,
- bootstrap de privilegios ativo via `pkexec` + allowlist,
- testes automatizados iniciais em `tests/` (`python3 -m unittest discover -s tests -v`).
