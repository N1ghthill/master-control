---
name: MC Capability
about: Propor uma nova capacidade do MasterControl
title: "[mc-capability] "
labels: enhancement
assignees: ""
---

## Operator Need

- Qual problema real do operador precisa ser resolvido?
- Em que contexto isso acontece no uso real do `MC`?

## Expected Operator Protocol

- O que o operador quer delegar, observar, confirmar ou bloquear?
- Existe instrucao, limite ou regra operacional que precisa ficar explicita?

## MC Capability

- O que o `MC` precisa passar a saber, decidir, comunicar ou executar?
- Por que isso pertence ao agente central e nao apenas a um modulo?

## Modules / Tools Involved

- Quais modulos, ferramentas ou integracoes estao envolvidos?
- Essa mudanca mantem os modulos como extensoes do `MC`?

## Policy / Risk

- Qual e o risco esperado?
- Ha impacto em confirmacao, step-up, privilegio, auditoria ou rollback?

## Humanization / Intelligence

- Como o `MC` deve se adaptar ao operador nesse fluxo?
- Como a inteligencia local ajuda sem romper o controle?

## Acceptance Criteria

- [ ] O fluxo do operador ficou claro.
- [ ] O papel do `MC` ficou claro.
- [ ] O impacto em policy e seguranca ficou claro.
- [ ] O criterio de verificacao ficou claro.

## Verification Plan

- Testes unitarios:
- Smoke / fluxo real:
- Verificacao manual:

## References

- `docs/MC_ENGINEERING_FLOW.md`
- `docs/PROJECT_FOUNDATIONS.md`
- `docs/ARCHITECTURE.md`
