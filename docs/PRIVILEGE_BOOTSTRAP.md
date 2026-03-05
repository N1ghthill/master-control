# MasterControl - Bootstrap de privilegios no Debian

## O que este bootstrap entrega

- Executor root allowlisted: `/usr/lib/mastercontrol/root-exec`
- Allowlist de acoes: `/etc/mastercontrol/actions.json`
- Policy polkit para `pkexec`: `io.mastercontrol.rootexec`
- Log de auditoria: `/var/log/mastercontrol/root-exec.log`

## Instalar

No repositorio:

```bash
pkexec bash /home/irving/ruas/repos/master-control/scripts/install-privilege-bootstrap.sh
```

## Testar

Listar acoes permitidas:

```bash
pkexec /usr/lib/mastercontrol/root-exec list-actions
```

Executar acao de DNS:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-root-action dns.unbound.flush_negative
```

Dry-run seguro:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-root-action --dry-run service.systemctl.restart unit=unbound.service
```

Diagnostico de rede (dry-run):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-root-action --dry-run network.diagnose.ping host=1.1.1.1
```

Reiniciar servico:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-root-action service.systemctl.restart unit=unbound.service
```

## Regras importantes

- Nao existe shell root livre neste caminho.
- Apenas `action_id` presente no `actions.json`.
- Argumentos fora do schema sao rejeitados.
- Toda execucao grava auditoria.
- `mc-root-action` usa `config/privilege/actions.json` do repositorio por padrao quando presente (ou `MC_ACTIONS_FILE`/`--actions-file`).

## Integracao futura

Este bootstrap e etapa inicial. O caminho alvo e:

- `mc-privilege-broker` em service root dedicado (systemd),
- aprovacoes temporais por lote,
- policy engine integrado ao core.
