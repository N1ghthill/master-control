# MasterControl - Operacao de Incidentes

## Objetivo

Definir o uso operacional correto do ciclo:

`alerta -> incidente -> contenção -> resolve/dismiss`

Este documento fecha a semantica entre as acoes de alerta e as acoes explicitas do ledger de incidentes.

## Conceitos

- `security_alerts`: evidencias locais derivadas do watcher.
- `incidents`: agrupamento persistente de evidencias correlacionadas por `fingerprint + category`.
- `incident_activity`: trilha de transicoes e decisoes do operador.

Regra pratica:

- alerta responde a evidencia;
- incidente responde ao caso operacional.

## Quando usar cada acao

### `ack`

Use `ack` quando:

- voce revisou a evidencia;
- nao quer mais tratar aquele alerta como pendente;
- ainda nao quer criar uma janela de supressao.

Efeito:

- alertas selecionados passam para `acknowledged`;
- se o escopo do incidente ficar sem alertas `new`, o incidente relacionado fecha como `resolved`;
- se ainda restarem alertas `new`, o incidente continua aberto e a trilha registra a revisao.

Resumo:

- `ack` e uma decisao sobre evidencia;
- pode resolver o incidente indiretamente, mas so quando o escopo realmente esvazia.

### `silence`

Use `silence` quando:

- o padrao ja foi entendido;
- novas ocorrencias iguais devem parar de reaparecer por um tempo;
- voce quer uma janela temporaria de supressao por `fingerprint`.

Efeito:

- cria linha em `security_silences`;
- alertas selecionados passam para `silenced`;
- se o escopo do incidente ficar sem alertas `new`, o incidente relacionado fecha como `dismissed`.

Resumo:

- `silence` suprime recorrencia temporaria;
- ele nao significa "corrigido";
- e mais forte que `ack` no controle de ruido, mas menos final que `resolve`.

### `resolve`

Use `resolve` quando:

- o caso operacional foi encerrado;
- voce quer fechar explicitamente um incidente por `incident_id`;
- o operador quer registrar encerramento, nao apenas revisar evidencia.

Efeito:

- o incidente vai para `resolved`;
- alertas abertos ligados ao incidente sao fechados localmente como `acknowledged`;
- a trilha registra a decisao explicita do operador.

Resumo:

- `resolve` e decisao de caso;
- preferir quando houve investigacao/conserto e o incidente pode ser dado como encerrado.

### `dismiss`

Use `dismiss` quando:

- o caso nao exige continuidade operacional;
- a correlacao foi descartada;
- voce quer fechar o incidente explicitamente sem criar janela de silencio.

Efeito:

- o incidente vai para `dismissed`;
- alertas abertos ligados ao incidente sao fechados localmente como `acknowledged`;
- nao cria `security_silences`.

Resumo:

- `dismiss` fecha o caso;
- diferente de `silence`, nao instala supressao temporaria futura.

### `contain`

Use `contain` quando:

- existe incidente ativo;
- a unidade alvo esta explicitamente correlacionada com o incidente;
- policy e approval ainda permitem mutacao.

Efeito:

- dispara uma acao allowlisted existente;
- se a acao real for bem-sucedida, o incidente pode ir para `contained`;
- `incident_activity` recebe a tentativa, bloqueio ou sucesso.

Resumo:

- `contain` e mutacao do host;
- `ack/silence/resolve/dismiss` sao acoes locais no ledger.

## Fluxos recomendados

### Caso comum: revisar e encerrar

1. Ver alertas ou incidentes ativos.
2. Abrir detalhe do incidente.
3. Se a evidencia foi apenas revisada, usar `ack`.
4. Se o caso foi realmente encerrado, usar `resolve`.

### Caso comum: ruido conhecido

1. Confirmar que o padrao e conhecido e temporario.
2. Usar `silence` no `fingerprint` ou alerta alvo.
3. Acompanhar o `silence_until_utc`.

### Caso comum: falso positivo ou correlacao descartada

1. Abrir o incidente.
2. Registrar a decisao operacional.
3. Usar `dismiss` no `incident_id`.

### Caso comum: remediacao controlada

1. Abrir o incidente.
2. Confirmar unidade correlacionada.
3. Executar `contain` somente se a policy permitir.
4. Depois da remediacao, decidir entre `resolve` ou manter em observacao.

## Comandos do operador

Na TUI/REPL:

- `/incidents`
- `/incident-show <incident_id>`
- `/incident-resolve <incident_id>`
- `/incident-dismiss <incident_id>`

No painel da TUI:

- `Up/Down` navegam entre incidentes ativos quando a linha de comando esta vazia.

## Validacao operacional no host

Gerar units sem instalar:

```bash
./scripts/install-security-watch-timer.sh --output-dir /tmp/mc-units
./scripts/install-privilege-broker.sh --output-dir /tmp/mc-units
systemd-analyze verify /tmp/mc-units/mastercontrol-security-watch.service /tmp/mc-units/mastercontrol-security-watch.timer
systemd-analyze verify /tmp/mc-units/mastercontrol-privilege-broker.service /tmp/mc-units/mastercontrol-privilege-broker.socket
```

Validar pruning manual:

```bash
./scripts/mc-security-watch --prune-only --db-path /tmp/mastercontrol-ops.db
```

Validar restart de servicos instalados:

```bash
systemctl restart mastercontrol-security-watch.timer
systemctl start mastercontrol-security-watch.service
systemctl restart mastercontrol-privilege-broker.socket
systemctl restart mastercontrol-privilege-broker.service
```

Inspecionar estado:

```bash
systemctl status mastercontrol-security-watch.timer --no-pager
journalctl -u mastercontrol-security-watch.service -n 50 --no-pager
systemctl status mastercontrol-privilege-broker.socket --no-pager
systemctl status mastercontrol-privilege-broker.service --no-pager
```
