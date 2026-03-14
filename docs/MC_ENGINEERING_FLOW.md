# MasterControl - Engineering Flow

## Proposito

Este documento define o fluxo de engenharia do `MasterControl` (`MC`) e a hierarquia correta do sistema.

Ele existe para evitar tres desvios comuns:

- tratar modulos como produto principal;
- tratar o LLM como centro do sistema;
- implementar automacao sem contrato claro com o operador.

No `MC`, a ordem certa e:

1. operador;
2. instrucoes, protocolos e limites definidos pelo operador;
3. `MasterControl` como agente central;
4. modulos como ferramentas e extensoes do `MC`;
5. host Linux real como ambiente operado.

## Regra fundadora

O `MC` existe para servir, ajudar e ampliar a capacidade operacional do operador.

Isso significa:

- o operador define prioridade, politica, estilo e limites;
- o `MC` interpreta, planeja, explica, executa e aprende dentro desse contrato;
- modulos existem para estender a capacidade do `MC`, nao para competir com ele;
- a camada de I.A existe para tornar o `MC` mais inteligente, adaptativo e humano, nao para tomar o lugar da arquitetura.

## Hierarquia do sistema

### 1) Operator first

O operador e a fonte de autoridade, direcao e protocolo.

Tudo que o sistema fizer deve responder a perguntas como:

- o operador pediu isso?
- o operador autorizou esse tipo de acao?
- existe protocolo definido para esse dominio?
- o risco e compativel com a confianca atual da sessao?

### 2) MC first

O `MasterControl` e o agente central.

Ele nao e apenas:

- uma interface de chat;
- um invocador de scripts;
- um agregador de modulos;
- um invoker de LLM.

Ele e o ponto de unificacao entre:

- identidade;
- contexto;
- planejamento;
- policy;
- execucao;
- memoria;
- humanizacao;
- relacao com o operador.

### 3) Modules as extensions

Modulos sao ferramentas do `MC`.

Eles devem:

- expor capacidades claras;
- respeitar contratos do core;
- operar como extensoes do agente central;
- nunca definir sozinhos a identidade do sistema;
- nunca contornar policy, auditoria ou protocolo do operador.

Pergunta de arquitetura obrigatoria:

`isso fortalece o MC ou esta criando um mini-sistema paralelo dentro de um modulo?`

### 4) AI as adaptive cognition

A I.A deve fortalecer o `MC` em quatro eixos:

- interpretar melhor o operador;
- adaptar comunicacao e profundidade;
- escolher contexto e caminho com mais precisao;
- reduzir desgaste operacional sem perder controle.

A I.A nao pode:

- dissolver contratos deterministas;
- bypassar policy;
- substituir verificacao e auditoria;
- introduzir identidade inconsistente;
- virar um centro paralelo de decisao fora do `MC`.

## Loop operacional canonico do MC

Toda capacidade do projeto deve caber, explicitamente, neste fluxo:

1. `Operator Contract`
- entrada do operador;
- instrucoes persistentes;
- protocolos do dominio;
- limites de risco, estilo e preferencia.

2. `Interpretation`
- entender intencao;
- decidir se e conversa, operacao, investigacao ou incidente;
- preservar contexto e alvo do pedido.

3. `Context Selection`
- usar `hot`, `warm` ou `deep` conforme necessidade;
- evitar coleta desnecessaria;
- buscar o menor contexto suficiente para agir bem.

4. `Planning`
- escolher `path`;
- selecionar capacidade/modulo;
- montar plano explicavel, verificavel e auditavel.

5. `Policy and Protocol Check`
- aplicar risco;
- aplicar protocolo do operador;
- decidir `allow`, `confirm`, `step_up` ou `deny`.

6. `Execution`
- executar por runtime deterministico;
- usar modulo adequado;
- usar privilegio somente via caminho aprovado.

7. `Verification and Audit`
- verificar efeito;
- registrar `request_id`, decisao, saida e impacto;
- definir rollback ou proximo passo seguro.

8. `Humanized Response`
- responder no tom certo;
- explicar o essencial sem desgaste;
- adaptar clareza, densidade e cautela ao momento.

9. `Operational Learning`
- registrar padroes do operador;
- aprender friccao, preferencia e recorrencia;
- melhorar o `MC` sem romper previsibilidade.

## Fluxo de engenharia para novas capacidades

Ao projetar qualquer nova feature, a ordem de construcao deve ser esta:

1. `Operator need`
- qual problema real do operador o `MC` vai resolver?
- qual protocolo ou regra operacional precisa existir?

2. `MC capability`
- o que o agente central precisa passar a saber, decidir ou comunicar?
- essa capacidade reforca o `MC` como agente ou espalha logica pelo sistema?

3. `Contract`
- quais contratos de intent, contexto, plano, policy ou resultado mudam?
- como isso fica explicito e testavel?

4. `Module or tool integration`
- existe modulo novo?
- modulo atual precisa de nova capacidade?
- a integracao e uma extensao limpa do core?

5. `Policy and safety`
- qual risco existe?
- qual aprovacao e necessaria?
- como impedir bypass?

6. `Humanization and intelligence`
- como o `MC` explica isso ao operador?
- qual adaptacao de tom, densidade e atrito faz sentido?
- onde a I.A agrega decisao melhor sem perder controle?

7. `Verification`
- como provar que a feature funciona no fluxo real?
- quais testes unitarios, de fluxo e smoke sao necessarios?

## Checklist de design obrigatorio

Antes de aceitar uma mudanca, confirmar:

- o centro da mudanca e o `MC`, nao um modulo isolado;
- a feature nasce de uma necessidade real do operador;
- existe protocolo, guardrail ou contrato claro;
- a camada de I.A esta servindo o agente, nao competindo com ele;
- a resposta ao operador ficou mais util, mais clara ou menos desgastante;
- o Linux real continua sendo a fonte de verdade operacional;
- ha verificacao e auditoria proporcionais ao risco.

## Anti-padroes

Evitar explicitamente:

- `module-first design`: quando o modulo passa a parecer o produto principal;
- `LLM-first design`: quando o sistema gira em torno do modelo e nao do agente;
- `chat-first design`: quando conversa substitui operacao;
- `automation-first design`: quando autonomia cresce sem protocolo do operador;
- `tool sprawl`: quando novas ferramentas entram sem caber no fluxo do `MC`;
- `humanization as skin`: quando humanizacao vira cosmetica, em vez de adaptacao real.

## Definicao pratica de humanizacao

No `MC`, humanizacao significa:

- identidade estavel;
- memoria operacional do operador;
- comunicacao proporcional ao risco e ao contexto;
- explicacao clara do que entendeu, vai fazer e fez;
- reducao de atrito repetitivo;
- firmeza em risco alto sem perder postura de servico.

Humanizacao nao significa:

- excesso de conversa;
- persona solta sem disciplina operacional;
- opiniao acima de protocolo;
- eloquencia sem precisao.

## Definicao pratica de inteligencia

No `MC`, inteligencia significa:

- usar o contexto certo;
- escolher o caminho certo;
- interpretar com pouca perda de alvo;
- saber quando perguntar, quando executar e quando bloquear;
- reaproveitar historico e preferencia sem cair em automatismo cego;
- manter qualidade operacional sob restricoes reais do host.

## Regra final de governanca

Se houver duvida sobre uma mudanca, decidir nesta ordem:

1. protege e serve melhor o operador?
2. fortalece o `MC` como agente central?
3. respeita os protocolos e guardrails?
4. mantem integracao real com Linux?
5. usa I.A para melhorar decisao e humanizacao sem perder controle?

Se a resposta comecar por modulo, LLM ou conveniencia tecnica, a mudanca esta partindo do centro errado.
