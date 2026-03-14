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

Dry-run com allowlist custom (somente validacao local):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-root-action --dry-run --actions-file /tmp/actions.json network.diagnose.route_default
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
- Execucao privilegiada usa `/etc/mastercontrol/actions.json` como fonte padrao.
- `--actions-file` customizado so e aceito no `mc-root-action` quando `--dry-run`.
- `root-exec` em modo root rejeita allowlist fora de `/etc/mastercontrol`, com owner != root ou gravavel por grupo/outros.

## Integracao futura

Este bootstrap continua como fallback e etapa inicial. O caminho atual mais forte e:

- `mc-privilege-broker` via socket Unix local,
- tokens de aprovacao curtos,
- policy engine integrado ao core.

Instalacao do broker:

```bash
pkexec bash /home/irving/ruas/repos/master-control/scripts/install-privilege-broker.sh
```

O caminho ainda desejado de maturidade e:

- aprovacoes temporais por lote,
- policy engine integrado ao core.
