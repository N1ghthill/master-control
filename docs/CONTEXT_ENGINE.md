# MasterControl - Context Engine

## Objetivo

Definir como o MC mantem consciencia situacional com custo proporcional a tarefa.

## Regra principal

O MC opera com `contexto minimo suficiente`.

Isso significa:

- nao existe checklist fixa por interacao;
- contexto simples deve ser reaproveitado quando ainda estiver valido;
- contexto adicional so deve ser coletado quando houver necessidade objetiva.

## Camadas

### `hot`

Usada quando a tarefa e simples, de baixo risco e sem necessidade diagnostica ampliada.

Exemplos:

- identidade do operador,
- sessao atual,
- host,
- diretorio atual,
- estado operacional imediato.

### `warm`

Usada quando existe mutacao potencial, ambiguidade ou necessidade tecnica moderada.

Exemplos:

- servicos principais,
- rede e DNS,
- recursos do host,
- hardware e snapshots recentes.

### `deep`

Usada quando ha diagnostico, incidente, alta incerteza ou risco alto.

Exemplos:

- logs detalhados,
- correlacao de falhas,
- investigacao de incidente,
- analise mais ampla do estado do host.

## Componentes

Implementados inicialmente em `mastercontrol/context/contextd.py`:

- `CollectorSpec`
- `ContextCollector`
- `InMemoryContextStore`
- `SQLiteContextStore`
- `ContextEngine`
- `SessionContextCollector`
- `HostContextCollector`
- `NetworkContextCollector`
- `ServiceContextCollector`
- `AlertJournalCollector`
- `SystemEventMonitor` em `mastercontrol/context/events.py`

## Estado atual

Os coletores reais atuais seguem estrategia `Debian-first` com custo controlado:

- `SessionContextCollector`: sessao, operador, host, `cwd`, hora local.
- `HostContextCollector`: kernel, arquitetura, CPU, memoria, carga e uptime.
- `NetworkContextCollector`: rota default, interfaces e `nameserver`.
- `ServiceContextCollector`: estado geral do `systemd` e unidades falhas.
- `AlertJournalCollector`: ultimas entradas de warning/error do `journal`.

O `mastercontrold` ja usa esses coletores para preencher `hot`, `warm` e `deep context`, reaproveitando snapshots via `TTL`.

Os snapshots persistem em `SQLite` no mesmo banco local do profiler (`mastercontrol.db`), na tabela `context_snapshots`.
Isso permite:

- reaproveitamento entre requests e reinicios do processo;
- leitura de sinais operacionais reais pelo `PathSelector`;
- promocao de path baseada em degradacao de servicos, rede ou pressao do host, sem depender so de heuristica textual.
- invalidacao seletiva de snapshots quando o proprio MC executa mutacoes com sucesso.
- invalidacao incremental por eventos do sistema via `journald`, com cursor persistido e `min_interval` para evitar custo fixo por interacao.
- deteccao incremental de mudancas de topologia por `udevadm info --export-db`, persistindo baseline em `event_source_state`.
- deteccao incremental de mudancas de sessao por `dbus/login1` via `busctl`, com fallback em `loginctl`.
- reaproveitamento dos `system_events` persistidos por modulos locais de seguranca, como `security.audit.recent_events` e `security.vigilance.status`.
- reaproveitamento dos mesmos sinais por um watcher local continuo que consolida `security_alerts`.

## Comportamento esperado

`ContextEngine.required_tier(...)` deve decidir a camada minima necessaria com base em:

- risco,
- mutacao,
- diagnostico,
- incidente,
- ambiguidade.

`ContextEngine.ensure_context(...)` deve:

1. descobrir a camada necessaria;
2. coletar apenas os coletores ate essa camada;
3. reaproveitar snapshots ainda validos;
4. devolver somente contexto fresco.

## Proximo passo tecnico

- ampliar coletores de seguranca, hardware e diagnostico profundo.
- conectar mais modulos e sinais de seguranca ao `PathSelector` e ao policy engine.
- evoluir o monitor incremental para mais fontes alem de `journald`, `udev` e `dbus/login1`, incluindo eventos dedicados de seguranca.
