# MasterControl - Diario de Acoes e Resultados

## 2026-03-14 - Fix de auto-observacao do watcher e limpeza do host

### Objetivo do ciclo

Corrigir a regressao descoberta durante a validacao no host: o watcher estava relendo o proprio JSON no `journald` e reabrindo incidente de auth com artefatos do proprio sistema.

### Acoes executadas

1. Ajustado `SystemEventMonitor` para ignorar eventos emitidos por unidades/identificadores do proprio MasterControl.
2. Ajustado o detector `security.auth.anomaly` para nao tratar qualquer ocorrencia de `root` ou `session opened for user` como anomalia por si so.
3. Adicionada cobertura automatizada:
   - evento self-log do watcher ignorado;
   - sessao `pkexec` bem-sucedida nao gera `security.auth.anomaly`.
4. Revalidado em host real com dois sweeps do `mastercontrol-security-watch.service` separados pelo `min_interval` do monitor.
5. Confirmado no SQLite que nenhum novo `system_events.source='mc-security-watch'` entrou apos o patch.
6. Limpas 5 linhas antigas de `system_events` geradas pelo proprio watcher e descartado o incidente de auth auto-gerado que elas deixaram aberto.
7. Reaplicada a configuracao do watcher no host com retencao:
   - `system_events=7d`
   - `security_alerts=21d`
   - `incidents=60d`
   - `incident_activity=90d`
   - `security_silences=14d`

### Resultado

- O watcher deixou de entrar em loop com o proprio `journald`.
- O incidente de auth artificial foi removido do host.
- O host permaneceu com apenas incidentes reais/ruidosos de `service.failure.cluster` e `network.instability`, sem reabertura espuria de auth.
- Revalidada a suite completa apos o patch operacional:
  - `python3 -m unittest discover -s tests -v`
  - `153` testes verdes.

## 2026-03-14 - Instaladores operacionais, playbook do operador e validacao local de units

### Objetivo do ciclo

Transformar o que ainda estava como orientacao de proximo passo em fluxo operacional concreto: retencao configuravel no watcher, validacao nao-destrutiva de units e semantica fechada para o operador.

### Acoes executadas

1. Expandido `install-security-watch-timer.sh`:
   - flags de pruning/retencao por tipo de dado,
   - `--no-prune`,
   - `--output-dir`,
   - `--no-enable`.
2. Expandido `install-privilege-broker.sh`:
   - `--output-dir`,
   - `--no-enable`.
3. Fechado playbook do operador em `docs/INCIDENT_OPERATIONS.md`:
   - diferenca entre `ack`, `silence`, `resolve`, `dismiss` e `contain`,
   - fluxos recomendados,
   - comandos da TUI/REPL,
   - roteiro de validacao no host.
4. Adicionada cobertura automatizada para os instaladores em modo `--output-dir`.
5. Validado operacionalmente fora do `unittest`:
   - geracao real dos units em diretorio temporario,
   - `systemd-analyze verify` para watcher e broker,
   - `mc-security-watch --prune-only` retornando `schema_version=3`,
   - roundtrip do broker com restart entre `approve` e `exec` usando transporte real por socket.
6. Sincronizados `README.md`, `docs/INDEX.md`, `docs/SECURITY_WATCH.md`, `docs/PRIVILEGE_BROKER.md`, `docs/NEXT_SESSION.md` e `docs/ROADMAP.md`.
7. Revalidada a suite completa:
   - `python3 -m unittest discover -s tests -v`
   - `151` testes verdes.

### Resultado

- Pruning do watcher deixou de ser apenas capacidade interna e virou configuracao de instalacao.
- Watcher e broker agora podem ser validados com units gerados sem tocar em `/etc/systemd/system`.
- A semantica operacional do operador deixou de ficar implícita no codigo e passou a ter playbook dedicado.

## 2026-03-14 - TUI navegavel de incidentes, schema versionado e recovery coberto

### Objetivo do ciclo

Executar integralmente o sprint seguinte do ledger: fechar a UX da TUI, controlar lifecycle de dados do watcher e validar recovery persistido.

### Acoes executadas

1. Expandida a interface local/TUI:
   - painel navegavel de incidentes ativos,
   - detalhe do incidente selecionado,
   - selecao por `Up/Down`,
   - refresh automatico apos intents e execucoes.
2. Expandida a interface IA:
   - cache de snapshot de incidente ativo,
   - carregamento de detalhe por `incident_id` selecionado.
3. Versionado o schema do watcher:
   - tabela `security_watch_meta`,
   - migracoes idempotentes ate a versao `3`,
   - indices adicionais para consulta e pruning.
4. Implementado lifecycle de dados do watcher:
   - `prune_data(...)`,
   - pruning de `system_events`,
   - pruning de `security_alerts`,
   - pruning de `security_silences`,
   - pruning de `incidents`,
   - pruning de `incident_activity`,
   - preservacao de incidentes ativos e referencias ligadas.
5. Exposta operacao de pruning no CLI do watcher:
   - `--prune`
   - `--prune-only`
   - flags de retencao por tipo de dado.
6. Validados cenarios de recovery persistido:
   - reinicio do watcher mantendo ledger e transicao posterior de incidente,
   - reinicio do broker mantendo approval token `time_window`.
7. Revalidada a suite completa:
   - `python3 -m unittest discover -s tests -v`
   - `149` testes verdes.

### Resultado

- O ledger de incidente agora tem UX local utilizavel sem depender de texto corrido.
- O watcher passou a ter contrato explicito de schema e limpeza controlada de historico.
- Recovery persistido de watcher e broker deixou de ser hipotese e passou a ter cobertura automatizada.

## 2026-03-14 - Incident ledger operacional, comandos explicitos e docs sincronizadas

### Objetivo do ciclo

Fechar a lacuna entre a infraestrutura ja pronta de incidente e a superficie operacional real do produto, expondo o ledger ao operador e alinhando a documentacao com o estado verdadeiro do codigo.

### Acoes executadas

1. Consolidado o ledger persistente de incidente como superficie explicita do sistema:
   - `incidents`
   - `incident_activity`
   - contrato `IncidentRecord`
2. Expostas acoes locais explicitas no `mod_security`:
   - `security.incident.list`
   - `security.incident.show`
   - `security.incident.resolve`
   - `security.incident.dismiss`
3. Integrado o core para executar essas acoes localmente sem privilegio:
   - listagem do ledger,
   - detalhe por `incident_id`,
   - fechamento explicito de incidente,
   - descarte explicito de incidente.
4. Ajustado o watcher para:
   - retornar detalhe com evidencias e activity trail,
   - fechar alertas locais ligados ao incidente ao executar `resolve/dismiss`,
   - evitar reabertura imediata do mesmo incidente por evidencias antigas.
5. Expostas diretivas explicitas na interface:
   - `/incidents [status]`
   - `/incident-show <incident_id>`
   - `/incident-resolve <incident_id>`
   - `/incident-dismiss <incident_id>`
6. Sincronizada a documentacao operacional:
   - `README.md`
   - `docs/NEXT_SESSION.md`
   - `docs/ROADMAP.md`
   - `docs/SECURITY_WATCH.md`
   - `docs/MASTERCONTROLD_RUNTIME.md`
   - `docs/AI_INTERFACE.md`
   - `docs/CODE_MAP.md`
7. Revalidada a suite completa:
   - `python3 -m unittest discover -s tests -v`
   - `142` testes verdes naquele checkpoint.

### Resultado

- O ledger de incidente deixou de ser apenas infraestrutura interna e virou capacidade explicita do operador.
- O estado real do repositório e o handoff agora voltam a estar alinhados.
- O proximo bloco deixa de ser "criar o ledger" e passa a ser consolidar UX, retencao de dados e recovery no host.

## 2026-03-14 - Broker root, vigilancia continua e resposta a incidente limitada

### Objetivo do ciclo

Levar o MC de prototipo de orquestracao para uma base operacional mais madura em Debian Testing, com privilegio controlado, vigilancia do host e resposta a incidente limitada por policy.

### Acoes executadas

1. Consolidada a base documental do projeto:
   - `docs/PROJECT_FOUNDATIONS.md`
   - `docs/CORE_CONTRACTS.md`
   - `docs/CONTEXT_ENGINE.md`
   - `docs/PEXEC_MODEL.md`
   - `docs/PRIVILEGE_BROKER.md`
   - `CONTRIBUTING.md`
2. Formalizados contratos centrais e infraestrutura tecnica:
   - `mastercontrol/contracts.py`
   - `mastercontrol/context/contextd.py`
   - `mastercontrol/policy/engine.py`
   - `mastercontrol/privilege/pexec.py`
3. Integrado contexto real ao core:
   - coletores `hot/warm/deep`,
   - store SQLite persistente,
   - invalidacao por `TTL` e por evento.
4. Implementado monitor incremental do host:
   - `journald` com cursor persistido,
   - baseline `udevadm`,
   - sessoes via `dbus/login1`.
5. Entregue vigilancia local continua:
   - `mastercontrol/security/watcher.py`,
   - `scripts/mc-security-watch`,
   - `scripts/install-security-watch-timer.sh`,
   - alertas persistidos em `security_alerts`,
   - `ack` e `silence`,
   - resumo de alertas na interface/TUI.
6. Entregue runtime privilegiado mais maduro:
   - broker root via socket Unix,
   - approval tokens curtos,
   - instalador `systemd`,
   - fallback `pkexec_bootstrap`.
7. Validado E2E no host Debian Testing:
   - bloqueio sem token,
   - approval -> exec via broker,
   - `dry-run` de alto risco,
   - restart real e auditado de `unbound.service`.
8. Adicionada resposta a incidente em modo local:
   - `security.incident.plan`,
   - playbooks baseados em alertas ativos.
9. Adicionada contenção automatizada estreita, sempre reaproveitando acoes allowlisted:
   - `service`: servicos afetados com correlacao explicita,
   - `security/auth`: `ssh.service`,
   - `network`: servicos da stack de rede.

### Resultado

- O MC ja opera com:
  - contexto proporcional,
  - policy real,
  - broker root funcional,
  - vigilancia local continua,
  - resposta a incidente com guardrails.
- A suite de testes foi expandida e fechou verde no ultimo checkpoint com `126` testes.

### Proximo bloco recomendado

- Criar `incident ledger` persistente com estado, correlacao e resolucao.
- Handoff tecnico consolidado em `docs/NEXT_SESSION.md`.

## 2026-03-06 - Correcoes de UX na TUI e respostas factuais locais

### Objetivo do ciclo

Eliminar travamento percebido na interface de terminal durante chamadas de LLM e corrigir respostas incorretas para perguntas factuais simples.

### Acoes executadas

1. Refatorada a TUI em `mastercontrol/interface/mc_tui.py` para execucao assincrona:
   - warm-up e processamento de intents em thread de background,
   - fila de eventos para atualizar logs sem bloquear loop de input/render,
   - indicador visual de processamento (spinner) e bloqueio de requisicoes concorrentes.
2. Ajustada renderizacao de logs da TUI:
   - quebra de linha por largura da tela para evitar truncamento de respostas longas.
3. Fortalecidos guardrails factuais em `mastercontrol/interface/mc_ai.py`:
   - respostas locais deterministicas para:
     - data atual,
     - dias restantes para fim do ano,
     - configuracao local da maquina (host/SO/kernel/CPU/RAM/usuario/cwd).
   - bypass do LLM nesses casos para evitar alucinacao.
4. Cobertura de testes expandida em `tests/test_mc_ai_interface.py`:
   - deteccao de perguntas factuais,
   - garantia de que `_prepare_intent` nao chama o LLM nesses casos.
5. Documentacao atualizada:
   - `docs/AI_INTERFACE.md`
   - `docs/MASTERCONTROLD_RUNTIME.md`

### Resultado

- A TUI segue responsiva durante processamento.
- Perguntas factuais nao retornam mais datas incorretas nem respostas vagas.
- Suite de testes segue verde (`46` testes).

## 2026-03-06 - TUI padrao ao invocar `mastercontrol`

### Objetivo do ciclo

Iniciar uma interface de terminal estilo painel (TUI) automaticamente ao digitar `mastercontrol`, reduzindo friccao de uso no dia a dia.

### Acoes executadas

1. Criada TUI em `mastercontrol/interface/mc_tui.py`:
   - layout continuo (header de estado, area de logs e linha de comando),
   - processamento de linguagem natural e comandos `/...`,
   - fluxo de confirmacao (`n/d/e`) e confirmacao de alto risco (`EXECUTAR`),
   - integracao com guardrails e warm-up do LLM.
2. Ajustado launcher `scripts/mc-ai`:
   - sem argumentos em TTY interativo -> abre TUI por padrao,
   - `--repl` forca interface classica,
   - `--tui` forca TUI explicitamente.
3. Mantido comando global `mastercontrol` no ambiente do operador apontando para `scripts/mc-ai`.
4. Documentacao atualizada:
   - `docs/AI_INTERFACE.md`
   - `docs/MASTERCONTROLD_RUNTIME.md`

### Resultado

- `mastercontrol` agora sobe direto a TUI quando invocado sem argumentos.
- Fluxo classico continua disponivel com `mastercontrol --repl`.

## 2026-03-06 - Warm-up automatico no startup da interface IA

### Objetivo do ciclo

Reduzir latencia da primeira resposta no modo interativo (`mc-ai`) aquecendo o modelo local antes da primeira entrada.

### Acoes executadas

1. Adicionado warm-up explicito no `mc-ai`:
   - novo metodo `warmup_llm()` em `mastercontrol/interface/mc_ai.py`,
   - warm-up automatico no startup do REPL,
   - rewarm quando LLM e religado (`/llm on`) ou modelo trocado (`/model ...`).
2. Mantido `--once` sem warm-up inicial para nao penalizar modo one-shot.
3. Adicionada flag de controle:
   - `--no-llm-warmup` para pular aquecimento no modo interativo.
4. Cobertura de testes expandida em `tests/test_mc_ai_interface.py`:
   - warm-up uma vez por modelo,
   - rewarm apos troca de modelo,
   - resiliencia em erro de adapter.
5. Documentacao sincronizada:
   - `docs/AI_INTERFACE.md`
   - `docs/MASTERCONTROLD_RUNTIME.md`

### Resultado

- Primeira resposta no REPL tende a ficar mais estavel apos startup (modelo ja aquecido).
- Operacao continua com fallback seguro quando warm-up falha.
- Medicao local de referencia (modelo descarregado):
  - sem warm-up: primeira resposta ~`9031 ms`,
  - warm-up: ~`8609 ms` no startup + primeira resposta ~`4751 ms`.

## 2026-03-06 - Fechamento do gap DNS `flush_all` (todo/todos)

### Objetivo do ciclo

Corrigir o caso remanescente em que pedidos de flush total de cache DNS (`todo/todos`) caiam em `dns.unbound.flush_negative`.

### Acoes executadas

1. Ajustado parser de capacidade no `mod_dns`:
   - adicionada lista ampliada de sinais de escopo total (`all`, `todo`, `todos`, `tudo`, etc.),
   - mantida precedencia para `bogus` e `negative`.
2. Adicionados testes dedicados em `tests/test_dns_module.py`:
   - resolucao `todo` -> `dns.flush.all`,
   - resolucao `todos` -> `dns.flush.all`,
   - mapeamento final para `dns.unbound.flush_all`.
3. Revalidacao direta no fluxo do `mc-ai`:
   - `limpar todo o cache dns` mapeando para `dns.unbound.flush_all` de forma consistente.
4. Reexecutado benchmark completo (2 rodadas, 32 prompts):
   - comparado `/tmp/bench_qwen3_modules_mastercontrol_guardrail.json` (antes) vs
     `/tmp/bench_qwen3_modules_mastercontrol_guardrail_post_dnsfix.json` (depois).

### Resultado

- Gap de `dns_all` fechado no parser de modulo.
- `intent_action_accuracy` subiu de `0.9167` para `1.0`.
- `mod_dns.action_accuracy` subiu de `0.6667` para `1.0`.
- `misses` caiu de `2` para `0`.
- Suite completa segue verde (`38` testes).

## 2026-03-06 - Guardrails operacionais no mc-ai + rebenchmark por modulo

### Objetivo do ciclo

Corrigir falhas de roteamento/normalizacao do `qwen3:4b-instruct-2507-q4_K_M` para operacoes em `mod_network` e `mod_packages`, mantendo boa conversa em `chat`.

### Acoes executadas

1. Hardening do `mc-ai` em `mastercontrol/interface/mc_ai.py`:
   - detecao de comando operacional explicito (bypass de normalizacao),
   - fallback de rota: quando LLM responde `chat` para pedido operacional, forca `intent`,
   - guardrail de contexto: preserva intent original quando normalizacao perde alvo/escopo (IP, dominio, `bogus`, etc.).
2. Adicionados testes de regressao em `tests/test_mc_ai_interface.py`:
   - deteccao de pedido operacional vs pergunta explicativa,
   - bypass para comando explicito,
   - forca de `intent` quando LLM misclassifica para `chat`,
   - preservacao de contexto operacional.
3. Reexecutado benchmark ponta a ponta (2 rodadas, 32 prompts) com guardrails ativos:
   - relatorio: `/tmp/bench_qwen3_modules_mastercontrol_guardrail.json`.

### Resultado

- `route_accuracy`: `1.0` (antes `0.875`).
- `intent_module_accuracy`: `1.0` (antes `0.6667`).
- `intent_action_accuracy`: `0.9167` (antes `0.5417`).
- `mod_network`: `action_accuracy=1.0` (antes `0.0`).
- `mod_packages`: `action_accuracy=1.0` (antes `0.6667`).
- Gap remanescente: `dns_all` ainda cai para `dns.unbound.flush_negative` (2/2), indicando ajuste pendente no parser do `mod_dns`.

## 2026-03-06 - Troca de padrao para Qwen3 4B Instruct (Q4_K_M)

### Objetivo do ciclo

Atualizar o padrao da interface IA para um modelo menor e rapido, com boa conversa em PT-BR e suporte a tool use.

### Acoes executadas

1. Alterado default do `mc-ai` para `qwen3:4b-instruct-2507-q4_K_M`:
   - `mastercontrol/interface/mc_ai.py`
   - `scripts/mc-ai-chat`
2. Sincronizado default do adapter local:
   - `mastercontrol/llm/ollama_adapter.py`
3. Ajustada documentacao operacional:
   - `docs/AI_INTERFACE.md`
   - `docs/MASTERCONTROLD_RUNTIME.md`
4. Ajustados testes de default da interface:
   - `tests/test_mc_ai_interface.py`
5. Modelo baixado no runtime local Ollama (`127.0.0.1:11435`):
   - `qwen3:4b-instruct-2507-q4_K_M` (2.5 GB)

### Resultado

- O projeto passa a iniciar com `qwen3:4b-instruct-2507-q4_K_M` por padrao.
- `qwen2.5:7b` fica documentado como fallback estavel.

## 2026-03-06 - Hardening da alma no chat + contexto real de host

### Objetivo do ciclo

Garantir que a interface responda identidade correta do MasterControl no modo chat e exponha contexto real quando operador pergunta "onde voce esta".

### Acoes executadas

1. Adicionado guardrail de identidade no `mc-ai`:
   - perguntas de identidade retornam resposta deterministica baseada no soul profile,
   - perguntas de localizacao retornam host/os/user/cwd/time locais,
   - respostas chat com autoidentificacao externa (ex.: Alibaba) sao substituidas pela identidade local.
2. Adicionado snapshot real de contexto no `mastercontrold`:
   - coleta de `hostname`, `os_pretty`, `user`, `cwd`, `timestamp_local`,
   - plano passou a incluir esses dados no passo inicial de contexto.
3. Cobertura de testes:
   - novos testes de guardrail em `tests/test_mc_ai_interface.py`,
   - novo arquivo `tests/test_mastercontrold_context.py`.

### Resultado

- Fluxo de alma no runtime segue reconhecendo `MasterControl/Irving`.
- `mc-ai` deixou de responder identidade de provedor do modelo em perguntas de autoidentificacao.
- Perguntas sobre localizacao agora retornam contexto concreto do host local.

## 2026-03-06 - Documentacao de fluxo operacional da interface IA

### Objetivo do ciclo

Registrar de forma clara o fluxo ponta a ponta do `mc-ai` e um roteiro pratico de uso diario.

### Acoes executadas

1. Expandida documentacao da interface em `docs/AI_INTERFACE.md`:
   - secao "Fluxo ponta a ponta",
   - secao "Roteiro diario (5 comandos)".
2. Sincronizada referencia em `docs/MASTERCONTROLD_RUNTIME.md` para manter navegacao entre guias.

### Resultado

- Fluxo de interacao ficou explicitamente documentado (chat vs intent, fallback, execucao por modo e guardrails).
- Operacao diaria passou a ter guia rapido e padronizado para o operador.

## 2026-03-06 - Decisao final de modelo padrao (Qwen2.5)

### Objetivo do ciclo

Fechar modelo padrao para uso conversacional no `mc-ai` com base em benchmark mais representativo do fluxo real.

### Acoes executadas

1. Configurado runtime local persistente:
   - `ollama-local.service` em `~/.config/systemd/user`,
   - `OLLAMA_HOST=127.0.0.1:11435`,
   - `loginctl enable-linger` para manter servico no boot.
2. Executado benchmark de 20 prompts por modelo (10 conversacionais + 10 operacionais):
   - arquivo de resultado: `/tmp/bench_mc_ai_realistic_results.json`.
3. Ajustado padrao do projeto para `qwen2.5:7b`:
   - `mastercontrol/interface/mc_ai.py` (`DEFAULT_LLM_MODEL`, `DEFAULT_LLM_TIMEOUT_S`),
   - `scripts/mc-ai-chat` (preset padrao em `qwen2.5:7b`).

### Resultados observados

- `qwen2.5:7b`:
  - `avg_latency_s=8.621`,
  - `route_accuracy_overall=0.95`,
  - `route_accuracy_conversational=1.0`.
- `qwen3.5:4b`:
  - `avg_latency_s=16.287`,
  - `route_accuracy_overall=0.8`,
  - `route_accuracy_conversational=0.7`.
- Sem timeout/fallback em ambos no benchmark final, mas com maior estabilidade de rota no `qwen2.5:7b`.

### Conclusao de produto

- Modelo padrao aprovado: `qwen2.5:7b` (`--llm-timeout 25`).
- `qwen3.5:4b` permanece opcional para respostas mais elaboradas, com custo de latencia maior.

## 2026-03-06 - Benchmark conversacional (Qwen2.5 vs Qwen3.5)

### Objetivo do ciclo

Comparar latencia e qualidade de resposta conversacional para escolher modelo padrao de interacao no `mc-ai`.

### Acoes executadas

1. Validado requisito de runtime do `qwen3.5:4b`:
   - exige Ollama `>= 0.17.1`.
2. Subido runtime local atualizado (`0.17.6`) em porta dedicada (`127.0.0.1:11435`) para teste.
3. Baixados modelos no runtime local:
   - `qwen3.5:4b` (3.4 GB)
   - `qwen2.5:7b` (4.7 GB)
4. Executados benchmarks curtos de prompt conversacional no `mc-ai` e no adapter.
5. Criado atalho operacional `scripts/mc-ai-chat`:
   - preset conversacional (`qwen3.5:4b`, timeout 45s, com fallback para `qwen2.5:7b` se runtime local novo nao existir),
   - autodetecta runtime local em `~/.local/ollama-latest/bin/ollama`,
   - usa `OLLAMA_HOST=127.0.0.1:11435` por padrao quando runtime local existe.
6. Aplicado recomendado como padrao do `mc-ai`:
   - `--llm-model qwen3.5:4b`,
   - `--llm-timeout 45`,
   - autodeteccao de Ollama local atualizado (`~/.local/ollama-latest/bin/ollama`).

### Resultados observados

- Benchmark curto (4 prompts):
  - `qwen2.5:7b`: `avg_latency_s=10.844`, `ok_count=4/4`, respostas mais objetivas.
  - `qwen3.5:4b` (`--think=false`): `avg_latency_s=18.265`, `ok_count=4/4`, respostas mais naturais.
- Teste direto no `mc-ai` (mesmo prompt):
  - `qwen2.5:7b`: ~11s
  - `qwen3.5:4b`: ~17s
- Conclusao de adequacao:
  - para conversa natural, `qwen3.5:4b` foi superior;
  - para agilidade/baixa latencia, `qwen2.5:7b` segue melhor.

## 2026-03-06 - Integracao Ollama na interface IA

### Objetivo do ciclo

Permitir comunicacao direta com modelo local no `mc-ai`, reduzindo friccao de uso e mantendo os guardrails do runtime.

### Acoes executadas

1. Criado adapter local de LLM:
   - `mastercontrol/llm/ollama_adapter.py`
   - `mastercontrol/llm/__init__.py`
2. Integrada camada LLM na interface `mc-ai`:
   - roteamento `intent` vs `chat`,
   - normalizacao opcional de intent antes do runtime,
   - fallback automatico para fluxo local quando Ollama/modelo falha.
3. Ajustado adapter Ollama para modo conversacional:
   - tentativa padrao com `--think=false` e `--hidethinking`,
   - fallback automatico sem flags quando runtime nao suporta.
4. Adicionados controles de sessao no REPL:
   - `/llm <on|off|status>`
   - `/model <nome>`
   - `/raw <comando natural>` (bypass LLM por comando)
5. Adicionadas flags no CLI da interface:
   - `--no-llm`
   - `--llm-model`
   - `--llm-timeout`
   - `--ollama-bin`
6. Adicionados testes automatizados:
   - `tests/test_ollama_adapter.py`
   - extensoes em `tests/test_mc_ai_interface.py`
7. Atualizada documentacao:
   - `docs/AI_INTERFACE.md`
   - `docs/MASTERCONTROLD_RUNTIME.md`
   - `docs/CODE_MAP.md`
   - `README.md`

### Resultados observados

- `mc-ai` consegue conversar via modelo local sem abrir execucao privilegiada direta.
- Em falha de modelo/runtime, interface nao quebra e segue no caminho deterministico atual.
- Guardrails de execucao (`confirm`, `dry-run`, bloqueios de risco) permanecem ativos.

## 2026-03-06 - Interface IA conversacional (REPL)

### Objetivo do ciclo

Facilitar a interacao com o MasterControl sem depender de combinacoes extensas de flags em cada comando.

### Acoes executadas

1. Implementada interface IA em REPL:
   - `mastercontrol/interface/mc_ai.py`
   - wrapper `scripts/mc-ai`.
2. Adicionados comandos de controle de sessao:
   - `/risk`, `/path`, `/mode`, `/incident`, `/operator`, `/status`, `/help`, `/quit`.
3. Integrado fluxo guiado de execucao:
   - `confirm` (pergunta por comando),
   - `plan` (somente analise),
   - `dry-run` automatico,
   - `execute` automatico com confirmacao textual para alto risco (`EXECUTAR`).
4. Adicionados testes da interface:
   - `tests/test_mc_ai_interface.py`.
5. Atualizada documentacao de uso:
   - `docs/AI_INTERFACE.md`
   - referencias no `README`, `CODE_MAP` e `MASTERCONTROLD_RUNTIME`.

### Resultados observados

- Operacao por linguagem natural ficou direta no terminal, sem repetir flags.
- Guardrails de runtime foram preservados na interface.
- Testes de parsing/estado da interface passaram junto da suite existente.

## 2026-03-06 - Hardening de privilegios + correcoes de classificacao

### Objetivo do ciclo

Fechar risco de allowlist controlada por usuario em execucao root e corrigir desvio de classificacao por historico.

### Acoes executadas

1. Harden de `root_exec`:
   - fallback de root para `/etc/mastercontrol/actions.json`,
   - validacao de allowlist confiavel em modo root (`/etc/mastercontrol`, owner root, sem escrita para grupo/outros).
2. Ajuste de `mc-root-action`:
   - padrao privilegiado fixo em `/etc/mastercontrol/actions.json`,
   - `--actions-file` customizado permitido apenas com `--dry-run`.
3. Ajuste de classificacao em `mc-intent-classifier`:
   - prioridade para verbos explicitos de mutacao (`restart/start/stop`, `apt install/remove/update`) sobre vies de historico.
4. Adicao de testes automatizados:
   - `tests/test_root_exec_security.py`,
   - `tests/test_intent_classifier.py`.
5. Reaplicado bootstrap (`install-privilege-bootstrap.sh`) para sincronizar binario/allowlist instalados no host.

### Resultados observados

- `restart nginx service` voltou a mapear para `service.restart` com `intent_source=heuristic_explicit`.
- Execucao privilegiada continua funcional para acoes allowlisted (`network.diagnose.route_default`).
- Tentativa de usar `--actions-file` custom em execucao privilegiada via `mc-root-action` foi bloqueada.
- Suite de testes local passou com sucesso (`python3 -m unittest discover -s tests -v`).

### Evidencias de artefatos

- Runtime root: `mastercontrol/runtime/root_exec.py`
- Wrapper de privilegio: `scripts/mc-root-action`
- Classificador: `mastercontrol/tone/intent_classifier.py`
- Testes: `tests/test_root_exec_security.py`, `tests/test_intent_classifier.py`
- Documentacao atualizada: `docs/MASTERCONTROLD_RUNTIME.md`, `docs/PRIVILEGE_BOOTSTRAP.md`, `docs/PRIVILEGE_MODEL.md`, `docs/ADAPTIVE_INTELLIGENCE_SPEC.md`, `docs/CODE_MAP.md`

## 2026-03-05 - Sprint Zero

### Objetivo do ciclo

Criar base tecnica e funcional para:

- arquitetura do MasterControl,
- integracao profunda com privilegios no Debian,
- primeiro caminho real de operacao segura com auditoria.

### Acoes executadas

1. Repositorio preparado em `main`.
2. Especificacao inicial criada (`spec`, `arquitetura`, `roadmap`, `identidade`).
3. Modelo de privilegios adicionado ao desenho (Privilege Plane).
4. Bootstrap funcional de elevacao implementado:
   - allowlist de acoes root,
   - executor root allowlisted,
   - policy polkit,
   - instalador Debian,
   - wrapper de chamada.
5. Fluxos de validacao executados (dry-run, acao real, auditoria).

### Resultados observados

- `root-exec list-actions`: OK.
- `dns.unbound.flush_negative` via `pkexec`: OK (`returncode=0`).
- Validacao de argumento malicioso: bloqueada por regex/schema.
- Auditoria append-only registrada em `/var/log/mastercontrol/root-exec.log`.
- Regra de seguranca confirmada: sem shell root arbitrario.

### Evidencias de artefatos

- Bootstrap: `scripts/install-privilege-bootstrap.sh`
- Executor: `mastercontrol/runtime/root_exec.py`
- Allowlist: `config/privilege/actions.json`
- Policy: `config/polkit/io.mastercontrol.rootexec.policy`
- Guia: `docs/PRIVILEGE_BOOTSTRAP.md`

### Riscos abertos

- Dependencia de `pkexec` no bootstrap (etapa transitória).
- Necessidade de service root dedicado para reduzir friccao de autorizacao.

### Proximos passos

1. Implementar `mc-privilege-broker` via systemd/socket.
2. Integrar policy engine com `approval_scope` temporal.
3. Acoplar auditoria do broker ao `trace_id` do core.

## 2026-03-05 - Soul runtime

### Objetivo do ciclo

Garantir caracteristicas humanizadas no runtime como comportamento obrigatorio.

### Acoes executadas

1. Implementado `Soul Kernel` em `mastercontrol/core/humanized_kernel.py`.
2. Adicionado wrapper de execucao `scripts/mc-humanized`.
3. Criado documento de runtime humanizado com fluxo real de uso.
4. Integrado ao `README`.

### Resultados observados

- Contrato de comunicacao validado no runtime.
- Modo de comunicacao adapta por risco/incidente.
- Reflexao pos-acao gera checks de qualidade e seguranca.
- Identidade (`name`, `creator`, `role`) aparece na resposta ao operador.

### Evidencias de artefatos

- Kernel: `mastercontrol/core/humanized_kernel.py`
- Wrapper: `scripts/mc-humanized`
- Documentacao: `docs/HUMANIZATION_RUNTIME.md`

## 2026-03-05 - MasterControlD v0 loop

### Objetivo do ciclo

Conectar a alma humanizada ao loop principal de decisao para que toda resposta passe por ela.

### Acoes executadas

1. Implementado `Path Selector` autonomo em `mastercontrol/core/path_selector.py`.
2. Implementado `mastercontrold` inicial em `mastercontrol/core/mastercontrold.py`.
3. Adicionado comando de uso `scripts/mastercontrol`.
4. Documentado runtime em `docs/MASTERCONTROLD_RUNTIME.md`.

### Resultados observados

- `mastercontrold` decide `fast/deep` automaticamente quando `--path auto`.
- Toda resposta ao operador passa pelo `Soul Kernel`.
- Reflexao pos-acao e gerada no mesmo ciclo.
- Fluxo ja pronto para conectar modulos reais na proxima etapa.

### Evidencias de artefatos

- Selector: `mastercontrol/core/path_selector.py`
- Core loop: `mastercontrol/core/mastercontrold.py`
- CLI: `scripts/mastercontrol`
- Documentacao: `docs/MASTERCONTROLD_RUNTIME.md`

## 2026-03-05 - Adaptive layer (profiler + tone + dream)

### Objetivo do ciclo

Adicionar aprendizado operacional local sem depender de LLM pesado para cada comando.

### Acoes executadas

1. Criado `mc-operator-profiler` com SQLite local e tabelas de eventos/padroes.
2. Criado `mc-tone-analyzer` leve (heuristico) com cluster de intent e frustracao.
3. Criado `mc-dream` para gerar insights offline em janela de dias.
4. Integrado `mastercontrold` com tone + profile + registro de evento.
5. Atualizada especificacao adaptativa em `docs/ADAPTIVE_INTELLIGENCE_SPEC.md`.

### Resultados observados

- Core passou a decidir caminho considerando tom e preferencia do operador.
- Eventos operacionais passam a alimentar memoria local automaticamente.
- Pipeline pronto para timer noturno de insights (`mc-dream`).

### Evidencias de artefatos

- Profiler: `mastercontrol/context/mc_operator_profiler.py`
- Tone: `mastercontrol/tone/mc_tone_analyzer.py`
- Dream: `mastercontrol/dream/mc_dream.py`
- Wrappers: `scripts/mc-operator-profiler`, `scripts/mc-tone-analyzer`, `scripts/mc-dream`
- Spec: `docs/ADAPTIVE_INTELLIGENCE_SPEC.md`

### Validacao de resultado

- `mastercontrol` passou a expor no output: tom, cluster de intent e preferencia de path do operador.
- `mc-dream` gerou insights reais de repeticao de sequencia (`dns.flush -> dns.inspect`) com sugestao `dns.reset`.

## 2026-03-05 - Nightly automatic dream timer

### Objetivo do ciclo

Executar `mc-dream` automaticamente em janela noturna, sem acao manual.

### Acoes executadas

1. Criado instalador `scripts/install-dream-timer.sh`.
2. Definida unidade `systemd` com hardening e execução em nome do operador.
3. Definido timer diário com `Persistent=true`.
4. Documentado uso e verificação em `docs/DREAM_TIMER.md`.

### Resultado esperado

- MasterControl passa a "sonhar" toda madrugada, gerando insights no banco local mesmo após reboot/offline.

### Validacao de resultado

- `mastercontrol-dream.timer` ativo e aguardando proximo ciclo noturno.
- Proximo agendamento observado: `03:00` (com `RandomizedDelaySec` aplicado).
- Execucao manual de teste da service: `status=0/SUCCESS`.
- Insights gravados em `dream_insights`.

## 2026-03-05 - Consolidacao de documentacao tecnica

### Objetivo do ciclo

Deixar o inventario de codigo claro por camada para facilitar manutencao e evolucao.

### Acoes executadas

1. Criado `docs/CODE_MAP.md` com agrupamento por dominio:
   - Core Intelligence
   - Security/Privileges
   - Adaptive Intelligence
   - Soul/Identity Config
2. Atualizado `README.md` com link para `Code Map`.

### Resultado esperado

- Navegacao rapida de arquivos e responsabilidades sem ambiguidade.
- Base documental alinhada com estado atual do repositorio.

## 2026-03-05 - Integracao de execucao real no mastercontrold

### Objetivo do ciclo

Sair de simulacao e operar acao allowlisted real no loop principal:
interpretacao -> decisao de path -> execucao -> auditoria -> reflexao -> aprendizado.

### Acoes executadas

1. Atualizado `mastercontrold` para:
   - mapear intents para `action_id` allowlisted no `_build_plan`,
   - executar acoes reais via `scripts/mc-root-action`,
   - capturar `stdout/stderr/returncode` e refletir no resultado final,
   - registrar auditoria complementar em `~/.local/share/mastercontrol/mastercontrold.log`.
2. Integrada telemetria real no profiler:
   - `command_error` real,
   - latencia real,
   - sucesso/falha real.
3. Corrigido mapeamento de service restart:
   - precedencia de `restart` no `_map_action`,
   - regex de extracao de unit corrigida.

### Validacao de resultado

- `flush negative cache` com `--execute --dry-run`: OK, mapeado para `dns.unbound.flush_negative`.
- `flush dns cache` com `--execute --dry-run`: OK, mapeado para `dns.unbound.flush_negative`.
- `flush dns cache` com `--execute`: OK, execucao real concluida com sucesso.
- `restart unbound service --execute`: bloqueado por confirmacao (`fast_with_confirm`) sem `--approve`.
- `restart unbound service --execute --approve`: bloqueado por risco alto sem `--allow-high-risk`.
- `restart unbound service --execute --approve --allow-high-risk --dry-run`: OK.

### Evidencias de artefatos

- Core atualizado: `mastercontrol/core/mastercontrold.py`
- Runtime doc atualizado: `docs/MASTERCONTROLD_RUNTIME.md`
- Log core: `~/.local/share/mastercontrol/mastercontrold.log`

### Observacoes

- Leitura direta de `/var/log/mastercontrol/root-exec.log` depende de permissao root no ambiente atual.

## 2026-03-05 - Intent intelligence + mod_dns + learned rules

### Objetivo do ciclo

Evoluir de heuristica fraca para interpretacao mais robusta e fechar o ciclo adaptativo:
operador -> log -> dream -> learned rules -> path selector.

### Acoes executadas

1. Criado classificador de intencao local-first:
   - `transformer` local opcional (`MC_INTENT_MODEL_DIR`),
   - fallback por historico local (`command_events`),
   - fallback heuristico robusto.
2. Integrado classificador ao `mc-tone-analyzer` com novos campos:
   - `intent_source`
   - `intent_confidence`
3. Criado modulo operacional real `mod_dns` com contrato:
   - `capabilities()`
   - `pre_check()`
   - `apply()`
   - `verify()`
   - `rollback()`
4. `mastercontrold` passou a delegar DNS ao `mod_dns` e incluir verificacoes no plano.
5. Adicionada tabela `learned_rules` no SQLite e suporte no `mc-dream` para gerar/upsert de regras.
6. `PathSelector` passou a consumir `learned_rules` com guardrails de seguranca para risco alto/incidente.

### Validacao de resultado

- `mc-intent-classifier --text "flush negative cache now"`: `dns.flush`.
- `mc-intent-classifier --text "reiniciar serviço unbound"`: `service.restart`.
- `mastercontrol --intent "flush negative cache" --execute --dry-run --json`:
  - mapeamento DNS por `mod_dns` validado,
  - pre-check/verify presentes no plano,
  - acao allowlisted executada em dry-run com sucesso.
- `mc-dream --operator-id irving --window-days 30`:
  - gerou `learned_rules` e persistiu no banco.
- teste isolado do `PathSelector` com regra injetada:
  - `rule_applied=True` e ajuste de caminho/confianca confirmado.

### Evidencias de artefatos

- Intent classifier: `mastercontrol/tone/intent_classifier.py`
- Tone integration: `mastercontrol/tone/mc_tone_analyzer.py`
- DNS module: `mastercontrol/modules/mod_dns.py`
- Core integration: `mastercontrol/core/mastercontrold.py`
- Learned rules in selector: `mastercontrol/core/path_selector.py`
- Dream rule generation: `mastercontrol/dream/mc_dream.py`

## 2026-03-05 - mod_services integration

### Objetivo do ciclo

Separar operacoes de servicos do core para reduzir heuristica ad-hoc e manter o orquestrador enxuto.

### Acoes executadas

1. Criado `mod_services` com contrato:
   - `capabilities()`
   - `pre_check()`
   - `apply()`
   - `verify()`
   - `rollback()`
2. Implementada extracao de unit (`unbound`, `nginx`, `docker`, `*.service`) no modulo.
3. `mastercontrold` passou a resolver modulo por precedencia (`mod_services` antes de `mod_dns` quando aplicavel).
4. Removido parsing ad-hoc de service unit do core e mantido fallback minimo apenas para casos nao modulares.

### Validacao de resultado

- `reiniciar serviço unbound --execute --dry-run`: mapeado via `mod_services` para `service.systemctl.restart`.
- `start nginx service --execute --dry-run`: mapeado via `mod_services` para `service.systemctl.start`.
- `parar docker service --execute --dry-run`: mapeado via `mod_services` para `service.systemctl.stop`.
- `reiniciar serviço unbound --execute` sem `--approve`: bloqueio por `fast_with_confirm` mantido.

### Evidencias de artefatos

- Modulo: `mastercontrol/modules/mod_services.py`
- Integracao no core: `mastercontrol/core/mastercontrold.py`

## 2026-03-05 - mod_packages integration

### Objetivo do ciclo

Tirar operacoes de pacote do core e padronizar em modulo com contrato operacional.

### Acoes executadas

1. Criado `mod_packages` com contrato:
   - `capabilities()`
   - `pre_check()`
   - `apply()`
   - `verify()`
   - `rollback()`
2. Implementada extracao de pacote para intents:
   - `apt update`
   - `apt install <package>`
   - `apt remove <package>`
   - variações em linguagem natural.
3. Integrado `mastercontrold` para resolver modulo por cluster:
   - `service.*` -> prioridade `mod_services`
   - `package.*` -> prioridade `mod_packages`
   - `dns.*` -> prioridade `mod_dns`
4. Ajustado `mod_dns` para tokenizacao por palavras e evitar falso positivo por substring (ex.: `dnsutils`).

### Validacao de resultado

- `apt update --execute --dry-run`: mapeado para `package.apt.update` via `mod_packages`.
- `apt install htop --execute --dry-run`: mapeado para `package.apt.install_one`.
- `apt remove htop --execute --dry-run`: mapeado para `package.apt.remove_one`.
- `instalar pacote dnsutils --execute --dry-run`: mapeado para pacote corretamente (sem desvio para DNS).

### Evidencias de artefatos

- Modulo: `mastercontrol/modules/mod_packages.py`
- Integracao no core: `mastercontrol/core/mastercontrold.py`
- Ajuste DNS tokenizado: `mastercontrol/modules/mod_dns.py`

## 2026-03-05 - ModuleRegistry e core mais enxuto

### Objetivo do ciclo

Remover fallback heuristico residual do core e centralizar resolucao de modulo em uma camada unica.

### Acoes executadas

1. Criado contrato compartilhado de modulo:
   - `mastercontrol/modules/base.py` (`ModulePlan`, `OperationalModule`).
2. Criado `ModuleRegistry`:
   - resolucao por prioridade de cluster (`dns.*`, `service.*`, `package.*`),
   - fallback deterministico entre modulos registrados.
3. Refatorado `mastercontrold` para:
   - usar `registry.resolve(...)`,
   - remover fallback ad-hoc de mapeamento direto para DNS/pacotes,
   - registrar no plano quando nenhuma acao foi resolvida (`attempted_modules`).
4. Padronizados `mod_dns`, `mod_services` e `mod_packages` para o contrato comum.

### Validacao de resultado

- `flush negative cache --execute --dry-run`: resolvido por `mod_dns`.
- `reiniciar serviço unbound --execute --dry-run`: resolvido por `mod_services`.
- `apt install htop --execute --dry-run`: resolvido por `mod_packages`.
- `faz algo sem sentido xyz`: sem acao mapeada, analysis-only, com lista de modulos tentados.

### Evidencias de artefatos

- Contrato: `mastercontrol/modules/base.py`
- Registry: `mastercontrol/modules/registry.py`
- Core refatorado: `mastercontrol/core/mastercontrold.py`

## 2026-03-05 - mod_network + allowlist de diagnostico

### Objetivo do ciclo

Adicionar diagnostico de rede no mesmo padrao modular, com acoes read-only e risco baixo.

### Acoes executadas

1. Criado `mod_network` com contrato:
   - `capabilities()`
   - `pre_check()`
   - `apply()`
   - `verify()`
   - `rollback()`
2. Capabilities adicionadas:
   - `network.ping` -> `network.diagnose.ping`
   - `network.resolve` -> `network.diagnose.resolve`
   - `network.route.default` -> `network.diagnose.route_default`
3. Integrado no `ModuleRegistry` e no `mastercontrold` como modulo de primeira classe.
4. Expandida allowlist de privilegios com acoes de rede de baixo risco em `actions.json`.
5. Ajustado `mc-root-action` para usar por padrao o `actions.json` do repositorio quando presente (evita mismatch entre `/etc` e repo em desenvolvimento).

### Validacao de resultado

- `ping 1.1.1.1 --execute --dry-run`: `network.diagnose.ping` validado.
- `resolve openai.com --execute --dry-run`: `network.diagnose.resolve` validado.
- `show default route --execute --dry-run`: `network.diagnose.route_default` validado.
- `flush negative cache --execute --dry-run`: DNS continua operacional apos integracao.

### Evidencias de artefatos

- Modulo: `mastercontrol/modules/mod_network.py`
- Registry: `mastercontrol/modules/registry.py`
- Allowlist: `config/privilege/actions.json`
- Wrapper: `scripts/mc-root-action`
