# MasterControl - Privilege Broker

## O que e

`mc-privilege-broker` e o broker privilegiado local do MasterControl.

Ele roda via socket Unix local e executa apenas `action_id` allowlisted, reutilizando o executor endurecido do projeto.

## O que ele entrega agora

- transporte `broker` real no `PExec`;
- socket Unix local para o core;
- tokens de aprovacao curtos, emitidos antes da execucao real;
- correlacao por `request_id`, `operator_id` e `session_id`;
- auditoria local de `approval_issued`, `approval_used` e execucao allowlisted.

## Caminhos padrao

- socket: `/run/mastercontrol/privilege-broker.sock`
- auditoria: `/var/log/mastercontrol/privilege-broker.log`
- store de aprovacoes: `/var/lib/mastercontrol/privilege-broker.db`

## Instalar

```bash
/home/irving/ruas/repos/master-control/scripts/install-privilege-broker.sh
```

Exemplo explicito:

```bash
/home/irving/ruas/repos/master-control/scripts/install-privilege-broker.sh \
  --operator-id irving \
  --socket-group irving
```

Gerar units sem instalar:

```bash
/home/irving/ruas/repos/master-control/scripts/install-privilege-broker.sh \
  --operator-id irving \
  --socket-group irving \
  --output-dir /tmp/mc-units
systemd-analyze verify /tmp/mc-units/mastercontrol-privilege-broker.service /tmp/mc-units/mastercontrol-privilege-broker.socket
```

O instalador:

- garante o bootstrap privilegiado atual;
- cria `mastercontrol-privilege-broker.service`;
- cria `mastercontrol-privilege-broker.socket`;
- habilita o socket em `systemd`.

## Verificar

```bash
systemctl status mastercontrol-privilege-broker.socket
systemctl status mastercontrol-privilege-broker.service
ss -xl | grep privilege-broker.sock
journalctl -u mastercontrol-privilege-broker.service -n 50 --no-pager
```

## Uso manual

Emitir token curto:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-privilege-broker approve \
  --action service.systemctl.restart \
  --arg unit=unbound.service \
  --request-id req-demo \
  --operator-id irving \
  --session-id tty-1 \
  --risk-level high
```

Executar via broker:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-privilege-broker exec \
  --action service.systemctl.restart \
  --arg unit=unbound.service \
  --request-id req-demo \
  --approval-token TOKEN_AQUI
```

## Regras atuais

- `dry-run` nao exige token.
- execucao real via broker exige token curto.
- token e preso a `action_id` e `args`.
- `single_action` e consumido no primeiro uso.
- `time_window` continua valido ate expirar.
- o broker nao oferece shell root livre; ele apenas encaminha acoes allowlisted.
- restart do processo nao invalida `time_window` enquanto o token ainda existir no `approval_db`.
