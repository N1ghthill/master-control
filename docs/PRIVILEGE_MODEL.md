# MasterControl - Privilegios e elevacao

## Objetivo

Evitar retrabalho futuro com permissao/elevacao definindo desde o inicio:

- como executar operacoes privilegiadas,
- quem pode acionar cada operacao,
- quando exigir confirmacao/step-up,
- como auditar tudo.

## Principio central

MasterControl deve ser funcional e seguro ao mesmo tempo:

- funcional: conseguir realmente executar operacoes no Debian;
- seguro: sem dar root irrestrito ao LLM ou ao usuario final.

## Arquitetura de elevacao (v0.1)

1. Fluxo normal (preferencial)
- `mc-cli` (usuario) -> `mastercontrold` -> `mc-runtime` -> modulo.
- Se a acao exigir root, runtime chama `Privilege Broker`.

2. Privilege Broker
- Processo dedicado de execucao privilegiada.
- Recebe apenas `action_id` + argumentos validados.
- Nao executa shell arbitrario.

3. Fallback de bootstrap
- `pkexec` com policy polkit restrita para `root-exec`.
- Permite desenvolvimento funcional antes do broker completo em service root.

## Modelo de acao privilegiada

Cada operacao privilegiada e identificada por `action_id` e definida em allowlist:

- comando base permitido,
- argumentos permitidos por regex/schema,
- nivel de risco,
- se exige confirmacao/step-up.

Exemplo:

- `dns.unbound.flush_all`
- `service.systemctl.restart`
- `package.apt.update`

## Matriz risco x elevacao

- `low`: pode executar com confianca alta e policy allow.
- `medium`: geralmente exige confirmacao do operador.
- `high`: exige step-up explicito.
- `critical`: bloqueado por padrao sem politica dedicada.

## Regras obrigatorias

1. Nunca executar shell livre em contexto root.
2. Sempre validar argumentos antes de executar.
3. Sempre registrar auditoria com `request_id`.
4. Sempre capturar `stdout/stderr/exit_code`.
5. Sempre aplicar timeout.
6. Sempre retornar erro estruturado.

## Auditoria minima

Log append-only para operacoes privilegiadas:

- timestamp UTC,
- usuario solicitante,
- action_id,
- comando resolvido,
- resultado (rc, duracao),
- decisao de policy.

## Caminho de evolucao

- v0.1: `pkexec` + policy + executor root allowlist.
- v0.2: broker root via systemd socket activation.
- v0.3: aprovacao temporal por lote e sessao confiavel.

## Bootstrap implementado neste repositorio

- Allowlist: `config/privilege/actions.json`
- Policy polkit: `config/polkit/io.mastercontrol.rootexec.policy`
- Executor root: `mastercontrol/runtime/root_exec.py`
- Instalador Debian: `scripts/install-privilege-bootstrap.sh`
