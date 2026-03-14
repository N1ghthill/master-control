# MasterControl - Core Contracts

Este documento define os contratos centrais que devem permanecer estaveis entre core, contexto, policy, runtime, privilegio e modulos.

## Objetivo

Evitar acoplamento informal entre partes do sistema. O MC precisa de estruturas comuns para:

- entender intencao e contexto,
- planejar acoes,
- decidir policy,
- executar com privilegio controlado,
- registrar resultado e auditoria.

## Contratos atuais no codigo

Implementados em `mastercontrol/contracts.py`:

- `OperatorIdentity`
- `ContextSnapshot`
- `PlannedAction`
- `ActionPlan`
- `PolicyDecision`
- `ActionResult`
- `PExecRequest`
- `PExecResult`

## Contratos e responsabilidade

### `OperatorIdentity`

Representa quem esta operando o sistema e o nivel de confianca atual da sessao.

Campos centrais:

- `operator_id`
- `display_name`
- `unix_user`
- `session_id`
- `trust_level`
- `trust_score`

### `ContextSnapshot`

Representa um snapshot coletado por uma fonte de contexto.

Campos centrais:

- `source`
- `tier`
- `collected_at_utc`
- `ttl_s`
- `payload`
- `summary`

Regra:
- snapshots expiram por `ttl`; contexto velho nao deve ser tratado como verdade fresca.

### `PlannedAction`

Representa uma acao operacional individual planejada pelo sistema.

Campos centrais:

- `action_id`
- `module_id`
- `description`
- `args`
- `risk_level`
- `requires_privilege`

### `ActionPlan`

Representa o plano consolidado da tarefa atual.

Campos centrais:

- `plan_id`
- `intent`
- `path`
- `risk_level`
- `context_tier`
- `actions`
- `requires_mutation`

### `PolicyDecision`

Representa a decisao da policy antes da execucao.

Campos centrais:

- `allowed`
- `reason`
- `risk_level`
- `privilege_mode`
- `approval_scope`
- `requires_confirmation`
- `requires_step_up`
- `context_signals`

Regra:
- a policy pode endurecer aprovacao quando snapshots reais indicarem degradacao relevante do host durante uma mutacao.

### `ActionResult`

Representa o resultado de execucao de uma acao individual.

### `PExecRequest` e `PExecResult`

Representam o contrato do plano de execucao privilegiada.

`PExec` e o plano de execucao privilegiada do MC. No estado atual, o transporte bootstrap usa `pkexec`, mas o contrato nao deve depender disso para sempre.

## Regras de compatibilidade

- Mudancas nesses contratos devem ser pequenas, deliberadas e documentadas.
- Se uma mudanca quebrar modulo, runtime ou policy, ela exige atualizacao de documentacao e testes no mesmo patch.
- O objetivo e migrar implementacoes sem quebrar o significado do sistema.
