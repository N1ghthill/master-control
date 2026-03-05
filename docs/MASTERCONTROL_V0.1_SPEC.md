# MasterControl v0.1 - Especificacao

## 1) Problema

Usuarios avancados de Linux querem automacao profunda do SO sem perder controle, seguranca e previsibilidade. Ferramentas isoladas resolvem partes (DNS, pacotes, servicos), mas falta um orquestrador unico com contexto operacional continuo.

## 2) Objetivo do produto

Construir um agente local para Debian que:

- Entende ordens em linguagem natural.
- Mantem consciencia situacional continua.
- Controla modulos do SO de forma segura e auditavel.
- Opera rapido para tarefas simples e com profundidade para diagnosticos complexos.

## 3) Resultado esperado (visao do operador)

`MasterControl` se comporta como "cerebro do sistema":

- Recebe ordens.
- Interpreta intencao e risco.
- Executa via modulos.
- Explica o que fez e por que.
- Aprende preferencias operacionais sem perder governanca.

## 4) Escopo v0.1 (MVP forte)

Inclui:

- Core local (daemon + CLI).
- Modelo local open-source para planejamento/interpretacao.
- Motor de politica (permissoes por acao e nivel de risco).
- Modelo de privilegios/elevacao funcional desde a fundacao.
- Memoria operacional (estado, historico, preferencias).
- Modulos iniciais:
  - DNS (wrapper do `unbound-cli`).
  - Services (`systemctl`).
  - Packages (`apt`/`dpkg`).
  - Network (diagnostico e estado).
  - Security baseline (auditoria rapida).

Nao inclui em v0.1:

- Autonomia irrestrita sem aprovacao.
- Auto-modificacao de codigo em producao sem pipeline.
- Controle remoto multi-host.

## 5) Requisitos funcionais

1. Entender comandos em linguagem natural e mapear para "intents" estruturadas.
2. Obter contexto de execucao atual (`quem`, `onde`, `quando`, `estado do host`) sem reprocessar tudo a cada comando.
3. Selecionar modulo correto e montar plano de acao.
4. Classificar risco e aplicar politica.
5. Executar acao, validar resultado, registrar auditoria.
6. Fornecer resposta amigavel e tecnica ao mesmo tempo.
7. Executar operacoes privilegiadas por allowlist (sem shell root arbitrario).

## 6) Consciencia situacional (ponto central)

### 6.1 Modelo mental

Consciencia situacional nao pode ser calculada do zero por prompt. Ela deve ser mantida como um estado vivo do sistema.

### 6.2 Estrategia tecnica

- `State Collectors` atualizam um `World State Store` continuamente.
- O core consulta snapshots prontos com custo baixo.
- O LLM recebe somente o contexto necessario para aquela tarefa.

### 6.3 Eixos minimos de contexto

- `Who`: usuario Unix, sessao ativa, TTY, grupo, historico recente de comandos aprovados.
- `Where`: host, distro, kernel, rede ativa, ambiente local/remoto, diretorio atual.
- `When`: timestamp, janela operacional (ex.: madrugada/horario comercial), eventos recentes.
- `What now`: saude de servicos, alertas, incidentes, mudancas recentes.

### 6.4 Performance

- Fast path (comando simples): usar intent template + snapshot pronto.
- Deep path (analise complexa): ampliar contexto e usar cadeia de raciocinio guiada.
- Orquestracao por budget de latencia:
  - Simples: alvo < 500 ms ate plano.
  - Complexo: alvo < 3 s ate plano inicial.

### 6.5 Seletor autonomo de caminho (`Path Selector`)

A escolha entre fast/deep path e responsabilidade do MasterControl, nao do operador.

- Entrada do seletor:
  - complexidade da intent,
  - criticidade/risco da acao,
  - incerteza do parser/planner,
  - estado atual do host (incidentes, degradacao),
  - historico de erro em intents similares.
- Saida do seletor:
  - `FAST`
  - `DEEP`
  - `FAST_WITH_CONFIRM` (rapido, mas com confirmacao obrigatoria)
- Regra de seguranca:
  - se houver incerteza alta, promover para `DEEP`.
- Auto-correcao:
  - se a execucao falhar por contexto insuficiente, replanejar em `DEEP` e registrar aprendizado.

## 7) Identidade e confianca (sem UX robotica)

Autenticacao forte continua necessaria para risco alto, mas o uso diario pode ser contextual.

### 7.1 Sinais de confianca

- Sessao local ativa consistente.
- Usuario esperado (`uid`, grupos, historico de aprovacoes).
- Padrao de ambiente (host, rede, horario).
- Continuidade de sessao (sem troca suspeita).

### 7.2 Trust levels

- `T0` leitura segura (sem confirmacao).
- `T1` escrita reversivel (confirmacao leve ou politica pre-aprovada).
- `T2` alteracoes sensiveis (step-up obrigatorio).
- `T3` operacoes destrutivas (step-up forte + justificativa + janela controlada).

### 7.3 Step-up sem friccao excessiva

- Prompt de confirmacao contextual.
- Janela curta de autorizacao para lote de acoes relacionadas.
- Break-glass apenas para operador dono.

## 8) Seguranca e guardrails

- Separacao estrita:
  - `Control Plane` (LLM + planner).
  - `Execution Plane` (runtime deterministico com APIs tipadas).
- `Privilege Plane` dedicado para acoes root.
- Politica por acao, modulo, risco e alvo.
- Dry-run antes de mutacao quando possivel.
- Idempotencia e rollback documentado por modulo.
- Log de auditoria imutavel (append-only local).
- Elevacao via `pkexec/polkit` no bootstrap, evoluindo para broker root em service dedicado.

## 9) Modelo de aprendizagem

v0.1 aprende comportamento operacional sem retreino pesado:

- Memoria de preferencia do operador.
- Catalogo de incidentes e resolucoes.
- Ranking de playbooks por sucesso.

Treino/fine-tune (futuro):

- Offline, versionado e avaliavel.
- Nunca automatico em producao.

## 10) Modulos como capacidade operacional

Core decide "o que fazer". Modulo decide "como executar com seguranca".

Contrato minimo de modulo:

- `capabilities()`
- `health()`
- `plan(intent, context)`
- `apply(plan, policy)`
- `verify(expected_state)`
- `rollback(checkpoint)`

Exemplo:

- `mod-dns` usa `unbound-cli` como backend de operacao e diagnostico.

## 11) Niveis de autonomia

- `A0`: observador (somente leitura).
- `A1`: executa baixo risco automaticamente.
- `A2`: executa medio risco com confirmacao.
- `A3`: alto risco somente com step-up.

v0.1 recomendado: `A1` por padrao, com escalonamento para `A2/A3`.

## 12) Criterios de aceitacao v0.1

1. Core local responde comandos, monta plano e chama modulos.
2. Politica bloqueia acoes fora do permitido.
3. Auditoria registra decisao + execucao + resultado.
4. Latencia de fast path dentro de meta em ambiente desktop comum.
5. Modulos DNS/Services/Packages funcionam ponta a ponta.
6. Path Selector escolhe fast/deep de forma autonoma e explica o motivo da escolha.
7. Acoes root funcionam ponta a ponta via allowlist com auditoria.

## 13) Riscos principais

- Alucinacao do modelo em diagnostico.
- Excesso de automacao sem guardrails.
- Crescimento de escopo antes da base ficar estavel.

Mitigacao:

- Planner com schema estrito.
- Execucao somente por API tipada.
- Rollout em fases e com suites de teste por modulo.
