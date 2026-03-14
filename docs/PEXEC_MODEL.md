# MasterControl - PExec Model

## O que e PExec

`PExec` significa `Privileged Execution Plane`.

Ele define como o MC planeja e executa operacoes privilegiadas sem entregar shell root livre ao sistema conversacional.

## Regra central

Toda execucao privilegiada deve passar por:

1. `ActionPlan`
2. `PolicyDecision`
3. `PExecRequest`
4. transporte privilegiado controlado
5. auditoria

## Estado atual

O bootstrap atual continua usando `pkexec` e `polkit`, mas o transporte `broker` agora ja existe em forma inicial via socket Unix local.

Implementacao base:

- `mastercontrol/runtime/root_exec.py`
- `mastercontrol/privilege/broker.py`
- `scripts/mc-root-action`
- `scripts/mc-privilege-broker`
- `config/privilege/actions.json`
- `config/polkit/io.mastercontrol.rootexec.policy`

## Novo contrato

O planejamento de PExec agora existe em `mastercontrol/privilege/pexec.py`.

Objetos principais:

- `PExecRequest`
- `PExecResult`
- `BootstrapPkexecTransport`
- `PrivilegeBrokerTransport`
- `PrivilegeBrokerClient`
- `PrivilegeBrokerServer`
- `PExecPlanner`

## Modelo de transporte

### Transporte atual: `pkexec_bootstrap`

Uso:

- valida `action_id`
- valida argumentos
- usa allowlist
- grava auditoria

Este e o caminho transitorio de execucao privilegiada.

### Transporte futuro: `broker`

Estado atual:

- cliente local via `python -m mastercontrol.privilege.broker exec`
- socket Unix local
- servidor dedicado com reuse do executor allowlisted atual
- policy pode preferir broker quando o socket estiver disponivel
- execucao real pode exigir token curto emitido logo antes da mutacao
- `systemd socket activation` ja tem instalador dedicado

Proximos passos:

- aprovacao temporal,
- correlacao mais forte com sessao e policy,
- menos dependencia direta de `pkexec` no bootstrap do host.

## Regra de arquitetura

`pkexec` e um transporte bootstrap.

`PExec` e o plano de execucao privilegiada do MC.

O sistema deve evoluir de:

- `PExec -> pkexec bootstrap`

para:

- `PExec -> root broker dedicado`

sem quebrar os contratos de policy e auditoria. Essa transicao ja comecou: o broker agora e um transporte valido, mas ainda nao substitui por completo o bootstrap operacional do host.
