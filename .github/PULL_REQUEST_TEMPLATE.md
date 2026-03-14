## Summary

Descreva a mudanca em 2-5 linhas.

## Operator Need

- Qual necessidade real do operador esta sendo atendida?
- Qual desgaste operacional isso reduz ou evita?

## MC Capability

- O que o `MasterControl` passa a saber, decidir, explicar ou executar melhor?
- Como essa mudanca fortalece o `MC` como agente central?

## Protocol / Policy Impact

- Quais instrucoes, protocolos, guardrails ou contratos mudam?
- Ha impacto em risco, confirmacao, step-up, privilegio ou auditoria?

## Modules / Tools Impact

- Quais modulos ou ferramentas foram tocados?
- Eles continuam funcionando como extensoes do `MC`, sem logica paralela?

## Humanization / Intelligence Impact

- Como a mudanca melhora inteligencia operacional?
- Como ela melhora humanizacao, clareza ou adaptacao ao operador?

## Verification

- Testes unitarios:
- Smoke / fluxo real:
- Verificacao manual:

## Checklist

- [ ] A mudanca nasce de uma necessidade real do operador.
- [ ] O centro da mudanca e o `MC`, nao um modulo isolado.
- [ ] Modulos e ferramentas continuam como extensoes do `MC`.
- [ ] Policy, privilegio e auditoria foram considerados.
- [ ] Humanizacao e inteligencia foram tratadas como requisitos reais.
- [ ] Documentacao canonica foi atualizada quando necessario.
- [ ] Testes e/ou smoke foram executados e descritos acima.

## References

- `docs/MC_ENGINEERING_FLOW.md`
- `docs/PROJECT_FOUNDATIONS.md`
- `CONTRIBUTING.md`
